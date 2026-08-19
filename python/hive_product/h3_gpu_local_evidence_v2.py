"""GPU-local H3 CONTROL evidence preflight without model execution.

The calibration reader is deliberately specific to the incomplete 2026-08-19
CONTROL receipt.  It never promotes that partial evidence into a cache plan.
The CUDA collector is a bounded synthetic-verification surface: source payloads
remain on one GPU, reductions remain on that GPU, and only one compact metric
matrix is copied to pinned host memory during finalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from typing import Any, Mapping, Sequence

from .a3_g1_conditional_reuse import CORRECTION_CHUNK_ROWS
from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_row_region_safety import (
    CACHE_HARD_CAP_BYTES,
    FULL_Q_ROWS,
    MAX_EVIDENCE_RECORDS,
    SHAPE_WIDTH,
    TRANSFER_BUDGET_BYTES,
    _region_rows,
    evidence_design_receipt,
)
from .regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


SCHEMA_VERSION = "h3.gpu-local-evidence-transfer-v2-preflight.1"
ALGORITHM_ID = "GPU_LOCAL_BOUNDED_METRIC_BUFFER_V2"
CALIBRATION_STATUS = "CALIBRATION_ONLY"
HOLDOUT_STATUS = "UNKNOWN"
EXPECTED_RECORD_COUNT = 279
EXPECTED_FALSE_SAFE_COUNT = 19
EXPECTED_D2H_BYTES = 30_057_990_144
EXPECTED_H2D_BYTES = 12_856_610_816
EXPECTED_TRANSFER_BYTES = 42_914_600_960
TRANSFER_PREFLIGHT_LIMIT_BYTES = 32 * 1024**3
TRANSFER_HEADROOM_MIN_BYTES = 8 * 1024**3
KNOWN_C2_METADATA_D2H_BYTES = 3_840
METRIC_COLUMNS = (
    "raw_cosine",
    "raw_normalized_l2",
    "raw_normalized_mae",
    "raw_energy_ratio",
    "raw_finite",
    "corrected_cosine",
    "corrected_normalized_l2",
    "corrected_normalized_mae",
    "corrected_energy_ratio",
    "corrected_finite",
    "unsafe",
)
METRIC_DTYPE_BYTES = 4
CALIBRATION_VETO_BLOCKS = (30, 31, 48, 49)
SAFE_GEOMETRY_BLOCKS = tuple(range(30))
SAFE_GEOMETRY_REGION = 0


class PreflightInvariantError(ValueError):
    """Reject incomplete, changed, or internally inconsistent evidence."""


class EvidenceBufferOverflow(RuntimeError):
    """Reject an over-cap metric batch instead of truncating it."""


def metric(value: int | float | None, status: str, unit: str) -> dict[str, Any]:
    """Create a status-bearing receipt value; unknown values are never zeroed."""

    if status in {"UNKNOWN", "NOT_EXECUTED"} and value is not None:
        raise ValueError("unknown or unexecuted metrics must not carry a value")
    return {"value": value, "status": status, "unit": unit}


def evidence_admitted(*, completed: bool, overflow: bool, invalid: bool) -> bool:
    """Only one complete, finite, non-overflow generation may be admitted."""

    return bool(completed and not overflow and not invalid)


def _source_identity_digest(receipt: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    fields = (
        str(receipt["run_digest"]),
        str(receipt["model_revision_digest"]),
        str(receipt["workflow_revision_digest"]),
        str(receipt["settings_digest"]),
        str(int(record["source_step"])),
        str(int(record["block"])),
        str(int(record["region"])),
    )
    return sha256("|".join(fields).encode("ascii")).hexdigest()


def _planned_rows(region: int) -> int:
    return len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["omitted"])


def _attribute_false_safe(
    receipt: Mapping[str, Any], record: Mapping[str, Any]
) -> dict[str, Any]:
    region = int(record["region"])
    packed_rows = _region_rows(region)
    corrected = record["corrected"]
    step = int(record["step"])
    source_step = int(record["source_step"])
    return {
        "step": step,
        "source_step": source_step,
        "block": int(record["block"]),
        "region": region,
        "predicted_state": str(record["predicted_state"]),
        "motion_ppm": int(record["motion_ppm"]),
        "uncertainty_ppm": int(record["uncertainty_ppm"]),
        "corrected_cosine": float(corrected["cosine"]),
        "corrected_normalized_l2": float(corrected["normalized_l2"]),
        "packed_row_start": min(packed_rows),
        "packed_row_end": max(packed_rows),
        "packed_row_count": len(packed_rows),
        "cache_age": step - source_step,
        "source_identity_digest": _source_identity_digest(receipt, record),
        "payload_bytes": int(record["payload_bytes"]),
    }


def _transfer_ledger(receipt: Mapping[str, Any]) -> dict[str, int]:
    cache = receipt["attention_execution"]["cache"]
    d2h = int(cache["d2h_bytes"])
    h2d = int(cache["h2d_bytes"])
    total = int(cache["transfer_total_bytes"])
    if d2h != EXPECTED_D2H_BYTES or h2d != EXPECTED_H2D_BYTES:
        raise PreflightInvariantError("partial CONTROL transfer legs changed")
    if total != EXPECTED_TRANSFER_BYTES or d2h + h2d != total:
        raise PreflightInvariantError("partial CONTROL transfer ledger does not balance")
    return {
        "d2h_bytes": d2h,
        "h2d_bytes": h2d,
        "total_bytes": total,
        "hard_cap_bytes": int(cache["transfer_budget_bytes"]),
        "remaining_bytes": int(cache["transfer_budget_bytes"]) - total,
    }


def _profile_receipts(cache_bytes: int) -> dict[str, Any]:
    common = {
        "algorithm_id": ALGORITHM_ID,
        "candidate_blocks": list(SAFE_GEOMETRY_BLOCKS),
        "candidate_regions": [SAFE_GEOMETRY_REGION],
        "calibration_veto_blocks": list(CALIBRATION_VETO_BLOCKS),
        "cache_bytes": cache_bytes,
        "cache_hard_cap_bytes": CACHE_HARD_CAP_BYTES,
        "record_limit": MAX_EVIDENCE_RECORDS,
    }
    return {
        "Balanced12GB": {**common, "execution_status": "BOUNDED_SYNTHETIC_ONLY"},
        "Quality24GBPlus": {**common, "execution_status": "SIMULATED_NOT_EXECUTED"},
    }


def analyze_partial_control_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Attribute the failed CONTROL while preserving its holdout boundary."""

    safety = receipt["attention_execution"]["safety_evidence"]
    records = list(safety["records"])
    if len(records) != EXPECTED_RECORD_COUNT:
        raise PreflightInvariantError("partial CONTROL record count changed")
    if bool(safety.get("overflow", False)):
        raise PreflightInvariantError("overflowed evidence cannot be calibrated")
    false_safe_records = [record for record in records if bool(record["false_safe"])]
    if len(false_safe_records) != EXPECTED_FALSE_SAFE_COUNT:
        raise PreflightInvariantError("partial CONTROL false-safe count changed")

    attributions = [_attribute_false_safe(receipt, record) for record in false_safe_records]
    if any(item["cache_age"] != 1 for item in attributions):
        raise PreflightInvariantError("false-safe source age is not exactly one")
    risk_blocks = tuple(sorted({item["block"] for item in attributions}))
    if risk_blocks != CALIBRATION_VETO_BLOCKS:
        raise PreflightInvariantError("false-safe block cluster changed")

    selected_calibration = [
        record
        for record in records
        if str(record["predicted_state"]) == "STABLE"
        and int(record["block"]) not in CALIBRATION_VETO_BLOCKS
    ]
    selected_false_safe = sum(bool(record["false_safe"]) for record in selected_calibration)
    selected_invalid = sum(
        str(record["actual_safety"]) != "SAFE"
        or not bool(record["corrected"]["finite"])
        for record in selected_calibration
    )
    if selected_false_safe != 0 or selected_invalid != 0:
        raise PreflightInvariantError("conservative calibration veto is not false-safe zero")

    selected_calibration_rows = sum(
        _planned_rows(int(record["region"])) for record in selected_calibration
    )
    rows_per_event = len(SAFE_GEOMETRY_BLOCKS) * _planned_rows(SAFE_GEOMETRY_REGION)
    minimum_events = ceil((FULL_Q_ROWS * 3) / (100 * rows_per_event))
    potential_rows = rows_per_event * minimum_events
    potential_ratio = potential_rows / FULL_Q_ROWS
    if minimum_events > 16 or potential_ratio < 0.03:
        raise PreflightInvariantError("safe geometry cannot reach the unchanged three-percent Gate")

    payload_by_region = evidence_design_receipt()["payload_bytes_by_region"]
    cache_bytes = len(SAFE_GEOMETRY_BLOCKS) * int(payload_by_region[SAFE_GEOMETRY_REGION])
    if cache_bytes > CACHE_HARD_CAP_BYTES:
        raise PreflightInvariantError("safe geometry exceeds the two-GiB cache cap")

    metadata_bytes = MAX_EVIDENCE_RECORDS * len(METRIC_COLUMNS) * METRIC_DTYPE_BYTES
    projected_transfer = metadata_bytes + KNOWN_C2_METADATA_D2H_BYTES
    projected_headroom = TRANSFER_BUDGET_BYTES - projected_transfer
    if projected_transfer > TRANSFER_PREFLIGHT_LIMIT_BYTES:
        raise PreflightInvariantError("projected V2 CONTROL transfer exceeds 32 GiB")
    if projected_headroom < TRANSFER_HEADROOM_MIN_BYTES:
        raise PreflightInvariantError("projected V2 CONTROL transfer lacks 20 percent headroom")

    by_key: dict[str, int] = {}
    by_source_step: dict[str, int] = {}
    for item in attributions:
        key = f"b{item['block']}:r{item['region']}"
        by_key[key] = by_key.get(key, 0) + 1
        source = str(item["source_step"])
        by_source_step[source] = by_source_step.get(source, 0) + 1

    transfer = _transfer_ledger(receipt)
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_input_status": CALIBRATION_STATUS,
        "holdout_status": HOLDOUT_STATUS,
        "generation_completed": False,
        "admission_eligible": False,
        "rust_calls": 0,
        "rust_tensor_bytes": 0,
        "rust_calls_per_block": 0,
        "rust_calls_per_region": 0,
        "rust_calls_per_row": 0,
        "partial_q_executions": 0,
        "selective_executions": 0,
        "record_count": len(records),
        "record_limit": MAX_EVIDENCE_RECORDS,
        "overflow": False,
        "false_safe_count": len(attributions),
        "false_safe_attributions": attributions,
        "false_safe_clusters": {
            "by_block_region": dict(sorted(by_key.items())),
            "by_source_step": dict(sorted(by_source_step.items(), key=lambda item: int(item[0]))),
            "concentrated_blocks": list(risk_blocks),
        },
        "conservative_pre_attention_veto": {
            "rule": "FULL_COMPUTE_FOR_CALIBRATION_FALSE_SAFE_BLOCKS",
            "veto_blocks": list(CALIBRATION_VETO_BLOCKS),
            "uses_post_attention_metric_online": False,
            "selected_calibration_records": len(selected_calibration),
            "selected_calibration_false_safe": selected_false_safe,
            "selected_calibration_planned_q_rows": selected_calibration_rows,
            "selected_calibration_planned_q_ratio": selected_calibration_rows / FULL_Q_ROWS,
        },
        "safe_geometry_potential": {
            "candidate_blocks": list(SAFE_GEOMETRY_BLOCKS),
            "region": SAFE_GEOMETRY_REGION,
            "minimum_age_one_events_for_three_percent": minimum_events,
            "available_age_one_source_intervals": 16,
            "planned_q_rows": potential_rows,
            "planned_q_ratio": potential_ratio,
            "status": "GEOMETRY_POTENTIAL_NOT_HOLDOUT_RESULT",
        },
        "gpu_local_cache": {
            "payload_bytes": cache_bytes,
            "hard_cap_bytes": CACHE_HARD_CAP_BYTES,
            "within_cap": cache_bytes <= CACHE_HARD_CAP_BYTES,
            "control_evidence_cache_only": True,
            "future_selective_cache_separate": True,
            "actual_h3_vram_admission": "NOT_EXECUTED",
        },
        "failed_control_transfer_ledger": transfer,
        "projected_control_transfer_ledger": {
            "evidence_metadata_d2h_bytes": metadata_bytes,
            "known_c2_metadata_d2h_bytes": KNOWN_C2_METADATA_D2H_BYTES,
            "cache_payload_d2h_bytes": 0,
            "cache_payload_h2d_bytes": 0,
            "total_bytes": projected_transfer,
        },
        "profiles": _profile_receipts(cache_bytes),
        "performance_receipt": {
            "EVIDENCE_METADATA_D2H_BYTES": metric(metadata_bytes, "PROJECTED", "bytes"),
            "CACHE_PAYLOAD_D2H_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "CACHE_PAYLOAD_H2D_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "DUPLICATE_D2H_AVOIDED_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "DUPLICATE_H2D_AVOIDED_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "GPU_REDUCTION_KERNEL_TIME_MS": metric(None, "NOT_EXECUTED", "ms"),
            "TRANSFER_TIME_MS": metric(None, "NOT_EXECUTED", "ms"),
            "CUDA_SYNC_COUNT": metric(None, "NOT_EXECUTED", "count"),
            "FORCED_HOT_PATH_SYNC_COUNT": metric(0, "STRUCTURAL_ZERO", "count"),
            "BATCH_FLUSH_COUNT": metric(None, "NOT_EXECUTED", "count"),
            "RUST_CALLS_PER_GENERATION": metric(0, "STRUCTURAL_ZERO", "count"),
            "RUST_TENSOR_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            "PROJECTED_CONTROL_TOTAL_TRANSFER_BYTES": metric(
                projected_transfer, "PROJECTED", "bytes"
            ),
            "PROJECTED_CONTROL_TRANSFER_HEADROOM_BYTES": metric(
                projected_headroom, "PROJECTED", "bytes"
            ),
            "PROJECTED_ATTENTION_TIME_SAVED_MS": metric(None, "UNKNOWN", "ms"),
            "PROJECTED_TRANSFER_AND_SYNC_COST_MS": metric(None, "UNKNOWN", "ms"),
            "PROJECTED_NET_GAIN_MS": metric(None, "UNKNOWN", "ms"),
        },
    }


@dataclass
class _GpuSourceSlot:
    row_indices: Any
    representative_positions: Any
    omitted_positions: Any
    source: Any
    current: Any
    ready_event: Any
    source_step: int = -1
    lineage_digest: str = ""
    valid: bool = False


class GpuLocalEvidenceCollector:
    """Bounded GPU-local payload cache with one compact final D2H flush."""

    def __init__(
        self,
        torch_module: Any,
        *,
        device: Any,
        measured_free_vram_bytes: int,
        minimum_reserve_bytes: int,
        maximum_records: int = MAX_EVIDENCE_RECORDS,
        veto_blocks: Sequence[int] = CALIBRATION_VETO_BLOCKS,
    ) -> None:
        if maximum_records <= 0 or maximum_records > MAX_EVIDENCE_RECORDS:
            raise ValueError("invalid evidence record bound")
        if measured_free_vram_bytes <= 0 or minimum_reserve_bytes < 0:
            raise ValueError("measured free VRAM and reserve are required")
        if measured_free_vram_bytes <= minimum_reserve_bytes:
            raise ValueError("measured free VRAM does not satisfy the reserve")
        self.torch = torch_module
        self.device = device
        self.maximum_records = int(maximum_records)
        self.measured_free_vram_bytes = int(measured_free_vram_bytes)
        self.minimum_reserve_bytes = int(minimum_reserve_bytes)
        self.veto_blocks = frozenset(int(value) for value in veto_blocks)
        self.metric_buffer = self.torch.empty(
            (self.maximum_records, len(METRIC_COLUMNS)),
            dtype=self.torch.float32,
            device=device,
        )
        self.host_metric_buffer = self.torch.empty(
            (self.maximum_records, len(METRIC_COLUMNS)),
            dtype=self.torch.float32,
            device="cpu",
            pin_memory=True,
        )
        self._kernel_starts = [
            self.torch.cuda.Event(enable_timing=True) for _ in range(self.maximum_records)
        ]
        self._kernel_ends = [
            self.torch.cuda.Event(enable_timing=True) for _ in range(self.maximum_records)
        ]
        self._flush_start = self.torch.cuda.Event(enable_timing=True)
        self._flush_end = self.torch.cuda.Event(enable_timing=True)
        self._slots: dict[tuple[int, int], _GpuSourceSlot] = {}
        self._metadata: list[dict[str, Any]] = []
        self._source_identities: set[str] = set()
        self._finalized = False
        self.overflow = False
        self.invalid_count = 0
        self.duplicate_d2h_avoided_bytes = 0
        self.duplicate_h2d_avoided_bytes = 0
        self.persistent_cache_bytes = 0
        self.staging_bytes = 0
        self.pre_attention_veto_count = 0

    def prepare_slot(
        self,
        *,
        block: int,
        region: int,
        row_indices: Any,
        representative_positions: Any,
        omitted_positions: Any,
        width: int,
        dtype: Any,
    ) -> bool:
        """Allocate all persistent payload and staging storage before the hot path."""

        key = (int(block), int(region))
        if key[0] in self.veto_blocks:
            self.pre_attention_veto_count += 1
            return False
        if key in self._slots:
            raise ValueError("duplicate GPU-local source slot")
        rows = int(row_indices.numel())
        if rows <= 0 or int(width) <= 0:
            raise ValueError("empty GPU-local source slot")
        element_bytes = int(self.torch.empty((), dtype=dtype, device=self.device).element_size())
        source_bytes = rows * int(width) * element_bytes
        admitted_bytes = min(
            CACHE_HARD_CAP_BYTES,
            self.measured_free_vram_bytes - self.minimum_reserve_bytes,
        )
        if self.persistent_cache_bytes + source_bytes > admitted_bytes:
            return False
        self._slots[key] = _GpuSourceSlot(
            row_indices=row_indices,
            representative_positions=representative_positions,
            omitted_positions=omitted_positions,
            source=self.torch.empty((rows, int(width)), dtype=dtype, device=self.device),
            current=self.torch.empty((rows, int(width)), dtype=dtype, device=self.device),
            ready_event=self.torch.cuda.Event(blocking=False),
        )
        self.persistent_cache_bytes += source_bytes
        self.staging_bytes += source_bytes
        return True

    def capture_source(
        self,
        *,
        block: int,
        region: int,
        source_step: int,
        lineage_digest: str,
        full_core: Any,
    ) -> bool:
        """Capture one source identity on GPU without payload D2H."""

        slot = self._slots.get((int(block), int(region)))
        if slot is None or len(lineage_digest) != 64:
            self.invalid_count += 1
            return False
        source_identity = f"{lineage_digest}:{int(source_step)}:{int(block)}:{int(region)}"
        payload_bytes = int(slot.source.numel()) * int(slot.source.element_size())
        if source_identity in self._source_identities:
            self.duplicate_d2h_avoided_bytes += payload_bytes
            return True
        self.torch.index_select(full_core, 0, slot.row_indices, out=slot.source)
        slot.ready_event.record(self.torch.cuda.current_stream(device=self.device))
        slot.source_step = int(source_step)
        slot.lineage_digest = str(lineage_digest)
        slot.valid = True
        self._source_identities.add(source_identity)
        return True

    @staticmethod
    def _metric_result(accumulator: Mapping[str, Any], torch_module: Any) -> tuple[Any, ...]:
        actual_norm = torch_module.sqrt(accumulator["actual_sq"]).clamp_min(1e-12)
        predicted_norm = torch_module.sqrt(accumulator["predicted_sq"]).clamp_min(1e-12)
        cosine = accumulator["dot"] / (actual_norm * predicted_norm)
        normalized_l2 = torch_module.sqrt(accumulator["diff_sq"]) / actual_norm
        normalized_mae = accumulator["abs_diff"] / accumulator["actual_abs"].clamp_min(1e-12)
        energy_ratio = predicted_norm / actual_norm
        finite = accumulator["finite"] & torch_module.isfinite(
            torch_module.stack((cosine, normalized_l2, normalized_mae, energy_ratio))
        ).all()
        return cosine, normalized_l2, normalized_mae, energy_ratio, finite

    def _bounded_metrics(self, slot: _GpuSourceSlot) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        representative = slot.representative_positions
        omitted = slot.omitted_positions
        current_rep = slot.current.index_select(0, representative).float()
        source_rep = slot.source.index_select(0, representative).float()
        delta = (current_rep - source_rep).mean(dim=0)
        del current_rep, source_rep

        zero = lambda: self.torch.zeros((), dtype=self.torch.float32, device=self.device)
        accumulators = {
            kind: {
                "dot": zero(),
                "actual_sq": zero(),
                "predicted_sq": zero(),
                "diff_sq": zero(),
                "abs_diff": zero(),
                "actual_abs": zero(),
                "finite": self.torch.ones((), dtype=self.torch.bool, device=self.device),
            }
            for kind in ("raw", "corrected")
        }
        count = int(omitted.numel())
        for start in range(0, count, CORRECTION_CHUNK_ROWS):
            stop = min(count, start + CORRECTION_CHUNK_ROWS)
            positions = omitted[start:stop]
            actual = slot.current.index_select(0, positions).float()
            cached = slot.source.index_select(0, positions).float()
            corrected = cached + delta
            for kind, predicted in (("raw", cached), ("corrected", corrected)):
                accumulator = accumulators[kind]
                difference = actual - predicted
                accumulator["dot"].add_((actual * predicted).sum())
                accumulator["actual_sq"].add_((actual * actual).sum())
                accumulator["predicted_sq"].add_((predicted * predicted).sum())
                accumulator["diff_sq"].add_((difference * difference).sum())
                accumulator["abs_diff"].add_(difference.abs().sum())
                accumulator["actual_abs"].add_(actual.abs().sum())
                accumulator["finite"].logical_and_(
                    self.torch.isfinite(actual).all() & self.torch.isfinite(predicted).all()
                )
            del actual, cached, corrected
        return (
            self._metric_result(accumulators["raw"], self.torch),
            self._metric_result(accumulators["corrected"], self.torch),
        )

    def observe(
        self,
        *,
        block: int,
        region: int,
        step: int,
        lineage_digest: str,
        predicted_state: str,
        uncertainty_ppm: int,
        motion_ppm: int,
        full_core: Any,
    ) -> bool:
        """Reduce one exact Full-Compute observation without a host metric read."""

        if len(self._metadata) >= self.maximum_records:
            self.overflow = True
            raise EvidenceBufferOverflow("GPU metric buffer capacity exceeded")
        slot = self._slots.get((int(block), int(region)))
        if (
            slot is None
            or not slot.valid
            or slot.source_step + 1 != int(step)
            or slot.lineage_digest != str(lineage_digest)
        ):
            self.invalid_count += 1
            return False

        index = len(self._metadata)
        stream = self.torch.cuda.current_stream(device=self.device)
        stream.wait_event(slot.ready_event)
        self._kernel_starts[index].record(stream)
        self.torch.index_select(full_core, 0, slot.row_indices, out=slot.current)
        raw, corrected = self._bounded_metrics(slot)
        unsafe = (
            (~corrected[4])
            | (corrected[0] < CATASTROPHIC_COSINE_MIN)
            | (corrected[1] > CATASTROPHIC_NORMALIZED_L2_MAX)
        )
        row = self.torch.stack(
            (*raw[:4], raw[4].to(dtype=self.torch.float32), *corrected[:4], corrected[4].to(dtype=self.torch.float32), unsafe.to(dtype=self.torch.float32))
        )
        self.metric_buffer[index].copy_(row)
        self._kernel_ends[index].record(stream)
        payload_bytes = int(slot.source.numel()) * int(slot.source.element_size())
        self._metadata.append(
            {
                "step": int(step),
                "source_step": slot.source_step,
                "block": int(block),
                "region": int(region),
                "predicted_state": str(predicted_state),
                "uncertainty_ppm": int(uncertainty_ppm),
                "motion_ppm": int(motion_ppm),
                "payload_bytes": payload_bytes,
                "cache_age": int(step) - slot.source_step,
                "lineage_digest": str(lineage_digest),
            }
        )
        return True

    def finalize(self, *, completed: bool) -> dict[str, Any]:
        """Perform one bounded metadata flush and one final-only CUDA wait."""

        if self._finalized:
            raise RuntimeError("GPU-local evidence collector already finalized")
        self._finalized = True
        count = len(self._metadata)
        stream = self.torch.cuda.current_stream(device=self.device)
        self._flush_start.record(stream)
        if count:
            self.host_metric_buffer[:count].copy_(self.metric_buffer[:count], non_blocking=True)
        self._flush_end.record(stream)
        self._flush_end.synchronize()
        values = self.host_metric_buffer[:count].tolist()
        records = []
        for metadata, row in zip(self._metadata, values):
            metrics = dict(zip(METRIC_COLUMNS, row))
            unsafe = bool(metrics.pop("unsafe"))
            records.append(
                {
                    **metadata,
                    "raw": {
                        "cosine": metrics["raw_cosine"],
                        "normalized_l2": metrics["raw_normalized_l2"],
                        "normalized_mae": metrics["raw_normalized_mae"],
                        "energy_ratio": metrics["raw_energy_ratio"],
                        "finite": bool(metrics["raw_finite"]),
                    },
                    "corrected": {
                        "cosine": metrics["corrected_cosine"],
                        "normalized_l2": metrics["corrected_normalized_l2"],
                        "normalized_mae": metrics["corrected_normalized_mae"],
                        "energy_ratio": metrics["corrected_energy_ratio"],
                        "finite": bool(metrics["corrected_finite"]),
                    },
                    "actual_safety": "UNSAFE" if unsafe else "SAFE",
                    "false_safe": metadata["predicted_state"] == "STABLE" and unsafe,
                    "false_unsafe": metadata["predicted_state"] != "STABLE" and not unsafe,
                }
            )
        kernel_ms = sum(
            self._kernel_starts[index].elapsed_time(self._kernel_ends[index])
            for index in range(count)
        )
        transfer_ms = self._flush_start.elapsed_time(self._flush_end)
        metadata_bytes = count * len(METRIC_COLUMNS) * METRIC_DTYPE_BYTES
        admitted = evidence_admitted(
            completed=completed,
            overflow=self.overflow,
            invalid=self.invalid_count > 0 or any(not record["corrected"]["finite"] for record in records),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "scope": "BOUNDED_SYNTHETIC_CUDA_ONLY",
            "record_count": count,
            "record_limit": self.maximum_records,
            "overflow": self.overflow,
            "invalid_count": self.invalid_count,
            "admission_eligible": admitted,
            "pre_attention_veto_count": self.pre_attention_veto_count,
            "persistent_cache_bytes": self.persistent_cache_bytes,
            "staging_bytes": self.staging_bytes,
            "measured_free_vram_bytes": self.measured_free_vram_bytes,
            "minimum_reserve_bytes": self.minimum_reserve_bytes,
            "records": records,
            "performance_receipt": {
                "EVIDENCE_METADATA_D2H_BYTES": metric(metadata_bytes, "MEASURED_SYNTHETIC", "bytes"),
                "CACHE_PAYLOAD_D2H_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
                "CACHE_PAYLOAD_H2D_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
                "DUPLICATE_D2H_AVOIDED_BYTES": metric(
                    self.duplicate_d2h_avoided_bytes, "MEASURED_SYNTHETIC", "bytes"
                ),
                "DUPLICATE_H2D_AVOIDED_BYTES": metric(
                    self.duplicate_h2d_avoided_bytes, "MEASURED_SYNTHETIC", "bytes"
                ),
                "GPU_REDUCTION_KERNEL_TIME_MS": metric(kernel_ms, "MEASURED_SYNTHETIC", "ms"),
                "TRANSFER_TIME_MS": metric(transfer_ms, "MEASURED_SYNTHETIC", "ms"),
                "CUDA_SYNC_COUNT": metric(1, "MEASURED_SYNTHETIC", "count"),
                "FORCED_HOT_PATH_SYNC_COUNT": metric(0, "STRUCTURAL_ZERO", "count"),
                "BATCH_FLUSH_COUNT": metric(1, "MEASURED_SYNTHETIC", "count"),
                "RUST_CALLS_PER_GENERATION": metric(0, "STRUCTURAL_ZERO", "count"),
                "RUST_TENSOR_BYTES": metric(0, "STRUCTURAL_ZERO", "bytes"),
            },
        }
