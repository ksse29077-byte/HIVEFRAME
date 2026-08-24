"""Model-free V4 lineage comparison and frozen event-trace diagnostics."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence
import json

from .active_query_attention import BLOCK_COUNT, TOTAL_STEPS
from .h3_bounded_host_source_oracle_v4 import (
    FROZEN_EVENTS,
    REGION,
    SOURCE_BLOCKS,
    SOURCE_SLOT_EMPTY,
    SOURCE_SLOT_IDENTITY_FIELDS,
    SOURCE_SLOT_READY,
    SOURCE_STEPS,
    SourceSlotLifecycle,
    V4ContractError,
)


SCHEMA_VERSION = "h3.v4.lineage-diagnostic.1"
CAUSE_CAPTURE_TARGET_ORDERING = "CAPTURE_TARGET_ORDERING_ERROR"
CAUSE_UNKNOWN = "UNKNOWN"

LINEAGE_FIELDS = (
    "generation_digest",
    "profile_digest",
    "model_digest",
    "inventory_digest",
    "layout_digest",
    "source_step_ordinal",
    "source_scheduler_timestep",
    "source_block",
    "source_region",
    "source_slot_index",
    "source_slot_version",
    "source_capture_sequence",
    "source_capture_event_id",
    "source_tensor_shape",
    "source_dtype",
    "source_device_layout_identity",
    "source_completion_state",
    "legacy_lineage_digest",
)


def canonical_digest(value: Any) -> str:
    """Return one deterministic SHA-256 digest for diagnostic metadata."""

    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def source_slot_index(block: int) -> int:
    """Map a frozen source block to its stable bounded host slot."""

    try:
        return SOURCE_BLOCKS.index(int(block))
    except ValueError as error:
        raise ValueError("V4 source block has no bounded host slot") from error


def source_capture_sequence(block: int, source_step: int) -> int:
    """Return the deterministic one-based source-capture sequence."""

    try:
        step_index = SOURCE_STEPS.index(int(source_step))
    except ValueError as error:
        raise ValueError("V4 source step is outside the frozen inventory") from error
    return step_index * len(SOURCE_BLOCKS) + source_slot_index(block) + 1


def source_slot_version(source_step: int) -> int:
    """Return the monotonic per-block slot generation for a source step."""

    try:
        return SOURCE_STEPS.index(int(source_step)) + 1
    except ValueError as error:
        raise ValueError("V4 source step has no slot version") from error


def source_capture_event_id(
    *, generation_digest: str, block: int, source_step: int, sequence: int
) -> str:
    """Bind a capture event to generation, block, step, and sequence."""

    return canonical_digest(
        {
            "generation_digest": generation_digest,
            "source_block": int(block),
            "source_region": REGION,
            "source_step_ordinal": int(source_step),
            "source_capture_sequence": int(sequence),
        }
    )


def build_source_components(
    *,
    generation_digest: str,
    profile_digest: str,
    model_digest: str,
    inventory_digest: str,
    layout_digest: str,
    scheduler_timesteps: Sequence[str],
    block: int,
    source_step: int,
    tensor_shape: Sequence[int],
    tensor_dtype: str,
    completion_state: str,
    legacy_lineage_digest: str,
) -> dict[str, Any]:
    """Build non-payload source identity metadata for one host slot."""

    sequence = source_capture_sequence(block, source_step)
    return {
        "generation_digest": str(generation_digest),
        "profile_digest": str(profile_digest),
        "model_digest": str(model_digest),
        "inventory_digest": str(inventory_digest),
        "layout_digest": str(layout_digest),
        "source_step_ordinal": int(source_step),
        "source_scheduler_timestep": str(scheduler_timesteps[int(source_step)]),
        "source_block": int(block),
        "source_region": REGION,
        "source_slot_index": source_slot_index(block),
        "source_slot_version": source_slot_version(source_step),
        "source_capture_sequence": sequence,
        "source_capture_event_id": source_capture_event_id(
            generation_digest=generation_digest,
            block=block,
            source_step=source_step,
            sequence=sequence,
        ),
        "source_tensor_shape": [int(value) for value in tensor_shape],
        "source_dtype": str(tensor_dtype),
        "source_device_layout_identity": canonical_digest(
            {"device": "cpu-pinned", "layout_digest": str(layout_digest)}
        ),
        "source_completion_state": str(completion_state),
        "legacy_lineage_digest": str(legacy_lineage_digest),
    }


def build_target_components(
    *,
    scheduler_timesteps: Sequence[str],
    target_step: int,
    expected_source_step: int,
    block: int,
    target_sequence: int,
) -> dict[str, Any]:
    """Build target-side metadata without storing prompt or tensor payloads."""

    candidate_key = {
        "target_step_ordinal": int(target_step),
        "expected_source_step_ordinal": int(expected_source_step),
        "target_block": int(block),
        "target_region": REGION,
        "target_sequence": int(target_sequence),
    }
    return {
        **candidate_key,
        "target_scheduler_timestep": str(scheduler_timesteps[int(target_step)]),
        "expected_source_scheduler_timestep": str(
            scheduler_timesteps[int(expected_source_step)]
        ),
        "candidate_key_digest": canonical_digest(candidate_key),
    }


def compare_lineage(
    *,
    expected: Mapping[str, Any],
    actual: Mapping[str, Any] | None,
    target: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every frozen lineage field and return a bounded receipt."""

    actual_values = {} if actual is None else dict(actual)
    mismatches = [
        field for field in LINEAGE_FIELDS if expected.get(field) != actual_values.get(field)
    ]
    mask = sum(1 << index for index, field in enumerate(LINEAGE_FIELDS) if field in mismatches)
    first = mismatches[0] if mismatches else None
    classification = _classify_mismatch(mismatches)
    return {
        "schema_version": SCHEMA_VERSION,
        "matched": not mismatches,
        "matched_fields": [field for field in LINEAGE_FIELDS if field not in mismatches],
        "mismatched_fields": mismatches,
        "mismatch_count": len(mismatches),
        "mismatch_mask": mask,
        "classification": classification,
        "first_mismatch_field": first,
        "first_mismatch_expected": None if first is None else expected.get(first),
        "first_mismatch_actual": None if first is None else actual_values.get(first),
        "expected_identity_digest": canonical_digest(dict(expected)),
        "actual_identity_digest": (
            None if actual is None else canonical_digest(actual_values)
        ),
        "expected": dict(expected),
        "actual": actual_values,
        "target": dict(target),
    }


def _classify_mismatch(mismatches: Sequence[str]) -> str | None:
    if not mismatches:
        return None
    fields = set(mismatches)
    if "generation_digest" in fields:
        return "GENERATION_DIGEST_DRIFT"
    if "profile_digest" in fields:
        return "PROFILE_DIGEST_DRIFT"
    if "model_digest" in fields:
        return "MODEL_DIGEST_DRIFT"
    if fields & {"inventory_digest", "layout_digest"}:
        return "INVENTORY_OR_LAYOUT_DIGEST_DRIFT"
    if fields & {"source_block", "source_region"}:
        return "BLOCK_OR_REGION_IDENTITY_MISMATCH"
    if "source_completion_state" in fields:
        return "OTHER_PROVEN_CAUSE:INCOMPLETE_COMPLETION_EVENT"
    if fields & {
        "source_slot_index",
        "source_capture_sequence",
        "source_capture_event_id",
    }:
        return "SOURCE_SLOT_REUSE_OR_OVERWRITE"
    if "source_step_ordinal" in fields:
        return CAUSE_CAPTURE_TARGET_ORDERING
    if "source_scheduler_timestep" in fields:
        return "STEP_ORDINAL_VS_SCHEDULER_TIMESTEP"
    return "OTHER_PROVEN_CAUSE"


def replay_frozen_event_trace(scheduler_timesteps: Sequence[str]) -> dict[str, Any]:
    """Replay the complete 1000-call lineage order without H3 or CUDA."""

    if len(scheduler_timesteps) != TOTAL_STEPS:
        raise ValueError("V4 trace requires exactly 20 scheduler timesteps")
    by_target = {(event.block, event.target_step): event for event in FROZEN_EVENTS}
    slots = {block: SourceSlotLifecycle() for block in SOURCE_BLOCKS}
    captures = 0
    targets = 0
    mismatch = 0
    overwrite = 0
    incomplete = 0
    duplicate_consume = 0
    stale_slot = 0
    unread_overwrite = 0
    peak_live_slots = 0
    first_target_call = None

    def identity(block: int, source_step: int) -> dict[str, Any]:
        components = build_source_components(
            generation_digest="1" * 64,
            profile_digest="2" * 64,
            model_digest="3" * 64,
            inventory_digest="4" * 64,
            layout_digest="5" * 64,
            scheduler_timesteps=scheduler_timesteps,
            block=block,
            source_step=source_step,
            tensor_shape=(3367, 7168),
            tensor_dtype="torch.bfloat16",
            completion_state="EVENT_RECORDED",
            legacy_lineage_digest="6" * 64,
        )
        return {field: components[field] for field in SOURCE_SLOT_IDENTITY_FIELDS}

    for step in range(TOTAL_STEPS):
        for block in range(BLOCK_COUNT):
            event = by_target.get((block, step))
            if event is not None:
                if first_target_call is None:
                    first_target_call = step * BLOCK_COUNT + block + 1
                slot = slots[block]
                if slot.state != SOURCE_SLOT_READY:
                    incomplete += 1
                else:
                    try:
                        slot.begin_consume(identity(block, event.source_step))
                        slot.release()
                        targets += 1
                    except V4ContractError as error:
                        mismatch += 1
                        if "source_step_ordinal" in str(error):
                            stale_slot += 1
                        if "requires READY" in str(error):
                            duplicate_consume += 1
            if block in SOURCE_BLOCKS and step in SOURCE_STEPS:
                slot = slots[block]
                try:
                    slot.begin_capture(identity(block, step))
                    slot.mark_ready()
                    captures += 1
                except V4ContractError:
                    overwrite += 1
                    if slot.state == SOURCE_SLOT_READY:
                        unread_overwrite += 1
            peak_live_slots = max(
                peak_live_slots,
                sum(slot.state != SOURCE_SLOT_EMPTY for slot in slots.values()),
            )
    releases = sum(slot.release_count for slot in slots.values())
    consumes = sum(slot.consume_count for slot in slots.values())
    transition_errors = sum(slot.invalid_transition_count for slot in slots.values())
    passed = (
        captures == len(SOURCE_BLOCKS) * len(SOURCE_STEPS)
        and targets == len(FROZEN_EVENTS)
        and consumes == releases == len(FROZEN_EVENTS)
        and mismatch == overwrite == incomplete == 0
        and duplicate_consume == stale_slot == unread_overwrite == 0
        and transition_errors == 0
        and peak_live_slots <= len(SOURCE_BLOCKS)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_evidence": False,
        "full_attention_trace_calls": TOTAL_STEPS * BLOCK_COUNT,
        "source_capture_count": captures,
        "target_lookup_count": len(FROZEN_EVENTS),
        "target_consume_completed_count": consumes,
        "source_release_count": releases,
        "frozen_candidates_encountered": targets,
        "exact_candidate_admissions": targets,
        "lineage_mismatch_count": mismatch,
        "source_slot_overwrite_count": overwrite,
        "incomplete_source_admission_count": incomplete,
        "duplicate_consume_count": duplicate_consume,
        "stale_slot_admission_count": stale_slot,
        "unread_slot_overwrite_count": unread_overwrite,
        "slot_transition_error_count": transition_errors,
        "peak_simultaneous_live_slots": peak_live_slots,
        "first_target_full_attention_call": first_target_call,
        "passed": passed,
    }


def replay_retained_failure_prefix(
    *, full_attention_calls: int, source_capture_count: int, exact_record_count: int
) -> dict[str, Any]:
    """Compare retained counters with the frozen first-target prefix."""

    trace = replay_frozen_event_trace(tuple(float(20 - i).hex() for i in range(20)))
    expected_call = int(trace["first_target_full_attention_call"])
    reproduced = (
        int(full_attention_calls) == expected_call
        and int(source_capture_count) == len(SOURCE_BLOCKS)
        and int(exact_record_count) == 0
    )
    unexplained_delta = int(full_attention_calls) - expected_call
    return {
        "schema_version": SCHEMA_VERSION,
        "retained_full_attention_calls": int(full_attention_calls),
        "retained_source_capture_count": int(source_capture_count),
        "retained_exact_record_count": int(exact_record_count),
        "expected_first_target_full_attention_call": expected_call,
        "unexplained_full_attention_call_delta": unexplained_delta,
        "reproduced_from_frozen_order": reproduced,
        "classification": (
            CAUSE_CAPTURE_TARGET_ORDERING if reproduced else CAUSE_UNKNOWN
        ),
    }
