"""A3 regional attention-core output reuse capability for the H3 adapter.

This module freezes the model-independent policy boundary and the H3-specific
cache/correction contract without silently claiming that the current PyTorch
adapter can dispatch a same-block Full Attention fallback from a CUDA scalar
guard.  Until a GPU-native conditional-dispatch capability exists, the public
product default and every ambiguous runtime decision remain Full Compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence
import json
import math

from .active_query_attention import (
    ANCHOR_STEPS,
    ESCALATE_FULL_COMPUTE,
    FULL_COMPUTE,
    REGION_COUNT,
    REGION_LOCAL_ROWS,
    REGION_MASK,
    REGIONAL_ACTIVE_QUERY,
    VIDEO_TOKEN_COUNT,
)
from .regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


MECHANISM_ID = "REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1"
CORRECTION_ID = "REGION_CHANNEL_MEAN_DELTA"
RUST_ABI = "A1_ATTENTION_REGION_PLAN_ABI_V1"
CONTROL_MODE = "CONTROL_A3_OUTPUT_REUSE_SHADOW"
SELECTIVE_MODE = "SELECTIVE_A3_OUTPUT_REUSE_CORRECTION"
FULL_COMPUTE_ACTION = "FULL_ATTENTION"
REUSE_ACTION = "REUSE_WITH_CHANNEL_MEAN_DELTA"

ATTENTION_CORE_WIDTH = 56 * 128
ATTENTION_CORE_DTYPE_BYTES = 2
MAX_HOST_CACHE_BYTES = 2 * 1024**3
HOST_SAFETY_RESERVE_BYTES = 8 * 1024**3
MAX_CANDIDATE_BLOCKS = 16
MIN_CACHE_CAPABLE_BLOCKS = 3
MAX_GPU_STAGING_BYTES = 256 * 1024**2
REFERENCE_SAMPLER_SECONDS = 488.847320
CONTROL_REGRESSION_LIMIT = 0.05
CALLBACK_P95_NS_MAX = 3_000_000
MIN_PLANNED_Q_REDUCTION = 0.03
MIN_AFFECTED_NON_ANCHOR_STEPS = 3
MIN_STABLE_PLAN_EVENTS = 3

BLOCK_OBSERVATIONS_MIN = 3
MEAN_COSINE_MIN = 0.980
P05_COSINE_MIN = 0.950
MEAN_NORMALIZED_L2_MAX = 0.120
P95_NORMALIZED_L2_MAX = 0.250
MEAN_ENERGY_RATIO_MIN = 0.85
MEAN_ENERGY_RATIO_MAX = 1.15
REPRESENTATIVE_COSINE_MIN = 0.97
REPRESENTATIVE_NORMALIZED_L2_MAX = 0.25
CATASTROPHIC_COSINE_MIN = 0.950
CATASTROPHIC_NORMALIZED_L2_MAX = 0.250


CACHE_LOCAL_ROWS = tuple(sorted(row for rows in REGION_LOCAL_ROWS for row in rows))
CACHE_ROW_POSITION = {row: index for index, row in enumerate(CACHE_LOCAL_ROWS)}
REGION_CACHE_POSITIONS = tuple(
    tuple(CACHE_ROW_POSITION[row] for row in rows) for rows in REGION_LOCAL_ROWS
)
PER_BLOCK_WORST_CASE_CACHE_BYTES = (
    len(CACHE_LOCAL_ROWS) * ATTENTION_CORE_WIDTH * ATTENTION_CORE_DTYPE_BYTES
)
PER_BLOCK_GPU_STAGING_BYTES = PER_BLOCK_WORST_CASE_CACHE_BYTES


def fixed_contract() -> dict[str, Any]:
    return {
        "mechanism": MECHANISM_ID,
        "correction": CORRECTION_ID,
        "rust_abi": RUST_ABI,
        "product_default_enabled": False,
        "cache_source": "ACTUAL_FULL_ATTENTION_CORE_OUTPUT_ONLY",
        "cache_location": "PINNED_HOST_MEMORY",
        "cache_age_source_intervals": 1,
        "approximation_chaining": False,
        "cache_rows": "H3_EXCLUSIVE_REGIONAL_INTERIORS",
        "cache_dtype": "BF16",
        "global_kv": "FULL",
        "qkv_projection": "FULL",
        "output_projection": "FULL_ORIGINAL",
        "mlp": "FULL",
        "vae": "FULL",
        "audio": "FULL",
        "anchors": list(ANCHOR_STEPS),
        "active": "FULL_ATTENTION",
        "uncertain": "FULL_ATTENTION",
        "halo": "FULL_ATTENTION",
        "missing_late_or_ambiguous": "FULL_ATTENTION",
        "tensor_bytes_to_rust": 0,
        "rust_calls_per_block": 0,
        "rust_calls_per_token": 0,
        "maximum_host_cache_bytes": MAX_HOST_CACHE_BYTES,
        "host_safety_reserve_bytes": HOST_SAFETY_RESERVE_BYTES,
        "maximum_candidate_blocks": MAX_CANDIDATE_BLOCKS,
        "minimum_cache_capable_blocks": MIN_CACHE_CAPABLE_BLOCKS,
        "maximum_gpu_staging_bytes": MAX_GPU_STAGING_BYTES,
        "runtime_guard": {
            "representative_cosine_min": REPRESENTATIVE_COSINE_MIN,
            "representative_normalized_l2_max": REPRESENTATIVE_NORMALIZED_L2_MAX,
            "nonfinite_count": 0,
            "failure_action": "SAME_BLOCK_REGION_FULL_ATTENTION",
        },
        "current_adapter_conditional_dispatch": "NOT_AVAILABLE",
    }


def settings_digest(*, mode: str, candidate_blocks: Sequence[int] = ()) -> str:
    if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
        raise ValueError("unsupported A3 mode")
    payload = {
        "contract": fixed_contract(),
        "mode": mode,
        "candidate_blocks": list(candidate_blocks),
        "control_reference_seconds": REFERENCE_SAMPLER_SECONDS,
        "control_regression_limit": CONTROL_REGRESSION_LIMIT,
        "callback_p95_ns_max": CALLBACK_P95_NS_MAX,
        "block_admission": {
            "minimum_observations": BLOCK_OBSERVATIONS_MIN,
            "mean_cosine_min": MEAN_COSINE_MIN,
            "p05_cosine_min": P05_COSINE_MIN,
            "mean_normalized_l2_max": MEAN_NORMALIZED_L2_MAX,
            "p95_normalized_l2_max": P95_NORMALIZED_L2_MAX,
            "mean_energy_ratio": [MEAN_ENERGY_RATIO_MIN, MEAN_ENERGY_RATIO_MAX],
            "nonfinite_count": 0,
            "corrected_l2_non_regression": True,
        },
        "opportunity": {
            "planned_q_reduction_min": MIN_PLANNED_Q_REDUCTION,
            "affected_non_anchor_steps_min": MIN_AFFECTED_NON_ANCHOR_STEPS,
            "stable_plan_events_min": MIN_STABLE_PLAN_EVENTS,
            "minimum_admitted_blocks": MIN_CACHE_CAPABLE_BLOCKS,
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class CacheBudgetPlan:
    available_host_bytes: int
    usable_cache_budget_bytes: int
    per_block_cache_bytes: int
    per_block_gpu_staging_bytes: int
    maximum_by_budget: int
    candidate_blocks: tuple[int, ...]
    admitted: bool
    reason: str | None

    def receipt(self) -> dict[str, Any]:
        return {
            "available_host_bytes": self.available_host_bytes,
            "usable_cache_budget_bytes": self.usable_cache_budget_bytes,
            "per_block_cache_bytes": self.per_block_cache_bytes,
            "per_block_gpu_staging_bytes": self.per_block_gpu_staging_bytes,
            "maximum_by_budget": self.maximum_by_budget,
            "candidate_blocks": list(self.candidate_blocks),
            "candidate_block_count": len(self.candidate_blocks),
            "admitted": self.admitted,
            "reason": self.reason,
        }


def cache_budget_plan(
    *,
    available_host_bytes: int,
    ranked_blocks: Sequence[int],
) -> CacheBudgetPlan:
    if available_host_bytes < 0:
        raise ValueError("available host memory cannot be negative")
    if len(set(ranked_blocks)) != len(ranked_blocks) or any(not 0 <= int(value) < 50 for value in ranked_blocks):
        raise ValueError("ranked H3 block list is malformed")
    usable = min(MAX_HOST_CACHE_BYTES, max(0, int(available_host_bytes) - HOST_SAFETY_RESERVE_BYTES))
    maximum_by_budget = min(MAX_CANDIDATE_BLOCKS, usable // PER_BLOCK_WORST_CASE_CACHE_BYTES)
    candidates = tuple(int(value) for value in ranked_blocks[:maximum_by_budget])
    admitted = len(candidates) >= MIN_CACHE_CAPABLE_BLOCKS and PER_BLOCK_GPU_STAGING_BYTES <= MAX_GPU_STAGING_BYTES
    reason = None
    if PER_BLOCK_GPU_STAGING_BYTES > MAX_GPU_STAGING_BYTES:
        reason = "gpu_staging_budget_exceeded"
    elif len(candidates) < MIN_CACHE_CAPABLE_BLOCKS:
        reason = "host_cache_capacity_below_three_blocks"
    return CacheBudgetPlan(
        available_host_bytes=int(available_host_bytes),
        usable_cache_budget_bytes=usable,
        per_block_cache_bytes=PER_BLOCK_WORST_CASE_CACHE_BYTES,
        per_block_gpu_staging_bytes=PER_BLOCK_GPU_STAGING_BYTES,
        maximum_by_budget=int(maximum_by_budget),
        candidate_blocks=candidates,
        admitted=admitted,
        reason=reason,
    )


def a2_full_ranking(calibration: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    """Reproduce the frozen A2 full-ranking order, including rejected blocks."""

    if len(calibration) != 50:
        raise ValueError("A2 full block-level calibration must contain 50 rows")
    rows: list[tuple[float, float, float, int]] = []
    for row in calibration:
        block = row.get("block_index")
        l2 = row.get("mean_normalized_l2")
        cosine = row.get("mean_cosine")
        p95 = row.get("p95_normalized_l2")
        if not isinstance(block, int) or not all(isinstance(value, (int, float)) for value in (l2, cosine, p95)):
            raise ValueError("A2 calibration row is incomplete")
        values = (float(l2), float(cosine), float(p95))
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A2 calibration contains nonfinite ranking data")
        rows.append((values[0], -values[1], values[2], block))
    if {row[3] for row in rows} != set(range(50)):
        raise ValueError("A2 calibration block identities are incomplete")
    return tuple(row[3] for row in sorted(rows))


@dataclass(frozen=True)
class CacheLineage:
    block_index: int
    source_step: int
    source_kind: str
    region_mask: int = REGION_MASK
    event_ready: bool = True

    def eligible(self, *, target_step: int, region: int) -> bool:
        return (
            self.source_kind == "ACTUAL_FULL_ATTENTION_CORE_OUTPUT"
            and target_step == self.source_step + 1
            and region in range(REGION_COUNT)
            and bool(self.region_mask & (1 << region))
            and self.event_ready
        )


@dataclass(frozen=True)
class H3RegionalAttentionOutputReuseCapability:
    """Reusable H3 adapter capability descriptor; disabled until admitted."""

    enabled: bool = False
    runtime_conditional_dispatch_available: bool = False

    def preflight(
        self,
        *,
        source_admission: Mapping[str, Any],
        cache_plan: CacheBudgetPlan,
    ) -> dict[str, Any]:
        admission = structural_admission(
            source_admission=source_admission,
            cache_plan=cache_plan,
            runtime_conditional_dispatch_available=self.runtime_conditional_dispatch_available,
        )
        admission["capability_enabled"] = self.enabled
        admission["pipeline_integration_ready"] = bool(self.enabled and admission["passed"])
        return admission


def make_cache_lineage(
    *, block_index: int, source_step: int, source_kind: str, event_ready: bool = True
) -> CacheLineage | None:
    if source_kind != "ACTUAL_FULL_ATTENTION_CORE_OUTPUT":
        return None
    return CacheLineage(
        block_index=int(block_index),
        source_step=int(source_step),
        source_kind=source_kind,
        event_ready=bool(event_ready),
    )


def correction_tensors(
    *, current_representative: Any, cached_representative: Any, cached_omitted: Any
) -> tuple[Any, Any]:
    """Return per-channel delta and corrected omitted rows without region crossing."""

    if current_representative.shape != cached_representative.shape:
        raise ValueError("representative tensor shapes differ")
    if len(current_representative.shape) != 2 or len(cached_omitted.shape) != 2:
        raise ValueError("A3 correction expects row-by-channel tensors")
    if current_representative.shape[1] != cached_omitted.shape[1] or current_representative.shape[0] == 0:
        raise ValueError("A3 correction channel or row contract changed")
    delta = (current_representative.float() - cached_representative.float()).mean(dim=0)
    corrected = cached_omitted.float() + delta.unsqueeze(0)
    return delta, corrected.to(dtype=cached_omitted.dtype)


def metric_tensors(actual: Any, predicted: Any, torch_module: Any) -> dict[str, Any]:
    if actual.shape != predicted.shape or len(actual.shape) != 2:
        raise ValueError("metric tensors must share a row-by-channel shape")
    actual32, predicted32 = actual.float(), predicted.float()
    flat_actual, flat_predicted = actual32.flatten(), predicted32.flatten()
    actual_norm = torch_module.linalg.vector_norm(flat_actual).clamp_min(1e-12)
    predicted_norm = torch_module.linalg.vector_norm(flat_predicted).clamp_min(1e-12)
    cosine = torch_module.dot(flat_actual, flat_predicted) / (actual_norm * predicted_norm)
    normalized_l2 = torch_module.linalg.vector_norm(flat_actual - flat_predicted) / actual_norm
    normalized_mae = (flat_actual - flat_predicted).abs().mean() / flat_actual.abs().mean().clamp_min(1e-12)
    energy_ratio = predicted_norm / actual_norm
    finite = torch_module.isfinite(torch_module.stack((cosine, normalized_l2, normalized_mae, energy_ratio))).all()
    return {
        "cosine": cosine,
        "normalized_l2": normalized_l2,
        "normalized_mae": normalized_mae,
        "energy_ratio": energy_ratio,
        "finite": finite,
    }


def representative_guard_from_scalars(
    *, cosine: float, normalized_l2: float, finite: bool
) -> bool:
    """Model-free/test guard; production CUDA tensors must not be host-synchronized."""

    return (
        bool(finite)
        and math.isfinite(float(cosine))
        and math.isfinite(float(normalized_l2))
        and float(cosine) >= REPRESENTATIVE_COSINE_MIN
        and float(normalized_l2) <= REPRESENTATIVE_NORMALIZED_L2_MAX
    )


def region_action(
    *,
    plan: Mapping[str, Any] | None,
    step: int,
    region: int,
    cache: CacheLineage | None,
    runtime_guard_passed: bool | None,
    layout_valid: bool = True,
    digest_valid: bool = True,
) -> tuple[str, str]:
    """Fail-open policy decision with no tensor or CUDA state in Generic Core."""

    if plan is None:
        return FULL_COMPUTE_ACTION, "plan_missing"
    if not layout_valid:
        return FULL_COMPUTE_ACTION, "layout_mismatch"
    if not digest_valid:
        return FULL_COMPUTE_ACTION, "plan_digest_mismatch"
    if step in ANCHOR_STEPS or bool(plan.get("anchor_step")):
        return FULL_COMPUTE_ACTION, "anchor_step"
    if int(plan.get("decision_code", ESCALATE_FULL_COMPUTE)) != REGIONAL_ACTIVE_QUERY:
        return FULL_COMPUTE_ACTION, "plan_requires_full_compute"
    if int(plan.get("uncertain_mask", 0)) & (1 << region):
        return FULL_COMPUTE_ACTION, "uncertain_region"
    if int(plan.get("active_mask", 0)) & (1 << region):
        return FULL_COMPUTE_ACTION, "active_region"
    if int(plan.get("refresh_region_mask", 0)) & (1 << region):
        return FULL_COMPUTE_ACTION, "refresh_required"
    if not int(plan.get("stable_region_mask", 0)) & (1 << region):
        return FULL_COMPUTE_ACTION, "region_not_stable"
    if cache is None or not cache.eligible(target_step=step, region=region):
        return FULL_COMPUTE_ACTION, "cache_missing_stale_or_not_ready"
    if runtime_guard_passed is not True:
        return FULL_COMPUTE_ACTION, "runtime_guard_unavailable_or_failed"
    return REUSE_ACTION, "regional_reuse_admitted"


def structural_admission(
    *,
    source_admission: Mapping[str, Any],
    cache_plan: CacheBudgetPlan,
    runtime_conditional_dispatch_available: bool,
) -> dict[str, Any]:
    source_checks = source_admission.get("checks") if isinstance(source_admission.get("checks"), Mapping) else {}
    claim = source_admission.get("claim_boundary") if isinstance(source_admission.get("claim_boundary"), Mapping) else {}
    checks = {
        "installed_h3_source_fixed": source_admission.get("admitted") is True,
        "a1_smaller_q_full_kv_reachable": claim.get("attention_core_query_reduction") is True and claim.get("global_kv_preserved") is True,
        "attention_core_output_hook_available": source_checks.get("optimized_attention_boundary_present") is True,
        "full_output_projection_original": source_checks.get("output_projection_separate") is True,
        "full_attention_fallback_callable": source_checks.get("attention_class_present") is True,
        "a2_representative_mapping_reusable": all(
            item["exact_partition"] and item["neighbor_rows_same_region"]
            for item in _mapping_regions()
        ),
        "host_cache_capacity": cache_plan.admitted,
        "gpu_staging_capacity": cache_plan.per_block_gpu_staging_bytes <= MAX_GPU_STAGING_BYTES,
        "generic_core_h3_leakage_zero": True,
        "rust_abi_unchanged": RUST_ABI == "A1_ATTENTION_REGION_PLAN_ABI_V1",
        "same_block_gpu_guard_conditional_dispatch": bool(runtime_conditional_dispatch_available),
    }
    passed = all(checks.values())
    blocker = None if passed else (
        "same_block_gpu_guard_requires_blocking_host_sync_or_unconditional_full_attention"
        if not checks["same_block_gpu_guard_conditional_dispatch"]
        else "a3_structural_contract_not_satisfied"
    )
    return {
        "schema_version": "a3.h3.structural-admission.1",
        "mechanism": MECHANISM_ID,
        "checks": checks,
        "passed": passed,
        "decision": "A3_CONTROL_STRUCTURALLY_ADMITTED" if passed else "A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED",
        "blocker": blocker,
        "generation_budget_consumed": 0,
        "cuda_execution_count": 0,
        "cache_budget": cache_plan.receipt(),
        "claim_boundary": {
            "cache_capacity_admitted": cache_plan.admitted,
            "runtime_guard_dispatch_admitted": bool(runtime_conditional_dispatch_available),
            "attention_reuse_executed": False,
            "speedup_claim": 0,
            "quality_promotion": 0,
            "product_promotion": 0,
            "full_compute_fallback_preserved": True,
        },
    }


def _mapping_regions() -> tuple[dict[str, bool], ...]:
    rows: list[dict[str, bool]] = []
    for region in range(REGION_COUNT):
        plan = CPU_PROTOTYPE_PLANS[1 << region]
        details = plan.region_rows[region]
        representatives = set(details["representative"])
        omitted = set(details["omitted"])
        local = set(REGION_LOCAL_ROWS[region])
        rows.append(
            {
                "exact_partition": representatives | omitted == local and not representatives & omitted,
                "neighbor_rows_same_region": all(set(group).issubset(representatives) for group in details["neighbors"]),
            }
        )
    return tuple(rows)


__all__ = [
    "ATTENTION_CORE_WIDTH",
    "BLOCK_OBSERVATIONS_MIN",
    "CACHE_LOCAL_ROWS",
    "CONTROL_MODE",
    "CORRECTION_ID",
    "CacheBudgetPlan",
    "CacheLineage",
    "FULL_COMPUTE_ACTION",
    "H3RegionalAttentionOutputReuseCapability",
    "MAX_HOST_CACHE_BYTES",
    "MECHANISM_ID",
    "PER_BLOCK_GPU_STAGING_BYTES",
    "PER_BLOCK_WORST_CASE_CACHE_BYTES",
    "REGION_CACHE_POSITIONS",
    "REUSE_ACTION",
    "SELECTIVE_MODE",
    "a2_full_ranking",
    "cache_budget_plan",
    "correction_tensors",
    "fixed_contract",
    "make_cache_lineage",
    "metric_tensors",
    "region_action",
    "representative_guard_from_scalars",
    "settings_digest",
    "structural_admission",
]
