"""Bounded host-staged CONTROL oracle for the H3 12 GB cache profile.

This module is model-free. It defines the memory and synchronization contract
for a future H3 Full Compute CONTROL, plus a small synthetic CUDA surface. It
does not submit workflows, omit Attention work, or authorize Selective reuse.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from time import perf_counter
from typing import Any, Mapping, Sequence

from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_gpu_local_evidence_v2 import (
    CALIBRATION_VETO_BLOCKS,
    HOLDOUT_STATUS,
    SAFE_GEOMETRY_BLOCKS,
    analyze_partial_control_receipt,
    metric,
)
from .h3_row_region_safety import FULL_Q_ROWS, MAX_EVIDENCE_RECORDS


SCHEMA_VERSION = "h3.12gb-hybrid-cache-staging-preflight.1"
ALGORITHM_ID = "GPU_PREDICTOR_HOST_BF16_CONTROL_ORACLE_V1"
BALANCED_PROFILE = "Balanced12GB"
QUALITY_PROFILE = "Quality24GBPlus"
CONTROL_ORACLE_MODE = "FULL_COMPUTE_CPU_EXACT_HOLDOUT_LABEL_ONLY"
QUALITY_ORACLE_MODE = "FULL_COMPUTE_GPU_RESIDENT_SIMULATED"

PHYSICAL_VRAM_BYTES = 12_884_377_600
HISTORICAL_COMFY_PEAK_VRAM_BYTES = 12_459_802_548
HISTORICAL_NVIDIA_PEAK_VRAM_BYTES = 11_990_466_560
HISTORICAL_ALLOCATED_PEAK_BYTES = 3_315_037_120
HISTORICAL_RESERVED_PEAK_BYTES = 3_690_987_520
HISTORICAL_SYSTEM_RAM_PEAK_BYTES = 62_809_526_272
HISTORICAL_PROCESS_TREE_RSS_PEAK_BYTES = 47_340_367_872

CANDIDATE_COUNT = 30
CANDIDATE_SLOT_BYTES = 48_269_312
CANDIDATE_AGGREGATE_BYTES = 1_448_079_360
CONTROL_STEP_UPPER_BOUND = 20
CONTROL_ORACLE_D2H_BYTES = CANDIDATE_AGGREGATE_BYTES * CONTROL_STEP_UPPER_BOUND
CONTROL_TRANSFER_LIMIT_BYTES = 32 * 1024**3
TRACE_MEASURED_MAX_IN_FLIGHT = 3
RING_SAFETY_SLOT_COUNT = 1
PINNED_RING_DEPTH = TRACE_MEASURED_MAX_IN_FLIGHT + RING_SAFETY_SLOT_COUNT
PINNED_HOST_TOTAL_BYTES = CANDIDATE_SLOT_BYTES * PINNED_RING_DEPTH
HOST_SOURCE_CACHE_BYTES = CANDIDATE_AGGREGATE_BYTES
GPU_SHARED_STAGING_BYTES = CANDIDATE_SLOT_BYTES
GPU_METRIC_BUFFER_BYTES = MAX_EVIDENCE_RECORDS * 11 * 4
CUDA_BOOKKEEPING_RESERVE_BYTES = 1 * 1024**2
HOST_OS_COMFY_RESERVE_BYTES = 1536 * 1024**2
QUALITY_PROJECTED_PEAK_BYTES = 15_355_989_428


class HybridPreflightError(RuntimeError):
    """Block CONTROL admission on a staging or oracle invariant failure."""


class RingBackpressureError(HybridPreflightError):
    """The CPU oracle did not release a pinned slot before reuse."""


_SLOT_TRANSITIONS = {
    "FREE": "D2H_IN_FLIGHT",
    "D2H_IN_FLIGHT": "CPU_READY",
    "CPU_READY": "PROCESSING",
    "PROCESSING": "FINALIZED",
    "FINALIZED": "FREE",
}


def _transition_preflight_slot(slot: Any, target: str) -> None:
    expected = _SLOT_TRANSITIONS.get(str(slot.state))
    if expected != target:
        raise HybridPreflightError(
            f"invalid preflight slot transition: {slot.state}->{target}"
        )
    slot.state = target


@dataclass
class _PinnedSlot:
    payload: Any
    event: Any
    state: str = "FREE"
    block: int = -1
    region: int = -1
    step: int = -1
    lineage_digest: str = ""
    source_identity: str = ""


def _metric_values(torch_module: Any, source: Any, current: Any) -> dict[str, Any]:
    rows = int(source.shape[0])
    representative_count = min(16, max(1, rows // 6))
    representative = torch_module.arange(
        representative_count, dtype=torch_module.long, device=source.device
    )
    omitted = torch_module.arange(
        representative_count, rows, dtype=torch_module.long, device=source.device
    )
    source_float = source.float()
    current_float = current.float()
    delta = (
        current_float.index_select(0, representative)
        - source_float.index_select(0, representative)
    ).mean(dim=0)

    def calculate(predicted: Any) -> dict[str, Any]:
        actual = current_float.index_select(0, omitted)
        prediction = predicted.index_select(0, omitted)
        difference = actual - prediction
        actual_norm = torch_module.sqrt((actual * actual).sum()).clamp_min(1e-12)
        predicted_norm = torch_module.sqrt((prediction * prediction).sum()).clamp_min(1e-12)
        values = {
            "cosine": (actual * prediction).sum() / (actual_norm * predicted_norm),
            "normalized_l2": torch_module.sqrt((difference * difference).sum()) / actual_norm,
        }
        values["finite"] = (
            torch_module.isfinite(actual).all()
            & torch_module.isfinite(prediction).all()
            & torch_module.isfinite(values["cosine"])
            & torch_module.isfinite(values["normalized_l2"])
        )
        return values

    raw = calculate(source_float)
    corrected = calculate(source_float + delta)
    return {"raw": raw, "corrected": corrected}


def _host_scalars(metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        group: {
            "cosine": float(values["cosine"].item()),
            "normalized_l2": float(values["normalized_l2"].item()),
            "finite": bool(values["finite"].item()),
        }
        for group, values in metrics.items()
    }


def _classification(metrics: Mapping[str, Mapping[str, Any]]) -> str:
    corrected = metrics["corrected"]
    if not bool(corrected["finite"]):
        return "INVALID"
    if (
        float(corrected["cosine"]) < CATASTROPHIC_COSINE_MIN
        or float(corrected["normalized_l2"]) > CATASTROPHIC_NORMALIZED_L2_MAX
    ):
        return "UNSAFE"
    return "SAFE"


class HybridControlOracleRing:
    """One-way async D2H ring with pageable BF16 source retention.

    ``enqueue`` is the only hot-path method. It never reads a CUDA scalar or
    waits for device completion. ``consume`` belongs to the background CPU
    worker and is the only place allowed to wait on a slot event.
    """

    def __init__(
        self,
        torch_module: Any,
        *,
        device: Any,
        slot_shape: Sequence[int],
        dtype: Any,
        ring_depth: int = PINNED_RING_DEPTH,
        maximum_records: int = MAX_EVIDENCE_RECORDS,
        veto_blocks: Sequence[int] = CALIBRATION_VETO_BLOCKS,
    ) -> None:
        if ring_depth < 2:
            raise ValueError("the bounded oracle ring requires at least two slots")
        if maximum_records <= 0 or maximum_records > MAX_EVIDENCE_RECORDS:
            raise ValueError("invalid evidence record bound")
        self.torch = torch_module
        self.device = device
        self.dtype = dtype
        self.maximum_records = int(maximum_records)
        self.veto_blocks = frozenset(int(value) for value in veto_blocks)
        self.transfer_stream = self.torch.cuda.Stream(device=device)
        self.slots = [
            _PinnedSlot(
                payload=self.torch.empty(
                    tuple(int(value) for value in slot_shape),
                    dtype=dtype,
                    device="cpu",
                    pin_memory=True,
                ),
                event=self.torch.cuda.Event(blocking=False),
            )
            for _ in range(int(ring_depth))
        ]
        self._write_index = 0
        self._source_cache: dict[tuple[int, int], Any] = {}
        self._source_steps: dict[tuple[int, int], int] = {}
        self._source_lineages: dict[tuple[int, int], str] = {}
        self._source_identities: set[str] = set()
        self.records: list[dict[str, Any]] = []
        self.d2h_bytes = 0
        self.duplicate_d2h_avoided_bytes = 0
        self.background_event_wait_count = 0
        self.ring_backpressure_count = 0
        self.ring_overflow_count = 0
        self.invalid_count = 0
        self.cpu_oracle_time_ms = 0.0
        self.d2h_transfer_time_ms = 0.0

    def enqueue(
        self,
        *,
        block: int,
        region: int,
        step: int,
        lineage_digest: str,
        payload: Any,
        producer_event: Any | None = None,
    ) -> bool:
        """Schedule one candidate D2H exactly once without a host wait."""

        if int(block) in self.veto_blocks:
            return False
        if len(lineage_digest) != 64 or payload.device.type != "cuda":
            self.invalid_count += 1
            return False
        if payload.dtype != self.dtype or tuple(payload.shape) != tuple(self.slots[0].payload.shape):
            self.invalid_count += 1
            return False
        identity = f"{lineage_digest}:{int(step)}:{int(block)}:{int(region)}"
        payload_bytes = int(payload.numel()) * int(payload.element_size())
        if identity in self._source_identities:
            self.duplicate_d2h_avoided_bytes += payload_bytes
            return True
        slot = self.slots[self._write_index]
        if slot.state != "FREE":
            self.ring_backpressure_count += 1
            self.ring_overflow_count += 1
            raise RingBackpressureError("pinned ring slot would be overwritten")
        with self.torch.cuda.stream(self.transfer_stream):
            if producer_event is not None:
                self.transfer_stream.wait_event(producer_event)
            slot.payload.copy_(payload, non_blocking=True)
            slot.event.record(self.transfer_stream)
        _transition_preflight_slot(slot, "D2H_IN_FLIGHT")
        slot.block = int(block)
        slot.region = int(region)
        slot.step = int(step)
        slot.lineage_digest = str(lineage_digest)
        slot.source_identity = identity
        self._source_identities.add(identity)
        self.d2h_bytes += payload_bytes
        self._write_index = (self._write_index + 1) % len(self.slots)
        return True

    def consume(self, slot_index: int) -> dict[str, Any] | None:
        """Wait in the background worker, run exact CPU metrics, then release."""

        slot = self.slots[int(slot_index)]
        if slot.state != "D2H_IN_FLIGHT":
            raise HybridPreflightError("only a D2H-in-flight slot may be consumed")
        self.background_event_wait_count += 1
        transfer_start = perf_counter()
        slot.event.synchronize()
        _transition_preflight_slot(slot, "CPU_READY")
        _transition_preflight_slot(slot, "PROCESSING")
        self.d2h_transfer_time_ms += (perf_counter() - transfer_start) * 1000.0
        key = (slot.block, slot.region)
        source = self._source_cache.get(key)
        result = None
        if source is not None:
            if (
                self._source_steps[key] + 1 != slot.step
                or self._source_lineages[key] != slot.lineage_digest
            ):
                self.invalid_count += 1
                raise HybridPreflightError("source lineage or step ordering changed")
            if len(self.records) >= self.maximum_records:
                self.ring_overflow_count += 1
                raise HybridPreflightError("bounded oracle evidence overflow")
            cpu_start = perf_counter()
            scalar_metrics = _host_scalars(_metric_values(self.torch, source, slot.payload))
            self.cpu_oracle_time_ms += (perf_counter() - cpu_start) * 1000.0
            result = {
                "step": slot.step,
                "source_step": self._source_steps[key],
                "block": slot.block,
                "region": slot.region,
                "lineage_digest": slot.lineage_digest,
                "metrics": scalar_metrics,
                "actual_safety": _classification(scalar_metrics),
            }
            self.records.append(result)
        self._source_cache[key] = slot.payload.clone()
        self._source_steps[key] = slot.step
        self._source_lineages[key] = slot.lineage_digest
        _transition_preflight_slot(slot, "FINALIZED")
        _transition_preflight_slot(slot, "FREE")
        return result

    def receipt(self) -> dict[str, Any]:
        """Return only measured synthetic counters; no H3 claims are implied."""

        return {
            "scope": "BOUNDED_SYNTHETIC_CUDA_ONLY",
            "record_count": len(self.records),
            "invalid_count": self.invalid_count,
            "D2H_TRANSFER_BYTES": metric(self.d2h_bytes, "MEASURED_SYNTHETIC", "bytes"),
            "H2D_TRANSFER_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "DUPLICATE_D2H_AVOIDED_BYTES": metric(
                self.duplicate_d2h_avoided_bytes, "MEASURED_SYNTHETIC", "bytes"
            ),
            "HOT_PATH_FORCED_SYNC_COUNT": metric(0, "STRUCTURAL_ZERO", "count"),
            "BACKGROUND_EVENT_WAIT_COUNT": metric(
                self.background_event_wait_count, "MEASURED_SYNTHETIC", "count"
            ),
            "RING_BACKPRESSURE_COUNT": metric(
                self.ring_backpressure_count, "MEASURED_SYNTHETIC", "count"
            ),
            "RING_OVERFLOW_COUNT": metric(
                self.ring_overflow_count, "MEASURED_SYNTHETIC", "count"
            ),
            "CPU_ORACLE_TIME_MS": metric(
                self.cpu_oracle_time_ms, "MEASURED_SYNTHETIC", "ms"
            ),
            "D2H_TRANSFER_TIME_MS": metric(
                self.d2h_transfer_time_ms, "MEASURED_SYNTHETIC", "ms"
            ),
        }


def _allocator_adjusted_incremental_bytes() -> int:
    additional = GPU_SHARED_STAGING_BYTES + GPU_METRIC_BUFFER_BYTES
    return ceil(
        additional * HISTORICAL_RESERVED_PEAK_BYTES / HISTORICAL_ALLOCATED_PEAK_BYTES
    )


def build_ring_capacity_admission(
    *,
    current_available_ram_bytes: int,
    required_slots: int = PINNED_RING_DEPTH,
    actual_slot_bytes: int = CANDIDATE_SLOT_BYTES,
    required_host_reserve_bytes: int = HOST_OS_COMFY_RESERVE_BYTES,
    non_ring_runtime_reserve_bytes: int = HOST_SOURCE_CACHE_BYTES,
) -> dict[str, Any]:
    """Admit the trace-derived ring without double-counting existing pinned RAM."""

    if required_slots < 2 or actual_slot_bytes <= 0:
        raise ValueError("ring capacity inputs must be positive")
    available_ring_bytes = max(
        0,
        int(current_available_ram_bytes)
        - int(required_host_reserve_bytes)
        - int(non_ring_runtime_reserve_bytes),
    )
    maximum_slots = available_ring_bytes // int(actual_slot_bytes)
    total_pinned_bytes = int(required_slots) * int(actual_slot_bytes)
    return {
        "available_system_ram_bytes": int(current_available_ram_bytes),
        "required_host_reserve_bytes": int(required_host_reserve_bytes),
        "non_ring_runtime_reserve_bytes": int(non_ring_runtime_reserve_bytes),
        "available_ring_bytes": available_ring_bytes,
        "actual_slot_bytes": int(actual_slot_bytes),
        "measured_maximum_in_flight": TRACE_MEASURED_MAX_IN_FLIGHT,
        "safety_slot_count": RING_SAFETY_SLOT_COUNT,
        "required_slots": int(required_slots),
        "maximum_slots": maximum_slots,
        "total_pinned_bytes": total_pinned_bytes,
        "admitted": int(required_slots) <= maximum_slots,
    }


def build_runtime_admission(
    *,
    physical_ram_bytes: int,
    current_available_ram_bytes: int,
    physical_vram_bytes: int = PHYSICAL_VRAM_BYTES,
    ring_depth: int = PINNED_RING_DEPTH,
) -> dict[str, Any]:
    """Build conservative 12 GB and simulated 24 GB+ memory ledgers."""

    allocator_increment = _allocator_adjusted_incremental_bytes()
    balanced_peak = (
        HISTORICAL_COMFY_PEAK_VRAM_BYTES
        + allocator_increment
        + CUDA_BOOKKEEPING_RESERVE_BYTES
    )
    vram_headroom = int(physical_vram_bytes) - balanced_peak
    ring_admission = build_ring_capacity_admission(
        current_available_ram_bytes=current_available_ram_bytes,
        required_slots=ring_depth,
    )
    pinned_host_total_bytes = CANDIDATE_SLOT_BYTES * int(ring_depth)
    host_increment = HOST_SOURCE_CACHE_BYTES + pinned_host_total_bytes
    host_peak = HISTORICAL_SYSTEM_RAM_PEAK_BYTES + host_increment
    host_headroom = int(physical_ram_bytes) - host_peak
    host_current_allocation_safe = (
        int(current_available_ram_bytes) >= host_increment + HOST_OS_COMFY_RESERVE_BYTES
    )
    host_historical_peak_safe = host_headroom >= HOST_OS_COMFY_RESERVE_BYTES
    host_safe = (
        host_current_allocation_safe
        and host_historical_peak_safe
        and bool(ring_admission["admitted"])
    )
    balanced_safe = balanced_peak < int(physical_vram_bytes) and host_safe

    common = {
        "algorithm_id": ALGORITHM_ID,
        "candidate_blocks": list(SAFE_GEOMETRY_BLOCKS),
        "calibration_veto_blocks": list(CALIBRATION_VETO_BLOCKS),
        "decision_location": "GPU_PRE_ATTENTION",
        "rust_boundary": "ONE_BOUNDED_METADATA_BATCH_PER_GENERATION",
        "rust_tensor_bytes": 0,
        "post_attention_label_online_use": False,
        "actual_attention_omission_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
    }
    balanced_receipt = {
        "PROFILE": BALANCED_PROFILE,
        "ORACLE_MODE": CONTROL_ORACLE_MODE,
        "GPU_SOURCE_CACHE_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
        "GPU_STAGING_BYTES": metric(GPU_SHARED_STAGING_BYTES, "PROJECTED", "bytes"),
        "GPU_METRIC_BUFFER_BYTES": metric(GPU_METRIC_BUFFER_BYTES, "PROJECTED", "bytes"),
        "PINNED_RING_SLOT_BYTES": metric(CANDIDATE_SLOT_BYTES, "DESIGN_BOUND", "bytes"),
        "PINNED_RING_DEPTH": metric(int(ring_depth), "TRACE_DERIVED_BOUND", "count"),
        "PINNED_HOST_TOTAL_BYTES": metric(
            pinned_host_total_bytes, "RAM_ADMITTED_BOUND", "bytes"
        ),
        "CONTROL_ORACLE_D2H_BYTES": metric(CONTROL_ORACLE_D2H_BYTES, "PROJECTED", "bytes"),
        "CONTROL_ORACLE_H2D_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
        "DUPLICATE_D2H_AVOIDED_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
        "DUPLICATE_H2D_AVOIDED_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
        "CUDA_STREAM_COUNT": metric(1, "DESIGN_BOUND", "count"),
        "CUDA_EVENT_COUNT": metric(int(ring_depth), "DESIGN_BOUND", "count"),
        "HOT_PATH_FORCED_SYNC_COUNT": metric(0, "STRUCTURAL_ZERO", "count"),
        "BACKGROUND_EVENT_WAIT_COUNT": metric(None, "NOT_EXECUTED", "count"),
        "RING_BACKPRESSURE_COUNT": metric(None, "NOT_EXECUTED", "count"),
        "RING_OVERFLOW_COUNT": metric(None, "NOT_EXECUTED", "count"),
        "CPU_ORACLE_TIME_MS": metric(None, "NOT_EXECUTED", "ms"),
        "D2H_TRANSFER_TIME_MS": metric(None, "NOT_EXECUTED", "ms"),
        "GPU_PREDICTOR_TIME_MS": metric(None, "NOT_EXECUTED", "ms"),
        "RUST_CALLS_PER_GENERATION": metric(1, "DESIGN_MAXIMUM", "count"),
        "RUST_TENSOR_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
        "PROJECTED_ATTENTION_TIME_SAVED_MS": metric(None, "UNKNOWN", "ms"),
        "PROJECTED_H2D_AND_SYNC_COST_MS": metric(None, "UNKNOWN", "ms"),
        "PROJECTED_NET_GAIN_MS": metric(None, "UNKNOWN", "ms"),
    }
    quality_receipt = {
        **balanced_receipt,
        "PROFILE": QUALITY_PROFILE,
        "ORACLE_MODE": QUALITY_ORACLE_MODE,
        "GPU_SOURCE_CACHE_BYTES": metric(CANDIDATE_AGGREGATE_BYTES, "SIMULATED", "bytes"),
        "CONTROL_ORACLE_D2H_BYTES": metric(0, "SIMULATED", "bytes"),
        "execution_status": "SIMULATED_NOT_EXECUTED",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "common_contract": common,
        "balanced_12gb": {
            "receipt": balanced_receipt,
            "persistent_full_source_cuda_bytes": 0,
            "host_source_cache_bytes": HOST_SOURCE_CACHE_BYTES,
            "candidate_aggregate_bytes_per_step": CANDIDATE_AGGREGATE_BYTES,
            "control_step_upper_bound": CONTROL_STEP_UPPER_BOUND,
            "projected_d2h_within_32gib": CONTROL_ORACLE_D2H_BYTES
            <= CONTROL_TRANSFER_LIMIT_BYTES,
            "allocator_reserved_increment_bytes": allocator_increment,
            "projected_peak_vram_bytes": balanced_peak,
            "physical_vram_bytes": int(physical_vram_bytes),
            "projected_vram_headroom_bytes": vram_headroom,
            "two_gib_reserve_satisfied": False,
            "BALANCED12GB_2GIB_RESERVE_SATISFIED": False,
            "host_ram": {
                "historical_system_peak_bytes": HISTORICAL_SYSTEM_RAM_PEAK_BYTES,
                "historical_process_tree_rss_peak_bytes": HISTORICAL_PROCESS_TREE_RSS_PEAK_BYTES,
                "source_cache_bytes": HOST_SOURCE_CACHE_BYTES,
                "pinned_ring_bytes": pinned_host_total_bytes,
                "ring_capacity_admission": ring_admission,
                "expected_peak_bytes": host_peak,
                "physical_ram_bytes": int(physical_ram_bytes),
                "current_available_ram_bytes": int(current_available_ram_bytes),
                "os_comfy_reserve_bytes": HOST_OS_COMFY_RESERVE_BYTES,
                "projected_headroom_bytes": host_headroom,
                "current_allocation_safe": host_current_allocation_safe,
                "historical_peak_safe": host_historical_peak_safe,
                "admission": "PASS" if host_safe else "BLOCK",
                "allocation_or_page_lock_failure": "BLOCK_CONTROL_SUBMISSION",
            },
            "runtime_admission": "PASS" if balanced_safe else "BLOCK",
        },
        "quality_24gb_plus": {
            "receipt": quality_receipt,
            "projected_peak_vram_bytes": QUALITY_PROJECTED_PEAK_BYTES,
            "execution_status": "SIMULATED_NOT_EXECUTED",
            "physical_24gb_device_present": int(physical_vram_bytes) >= 24 * 1024**3,
            "speed_claim": "NOT_EXECUTED",
            "quality_claim": "NOT_EXECUTED",
        },
        "vram_timeline": {
            "simultaneous_interval": "H3_ATTENTION_FULL_COMPUTE_WITH_ASYNC_D2H_STAGING",
            "historical_comfy_peak_bytes": HISTORICAL_COMFY_PEAK_VRAM_BYTES,
            "historical_nvidia_peak_bytes": HISTORICAL_NVIDIA_PEAK_VRAM_BYTES,
            "shared_staging_allocated_bytes": GPU_SHARED_STAGING_BYTES,
            "metric_buffer_allocated_bytes": GPU_METRIC_BUFFER_BYTES,
            "allocator_reserve_factor": HISTORICAL_RESERVED_PEAK_BYTES
            / HISTORICAL_ALLOCATED_PEAK_BYTES,
            "allocator_bookkeeping_reserve_bytes": CUDA_BOOKKEEPING_RESERVE_BYTES,
        },
        "future_selective_contract": {
            "execution_status": "NOT_EXECUTED",
            "source_storage": "BF16_PINNED_OR_PAGEABLE_HOST",
            "h2d_only_on_actual_cache_hit": True,
            "fixed_source_and_current_staging": True,
            "overlap_when_safe": True,
            "admit_only_when_attention_saved_exceeds_h2d_and_sync": True,
            "miss_timeout_lineage_scene_cut_action": "FULL_COMPUTE_REGION",
            "partial_full_xor_required": True,
            "quantized_cache_allowed": False,
            "actual_reuse_count": 0,
        },
        "control_submission_allowed": balanced_safe,
    }


def calibration_gate(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Reuse the immutable 279-record calibration without promoting it."""

    calibration = analyze_partial_control_receipt(receipt)
    potential = calibration["safe_geometry_potential"]
    return {
        "source_status": calibration["decision_input_status"],
        "holdout_status": HOLDOUT_STATUS,
        "record_count": calibration["record_count"],
        "selected_false_safe_count": calibration["conservative_pre_attention_veto"][
            "selected_calibration_false_safe"
        ],
        "veto_blocks": list(CALIBRATION_VETO_BLOCKS),
        "potential_candidate_count": len(SAFE_GEOMETRY_BLOCKS),
        "planned_q_rows": potential["planned_q_rows"],
        "full_q_rows": FULL_Q_ROWS,
        "planned_q_ratio": potential["planned_q_ratio"],
        "status": "CALIBRATION_GEOMETRY_ONLY",
    }
