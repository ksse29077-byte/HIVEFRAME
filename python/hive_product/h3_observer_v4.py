"""Generation-scoped observer for one unchanged H3 Full Compute CONTROL."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import perf_counter
from typing import Any, Mapping, Sequence
import json

from .a3_g1_conditional_reuse import CONTROL_MODE, H3A3G1Controller
from .h3_bounded_host_source_oracle_v4 import (
    CANDIDATE_H2D_HARD_CAP_BYTES,
    FROZEN_EVENTS,
    GPU_STAGING_BUDGET_BYTES,
    HOLDOUT_LABEL,
    HOST_SOURCE_BUDGET_BYTES,
    HOST_SOURCE_RESIDENT_BYTES,
    METADATA_D2H_BYTES,
    MINIMUM_CANDIDATE_H2D_BYTES,
    MINIMUM_EXACT_RECORDS,
    MINIMUM_PLANNED_Q_RATIO,
    MINIMUM_PLANNED_Q_ROWS,
    OMITTED_POSITIONS,
    PLANNED_Q_ROWS_PER_RECORD,
    REGION,
    REGION_ROWS,
    REPRESENTATIVE_POSITIONS,
    SOURCE_BLOCKS,
    SOURCE_CAPTURE_D2H_BYTES,
    SOURCE_PAYLOAD_BYTES,
    SOURCE_SHAPE,
    SOURCE_SLOT_CONSUMING,
    SOURCE_SLOT_EMPTY,
    SOURCE_SLOT_IDENTITY_FIELDS,
    SOURCE_SLOT_READY,
    SOURCE_SLOT_RELEASED,
    SOURCE_STEPS,
    SharedStagingState,
    SourceSlotLifecycle,
    SourceIdentity,
    TOTAL_TENSOR_TRANSFER_BYTES,
    TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
    V4ContractError,
    frozen_inventory_digest,
    settings_digest,
)
from .h3_bounded_host_source_oracle_v4_cuda import (
    gpu_compressed_fingerprint,
    gpu_exact_oracle_metrics_indexed,
    gpu_indexed_compressed_fingerprint,
    gpu_preliminary_metrics,
    threshold_classification,
)
from .h3_row_region_safety import FULL_Q_ROWS
from .h3_v4_lineage_diagnostic import (
    build_source_components,
    build_target_components,
    compare_lineage,
)


SCHEMA_VERSION = "h3.observer-runtime-v4.1"
PROFILE_ID = "H3_V4_BOUNDED_HOST_SOURCE_OBSERVER_CONTROL"
PROFILE_DIGEST = settings_digest()
SOURCE_CAPTURE_COUNT = len(SOURCE_BLOCKS) * len(SOURCE_STEPS)
METRIC_COLUMN_COUNT = 9
PACKED_LAYOUT_DIGEST = sha256(
    json.dumps(
        {
            "region": REGION,
            "rows": REGION_ROWS,
            "representative_positions": REPRESENTATIVE_POSITIONS,
            "omitted_positions": OMITTED_POSITIONS,
            "shape": SOURCE_SHAPE,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
).hexdigest()


class V4ObserverAbort(Exception):
    """Abort the one-shot observer without entering a native retry path."""


@dataclass
class V4HostSourceSlot:
    """One block-local exact BF16 host source and its completion identity."""

    payload: Any
    lifecycle: SourceSlotLifecycle = field(default_factory=SourceSlotLifecycle)
    lineage_digest: str | None = None
    lineage_components: dict[str, Any] | None = None
    completion_event: Any | None = None

    @property
    def state(self) -> str:
        return self.lifecycle.state

    @property
    def valid(self) -> bool:
        return self.state in {
            SOURCE_SLOT_READY,
            SOURCE_SLOT_CONSUMING,
            SOURCE_SLOT_RELEASED,
        }

    @property
    def consumed(self) -> bool:
        return self.state in {SOURCE_SLOT_EMPTY, SOURCE_SLOT_RELEASED}

    @property
    def source_step(self) -> int | None:
        if self.lifecycle.identity is None:
            return None
        return int(self.lifecycle.identity["source_step_ordinal"])

    @property
    def version(self) -> int:
        return self.lifecycle.version

    def begin_capture(self, components: Mapping[str, Any]) -> None:
        self.lifecycle.begin_capture(components)
        self.lineage_digest = None
        self.lineage_components = None
        self.completion_event = None

    def mark_ready(
        self,
        *,
        lineage_digest: str,
        lineage_components: Mapping[str, Any],
        completion_event: Any,
    ) -> None:
        self.lineage_digest = lineage_digest
        self.lineage_components = dict(lineage_components)
        self.completion_event = completion_event
        self.lifecycle.mark_ready()

    def begin_consume(self, expected_components: Mapping[str, Any]) -> None:
        expected = {
            field: expected_components[field] for field in SOURCE_SLOT_IDENTITY_FIELDS
        }
        self.lifecycle.begin_consume(expected)

    def release(self) -> None:
        self.lifecycle.release()

    def complete_release(self, *, expected_version: int) -> None:
        if self.state != SOURCE_SLOT_CONSUMING:
            raise V4ContractError("V4 completion requires CONSUMING slot")
        if self.version != expected_version:
            raise V4ContractError("V4 completion slot version changed")
        self.lifecycle.release()
        self.lifecycle.return_empty()
        self.lineage_digest = None
        self.lineage_components = None
        self.completion_event = None

    def reset(self) -> None:
        self.lifecycle.reset()
        self.lineage_digest = None
        self.lineage_components = None
        self.completion_event = None


class V4HostSourceResources:
    """Process-owned pinned storage admitted before the one-shot submission."""

    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module
        self.slots = {
            block: V4HostSourceSlot(
                payload=torch_module.empty(
                    SOURCE_SHAPE,
                    dtype=torch_module.bfloat16,
                    device="cpu",
                    pin_memory=True,
                )
            )
            for block in SOURCE_BLOCKS
        }
        self.metric_rows = torch_module.empty(
            (MINIMUM_EXACT_RECORDS, METRIC_COLUMN_COUNT),
            dtype=torch_module.float32,
            device="cpu",
            pin_memory=True,
        )
        self.active_generation: str | None = None
        self.allocated_source_bytes = sum(
            int(slot.payload.numel()) * int(slot.payload.element_size())
            for slot in self.slots.values()
        )
        self.allocated_metric_bytes = int(self.metric_rows.numel()) * int(
            self.metric_rows.element_size()
        )
        if self.allocated_source_bytes != HOST_SOURCE_RESIDENT_BYTES:
            raise RuntimeError("V4 pinned source allocation changed")
        if self.allocated_source_bytes > HOST_SOURCE_BUDGET_BYTES:
            raise RuntimeError("V4 pinned source allocation exceeds 768 MiB")

    def acquire(self, generation_digest: str) -> None:
        if self.active_generation is not None:
            raise RuntimeError("V4 host resources reject concurrent generations")
        self.active_generation = generation_digest
        for slot in self.slots.values():
            slot.reset()

    def release(self, generation_digest: str) -> None:
        if self.active_generation != generation_digest:
            raise RuntimeError("V4 host resource generation ownership changed")
        for slot in self.slots.values():
            slot.reset()
        self.active_generation = None

    def admission_receipt(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "profile_id": PROFILE_ID,
            "profile_digest": PROFILE_DIGEST,
            "inventory_digest": frozen_inventory_digest(),
            "source_slot_count": len(self.slots),
            "source_shape": list(SOURCE_SHAPE),
            "source_dtype": "torch.bfloat16",
            "source_slots_page_locked": all(
                bool(slot.payload.is_pinned()) for slot in self.slots.values()
            ),
            "metric_buffer_page_locked": bool(self.metric_rows.is_pinned()),
            "pinned_source_bytes": self.allocated_source_bytes,
            "pinned_metric_bytes": self.allocated_metric_bytes,
            "host_source_budget_bytes": HOST_SOURCE_BUDGET_BYTES,
            "shared_gpu_staging_budget_bytes": GPU_STAGING_BUDGET_BYTES,
            "active_generation": self.active_generation,
        }


@dataclass
class _TimingPair:
    kind: str
    start: Any
    end: Any


@dataclass
class _PendingCompletion:
    block_index: int
    slot_version: int
    generation_digest: str
    source_identity: dict[str, Any]
    capture_completion_event: Any
    oracle_completion_event: Any
    target_key: tuple[int, int]
    pending_record: dict[str, Any]
    evidence_committed: bool = False
    release_eligible: bool = False


@dataclass
class _DeferredCapture:
    block_index: int
    source_step: int
    lineage_digest: str
    lineage_components: dict[str, Any]
    completion_event: Any


class H3ObserverControllerV4(H3A3G1Controller):
    """Observe frozen V4 candidates after exact H3 Full Attention."""

    _TRANSITIONS = {
        "created": {"admitted", "aborted"},
        "admitted": {"observing", "aborted"},
        "observing": {"finalizing", "aborted"},
        "finalizing": {"complete", "aborted"},
        "complete": set(),
        "aborted": set(),
    }

    def __init__(
        self,
        *,
        plan_bridge: Any,
        h3_model: Any,
        torch_module: Any,
        resources: V4HostSourceResources,
        generation_digest: str,
        workflow_digest: str,
        model_digest: str,
        profile_digest: str,
        scheduler_timesteps: Sequence[str],
    ) -> None:
        super().__init__(
            mode=CONTROL_MODE,
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch_module,
            candidate_blocks=SOURCE_BLOCKS,
        )
        self.resources = resources
        self.generation_digest = generation_digest
        self.workflow_digest = workflow_digest
        self.model_digest = model_digest
        self.profile_digest = profile_digest
        self.scheduler_timesteps = tuple(str(value) for value in scheduler_timesteps)
        self.scheduler_digest = sha256(
            json.dumps(self.scheduler_timesteps, separators=(",", ":")).encode("ascii")
        ).hexdigest()
        self.state = "created"
        self.lifecycle = ["created"]
        self.abort_reason: str | None = None
        self._event_by_target = {
            (event.block, event.target_step): event for event in FROZEN_EVENTS
        }
        self._inventory_digest = frozen_inventory_digest()
        self._expected_targets = set(self._event_by_target)
        self._expected_sources = {
            (block, step) for step in SOURCE_STEPS for block in SOURCE_BLOCKS
        }
        self._seen_targets: set[tuple[int, int]] = set()
        self._seen_sources: set[tuple[int, int]] = set()
        self._pending_records: list[dict[str, Any]] = []
        self._pending_completions: list[_PendingCompletion] = []
        self._deferred_captures: dict[int, _DeferredCapture] = {}
        self._scheduled_targets: set[tuple[int, int]] = set()
        self._scheduled_sources: set[tuple[int, int]] = set()
        self._timings: list[_TimingPair] = []
        self._transfer_stream: Any | None = None
        self._staging_release_event: Any | None = None
        self._staging_state = SharedStagingState()
        self._final_receipt: dict[str, Any] | None = None
        self.source_capture_d2h_bytes = 0
        self.candidate_source_h2d_bytes = 0
        self.metadata_actual_d2h_bytes = 0
        self.output_mutation_count = 0
        self.duplicate_record_count = 0
        self.missing_record_count = 0
        self.unexpected_record_count = 0
        self.source_overwrite_count = 0
        self.dropped_source_count = 0
        self.incomplete_source_count = 0
        self.lineage_mismatch_count = 0
        self.lineage_diagnostic: dict[str, Any] | None = None
        self.staging_conflict_count = 0
        self.nonfinite_count = 0
        self.hot_path_forced_sync_count = 0
        self.finalization_sync_count = 0
        self.legacy_v2_cpu_oracle_count = 0
        self.legacy_all_candidate_d2h_count = 0
        self.completion_event_created_count = 0
        self.completion_event_recorded_count = 0
        self.capture_event_created_count = 0
        self.capture_event_recorded_count = 0
        self.oracle_dependency_registered_count = 0
        self.completion_query_count = 0
        self.completion_not_ready_count = 0
        self.evidence_commit_count = 0
        self.slot_release_requested_count = 0
        self.slot_release_completed_count = 0
        self.slot_returned_empty_count = 0
        self.duplicate_release_count = 0
        self.stale_completion_count = 0
        self.completion_commit_failure_count = 0
        self.completion_pump_reentry_count = 0
        self._completion_pump_active = False
        self.completion_pump_calls: dict[str, int] = {}
        self.peak_pending_completions = 0
        self.root_cause = "CALLBACK_ORDERING_GAP"
        if profile_digest != PROFILE_DIGEST:
            raise V4ObserverAbort("V4 observer profile digest changed")
        if len(self.scheduler_timesteps) != 20:
            raise V4ObserverAbort("V4 scheduler trace must contain exactly 20 steps")
        resources.acquire(generation_digest)
        self._transition("admitted")

    def _transition(self, target: str) -> None:
        if target not in self._TRANSITIONS[self.state]:
            raise V4ObserverAbort(f"invalid V4 lifecycle transition {self.state}->{target}")
        self.state = target
        self.lifecycle.append(target)

    def start_observing(self) -> None:
        self._transition("observing")

    def _native_error_fallback_allowed(self) -> bool:
        return False

    @staticmethod
    def _predicted_state(plan: Mapping[str, Any] | None) -> str:
        if not isinstance(plan, Mapping) or bool(plan.get("global_invalidation", True)):
            return "UNCERTAIN"
        stable = plan.get("stable_region_mask", 0)
        active = plan.get("active_mask", 0)
        uncertain = plan.get("uncertain_mask", 0)
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (stable, active, uncertain)
        ):
            return "UNCERTAIN"
        if stable & 1 and not ((active | uncertain) & 1):
            return "STABLE"
        if active & 1 and not (uncertain & 1):
            return "ACTIVE"
        return "UNCERTAIN"

    def _source_identity(self, block_index: int, source_step: int) -> SourceIdentity:
        return SourceIdentity(
            generation_digest=self.generation_digest,
            model_digest=self.model_digest,
            settings_digest=self.profile_digest,
            scheduler_digest=self.scheduler_digest,
            resolution="864x480",
            fps=24,
            block=block_index,
            region=REGION,
            source_step=source_step,
            source_scheduler_timestep=self.scheduler_timesteps[source_step],
            packed_row_layout_digest=PACKED_LAYOUT_DIGEST,
            shape=SOURCE_SHAPE,
            dtype="torch.bfloat16",
            device_kind="cpu-pinned",
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
            hardware_profile="Balanced12GB_RTX3060",
            cache_precision="EXACT_BF16",
        )

    def _source_lineage_components(
        self, *, block_index: int, source_step: int, legacy_digest: str
    ) -> dict[str, Any]:
        return build_source_components(
            generation_digest=self.generation_digest,
            profile_digest=self.profile_digest,
            model_digest=self.model_digest,
            inventory_digest=self._inventory_digest,
            layout_digest=PACKED_LAYOUT_DIGEST,
            scheduler_timesteps=self.scheduler_timesteps,
            block=block_index,
            source_step=source_step,
            tensor_shape=SOURCE_SHAPE,
            tensor_dtype="torch.bfloat16",
            completion_state="EVENT_RECORDED",
            legacy_lineage_digest=legacy_digest,
        )

    def lineage_diagnostic_receipt(self) -> dict[str, Any]:
        """Return bounded component evidence without tensor or prompt payloads."""

        return self.lineage_diagnostic or {
            "schema_version": "h3.v4.lineage-diagnostic.1",
            "matched": True,
            "mismatch_count": self.lineage_mismatch_count,
            "first_mismatch": None,
        }

    def _timed_events(self, kind: str, stream: Any) -> tuple[Any, Any]:
        start = self.torch.cuda.Event(enable_timing=True, blocking=False)
        end = self.torch.cuda.Event(enable_timing=True, blocking=False)
        start.record(stream)
        self._timings.append(_TimingPair(kind=kind, start=start, end=end))
        return start, end

    def _wait_for_staging(self, stream: Any) -> None:
        if self._staging_release_event is not None:
            stream.wait_event(self._staging_release_event)
            self._staging_release_event = None

    def _admit_capture(self, capture: _DeferredCapture) -> None:
        slot = self.resources.slots[capture.block_index]
        try:
            slot.begin_capture(capture.lineage_components)
            slot.mark_ready(
                lineage_digest=capture.lineage_digest,
                lineage_components=capture.lineage_components,
                completion_event=capture.completion_event,
            )
        except V4ContractError as error:
            self.completion_commit_failure_count += 1
            raise V4ObserverAbort("V4 deferred source admission failed") from error
        key = (capture.block_index, capture.source_step)
        self._seen_sources.add(key)
        self.source_capture_d2h_bytes += SOURCE_PAYLOAD_BYTES
        self.full_refreshes += 1
        self.eligible_source_steps_seen.add(capture.source_step)

    def _commit_completion(self, pending: _PendingCompletion) -> None:
        slot = self.resources.slots[pending.block_index]
        if pending.evidence_committed or pending.release_eligible:
            self.duplicate_release_count += 1
            raise V4ObserverAbort("V4 completion was committed twice")
        if pending.generation_digest != self.generation_digest:
            self.stale_completion_count += 1
            raise V4ObserverAbort("V4 completion generation changed")
        if slot.version != pending.slot_version:
            self.stale_completion_count += 1
            raise V4ObserverAbort("V4 late completion targeted a reused slot")
        if slot.lifecycle.identity != pending.source_identity:
            self.stale_completion_count += 1
            raise V4ObserverAbort("V4 completion source identity changed")

        record = dict(pending.pending_record)
        record["completion_state"] = "GPU_COMPLETE"
        self._pending_records.append(record)
        pending.evidence_committed = True
        self.evidence_commit_count += 1
        self._seen_targets.add(pending.target_key)
        self.candidate_source_h2d_bytes += SOURCE_PAYLOAD_BYTES
        self.region_upload_count += 1
        pending.release_eligible = True
        self.slot_release_requested_count += 1
        try:
            slot.complete_release(expected_version=pending.slot_version)
        except V4ContractError as error:
            self.completion_commit_failure_count += 1
            raise V4ObserverAbort("V4 completed evidence could not release its slot") from error
        self.slot_release_completed_count += 1
        self.slot_returned_empty_count += 1

        deferred = self._deferred_captures.pop(pending.block_index, None)
        if deferred is not None:
            self._admit_capture(deferred)

    def _pump_completions(self, position: str) -> int:
        """Commit completed oracle records without blocking the callback thread."""

        self.completion_pump_calls[position] = self.completion_pump_calls.get(position, 0) + 1
        if self._completion_pump_active:
            self.completion_pump_reentry_count += 1
            return 0
        self._completion_pump_active = True
        completed = 0
        try:
            retained: list[_PendingCompletion] = []
            for pending in self._pending_completions:
                self.completion_query_count += 1
                try:
                    ready = bool(pending.oracle_completion_event.query())
                except BaseException as error:
                    self.completion_commit_failure_count += 1
                    raise V4ObserverAbort("V4 oracle completion query failed") from error
                if not ready:
                    self.completion_not_ready_count += 1
                    retained.append(pending)
                    continue
                self._commit_completion(pending)
                completed += 1
            self._pending_completions = retained
            return completed
        finally:
            self._completion_pump_active = False

    def _exact_full(
        self,
        *,
        q: Any,
        k: Any,
        v: Any,
        attention: Any,
        options: Mapping[str, Any],
    ) -> Any:
        stream = self.torch.cuda.current_stream(device=q.device)
        _, end = self._timed_events("full_attention", stream)
        result = super()._exact_full(
            q=q,
            k=k,
            v=v,
            attention=attention,
            options=options,
        )
        end.record(stream)
        return result

    def _observe_full_compute_control(
        self,
        *,
        block_index: int,
        step: int,
        plan: Mapping[str, Any] | None,
        directive: str,
        stable_mask: int,
        full_core: Any,
    ) -> None:
        del directive, stable_mask
        if self.state != "observing":
            raise V4ObserverAbort("V4 callback executed outside observing state")
        self._pump_completions("callback_entry")
        event = self._event_by_target.get((block_index, step))
        if event is None:
            return
        key = (block_index, step)
        if key in self._seen_targets or key in self._scheduled_targets:
            self.duplicate_record_count += 1
            raise V4ObserverAbort("V4 duplicate target record")
        slot = self.resources.slots[block_index]
        expected_lineage = self._source_identity(block_index, event.source_step).lineage_digest()
        expected_components = self._source_lineage_components(
            block_index=block_index,
            source_step=event.source_step,
            legacy_digest=expected_lineage,
        )
        target_components = build_target_components(
            scheduler_timesteps=self.scheduler_timesteps,
            target_step=step,
            expected_source_step=event.source_step,
            block=block_index,
            target_sequence=event.ordinal,
        )
        if slot.state != SOURCE_SLOT_READY or slot.completion_event is None:
            self.incomplete_source_count += 1
            self.lineage_diagnostic = compare_lineage(
                expected=expected_components,
                actual=slot.lineage_components,
                target=target_components,
            )
            raise V4ObserverAbort(
                "V4 candidate source is incomplete: "
                f"slot={expected_components['source_slot_index']} "
                f"source_step={event.source_step} target_step={step} "
                f"block={block_index} region={REGION}"
            )
        comparison = compare_lineage(
            expected=expected_components,
            actual=slot.lineage_components,
            target=target_components,
        )
        if not comparison["matched"] or slot.lineage_digest != expected_lineage:
            self.lineage_mismatch_count += 1
            self.lineage_diagnostic = comparison
            first = self.lineage_diagnostic["first_mismatch_field"]
            raise V4ObserverAbort(
                "V4 candidate source lineage changed: "
                f"field={first} "
                f"expected={self.lineage_diagnostic['first_mismatch_expected']} "
                f"actual={self.lineage_diagnostic['first_mismatch_actual']} "
                f"slot={expected_components['source_slot_index']} "
                f"source_step={event.source_step} target_step={step} "
                f"block={block_index} region={REGION}"
            )
        try:
            slot.begin_consume(expected_components)
        except V4ContractError as error:
            self.lineage_mismatch_count += 1
            self.lineage_diagnostic = comparison
            raise V4ObserverAbort(str(error)) from error
        stream = self.torch.cuda.current_stream(device=full_core.device)
        self._wait_for_staging(stream)
        stream.wait_event(slot.completion_event)
        staging = self._region_staging
        if staging is None or int(staging.numel()) * int(staging.element_size()) != SOURCE_PAYLOAD_BYTES:
            self.staging_conflict_count += 1
            raise V4ObserverAbort("V4 shared staging shape changed")
        version_before = int(getattr(full_core, "_version", 0))
        observer_start, _ = self._timed_events("observer", stream)
        self._staging_state.transition("H2D_IN_FLIGHT", owner_ordinal=event.ordinal)
        _, h2d_end = self._timed_events("candidate_h2d", stream)
        staging.copy_(slot.payload, non_blocking=True)
        h2d_end.record(stream)
        self._staging_state.transition("GPU_READY", owner_ordinal=event.ordinal)
        source_summary = gpu_compressed_fingerprint(
            self.torch, staging, self._region_cache_positions[REGION]["representative"]
        )
        current_summary = gpu_indexed_compressed_fingerprint(
            self.torch,
            full_core,
            self._region_cache_indices[REGION],
            self._region_cache_positions[REGION]["representative"],
        )
        preliminary = gpu_preliminary_metrics(
            self.torch, source_summary, current_summary
        )
        _, oracle_end = self._timed_events("exact_gpu_oracle", stream)
        self._staging_state.transition("ORACLE_PROCESSING", owner_ordinal=event.ordinal)
        exact = gpu_exact_oracle_metrics_indexed(
            self.torch,
            staging,
            full_core,
            self._region_cache_indices[REGION],
            self._region_cache_positions[REGION]["representative"],
            self._region_cache_positions[REGION]["omitted"],
        )
        oracle_end.record(stream)
        metric_values = self.torch.cat((preliminary, exact)).float()
        self.resources.metric_rows[event.ordinal - 1].copy_(
            metric_values, non_blocking=True
        )
        completion = self.torch.cuda.Event(enable_timing=False, blocking=False)
        self.completion_event_created_count += 1
        completion.record(stream)
        self.completion_event_recorded_count += 1
        observer_pair = next(
            pair for pair in reversed(self._timings) if pair.start is observer_start
        )
        observer_pair.end.record(stream)
        self._staging_state.transition("FINALIZED", owner_ordinal=event.ordinal)
        self._staging_state.transition("FREE", owner_ordinal=event.ordinal)
        if int(getattr(full_core, "_version", 0)) != version_before:
            self.output_mutation_count += 1
            raise V4ObserverAbort("V4 observer mutated the Full Attention core")
        confidence = (
            plan.get("eye_confidence_ppm", [0] * 5)
            if isinstance(plan, Mapping)
            else [0] * 5
        )
        motion = (
            plan.get("eye_change_ppm", [1_000_000] * 5)
            if isinstance(plan, Mapping)
            else [1_000_000] * 5
        )
        pending_record = {
                "ordinal": event.ordinal,
                "evidence_label": HOLDOUT_LABEL,
                "generation_id": self.generation_digest,
                "step": step,
                "source_step": event.source_step,
                "block": block_index,
                "region": REGION,
                "full_q_row_start": 0,
                "full_q_row_count": int(full_core.shape[0]),
                "planned_q_row_count": PLANNED_Q_ROWS_PER_RECORD,
                "predicted_state": self._predicted_state(plan),
                "uncertainty_ppm": max(0, 1_000_000 - int(confidence[REGION + 1])),
                "motion_ppm": int(motion[REGION + 1]),
                "payload_bytes": SOURCE_PAYLOAD_BYTES,
                "effect_numerator": PLANNED_Q_ROWS_PER_RECORD,
                "effect_denominator": SOURCE_PAYLOAD_BYTES,
                "source_lineage_digest": expected_lineage,
                "layout_digest": PACKED_LAYOUT_DIGEST,
                "profile_digest": self.profile_digest,
                "source_available": True,
                "completion_state": "GPU_ENQUEUED",
                "bf16_bit_preserving_copy_path": True,
            }
        self._pending_completions.append(
            _PendingCompletion(
                block_index=block_index,
                slot_version=slot.version,
                generation_digest=self.generation_digest,
                source_identity=dict(slot.lifecycle.identity or {}),
                capture_completion_event=slot.completion_event,
                oracle_completion_event=completion,
                target_key=key,
                pending_record=pending_record,
            )
        )
        self._scheduled_targets.add(key)
        self.peak_pending_completions = max(
            self.peak_pending_completions, len(self._pending_completions)
        )
        self._pump_completions("callback_exit")

    def _refresh_cache(self, *, block_index: int, step: int, full_core: Any) -> None:
        self._pump_completions("before_capture_admission")
        if step not in SOURCE_STEPS:
            self.skipped_ineligible_source_refreshes += 1
            return
        key = (block_index, step)
        if key not in self._expected_sources:
            self.unexpected_record_count += 1
            raise V4ObserverAbort("V4 unexpected source capture key")
        if key in self._seen_sources or key in self._scheduled_sources:
            self.duplicate_record_count += 1
            raise V4ObserverAbort("V4 duplicate source capture")
        slot = self.resources.slots[block_index]
        identity = self._source_identity(block_index, step)
        lineage_digest = identity.lineage_digest()
        lineage_components = self._source_lineage_components(
            block_index=block_index,
            source_step=step,
            legacy_digest=lineage_digest,
        )
        deferred = slot.state == SOURCE_SLOT_CONSUMING
        if deferred and block_index in self._deferred_captures:
            self.source_overwrite_count += 1
            raise V4ObserverAbort("V4 deferred source capture already exists")
        if not deferred:
            try:
                slot.begin_capture(lineage_components)
            except V4ContractError as error:
                self.source_overwrite_count += 1
                raise V4ObserverAbort(str(error)) from error
        stream = self.torch.cuda.current_stream(device=full_core.device)
        self._wait_for_staging(stream)
        if deferred:
            pending = next(
                (
                    item
                    for item in self._pending_completions
                    if item.block_index == block_index and item.slot_version == slot.version
                ),
                None,
            )
            if pending is None:
                self.incomplete_source_count += 1
                raise V4ObserverAbort("V4 consuming slot has no oracle completion")
            stream.wait_event(pending.oracle_completion_event)
            self.oracle_dependency_registered_count += 1
        staging = self._region_staging
        if staging is None:
            raise V4ObserverAbort("V4 shared staging is unavailable")
        self.torch.index_select(
            full_core,
            0,
            self._region_cache_indices[REGION],
            out=staging,
        )
        producer_event = self.torch.cuda.Event(enable_timing=False, blocking=False)
        producer_event.record(stream)
        if self._transfer_stream is None:
            self._transfer_stream = self.torch.cuda.Stream(device=full_core.device)
        self._transfer_stream.wait_event(producer_event)
        _, d2h_end = self._timed_events("source_d2h", self._transfer_stream)
        slot.payload.copy_(staging, non_blocking=True)
        d2h_end.record(self._transfer_stream)
        completion = self.torch.cuda.Event(enable_timing=False, blocking=False)
        self.capture_event_created_count += 1
        completion.record(self._transfer_stream)
        self.capture_event_recorded_count += 1
        capture = _DeferredCapture(
            block_index=block_index,
            source_step=step,
            lineage_digest=lineage_digest,
            lineage_components=dict(lineage_components),
            completion_event=completion,
        )
        if deferred:
            self._deferred_captures[block_index] = capture
        else:
            try:
                slot.mark_ready(
                    lineage_digest=lineage_digest,
                    lineage_components=lineage_components,
                    completion_event=completion,
                )
            except V4ContractError as error:
                raise V4ObserverAbort(str(error)) from error
            self._seen_sources.add(key)
            self.source_capture_d2h_bytes += SOURCE_PAYLOAD_BYTES
            self.full_refreshes += 1
            self.eligible_source_steps_seen.add(step)
        self._staging_release_event = completion
        self._scheduled_sources.add(key)
        self._pump_completions("callback_exit")

    def _timing_totals(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for pair in self._timings:
            totals[pair.kind] = totals.get(pair.kind, 0.0) + float(
                pair.start.elapsed_time(pair.end)
            )
        return totals

    def _materialize_records(self) -> list[dict[str, Any]]:
        ordered = sorted(self._pending_records, key=lambda item: int(item["ordinal"]))
        values = [
            self.resources.metric_rows[int(item["ordinal"]) - 1].tolist()
            for item in ordered
        ]
        records: list[dict[str, Any]] = []
        for pending, row in zip(ordered, values):
            preliminary_finite = bool(row[2])
            corrected_finite = bool(row[8])
            preliminary_state = threshold_classification(
                cosine=float(row[0]),
                normalized_l2=float(row[1]),
                finite=preliminary_finite,
            )
            actual_safety = threshold_classification(
                cosine=float(row[6]),
                normalized_l2=float(row[7]),
                finite=corrected_finite,
            )
            if not corrected_finite:
                self.nonfinite_count += 1
            record = dict(pending)
            record.update(
                {
                    "completion_state": "COMPLETE",
                    "preliminary": {
                        "cosine": float(row[0]),
                        "normalized_l2": float(row[1]),
                        "finite": preliminary_finite,
                        "classification": preliminary_state,
                    },
                    "raw": {
                        "cosine": float(row[3]),
                        "normalized_l2": float(row[4]),
                        "finite": bool(row[5]),
                    },
                    "corrected": {
                        "cosine": float(row[6]),
                        "normalized_l2": float(row[7]),
                        "finite": corrected_finite,
                    },
                    "actual_safety": actual_safety,
                    "false_safe": pending["predicted_state"] == "STABLE"
                    and actual_safety != "SAFE",
                    "false_unsafe": pending["predicted_state"] != "STABLE"
                    and actual_safety == "SAFE",
                }
            )
            records.append(record)
        self.metadata_actual_d2h_bytes = len(records) * METRIC_COLUMN_COUNT * 4
        return records

    def finalize(self) -> dict[str, Any]:
        if self.state != "observing":
            raise V4ObserverAbort("V4 finalization requires observing state")
        self._transition("finalizing")
        finalization_started = perf_counter()
        try:
            self.torch.cuda.synchronize()
            self.finalization_sync_count += 1
            self._pump_completions("generation_finalize")
            if self._pending_completions or self._deferred_captures:
                raise V4ObserverAbort("V4 completion pump left pending work at finalize")
            records = self._materialize_records()
            missing_targets = self._expected_targets - self._seen_targets
            missing_sources = self._expected_sources - self._seen_sources
            unexpected_targets = self._seen_targets - self._expected_targets
            unexpected_sources = self._seen_sources - self._expected_sources
            self.missing_record_count = len(missing_targets) + len(missing_sources)
            self.unexpected_record_count += len(unexpected_targets) + len(unexpected_sources)
            terminal_unconsumed = sum(
                slot.state == SOURCE_SLOT_READY for slot in self.resources.slots.values()
            )
            slot_lifecycle = {
                "capture_count": sum(
                    slot.lifecycle.capture_count for slot in self.resources.slots.values()
                ),
                "consume_count": sum(
                    slot.lifecycle.consume_count for slot in self.resources.slots.values()
                ),
                "release_count": sum(
                    slot.lifecycle.release_count for slot in self.resources.slots.values()
                ),
                "invalid_transition_count": sum(
                    slot.lifecycle.invalid_transition_count
                    for slot in self.resources.slots.values()
                ),
                "peak_slot_count": len(self.resources.slots),
            }
            confusion = {
                "true_safe": sum(
                    item["predicted_state"] == "STABLE"
                    and item["actual_safety"] == "SAFE"
                    for item in records
                ),
                "false_safe": sum(bool(item["false_safe"]) for item in records),
                "true_unsafe": sum(
                    item["predicted_state"] != "STABLE"
                    and item["actual_safety"] != "SAFE"
                    for item in records
                ),
                "false_unsafe": sum(bool(item["false_unsafe"]) for item in records),
            }
            timing = self._timing_totals()
            integrity = {
                "controller_generation_one": True,
                "inventory_digest_match": frozen_inventory_digest()
                == self._inventory_digest,
                "source_capture_count_exact": len(self._seen_sources)
                == SOURCE_CAPTURE_COUNT,
                "exact_record_count_199": len(records) == MINIMUM_EXACT_RECORDS,
                "missing_zero": self.missing_record_count == 0,
                "unexpected_zero": self.unexpected_record_count == 0,
                "duplicate_zero": self.duplicate_record_count == 0,
                "source_overwrite_zero": self.source_overwrite_count == 0,
                "dropped_source_zero": self.dropped_source_count == 0,
                "incomplete_source_zero": self.incomplete_source_count == 0,
                "lineage_mismatch_zero": self.lineage_mismatch_count == 0,
                "staging_conflict_zero": self.staging_conflict_count == 0,
                "staging_state_free": self._staging_state.state == "FREE",
                "staging_transition_errors_zero": self._staging_state.invalid_transition_count
                == 0,
                "staging_overwrite_zero": self._staging_state.overwritten_staging_count
                == 0,
                "output_mutation_zero": self.output_mutation_count == 0,
                "source_d2h_exact": self.source_capture_d2h_bytes
                == SOURCE_CAPTURE_D2H_BYTES,
                "candidate_h2d_exact": self.candidate_source_h2d_bytes
                == MINIMUM_CANDIDATE_H2D_BYTES,
                "candidate_h2d_within_12_gib": self.candidate_source_h2d_bytes
                <= CANDIDATE_H2D_HARD_CAP_BYTES,
                "total_tensor_transfer_exact": self.source_capture_d2h_bytes
                + self.candidate_source_h2d_bytes
                == TOTAL_TENSOR_TRANSFER_BYTES,
                "total_tensor_transfer_within_32_gib": self.source_capture_d2h_bytes
                + self.candidate_source_h2d_bytes
                <= TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
                "metadata_within_one_mib": METADATA_D2H_BYTES <= 1024**2,
                "legacy_v2_cpu_oracle_zero": self.legacy_v2_cpu_oracle_count == 0,
                "legacy_all_candidate_d2h_zero": self.legacy_all_candidate_d2h_count
                == 0,
                "hot_path_forced_sync_zero": self.hot_path_forced_sync_count == 0,
                "partial_attention_zero": self.partial_attention_calls == 0,
                "terminal_unconsumed_sources_expected": terminal_unconsumed
                == len(SOURCE_BLOCKS) - 4,
                "slot_capture_count_exact": slot_lifecycle["capture_count"]
                == SOURCE_CAPTURE_COUNT,
                "slot_consume_count_exact": slot_lifecycle["consume_count"]
                == MINIMUM_EXACT_RECORDS,
                "slot_release_count_exact": slot_lifecycle["release_count"]
                == MINIMUM_EXACT_RECORDS,
                "slot_transition_errors_zero": slot_lifecycle[
                    "invalid_transition_count"
                ]
                == 0,
                "completion_events_created_recorded_exact": self.completion_event_created_count
                == self.completion_event_recorded_count
                == MINIMUM_EXACT_RECORDS,
                "capture_events_created_recorded_exact": self.capture_event_created_count
                == self.capture_event_recorded_count
                == SOURCE_CAPTURE_COUNT,
                "completion_queries_present": self.completion_query_count
                >= MINIMUM_EXACT_RECORDS,
                "evidence_commit_exact": self.evidence_commit_count
                == MINIMUM_EXACT_RECORDS,
                "release_requested_completed_exact": self.slot_release_requested_count
                == self.slot_release_completed_count
                == MINIMUM_EXACT_RECORDS,
                "slot_returned_empty_exact": self.slot_returned_empty_count
                == MINIMUM_EXACT_RECORDS,
                "duplicate_release_zero": self.duplicate_release_count == 0,
                "stale_completion_zero": self.stale_completion_count == 0,
                "completion_commit_failure_zero": self.completion_commit_failure_count
                == 0,
                "completion_pump_reentry_zero": self.completion_pump_reentry_count
                == 0,
                "pending_completion_zero": not self._pending_completions,
                "deferred_capture_zero": not self._deferred_captures,
            }
            if not all(integrity.values()):
                raise V4ObserverAbort("V4 observer integrity Gate failed")
            base = super().finalize()
            self._transition("complete")
            self._final_receipt = {
                **base,
                "schema_version": SCHEMA_VERSION,
                "profile_id": PROFILE_ID,
                "profile_digest": self.profile_digest,
                "inventory_digest": frozen_inventory_digest(),
                "generation_lifecycle": list(self.lifecycle),
                "generation_digest": self.generation_digest,
                "full_compute_only": True,
                "output_mutation_count": self.output_mutation_count,
                "selective_execution_count": 0,
                "partial_q_execution_count": 0,
                "attention_omission_count": 0,
                "safety_evidence": {
                    "label": HOLDOUT_LABEL,
                    "records": records,
                    "record_count": len(records),
                    "record_limit": MINIMUM_EXACT_RECORDS,
                    "complete": True,
                    "overflow": False,
                    "truncated": False,
                    "confusion_matrix": confusion,
                    "planned_q_rows": MINIMUM_PLANNED_Q_ROWS,
                    "full_q_rows": FULL_Q_ROWS,
                    "planned_q_reduction_ratio": MINIMUM_PLANNED_Q_RATIO,
                    "rust_tensor_transfer_bytes": 0,
                },
                "v4_oracle": {
                    "source_capture_count": len(self._seen_sources),
                    "exact_completed_record_count": len(records),
                    "terminal_unconsumed_source_count": terminal_unconsumed,
                    "terminal_unconsumed_sources_expected": len(SOURCE_BLOCKS) - 4,
                    "source_capture_d2h_bytes": self.source_capture_d2h_bytes,
                    "current_payload_d2h_bytes": 0,
                    "cpu_oracle_payload_d2h_bytes": 0,
                    "candidate_source_h2d_bytes": self.candidate_source_h2d_bytes,
                    "metadata_d2h_bytes": METADATA_D2H_BYTES,
                    "metadata_actual_metric_bytes": self.metadata_actual_d2h_bytes,
                    "total_tensor_transfer_bytes": self.source_capture_d2h_bytes
                    + self.candidate_source_h2d_bytes,
                    "host_source_bytes": self.resources.allocated_source_bytes,
                    "shared_gpu_staging_bytes": self.region_staging_peak_bytes,
                    "persistent_exact_gpu_source_bytes": 0,
                    "timing_ms": timing,
                    "evidence_finalization_seconds": perf_counter()
                    - finalization_started,
                    "finalization_sync_count": self.finalization_sync_count,
                    "integrity_checks": integrity,
                    "passed": all(integrity.values()),
                    "lineage_diagnostic": self.lineage_diagnostic_receipt(),
                    "source_slot_lifecycle": slot_lifecycle,
                    "async_completion": self._async_completion_receipt(),
                },
            }
            return self._final_receipt
        except BaseException as error:
            self.abort_reason = type(error).__name__
            if self.state != "aborted":
                self._transition("aborted")
            raise

    def abort(self, reason: str) -> None:
        if self.state in {"complete", "aborted"}:
            return
        self.abort_reason = reason
        self._transition("aborted")
        try:
            self.torch.cuda.synchronize()
            self.finalization_sync_count += 1
        except (RuntimeError, ValueError):
            pass
        try:
            self._pump_completions("abort_cleanup")
        except V4ObserverAbort:
            self.completion_commit_failure_count += 1

    def _async_completion_receipt(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "capture_event_created_count": self.capture_event_created_count,
            "capture_event_recorded_count": self.capture_event_recorded_count,
            "oracle_dependency_registered_count": self.oracle_dependency_registered_count,
            "oracle_completion_event_created_count": self.completion_event_created_count,
            "oracle_completion_event_recorded_count": self.completion_event_recorded_count,
            "completion_query_count": self.completion_query_count,
            "completion_not_ready_count": self.completion_not_ready_count,
            "evidence_commit_count": self.evidence_commit_count,
            "slot_release_requested_count": self.slot_release_requested_count,
            "slot_release_completed_count": self.slot_release_completed_count,
            "slot_returned_empty_count": self.slot_returned_empty_count,
            "duplicate_release_count": self.duplicate_release_count,
            "stale_completion_count": self.stale_completion_count,
            "completion_commit_failure_count": self.completion_commit_failure_count,
            "completion_pump_reentry_count": self.completion_pump_reentry_count,
            "completion_pump_calls": dict(self.completion_pump_calls),
            "peak_pending_completions": self.peak_pending_completions,
            "pending_completion_count": len(self._pending_completions),
            "deferred_capture_count": len(self._deferred_captures),
            "hot_path_forced_cpu_sync_count": self.hot_path_forced_sync_count,
        }

    def failure_receipt(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "profile_id": PROFILE_ID,
            "profile_digest": self.profile_digest,
            "inventory_digest": frozen_inventory_digest(),
            "generation_lifecycle": list(self.lifecycle),
            "abort_reason": self.abort_reason,
            "full_compute_only": True,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "full_attention_calls": self.full_attention_calls,
            "partial_attention_calls": self.partial_attention_calls,
            "source_capture_count": len(self._seen_sources),
            "exact_record_count": len(self._seen_targets),
            "source_capture_d2h_bytes": self.source_capture_d2h_bytes,
            "candidate_source_h2d_bytes": self.candidate_source_h2d_bytes,
            "output_mutation_count": self.output_mutation_count,
            "rust_tensor_transfer_bytes": 0,
            "lineage_diagnostic": self.lineage_diagnostic_receipt(),
            "source_slot_lifecycle": {
                "states": {
                    str(block): slot.state
                    for block, slot in self.resources.slots.items()
                },
                "versions": {
                    str(block): slot.version
                    for block, slot in self.resources.slots.items()
                },
                "capture_count": sum(
                    slot.lifecycle.capture_count for slot in self.resources.slots.values()
                ),
                "consume_count": sum(
                    slot.lifecycle.consume_count for slot in self.resources.slots.values()
                ),
                "release_count": sum(
                    slot.lifecycle.release_count for slot in self.resources.slots.values()
                ),
            },
            "async_completion": self._async_completion_receipt(),
        }

    def close(self) -> None:
        if self.state not in {"complete", "aborted"}:
            self.abort("controller closed before terminal state")
        self._pending_records.clear()
        self._pending_completions.clear()
        self._deferred_captures.clear()
        self._scheduled_targets.clear()
        self._scheduled_sources.clear()
        self._timings.clear()
        self._transfer_stream = None
        self._staging_release_event = None
        self._region_staging = None
        self._region_cache_indices.clear()
        self._region_cache_positions.clear()
        if self.resources.active_generation == self.generation_digest:
            self.resources.release(self.generation_digest)


if SOURCE_CAPTURE_COUNT != 208:
    raise RuntimeError("V4 source capture cardinality changed")
if len(FROZEN_EVENTS) != 199:
    raise RuntimeError("V4 target cardinality changed")
if TOTAL_TENSOR_TRANSFER_BYTES != 19_645_609_984:
    raise RuntimeError("V4 tensor transfer contract changed")
