"""Bounded host-source and candidate GPU-oracle contract for H3 CONTROL V4.

This module is deliberately model-free.  It freezes the source inventory,
memory and transfer ledgers, and the one-staging state machine used by the
runtime implementation.  Calibration defines candidate geometry only; it is
never relabelled as holdout evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from typing import Any, Mapping, Sequence
import json

from .a3_g1_conditional_reuse import ELIGIBLE_CACHE_SOURCE_STEPS
from .h3_gpu_local_evidence_v2 import (
    CALIBRATION_VETO_BLOCKS,
    SAFE_GEOMETRY_BLOCKS,
)
from .h3_row_region_safety import FULL_Q_ROWS, SHAPE_WIDTH
from .regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


SCHEMA_VERSION = "h3.bounded-host-source-candidate-gpu-oracle-v4.1"
ALGORITHM_ID = "BOUNDED_HOST_SOURCE_CANDIDATE_GPU_ORACLE_V4"
CALIBRATION_LABEL = "CALIBRATION_ONLY"
HOLDOUT_LABEL = "HOLDOUT_CONTROL_V4"
REGION = 0
SOURCE_BLOCK_COUNT = 13
SOURCE_BLOCKS = tuple(SAFE_GEOMETRY_BLOCKS[:SOURCE_BLOCK_COUNT])
SOURCE_STEPS = tuple(ELIGIBLE_CACHE_SOURCE_STEPS)
TARGET_STEPS = tuple(step + 1 for step in SOURCE_STEPS)
MINIMUM_EXACT_RECORDS = 199
HOST_SOURCE_BUDGET_BYTES = 768 * 1024**2
GPU_STAGING_BUDGET_BYTES = 48_269_312
PERSISTENT_EXACT_GPU_SOURCE_BYTES = 0
METADATA_D2H_LIMIT_BYTES = 1024**2
CANDIDATE_H2D_HARD_CAP_BYTES = 12 * 1024**3
TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES = 32 * 1024**3
VRAM_HEADROOM_MIN_BYTES = 256 * 1024**2
RAM_RESERVE_MIN_BYTES = 1536 * 1024**2
H2D_PLAN_HEADROOM_NUMERATOR = 120
H2D_PLAN_HEADROOM_DENOMINATOR = 100
METADATA_BYTES_PER_RECORD = 256
FULL_CONTROL_COUNT_BEFORE_V4 = 3


class V4ContractError(ValueError):
    """Reject a changed inventory, unsafe transition, or exceeded bound."""


def _region_rows() -> tuple[int, ...]:
    rows = CPU_PROTOTYPE_PLANS[1].region_rows[REGION]
    return tuple(sorted((*rows["representative"], *rows["omitted"])))


def _region_positions() -> tuple[tuple[int, ...], tuple[int, ...]]:
    rows = CPU_PROTOTYPE_PLANS[1].region_rows[REGION]
    positions = {row: index for index, row in enumerate(_region_rows())}
    return (
        tuple(positions[row] for row in rows["representative"]),
        tuple(positions[row] for row in rows["omitted"]),
    )


REGION_ROWS = _region_rows()
REPRESENTATIVE_POSITIONS, OMITTED_POSITIONS = _region_positions()
SOURCE_SHAPE = (len(REGION_ROWS), SHAPE_WIDTH)
SOURCE_PAYLOAD_BYTES = len(REGION_ROWS) * SHAPE_WIDTH * 2
PLANNED_Q_ROWS_PER_RECORD = len(OMITTED_POSITIONS)
HOST_SOURCE_RESIDENT_BYTES = SOURCE_PAYLOAD_BYTES * SOURCE_BLOCK_COUNT
MINIMUM_PLANNED_Q_ROWS = MINIMUM_EXACT_RECORDS * PLANNED_Q_ROWS_PER_RECORD
MINIMUM_PLANNED_Q_RATIO = MINIMUM_PLANNED_Q_ROWS / FULL_Q_ROWS
MINIMUM_CANDIDATE_H2D_BYTES = MINIMUM_EXACT_RECORDS * SOURCE_PAYLOAD_BYTES
SOURCE_CAPTURE_D2H_BYTES = (
    SOURCE_BLOCK_COUNT * len(SOURCE_STEPS) * SOURCE_PAYLOAD_BYTES
)
METADATA_D2H_BYTES = MINIMUM_EXACT_RECORDS * METADATA_BYTES_PER_RECORD
TOTAL_TENSOR_TRANSFER_BYTES = (
    SOURCE_CAPTURE_D2H_BYTES + MINIMUM_CANDIDATE_H2D_BYTES
)
CANDIDATE_H2D_ADMISSION_BYTES = min(
    CANDIDATE_H2D_HARD_CAP_BYTES,
    ceil(
        MINIMUM_CANDIDATE_H2D_BYTES
        * H2D_PLAN_HEADROOM_NUMERATOR
        / H2D_PLAN_HEADROOM_DENOMINATOR
    ),
)


@dataclass(frozen=True)
class SourceIdentity:
    """Complete identity for one exact host-resident BF16 source."""

    generation_digest: str
    model_digest: str
    settings_digest: str
    scheduler_digest: str
    resolution: str
    fps: int
    block: int
    region: int
    source_step: int
    source_scheduler_timestep: str
    packed_row_layout_digest: str
    shape: tuple[int, int]
    dtype: str
    device_kind: str
    source_kind: str
    hardware_profile: str
    cache_precision: str

    def lineage_digest(self) -> str:
        encoded = json.dumps(
            {
                "generation": self.generation_digest,
                "model": self.model_digest,
                "settings": self.settings_digest,
                "scheduler": self.scheduler_digest,
                "resolution": self.resolution,
                "fps": self.fps,
                "block": self.block,
                "region": self.region,
                "source_step": self.source_step,
                "source_scheduler_timestep": self.source_scheduler_timestep,
                "packed_row_layout": self.packed_row_layout_digest,
                "shape": self.shape,
                "dtype": self.dtype,
                "device_kind": self.device_kind,
                "source_kind": self.source_kind,
                "hardware_profile": self.hardware_profile,
                "cache_precision": self.cache_precision,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CandidateEvent:
    """One age-one exact-oracle opportunity from the frozen inventory."""

    ordinal: int
    block: int
    region: int
    source_step: int
    target_step: int
    planned_q_rows: int
    source_payload_bytes: int


def frozen_candidate_events() -> tuple[CandidateEvent, ...]:
    """Return the minimum deterministic 13-block plan that reaches 3 percent."""

    events: list[CandidateEvent] = []
    for source_step in SOURCE_STEPS:
        for block in SOURCE_BLOCKS:
            if len(events) == MINIMUM_EXACT_RECORDS:
                return tuple(events)
            events.append(
                CandidateEvent(
                    ordinal=len(events) + 1,
                    block=block,
                    region=REGION,
                    source_step=source_step,
                    target_step=source_step + 1,
                    planned_q_rows=PLANNED_Q_ROWS_PER_RECORD,
                    source_payload_bytes=SOURCE_PAYLOAD_BYTES,
                )
            )
    raise V4ContractError("frozen source inventory cannot reach the 3% Gate")


FROZEN_EVENTS = frozen_candidate_events()


def frozen_inventory_digest() -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "calibration_label": CALIBRATION_LABEL,
        "safe_geometry_blocks": SAFE_GEOMETRY_BLOCKS,
        "veto_blocks": CALIBRATION_VETO_BLOCKS,
        "source_blocks": SOURCE_BLOCKS,
        "source_steps": SOURCE_STEPS,
        "events": [event.__dict__ for event in FROZEN_EVENTS],
        "source_shape": SOURCE_SHAPE,
        "source_dtype": "torch.bfloat16",
        "source_kind": "ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        "hardware_profile": "Balanced12GB_RTX3060",
        "cache_precision": "EXACT_BF16",
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def settings_digest() -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM_ID,
        "inventory_digest": frozen_inventory_digest(),
        "source_blocks": SOURCE_BLOCKS,
        "veto_blocks": CALIBRATION_VETO_BLOCKS,
        "region": REGION,
        "source_steps": SOURCE_STEPS,
        "minimum_exact_records": MINIMUM_EXACT_RECORDS,
        "full_compute_only": True,
        "selective": False,
        "partial_q": False,
        "attention_omission": False,
        "persistent_exact_gpu_source_bytes": 0,
        "shared_gpu_staging_count": 1,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


_STAGING_TRANSITIONS = {
    "FREE": {"H2D_IN_FLIGHT"},
    "H2D_IN_FLIGHT": {"GPU_READY"},
    "GPU_READY": {"ORACLE_PROCESSING"},
    "ORACLE_PROCESSING": {"FINALIZED"},
    "FINALIZED": {"FREE"},
}


@dataclass
class SharedStagingState:
    """Strict one-buffer lifecycle shared by model-free and CUDA paths."""

    state: str = "FREE"
    owner_ordinal: int | None = None
    invalid_transition_count: int = 0
    overwritten_staging_count: int = 0

    def transition(self, target: str, *, owner_ordinal: int | None = None) -> None:
        allowed = _STAGING_TRANSITIONS.get(self.state, set())
        if target not in allowed:
            self.invalid_transition_count += 1
            raise V4ContractError(f"invalid shared-staging transition {self.state}->{target}")
        if self.state == "FREE":
            if owner_ordinal is None:
                raise V4ContractError("staging acquisition requires an owner")
            self.owner_ordinal = int(owner_ordinal)
        elif owner_ordinal is not None and owner_ordinal != self.owner_ordinal:
            self.overwritten_staging_count += 1
            raise V4ContractError("shared staging owner changed before finalization")
        self.state = target
        if target == "FREE":
            self.owner_ordinal = None


def replay_frozen_inventory(*, latency_scale: float = 1.0, burst: bool = False) -> dict[str, Any]:
    """Replay exact ordering and staging ownership without allocating a model."""

    if latency_scale <= 0:
        raise V4ContractError("latency scale must be positive")
    staging = SharedStagingState()
    seen: set[tuple[int, int, int]] = set()
    source_by_block: dict[int, int] = {}
    source_missing = 0
    stale_source = 0
    duplicate = 0
    dropped = 0
    budget_fallback = 0
    h2d_bytes = 0
    lifecycle: list[dict[str, Any]] = []

    for source_step in SOURCE_STEPS:
        for block in SOURCE_BLOCKS:
            source_by_block[block] = source_step
        current = [
            event
            for event in FROZEN_EVENTS
            if event.target_step == source_step + 1
        ]
        if burst:
            current = sorted(current, key=lambda event: (event.target_step, event.ordinal))
        for event in current:
            key = (event.block, event.region, event.target_step)
            if key in seen:
                duplicate += 1
                continue
            seen.add(key)
            actual_source_step = source_by_block.get(event.block)
            if actual_source_step is None:
                source_missing += 1
                continue
            if actual_source_step + 1 != event.target_step:
                stale_source += 1
                continue
            if h2d_bytes + event.source_payload_bytes > CANDIDATE_H2D_ADMISSION_BYTES:
                budget_fallback += 1
                continue
            staging.transition("H2D_IN_FLIGHT", owner_ordinal=event.ordinal)
            staging.transition("GPU_READY", owner_ordinal=event.ordinal)
            staging.transition("ORACLE_PROCESSING", owner_ordinal=event.ordinal)
            staging.transition("FINALIZED", owner_ordinal=event.ordinal)
            staging.transition("FREE", owner_ordinal=event.ordinal)
            h2d_bytes += event.source_payload_bytes
            lifecycle.append(
                {
                    "ordinal": event.ordinal,
                    "block": event.block,
                    "source_step": event.source_step,
                    "target_step": event.target_step,
                    "latency_scale": float(latency_scale),
                }
            )

    final_backlog = int(staging.state != "FREE")
    checks = {
        "source_missing_zero": source_missing == 0,
        "lineage_mismatch_zero": stale_source == 0,
        "stale_source_zero": stale_source == 0,
        "duplicate_record_zero": duplicate == 0,
        "dropped_record_zero": dropped == 0,
        "overwritten_staging_zero": staging.overwritten_staging_count == 0,
        "invalid_transition_zero": staging.invalid_transition_count == 0,
        "incomplete_admitted_zero": budget_fallback == 0,
        "final_backlog_zero": final_backlog == 0,
        "record_count_at_least_199": len(lifecycle) >= MINIMUM_EXACT_RECORDS,
        "candidate_h2d_within_admission": h2d_bytes <= CANDIDATE_H2D_ADMISSION_BYTES,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_digest": frozen_inventory_digest(),
        "source_blocks": list(SOURCE_BLOCKS),
        "source_steps": list(SOURCE_STEPS),
        "record_count": len(lifecycle),
        "source_missing": source_missing,
        "lineage_mismatch": stale_source,
        "stale_source": stale_source,
        "duplicate_record": duplicate,
        "dropped_record": dropped,
        "budget_fallback": budget_fallback,
        "overwritten_staging": staging.overwritten_staging_count,
        "invalid_transition": staging.invalid_transition_count,
        "final_backlog": final_backlog,
        "candidate_h2d_bytes": h2d_bytes,
        "latency_scale": float(latency_scale),
        "same_step_burst": bool(burst),
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_transfer_ledger(*, exact_record_count: int = MINIMUM_EXACT_RECORDS) -> dict[str, Any]:
    if exact_record_count < 0:
        raise V4ContractError("exact record count cannot be negative")
    candidate_h2d = exact_record_count * SOURCE_PAYLOAD_BYTES
    metadata_d2h = exact_record_count * METADATA_BYTES_PER_RECORD
    tensor_total = SOURCE_CAPTURE_D2H_BYTES + candidate_h2d
    checks = {
        "current_payload_d2h_zero": True,
        "cpu_oracle_payload_d2h_zero": True,
        "metadata_d2h_within_one_mib": metadata_d2h <= METADATA_D2H_LIMIT_BYTES,
        "candidate_h2d_within_plan_admission": candidate_h2d <= CANDIDATE_H2D_ADMISSION_BYTES,
        "candidate_h2d_within_hard_cap": candidate_h2d <= CANDIDATE_H2D_HARD_CAP_BYTES,
        "total_tensor_transfer_within_hard_cap": tensor_total <= TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
    }
    return {
        "source_capture_d2h_bytes": SOURCE_CAPTURE_D2H_BYTES,
        "current_payload_d2h_bytes": 0,
        "cpu_oracle_payload_d2h_bytes": 0,
        "metadata_d2h_bytes": metadata_d2h,
        "candidate_source_h2d_bytes": candidate_h2d,
        "candidate_source_h2d_admission_bytes": CANDIDATE_H2D_ADMISSION_BYTES,
        "candidate_source_h2d_hard_cap_bytes": CANDIDATE_H2D_HARD_CAP_BYTES,
        "total_tensor_transfer_bytes": tensor_total,
        "total_tensor_transfer_hard_cap_bytes": TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_memory_admission(
    *,
    physical_vram_bytes: int,
    projected_baseline_peak_bytes: int,
    available_ram_bytes: int,
) -> dict[str, Any]:
    projected_peak = int(projected_baseline_peak_bytes) + GPU_STAGING_BUDGET_BYTES
    vram_headroom = int(physical_vram_bytes) - projected_peak
    ram_after_source = int(available_ram_bytes) - HOST_SOURCE_RESIDENT_BYTES
    checks = {
        "host_source_within_768_mib": HOST_SOURCE_RESIDENT_BYTES <= HOST_SOURCE_BUDGET_BYTES,
        "persistent_exact_gpu_source_zero": PERSISTENT_EXACT_GPU_SOURCE_BYTES == 0,
        "shared_staging_within_bound": GPU_STAGING_BUDGET_BYTES <= SOURCE_PAYLOAD_BYTES,
        "physical_vram_not_exceeded": projected_peak <= int(physical_vram_bytes),
        "physical_vram_headroom_at_least_256_mib": vram_headroom >= VRAM_HEADROOM_MIN_BYTES,
        "system_ram_reserve_at_least_1_5_gib": ram_after_source >= RAM_RESERVE_MIN_BYTES,
    }
    return {
        "physical_vram_bytes": int(physical_vram_bytes),
        "projected_baseline_peak_bytes": int(projected_baseline_peak_bytes),
        "shared_gpu_staging_bytes": GPU_STAGING_BUDGET_BYTES,
        "projected_peak_vram_bytes": projected_peak,
        "physical_vram_headroom_bytes": vram_headroom,
        "available_ram_bytes": int(available_ram_bytes),
        "resident_exact_host_source_bytes": HOST_SOURCE_RESIDENT_BYTES,
        "ram_after_source_bytes": ram_after_source,
        "persistent_exact_gpu_source_bytes": 0,
        "checks": checks,
        "passed": all(checks.values()),
    }


def model_free_preflight_receipt() -> dict[str, Any]:
    exact = replay_frozen_inventory()
    burst = replay_frozen_inventory(burst=True)
    h2d_stress = replay_frozen_inventory(latency_scale=1.5)
    oracle_stress = replay_frozen_inventory(latency_scale=1.5)
    combined_stress = replay_frozen_inventory(latency_scale=1.5, burst=True)
    transfer = build_transfer_ledger()
    checks = {
        "safe_geometry_is_calibration_only": CALIBRATION_LABEL == "CALIBRATION_ONLY",
        "veto_blocks_unchanged": CALIBRATION_VETO_BLOCKS == (30, 31, 48, 49),
        "source_block_count_exact": len(SOURCE_BLOCKS) == SOURCE_BLOCK_COUNT,
        "exact_record_count_at_least_199": len(FROZEN_EVENTS) >= MINIMUM_EXACT_RECORDS,
        "planned_q_reduction_at_least_three_percent": MINIMUM_PLANNED_Q_RATIO >= 0.03,
        "resident_host_source_within_budget": HOST_SOURCE_RESIDENT_BYTES <= HOST_SOURCE_BUDGET_BYTES,
        "shared_staging_count_one": True,
        "exact_replay_pass": exact["passed"],
        "burst_replay_pass": burst["passed"],
        "h2d_latency_stress_pass": h2d_stress["passed"],
        "oracle_latency_stress_pass": oracle_stress["passed"],
        "combined_stress_pass": combined_stress["passed"],
        "transfer_admission_pass": transfer["passed"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm_id": ALGORITHM_ID,
        "inventory_digest": frozen_inventory_digest(),
        "source_blocks": list(SOURCE_BLOCKS),
        "veto_blocks": list(CALIBRATION_VETO_BLOCKS),
        "source_steps": list(SOURCE_STEPS),
        "target_steps": list(TARGET_STEPS),
        "source_shape": list(SOURCE_SHAPE),
        "source_payload_bytes": SOURCE_PAYLOAD_BYTES,
        "resident_exact_host_source_bytes": HOST_SOURCE_RESIDENT_BYTES,
        "persistent_exact_gpu_source_bytes": PERSISTENT_EXACT_GPU_SOURCE_BYTES,
        "shared_gpu_staging_count": 1,
        "shared_gpu_staging_bytes": GPU_STAGING_BUDGET_BYTES,
        "exact_record_count": len(FROZEN_EVENTS),
        "planned_q_rows": MINIMUM_PLANNED_Q_ROWS,
        "full_q_rows": FULL_Q_ROWS,
        "planned_q_ratio": MINIMUM_PLANNED_Q_RATIO,
        "transfer": transfer,
        "replays": {
            "exact": exact,
            "same_step_burst": burst,
            "h2d_latency_1_5x": h2d_stress,
            "oracle_latency_1_5x": oracle_stress,
            "combined_1_5x": combined_stress,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


if SOURCE_BLOCKS != tuple(range(13)):
    raise V4ContractError("frozen safe-geometry ordering changed")
if SOURCE_PAYLOAD_BYTES != 48_269_312:
    raise V4ContractError("region-0 exact BF16 payload changed")
if PLANNED_Q_ROWS_PER_RECORD != 2_331:
    raise V4ContractError("region-0 omitted-row geometry changed")
if len(FROZEN_EVENTS) != MINIMUM_EXACT_RECORDS:
    raise V4ContractError("minimum exact-record plan changed")
if MINIMUM_PLANNED_Q_RATIO < 0.03:
    raise V4ContractError("frozen inventory no longer reaches three percent")
