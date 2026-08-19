"""Model-free Python bridge for the generation-batched Rust cache-plan ABI V2."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import struct
from time import perf_counter_ns
from typing import Any, Mapping, Sequence


CACHE_PLAN_ABI_V2 = 2
CACHE_PLAN_CONTRACT_V2 = 1
FULL_COMPUTE = 0
PLAN_READY = 1
OVERFLOW_FULL_COMPUTE = 1
PYTHON_BOUNDARY_FAILURE = 1_001
PYTHON_MULTIPLE_CALL_FAILURE = 1_002
EXISTING_A1_STEP_POLICY_CALLS = 18

IDENTITY_FIELDS = frozenset(
    {
        "run_digest",
        "workflow_digest",
        "model_digest",
        "model_revision_digest",
        "settings_digest",
        "source_plan_digest",
        "layout_digest",
        "input_identity_digest",
        "generation_id",
        "scheduler_id",
        "total_steps",
        "width",
        "height",
        "frame_count",
        "fps_numerator",
        "fps_denominator",
    }
)
CANDIDATE_FIELDS = frozenset(
    {
        "target_step",
        "source_step",
        "block_index",
        "region",
        "packed_row_start",
        "packed_row_count",
        "state",
        "actual_safety_state",
        "safety_evidence_present",
        "uncertainty_ppm",
        "motion_ppm",
        "cosine_ppm",
        "corrected_nl2_ppm",
        "false_safe_count",
        "nonfinite_count",
        "cache_age",
        "source_kind",
        "shape_rows",
        "shape_width",
        "dtype",
        "device_class",
        "precision",
        "quantization",
        "admission_eligible",
        "rejection_reason",
        "planned_q_rows",
        "full_q_rows",
        "payload_bytes",
        "effect_numerator",
        "effect_denominator",
        "planned_d2h_bytes",
        "planned_h2d_bytes",
        "shape_digest",
        "packed_row_digest",
        "lineage_digest",
    }
)
INVENTORY_FIELDS = frozenset(
    {
        "block_index",
        "region",
        "source_step",
        "cache_age",
        "valid",
        "payload_bytes",
        "planned_q_rows",
        "lineage_digest",
    }
)
RECEIPT_FIELDS = (
    "rust_module_load_count",
    "rust_module_load_time_ns",
    "rust_process_spawn_count",
    "calls_per_generation",
    "calls_per_step",
    "calls_per_block",
    "calls_per_region",
    "calls_per_row",
    "evidence_record_count",
    "evidence_batch_bytes",
    "pyo3_conversion_time_ns",
    "rust_plan_time_ns",
    "ffi_total_time_ns",
    "serialization_time_ns",
    "rust_transfer_bytes",
    "gpu_to_cpu_metadata_bytes",
    "gpu_to_cpu_tensor_bytes",
    "cpu_to_gpu_metadata_bytes",
    "cpu_to_gpu_tensor_bytes",
    "cuda_sync_count",
    "selected_payload_bytes",
    "planned_d2h_bytes",
    "planned_h2d_bytes",
    "actual_d2h_bytes",
    "actual_h2d_bytes",
    "d2h_estimate_error_bytes",
    "h2d_estimate_error_bytes",
    "fallback_count",
    "partial_full_recovery_count",
    "rust_overhead_ratio_ppm",
)


@dataclass(frozen=True)
class GenerationIdentity:
    run_digest: bytes
    workflow_digest: bytes
    model_digest: bytes
    model_revision_digest: bytes
    settings_digest: bytes
    source_plan_digest: bytes
    layout_digest: bytes
    input_identity_digest: bytes
    generation_id: int
    scheduler_id: int
    total_steps: int
    width: int
    height: int
    frame_count: int
    fps_numerator: int
    fps_denominator: int

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def stable_digest(label: str) -> bytes:
    """Create a deterministic, non-identifying fixture digest."""

    return hashlib.sha256(label.encode("utf-8")).digest()


def cache_lineage_v2_digest(
    identity: Mapping[str, Any], candidate: Mapping[str, Any]
) -> bytes:
    """Mirror the Rust CacheLineageV2 digest without carrying source text or paths."""

    hasher = hashlib.sha256()
    hasher.update(b"hiveframe-cache-lineage-v2")
    for name in (
        "run_digest",
        "workflow_digest",
        "model_digest",
        "model_revision_digest",
        "settings_digest",
        "source_plan_digest",
        "layout_digest",
        "input_identity_digest",
    ):
        value = identity[name]
        if not isinstance(value, bytes) or len(value) != 32:
            raise ValueError(f"{name} must be exactly 32 bytes")
        hasher.update(value)
    for name in (
        "scheduler_id",
        "total_steps",
        "width",
        "height",
        "frame_count",
        "fps_numerator",
        "fps_denominator",
    ):
        hasher.update(struct.pack("<I", int(identity[name])))
    for name in (
        "block_index",
        "region",
        "source_step",
        "source_kind",
        "shape_rows",
        "shape_width",
        "dtype",
        "device_class",
        "precision",
        "quantization",
    ):
        hasher.update(struct.pack("<I", int(candidate[name])))
    for name in ("shape_digest", "packed_row_digest"):
        value = candidate[name]
        if not isinstance(value, bytes) or len(value) != 32:
            raise ValueError(f"{name} must be exactly 32 bytes")
        hasher.update(value)
    return hasher.digest()


def _metric(value: int | None, status: str) -> dict[str, int | str | None]:
    return {"value": value, "status": status}


def _fallback_receipt(record_count: int, batch_bytes: int) -> dict[str, Any]:
    measured = {
        "calls_per_generation": 0,
        "evidence_record_count": record_count,
        "evidence_batch_bytes": batch_bytes,
        "fallback_count": 1,
    }
    structural_zero = {
        "rust_process_spawn_count",
        "calls_per_step",
        "calls_per_block",
        "calls_per_region",
        "calls_per_row",
        "serialization_time_ns",
        "rust_transfer_bytes",
        "gpu_to_cpu_tensor_bytes",
        "cpu_to_gpu_tensor_bytes",
        "cuda_sync_count",
        "selected_payload_bytes",
        "planned_d2h_bytes",
        "planned_h2d_bytes",
    }
    not_executed = {
        "gpu_to_cpu_metadata_bytes",
        "cpu_to_gpu_metadata_bytes",
        "actual_d2h_bytes",
        "actual_h2d_bytes",
        "d2h_estimate_error_bytes",
        "h2d_estimate_error_bytes",
        "partial_full_recovery_count",
    }
    result = {}
    for name in RECEIPT_FIELDS:
        if name in measured:
            result[name] = _metric(measured[name], "MEASURED")
        elif name in structural_zero:
            result[name] = _metric(0, "STRUCTURAL_ZERO")
        elif name in not_executed:
            result[name] = _metric(None, "NOT_EXECUTED")
        else:
            result[name] = _metric(None, "UNKNOWN")
    return result


def _fallback_plan(reason_code: int, record_count: int, batch_bytes: int) -> dict[str, Any]:
    return {
        "ffi_status": 1,
        "abi_version": CACHE_PLAN_ABI_V2,
        "decision_code": FULL_COMPUTE,
        "reason_code": reason_code,
        "fallback_required": True,
        "selected": [],
        "rejected": [],
        "eviction_order": [],
        "total_selected_bytes": 0,
        "total_planned_q_rows": 0,
        "total_full_q_rows": 0,
        "planned_reduction_ppm": 0,
        "total_planned_d2h_bytes": 0,
        "total_planned_h2d_bytes": 0,
        "plan_digest": bytes(32),
        "lineage_digest": bytes(32),
        "performance_receipt": _fallback_receipt(record_count, batch_bytes),
    }


def _validate_record_fields(
    records: Sequence[Mapping[str, Any]], allowed_fields: frozenset[str]
) -> None:
    for record in records:
        if not isinstance(record, Mapping) or frozenset(record) != allowed_fields:
            raise ValueError("record fields do not match the fixed ABI V2 layout")
        for value in record.values():
            if not isinstance(value, (int, bytes)) or isinstance(value, bool):
                raise TypeError("ABI V2 accepts only bounded scalar metadata and digests")


class RustCachePlanV2Bridge:
    """Compile at most one metadata-only cache plan for one generation."""

    def __init__(self, extension: Any | None = None) -> None:
        self.extension = extension
        self.extension_error: str | None = None
        if self.extension is None:
            try:
                import _hive_retina_boundary as boundary

                self.extension = boundary
            except (ImportError, OSError) as error:
                self.extension_error = type(error).__name__
        self.contract: dict[str, Any] | None = None
        if self.extension is not None:
            try:
                self.contract = dict(self.extension.cache_plan_v2_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.compile_attempt_count = 0
        self.rust_call_count = 0
        self._compiled_generation_id: int | None = None
        self._cached_plan: dict[str, Any] | None = None

    def compile_generation(
        self,
        *,
        identity: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        total_full_q_rows: int,
        profile_name: str = "balanced_12gb",
        inventory: Sequence[Mapping[str, Any]] = (),
        current_step: int = 0,
    ) -> dict[str, Any]:
        self.compile_attempt_count += 1
        try:
            generation_id = int(identity["generation_id"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return _fallback_plan(PYTHON_BOUNDARY_FAILURE, len(candidates), 0)
        if self._compiled_generation_id == generation_id:
            if self._cached_plan is not None:
                return deepcopy(self._cached_plan)
            return _fallback_plan(PYTHON_MULTIPLE_CALL_FAILURE, len(candidates), 0)
        self._compiled_generation_id = generation_id
        if self.extension is None or self.contract is None:
            return _fallback_plan(PYTHON_BOUNDARY_FAILURE, len(candidates), 0)

        candidate_size = int(self.contract["candidate_struct_size"])
        header_size = int(self.contract["batch_header_struct_size"])
        batch_bytes = header_size + len(candidates) * candidate_size
        try:
            if frozenset(identity) != IDENTITY_FIELDS:
                raise ValueError("identity fields do not match ABI V2")
            _validate_record_fields(candidates, CANDIDATE_FIELDS)
            _validate_record_fields(inventory, INVENTORY_FIELDS)
            profile = dict(self.contract[profile_name])
            maximum_records = min(
                int(self.contract["maximum_records"]), int(profile["maximum_candidates"])
            )
            overflowed = len(candidates) > maximum_records or batch_bytes > int(
                profile["maximum_batch_bytes"]
            )
            transmitted_candidates = [] if overflowed else list(candidates)
            transmitted_bytes = header_size if overflowed else batch_bytes
            request = {
                "abi_version": CACHE_PLAN_ABI_V2,
                "struct_size": int(self.contract["request_struct_size"]),
                "contract_version": CACHE_PLAN_CONTRACT_V2,
                "overflow_policy": OVERFLOW_FULL_COMPUTE,
                "generation_id": generation_id,
                "current_step": int(current_step),
                "maximum_batch_records": maximum_records,
                "maximum_batch_bytes": int(profile["maximum_batch_bytes"]),
                "total_full_q_rows": int(total_full_q_rows),
                "unsupported_flags": 0,
            }
            batch_header = {
                "abi_version": CACHE_PLAN_ABI_V2,
                "struct_size": header_size,
                "generation_id": generation_id,
                "record_count": len(transmitted_candidates),
                "maximum_records": maximum_records,
                "batch_bytes": transmitted_bytes,
                "overflowed": int(overflowed),
                "truncated": int(overflowed),
                "tensor_bytes": 0,
                "unsupported_flags": 0,
            }
            started = perf_counter_ns()
            self.rust_call_count += 1
            result = dict(
                self.extension.compile_cache_plan_v2(
                    request,
                    dict(identity),
                    profile,
                    batch_header,
                    transmitted_candidates,
                    list(inventory),
                )
            )
            roundtrip_ns = perf_counter_ns() - started
            result["performance_receipt"]["ffi_total_time_ns"] = _metric(
                roundtrip_ns, "MEASURED"
            )
            result["bridge_contract"] = {
                "existing_a1_step_policy_calls": EXISTING_A1_STEP_POLICY_CALLS,
                "cache_plan_calls_per_generation": 1,
                "calls_per_block": 0,
                "calls_per_region": 0,
                "calls_per_row": 0,
                "tensor_bytes_per_call": 0,
            }
            self._cached_plan = deepcopy(result)
            return result
        except Exception:  # every boundary failure must fail open
            return _fallback_plan(PYTHON_BOUNDARY_FAILURE, len(candidates), batch_bytes)
