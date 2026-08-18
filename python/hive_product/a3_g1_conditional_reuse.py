"""A3-G1C real-H3 attention reuse with preplanned direct selection.

The metadata-only Rust plan chooses Full or Selective before Attention starts.
Selective executes subset-Q Attention exactly once and reconstructs omitted
rows from the previous actual Full output. Ambiguous state fails open before
partial work begins.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence
import json
import math

from .active_query_attention import (
    ANCHOR_STEPS,
    BLOCK_COUNT,
    ESCALATE_FULL_COMPUTE,
    REGION_COUNT,
    REGION_MASK,
    REGIONAL_ACTIVE_QUERY,
    TOTAL_STEPS,
    VIDEO_TOKEN_COUNT,
)
from .attention_output_reuse import (
    BLOCK_OBSERVATIONS_MIN,
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
    CORRECTION_ID,
    MEAN_COSINE_MIN,
    MEAN_ENERGY_RATIO_MAX,
    MEAN_ENERGY_RATIO_MIN,
    MEAN_NORMALIZED_L2_MAX,
    MECHANISM_ID,
    P05_COSINE_MIN,
    P95_NORMALIZED_L2_MAX,
    cache_budget_plan,
)
from .regional_query_prototype_attention import (
    CPU_PROTOTYPE_PLANS,
    GPUPrototypePlanCache,
    _project_qkv,
    attention_core,
    prototype_mapping_contract,
)


CONTROL_MODE = "CONTROL_A3_G1C_PREPLAN_DIRECT_REUSE"
SELECTIVE_MODE = "SELECTIVE_A3_G1C_PREPLAN_DIRECT_REUSE"
EXECUTION_AUTHORITY = "RUST_METADATA_PREPLAN_DIRECT_SELECTIVE_V1"
FORCE_FULL = "FORCE_FULL"
SELECTIVE_CANDIDATE = "SELECTIVE_CANDIDATE"

DECISION_REUSE_NOT_ADMITTED = "A3_G1C_REUSE_NOT_ADMITTED"
DECISION_ISLAND_NOT_ADMITTED = DECISION_REUSE_NOT_ADMITTED
DECISION_PREPLAN_NOT_SAFE = "A3_G1C_PREPLAN_NOT_SAFE"
DECISION_GUARD_NOT_SAFE = DECISION_PREPLAN_NOT_SAFE
DECISION_OMISSION_NOT_PROVEN = "A3_G1C_REAL_WORK_OMISSION_NOT_PROVEN"
DECISION_QUALITY_REJECTED = "A3_G1C_QUALITY_REJECTED"
DECISION_RUNTIME_NOT_POSITIVE = "A3_G1C_WORK_REDUCTION_VERIFIED_RUNTIME_NOT_POSITIVE"
DECISION_READY_FOR_VISUAL = "A3_G1C_REAL_H3_SELECTIVE_ACCELERATION_READY_FOR_VISUAL_REVIEW"
DECISION_DOUBLE_WORK = "A3_G1C_DOUBLE_ATTENTION_WORK_DETECTED"
DECISION_CORRECTION_MEMORY = "A3_G1C_CORRECTION_MEMORY_NOT_ADMITTED"

REMOVED_STATIC_QKV_BYTES = 663_355_392
PROJECTED_INCREMENTAL_BYTES = 255_110_464
MAX_REGION_STAGING_BYTES = 48_269_312
MAX_CORRECTION_TEMP_BYTES = 32 * 1024**2
CORRECTION_CHUNK_ROWS = 64

CALLBACK_P95_NS_MAX = 3_000_000
MIN_PLANNED_Q_REDUCTION = 0.03
MIN_ACTUAL_Q_REDUCTION = 0.03
MIN_AFFECTED_NON_ANCHOR_STEPS = 3
MIN_STABLE_PLAN_EVENTS = 3
MIN_ADMITTED_BLOCKS = 3

# Immutable order derived from the complete private A2 calibration receipt.
# It is evidence input, not a new measurement or a claim that A2 passed.
A2_RANKED_BLOCKS = (
    0,
    48,
    16,
    10,
    4,
    11,
    17,
    13,
    49,
    15,
    12,
    14,
)


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def fixed_contract() -> dict[str, Any]:
    return {
        "mechanism": MECHANISM_ID,
        "correction": CORRECTION_ID,
        "execution_authority": EXECUTION_AUTHORITY,
        "product_default_enabled": False,
        "rust_directives": [FORCE_FULL, SELECTIVE_CANDIDATE],
        "execution_decision_point": "BEFORE_ATTENTION",
        "cache_source": "ACTUAL_FULL_ATTENTION_CORE_OUTPUT_ONLY",
        "cache_age_source_intervals": 1,
        "approximation_chaining": False,
        "qkv_projection": "FULL",
        "global_kv": "FULL",
        "output_projection": "FULL_ORIGINAL",
        "mlp": "FULL",
        "vae": "FULL",
        "audio": "FULL",
        "anchors": list(ANCHOR_STEPS),
        "conditional_graph_used": False,
        "gpu_same_block_guard_used": False,
        "static_qkv_used": False,
        "maximum_region_staging_bytes": MAX_REGION_STAGING_BYTES,
        "maximum_correction_temporary_bytes": MAX_CORRECTION_TEMP_BYTES,
        "tensor_bytes_to_rust": 0,
        "rust_calls_per_block": 0,
        "rust_calls_per_token": 0,
        "generation_budget": {"control": 1, "selective": 1, "retry": 0},
    }


def settings_digest(*, mode: str, candidate_blocks: Sequence[int]) -> str:
    if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
        raise ValueError("unsupported A3-G1 mode")
    payload = {
        "contract": fixed_contract(),
        "mode": mode,
        "candidate_blocks": [int(value) for value in candidate_blocks],
        "block_admission": {
            "valid_observations_min": BLOCK_OBSERVATIONS_MIN,
            "mean_cosine_min": MEAN_COSINE_MIN,
            "p05_cosine_min": P05_COSINE_MIN,
            "mean_normalized_l2_max": MEAN_NORMALIZED_L2_MAX,
            "p95_normalized_l2_max": P95_NORMALIZED_L2_MAX,
            "mean_energy_ratio": [MEAN_ENERGY_RATIO_MIN, MEAN_ENERGY_RATIO_MAX],
            "corrected_l2_non_regression": True,
        },
        "opportunity": {
            "admitted_blocks_min": MIN_ADMITTED_BLOCKS,
            "planned_q_reduction_min": MIN_PLANNED_Q_REDUCTION,
            "actual_q_reduction_min": MIN_ACTUAL_Q_REDUCTION,
            "affected_non_anchor_steps_min": MIN_AFFECTED_NON_ANCHOR_STEPS,
            "stable_plan_events_min": MIN_STABLE_PLAN_EVENTS,
            "false_safe_count": 0,
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rust_directive(
    *,
    plan: Mapping[str, Any] | None,
    step: int,
    block_index: int,
    candidate_blocks: Sequence[int],
    cache_ready: bool,
) -> tuple[str, str]:
    """Choose the only Attention path before any current-block SDPA work."""

    if block_index not in candidate_blocks:
        return FORCE_FULL, "block_not_candidate"
    if step in ANCHOR_STEPS:
        return FORCE_FULL, "anchor_step"
    if plan is None:
        return FORCE_FULL, "plan_missing_or_late"
    if int(plan.get("target_step", -1)) != step:
        return FORCE_FULL, "plan_target_mismatch_or_late"
    if plan.get("source_valid") is not True or plan.get("prediction_valid") is not True:
        return FORCE_FULL, "plan_source_or_prediction_invalid"
    if bool(plan.get("fallback_used", False)):
        return FORCE_FULL, "plan_fallback"
    if int(plan.get("decision_code", ESCALATE_FULL_COMPUTE)) != REGIONAL_ACTIVE_QUERY:
        return FORCE_FULL, "plan_requires_full"
    stable = int(plan.get("stable_region_mask", 0))
    if stable == 0 or stable & ~REGION_MASK:
        return FORCE_FULL, "stable_mask_missing_or_invalid"
    if int(plan.get("uncertain_mask", 0)) != 0:
        return FORCE_FULL, "uncertain_region_present"
    if int(plan.get("active_mask", 0)) & stable:
        return FORCE_FULL, "active_region_would_be_omitted"
    if int(plan.get("refresh_region_mask", 0)) & stable:
        return FORCE_FULL, "refresh_required"
    if not cache_ready:
        return FORCE_FULL, "cache_missing_stale_or_not_ready"
    return SELECTIVE_CANDIDATE, "preplanned_stable_cache_candidate"


def work_accounting(
    *,
    full_q_rows_theoretical: int,
    forced_full_q_rows: int,
    partial_q_rows: int,
    reused_omitted_rows: int,
) -> dict[str, Any]:
    actual = forced_full_q_rows + partial_q_rows
    reduction = 1.0 - actual / full_q_rows_theoretical if full_q_rows_theoretical else 0.0
    return {
        "full_q_rows_theoretical": int(full_q_rows_theoretical),
        "actual_q_rows": int(actual),
        "actual_attention_q_rows": int(actual),
        "actual_current_q_rows": int(actual),
        "partial_q_rows": int(partial_q_rows),
        "reused_omitted_rows": int(reused_omitted_rows),
        "actual_q_reduction_ratio": float(reduction),
    }


def attention_path_is_xor(*, full_calls: int, partial_calls: int) -> bool:
    return (int(full_calls), int(partial_calls)) in {(1, 0), (0, 1)}


def correction_temp_bytes(*, rows: int, width: int, float_buffers: int) -> int:
    return int(rows) * int(width) * 4 * int(float_buffers) + int(width) * 4


def reconstruct_selected_core(selected_core: Any, kernel_indices: Any, sequence_length: int) -> Any:
    full_core = selected_core.new_empty((int(sequence_length), int(selected_core.shape[-1])))
    full_core.index_copy_(0, kernel_indices, selected_core)
    return full_core


@dataclass
class HostCacheEntry:
    tensors: dict[int, Any]
    event: Any
    source_step: int = -1
    source_kind: str = "INVALID"
    valid: bool = False

    def ready_for(self, *, target_step: int) -> bool:
        return (
            self.valid
            and self.source_kind == "ACTUAL_FULL_ATTENTION_CORE_OUTPUT"
            and target_step == self.source_step + 1
            and bool(self.event.query())
        )

    def invalidate(self) -> None:
        self.valid = False
        self.source_kind = "INVALID"


class H3A3G1Controller:
    """H3 block wrapper with a pre-Attention Full-or-Selective decision."""

    def __init__(
        self,
        *,
        mode: str,
        plan_bridge: Any,
        h3_model: Any,
        torch_module: Any,
        candidate_blocks: Sequence[int],
    ) -> None:
        if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
            raise ValueError("unsupported A3-G1C mode")
        candidates = tuple(int(value) for value in candidate_blocks)
        if len(set(candidates)) != len(candidates) or any(not 0 <= value < BLOCK_COUNT for value in candidates):
            raise ValueError("A3-G1C candidate block list is malformed")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.h3 = h3_model
        self.torch = torch_module
        self.candidate_blocks = candidates
        self.plan_cache = GPUPrototypePlanCache(torch_module)
        self._original_forward: Any | None = None
        self._dit_class: Any | None = None
        self._core_signature: tuple[Any, ...] | None = None
        self._region_cache_indices: dict[int, Any] = {}
        self._region_cache_positions: dict[int, dict[str, Any]] = {}
        self._region_staging: Any | None = None
        self._host_cache: dict[int, HostCacheEntry] = {}
        self._observations: dict[int, list[dict[str, Any]]] = {index: [] for index in candidates}
        self.block_call_count = 0
        self.model_forward_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.forced_full_blocks = 0
        self.selective_candidate_blocks = 0
        self.native_error_fallbacks = 0
        self.full_attention_calls = 0
        self.partial_attention_calls = 0
        self.normal_partial_plus_full_count = 0
        self.exception_partial_then_full_count = 0
        self.full_q_rows_theoretical = 0
        self.forced_full_q_rows = 0
        self.partial_q_rows = 0
        self.reused_omitted_rows = 0
        self.representative_q_rows = 0
        self.full_k_rows = 0
        self.actual_k_rows = 0
        self.full_v_rows = 0
        self.actual_v_rows = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cache_invalidations = 0
        self.full_refreshes = 0
        self.host_cache_bytes = 0
        self.h2d_bytes = 0
        self.d2h_bytes = 0
        self.region_staging_peak_bytes = 0
        self.correction_temp_peak_bytes = 0
        self.full_size_gpu_staging_count = 0
        self.guard_d2h_bytes = 0
        self.host_guard_reads = 0
        self.explicit_hot_path_cpu_sync = 0
        self.per_step: dict[int, dict[str, Any]] = {}
        self._memory_tracking = False
        try:
            if self.torch.cuda.is_available():
                self.torch.cuda.reset_peak_memory_stats()
                self._memory_tracking = True
        except (AttributeError, RuntimeError):
            self._memory_tracking = False

    @property
    def is_selective(self) -> bool:
        return self.mode == SELECTIVE_MODE

    @staticmethod
    def _video_segment(x: Any, mod_segments: Sequence[Sequence[int]]) -> tuple[int, int]:
        if not mod_segments or len(mod_segments[-1]) != 3:
            raise ValueError("H3 video segment unavailable")
        start, stop, _ = map(int, mod_segments[-1])
        if stop - start != VIDEO_TOKEN_COUNT or start < 0 or stop > int(x.shape[0]):
            raise ValueError("H3 packed video layout changed")
        return start, stop

    def _attention_kwargs(self) -> dict[str, Any]:
        return {
            "cast_to": self.h3.comfy.model_management.cast_to,
            "in_training": bool(self.h3.comfy.model_management.in_training),
            "rms_rope": self.h3.comfy.quant_ops.ck.rms_rope_split_half,
            "rms_rope_in_place": self.h3.comfy.quant_ops.ck.rms_rope_split_half_,
        }

    def _ensure_buffers(self, *, full_core: Any, video_start: int) -> None:
        signature = (tuple(int(value) for value in full_core.shape), full_core.dtype, str(full_core.device))
        if self._core_signature is not None:
            if signature != self._core_signature:
                raise ValueError("A3-G1C runtime tensor metadata changed")
            return
        self._core_signature = signature
        device = full_core.device
        maximum_rows = 0
        for region in range(REGION_COUNT):
            cpu_rows = CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]
            local_rows = tuple(sorted((*cpu_rows["representative"], *cpu_rows["omitted"])))
            positions = {row: index for index, row in enumerate(local_rows)}
            self._region_cache_indices[region] = self.torch.tensor(
                [video_start + row for row in local_rows], dtype=self.torch.long, device=device
            )
            self._region_cache_positions[region] = {
                "representative": self.torch.tensor(
                    [positions[row] for row in cpu_rows["representative"]],
                    dtype=self.torch.long,
                    device=device,
                ),
                "omitted": self.torch.tensor(
                    [positions[row] for row in cpu_rows["omitted"]],
                    dtype=self.torch.long,
                    device=device,
                ),
            }
            maximum_rows = max(maximum_rows, len(local_rows))
        self._region_staging = self.torch.empty(
            (maximum_rows, int(full_core.shape[-1])), dtype=full_core.dtype, device=device
        )
        staging = int(self._region_staging.numel()) * int(self._region_staging.element_size())
        self.region_staging_peak_bytes = staging
        if staging > MAX_REGION_STAGING_BYTES:
            raise RuntimeError("A3-G1C region staging exceeds the W0 budget")

    def _cache_entry(self, block_index: int, full_core: Any) -> HostCacheEntry:
        entry = self._host_cache.get(block_index)
        if entry is None:
            tensors = {
                region: self.torch.empty(
                    (int(indices.numel()), int(full_core.shape[-1])),
                    dtype=full_core.dtype,
                    device="cpu",
                    pin_memory=True,
                )
                for region, indices in self._region_cache_indices.items()
            }
            entry = HostCacheEntry(tensors=tensors, event=self.torch.cuda.Event(blocking=False))
            self._host_cache[block_index] = entry
            self.host_cache_bytes += sum(
                int(tensor.numel()) * int(tensor.element_size()) for tensor in tensors.values()
            )
        return entry

    def _cache_ready(self, block_index: int, step: int) -> bool:
        entry = self._host_cache.get(block_index)
        return bool(entry and entry.ready_for(target_step=step))

    def _upload_region(self, *, entry: HostCacheEntry, region: int) -> Any:
        source = entry.tensors[region]
        staging = self._region_staging[: int(source.shape[0])]
        staging.copy_(source, non_blocking=True)
        self.h2d_bytes += int(source.numel()) * int(source.element_size())
        return staging

    def _refresh_cache(self, *, block_index: int, step: int, full_core: Any) -> None:
        entry = self._cache_entry(block_index, full_core)
        for region in range(REGION_COUNT):
            indices = self._region_cache_indices[region]
            staging = self._region_staging[: int(indices.numel())]
            self.torch.index_select(full_core, 0, indices, out=staging)
            target = entry.tensors[region]
            target.copy_(staging, non_blocking=True)
            self.d2h_bytes += int(target.numel()) * int(target.element_size())
        entry.event.record(self.torch.cuda.current_stream(device=full_core.device))
        entry.source_step = step
        entry.source_kind = "ACTUAL_FULL_ATTENTION_CORE_OUTPUT"
        entry.valid = True
        self.full_refreshes += 1

    def _track_correction_temp(self, *, rows: int, width: int, float_buffers: int) -> None:
        estimate = correction_temp_bytes(rows=rows, width=width, float_buffers=float_buffers)
        self.correction_temp_peak_bytes = max(self.correction_temp_peak_bytes, estimate)
        if estimate > MAX_CORRECTION_TEMP_BYTES:
            raise RuntimeError("A3-G1C bounded correction exceeds 32 MiB")

    def _channel_mean_delta(self, *, full_core: Any, staging: Any, rows: Mapping[str, Any], positions: Mapping[str, Any]) -> Any:
        current_indices = rows["representative_indices"]
        cached_positions = positions["representative"]
        count = int(current_indices.numel())
        if count == 0:
            raise ValueError("A3-G1C representative rows are empty")
        width = int(full_core.shape[-1])
        delta = self.torch.zeros((width,), dtype=self.torch.float32, device=full_core.device)
        for start in range(0, count, CORRECTION_CHUNK_ROWS):
            stop = min(count, start + CORRECTION_CHUNK_ROWS)
            current = full_core.index_select(0, current_indices[start:stop]).float()
            cached = staging.index_select(0, cached_positions[start:stop]).float()
            difference = current - cached
            delta.add_(difference.sum(dim=0))
            self._track_correction_temp(rows=stop - start, width=width, float_buffers=3)
            del current, cached, difference
        return delta.div_(count)

    @staticmethod
    def _metric_result(accumulator: Mapping[str, Any], torch_module: Any) -> dict[str, Any]:
        actual_norm = torch_module.sqrt(accumulator["actual_sq"]).clamp_min(1e-12)
        predicted_norm = torch_module.sqrt(accumulator["predicted_sq"]).clamp_min(1e-12)
        values = {
            "cosine": accumulator["dot"] / (actual_norm * predicted_norm),
            "normalized_l2": torch_module.sqrt(accumulator["diff_sq"]) / actual_norm,
            "normalized_mae": accumulator["abs_diff"] / accumulator["actual_abs"].clamp_min(1e-12),
            "energy_ratio": predicted_norm / actual_norm,
        }
        values["finite"] = accumulator["finite"] & torch_module.isfinite(
            torch_module.stack(tuple(values.values()))
        ).all()
        return values

    def _bounded_region_metrics(
        self,
        *,
        full_core: Any,
        staging: Any,
        rows: Mapping[str, Any],
        positions: Mapping[str, Any],
        delta: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        actual_indices = rows["omitted_indices"]
        cached_positions = positions["omitted"]
        device = full_core.device
        zero = lambda: self.torch.zeros((), dtype=self.torch.float32, device=device)
        accumulators = {
            kind: {
                "dot": zero(),
                "actual_sq": zero(),
                "predicted_sq": zero(),
                "diff_sq": zero(),
                "abs_diff": zero(),
                "actual_abs": zero(),
                "finite": self.torch.ones((), dtype=self.torch.bool, device=device),
            }
            for kind in ("raw", "corrected")
        }
        count = int(actual_indices.numel())
        width = int(full_core.shape[-1])
        for start in range(0, count, CORRECTION_CHUNK_ROWS):
            stop = min(count, start + CORRECTION_CHUNK_ROWS)
            actual = full_core.index_select(0, actual_indices[start:stop]).float()
            cached = staging.index_select(0, cached_positions[start:stop]).float()
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
            self._track_correction_temp(rows=stop - start, width=width, float_buffers=8)
            del actual, cached, corrected
        return (
            self._metric_result(accumulators["raw"], self.torch),
            self._metric_result(accumulators["corrected"], self.torch),
        )

    def _apply_region_correction(
        self,
        *,
        full_core: Any,
        staging: Any,
        rows: Mapping[str, Any],
        positions: Mapping[str, Any],
        delta: Any,
    ) -> None:
        omitted_indices = rows["omitted_indices"]
        cached_positions = positions["omitted"]
        count = int(omitted_indices.numel())
        width = int(full_core.shape[-1])
        for start in range(0, count, CORRECTION_CHUNK_ROWS):
            stop = min(count, start + CORRECTION_CHUNK_ROWS)
            cached = staging.index_select(0, cached_positions[start:stop])
            corrected = (cached.float() + delta).to(dtype=full_core.dtype)
            full_core.index_copy_(0, omitted_indices[start:stop], corrected)
            self._track_correction_temp(rows=stop - start, width=width, float_buffers=3)
            del cached, corrected

    def _observe_control(self, *, block_index: int, step: int, stable_mask: int, full_core: Any) -> None:
        entry = self._host_cache.get(block_index)
        if entry is None or not entry.ready_for(target_step=step):
            return
        self.cache_hits += 1
        for region in range(REGION_COUNT):
            if not stable_mask & (1 << region):
                continue
            staging = self._upload_region(entry=entry, region=region)
            rows = self.plan_cache.get(1 << region).region_rows[region]
            positions = self._region_cache_positions[region]
            delta = self._channel_mean_delta(
                full_core=full_core, staging=staging, rows=rows, positions=positions
            )
            raw, corrected = self._bounded_region_metrics(
                full_core=full_core,
                staging=staging,
                rows=rows,
                positions=positions,
                delta=delta,
            )
            false_safe = (
                (~corrected["finite"])
                | (corrected["cosine"] < CATASTROPHIC_COSINE_MIN)
                | (corrected["normalized_l2"] > CATASTROPHIC_NORMALIZED_L2_MAX)
            )
            self._observations[block_index].append(
                {
                    "step": step,
                    "region": region,
                    "raw": raw,
                    "corrected": corrected,
                    "false_safe": false_safe,
                }
            )

    def _prepare_direct_reuse(
        self,
        *,
        block_index: int,
        step: int,
        stable_mask: int,
        q: Any,
        k: Any,
        v: Any,
        attention: Any,
        options: Mapping[str, Any],
    ) -> Any:
        entry = self._host_cache.get(block_index)
        if entry is None or not entry.ready_for(target_step=step):
            self.cache_misses += 1
            raise RuntimeError("A3-G1C host cache is missing, stale, or not ready")
        plan = self.plan_cache.get(stable_mask)
        selected_core = attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=plan.kernel_indices,
            attention=attention,
            optimized_attention=self.h3.optimized_attention,
            transformer_options=options,
        )
        self.partial_attention_calls += 1
        selected_rows = int(plan.kernel_indices.numel())
        self.partial_q_rows += selected_rows
        self.representative_q_rows += int(plan.representative_indices.numel())
        full_core = reconstruct_selected_core(selected_core, plan.kernel_indices, int(q.shape[0]))
        del selected_core
        self.cache_hits += 1
        omitted_total = 0
        for region in range(REGION_COUNT):
            if not stable_mask & (1 << region):
                continue
            staging = self._upload_region(entry=entry, region=region)
            rows = self.plan_cache.get(1 << region).region_rows[region]
            positions = self._region_cache_positions[region]
            delta = self._channel_mean_delta(
                full_core=full_core, staging=staging, rows=rows, positions=positions
            )
            self._apply_region_correction(
                full_core=full_core,
                staging=staging,
                rows=rows,
                positions=positions,
                delta=delta,
            )
            omitted_total += int(rows["omitted_indices"].numel())
        entry.invalidate()
        self.cache_invalidations += 1
        self.reused_omitted_rows += omitted_total
        return full_core

    def _exact_full(self, *, q: Any, k: Any, v: Any, attention: Any, options: Mapping[str, Any]) -> Any:
        self.full_attention_calls += 1
        return attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=None,
            attention=attention,
            optimized_attention=self.h3.optimized_attention,
            transformer_options=options,
        )

    def instrumented_forward(
        self,
        block: Any,
        x: Any,
        t_emb: Any,
        mod_segments: Sequence[Sequence[int]],
        rope_freqs: Any,
        transformer_options: Mapping[str, Any] | None = None,
    ) -> Any:
        call_index = self.block_call_count
        step, block_index = divmod(call_index, BLOCK_COUNT)
        if block_index == 0:
            self.model_forward_count += 1
        options = {} if transformer_options is None else transformer_options
        state_mutated = False
        partial_started = False
        full_before = self.full_attention_calls
        partial_before = self.partial_attention_calls
        try:
            if step >= TOTAL_STEPS or options.get("optimized_attention_override") is not None:
                self.mapping_error_count += 1
                raise ValueError("A3-G1C execution mapping or attention backend changed")
            video_start, video_stop = self._video_segment(x, mod_segments)
            self.plan_cache.materialize_all(
                sequence_length=int(x.shape[0]),
                video_start=video_start,
                video_stop=video_stop,
                device=x.device,
            )
            plan = self.plan_bridge.plans.get(step)
            stable_mask = (
                int(plan["stable_region_mask"])
                if plan is not None and int(plan["decision_code"]) == REGIONAL_ACTIVE_QUERY
                else 0
            )
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = block.adaln_proj(t_emb)
            attention_h = self.h3._mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments)
            q, k, v = _project_qkv(block.attn, attention_h, rope_freqs, **self._attention_kwargs())
            sequence = int(q.shape[0])
            self.full_q_rows_theoretical += sequence
            self.full_k_rows += sequence
            self.full_v_rows += sequence
            self.actual_k_rows += sequence
            self.actual_v_rows += sequence
            record = self.per_step.setdefault(
                step,
                {
                    "step": step,
                    "stable_region_mask": stable_mask,
                    "forced_full_blocks": 0,
                    "selective_candidate_blocks": 0,
                    "full_attention_calls": 0,
                    "partial_attention_calls": 0,
                },
            )
            cache_ready = self._cache_ready(block_index, step)
            directive, reason = rust_directive(
                plan=plan,
                step=step,
                block_index=block_index,
                candidate_blocks=self.candidate_blocks,
                cache_ready=cache_ready,
            )
            record["last_directive_reason"] = reason

            if self.mode == CONTROL_MODE:
                full_core = self._exact_full(q=q, k=k, v=v, attention=block.attn, options=options)
                self.forced_full_q_rows += sequence
                self.forced_full_blocks += 1
                record["forced_full_blocks"] += 1
                record["full_attention_calls"] += 1
                if block_index in self.candidate_blocks:
                    self._ensure_buffers(full_core=full_core, video_start=video_start)
                    if directive == SELECTIVE_CANDIDATE:
                        self.selective_candidate_blocks += 1
                        record["selective_candidate_blocks"] += 1
                        self._observe_control(
                            block_index=block_index,
                            step=step,
                            stable_mask=stable_mask,
                            full_core=full_core,
                        )
                    self._refresh_cache(block_index=block_index, step=step, full_core=full_core)
            elif directive == FORCE_FULL:
                full_core = self._exact_full(q=q, k=k, v=v, attention=block.attn, options=options)
                self.forced_full_blocks += 1
                self.forced_full_q_rows += sequence
                record["forced_full_blocks"] += 1
                record["full_attention_calls"] += 1
                if block_index in self.candidate_blocks:
                    self._ensure_buffers(full_core=full_core, video_start=video_start)
                    self._refresh_cache(block_index=block_index, step=step, full_core=full_core)
            else:
                self.selective_candidate_blocks += 1
                record["selective_candidate_blocks"] += 1
                partial_started = True
                full_core = self._prepare_direct_reuse(
                    block_index=block_index,
                    step=step,
                    stable_mask=stable_mask,
                    q=q,
                    k=k,
                    v=v,
                    attention=block.attn,
                    options=options,
                )
                record["partial_attention_calls"] += 1

            full_delta = self.full_attention_calls - full_before
            partial_delta = self.partial_attention_calls - partial_before
            if full_delta and partial_delta:
                self.normal_partial_plus_full_count += 1
                raise RuntimeError("A3-G1C normal path executed both Partial and Full Attention")
            if not attention_path_is_xor(full_calls=full_delta, partial_calls=partial_delta):
                raise RuntimeError("A3-G1C Attention path accounting is not XOR")

            attention_output = block.attn.out_proj(full_core)
            x = self.h3._mod_gate(x, gate_msa, attention_output, mod_segments)
            state_mutated = True
            h = self.h3._mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
            return self.h3._mod_gate(x, gate_mlp, block.mlp(h), mod_segments)
        except (IndexError, RuntimeError, TypeError, ValueError):
            if state_mutated:
                self.wrapper_failure_count += 1
                raise
            if partial_started:
                self.exception_partial_then_full_count += 1
            self.native_error_fallbacks += 1
            if self._original_forward is None:
                raise
            return self._original_forward(block, x, t_emb, mod_segments, rope_freqs, options)
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            self.block_call_count += 1

    def install(self, dit_class: Any) -> None:
        if self._original_forward is not None:
            raise RuntimeError("A3-G1 H3 wrapper already installed")
        self._dit_class = dit_class
        self._original_forward = dit_class.forward
        controller = self

        def wrapped(block, x, t_emb, mod_segments, rope_freqs, transformer_options=None):
            return controller.instrumented_forward(
                block, x, t_emb, mod_segments, rope_freqs, transformer_options
            )

        dit_class.forward = wrapped

    def restore(self) -> None:
        if self._original_forward is not None and self._dit_class is not None:
            self._dit_class.forward = self._original_forward
        self._original_forward = None
        self._dit_class = None

    def _observation_values(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        tensors = []
        for group in ("raw", "corrected"):
            metrics = observation[group]
            tensors.extend(
                (
                    metrics["cosine"],
                    metrics["normalized_l2"],
                    metrics["normalized_mae"],
                    metrics["energy_ratio"],
                    metrics["finite"].to(dtype=self.torch.float32),
                )
            )
        tensors.append(observation["false_safe"].to(dtype=self.torch.float32))
        values = self.torch.stack(tuple(tensors)).float().cpu().tolist()
        names = ("cosine", "normalized_l2", "normalized_mae", "energy_ratio", "finite")
        result: dict[str, Any] = {"step": observation["step"], "region": observation["region"]}
        offset = 0
        for group in ("raw", "corrected"):
            result[group] = {name: float(values[offset + index]) for index, name in enumerate(names)}
            result[group]["finite"] = bool(result[group]["finite"])
            offset += len(names)
        result["false_safe"] = bool(values[offset])
        return result

    def _block_calibration(self) -> tuple[list[dict[str, Any]], tuple[int, ...], int]:
        rows = []
        admitted = []
        false_safe_total = 0
        for block_index in self.candidate_blocks:
            values = [self._observation_values(item) for item in self._observations[block_index]]
            false_safe_total += sum(item["false_safe"] for item in values)
            corrected = [item["corrected"] for item in values if item["corrected"]["finite"]]
            raw = [item["raw"] for item in values if item["raw"]["finite"]]
            cosine = [item["cosine"] for item in corrected]
            l2 = [item["normalized_l2"] for item in corrected]
            energy = [item["energy_ratio"] for item in corrected]
            raw_l2 = [item["normalized_l2"] for item in raw]
            mean_cosine = sum(cosine) / len(cosine) if cosine else None
            p05_cosine = _percentile(cosine, 0.05)
            mean_l2 = sum(l2) / len(l2) if l2 else None
            p95_l2 = _percentile(l2, 0.95)
            mean_energy = sum(energy) / len(energy) if energy else None
            mean_raw_l2 = sum(raw_l2) / len(raw_l2) if raw_l2 else None
            passed = (
                len(values) >= BLOCK_OBSERVATIONS_MIN
                and len(corrected) == len(values)
                and mean_cosine is not None
                and mean_cosine >= MEAN_COSINE_MIN
                and p05_cosine is not None
                and p05_cosine >= P05_COSINE_MIN
                and mean_l2 is not None
                and mean_l2 <= MEAN_NORMALIZED_L2_MAX
                and p95_l2 is not None
                and p95_l2 <= P95_NORMALIZED_L2_MAX
                and mean_energy is not None
                and MEAN_ENERGY_RATIO_MIN <= mean_energy <= MEAN_ENERGY_RATIO_MAX
                and mean_raw_l2 is not None
                and mean_l2 <= mean_raw_l2
            )
            row = {
                "block_index": block_index,
                "observation_count": len(values),
                "nonfinite_count": len(values) - len(corrected),
                "mean_cosine": mean_cosine,
                "p05_cosine": p05_cosine,
                "mean_normalized_l2": mean_l2,
                "p95_normalized_l2": p95_l2,
                "mean_energy_ratio": mean_energy,
                "mean_raw_cache_normalized_l2": mean_raw_l2,
                "corrected_l2_non_regression": bool(
                    mean_l2 is not None and mean_raw_l2 is not None and mean_l2 <= mean_raw_l2
                ),
                "false_safe_count": sum(item["false_safe"] for item in values),
                "passed": passed,
            }
            rows.append(row)
            if passed:
                admitted.append(block_index)
        return rows, tuple(admitted), false_safe_total

    def finalize(self) -> dict[str, Any]:
        calibration, admitted, false_safe = self._block_calibration()
        accounting = work_accounting(
            full_q_rows_theoretical=self.full_q_rows_theoretical,
            forced_full_q_rows=self.forced_full_q_rows,
            partial_q_rows=self.partial_q_rows,
            reused_omitted_rows=self.reused_omitted_rows,
        )
        candidate_events = [
            record for record in self.per_step.values() if int(record["selective_candidate_blocks"]) > 0
        ]
        affected = sorted(record["step"] for record in candidate_events if record["step"] not in ANCHOR_STEPS)
        planned_omitted = sum(
            len(CPU_PROTOTYPE_PLANS[int(record["stable_region_mask"])].omitted_local_rows)
            * len(admitted)
            for record in candidate_events
        )
        actual_peak_allocated = actual_peak_reserved = None
        if self._memory_tracking:
            try:
                actual_peak_allocated = int(self.torch.cuda.max_memory_allocated())
                actual_peak_reserved = int(self.torch.cuda.max_memory_reserved())
            except (AttributeError, RuntimeError):
                pass
        return {
            "schema_version": "a3-g1c.h3.preplan-direct-selective.1",
            "mode": self.mode,
            "mechanism": MECHANISM_ID,
            "correction": CORRECTION_ID,
            "execution_authority": EXECUTION_AUTHORITY,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "candidate_blocks": list(self.candidate_blocks),
            "block_calibration": calibration,
            "admitted_blocks": list(admitted),
            "admitted_block_count": len(admitted),
            "false_safe_count": false_safe,
            "stable_plan_event_count": len(candidate_events),
            "affected_non_anchor_steps": affected,
            "planned_q_reduction_ratio": planned_omitted / max(1, self.full_q_rows_theoretical),
            "forced_full_blocks": self.forced_full_blocks,
            "selective_candidate_blocks": self.selective_candidate_blocks,
            "full_attention_calls": self.full_attention_calls,
            "partial_attention_calls": self.partial_attention_calls,
            "normal_partial_plus_full_count": self.normal_partial_plus_full_count,
            "exception_partial_then_full_count": self.exception_partial_then_full_count,
            "native_error_fallbacks": self.native_error_fallbacks,
            "work": {
                **accounting,
                "representative_q_rows": self.representative_q_rows,
                "full_k_rows": self.full_k_rows,
                "actual_k_rows": self.actual_k_rows,
                "full_v_rows": self.full_v_rows,
                "actual_v_rows": self.actual_v_rows,
            },
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "invalidations": self.cache_invalidations,
                "full_refreshes": self.full_refreshes,
                "host_cache_bytes": self.host_cache_bytes,
                "h2d_bytes": self.h2d_bytes,
                "d2h_bytes": self.d2h_bytes,
                "max_region_staging_bytes": self.region_staging_peak_bytes,
                "full_size_gpu_staging_count": self.full_size_gpu_staging_count,
            },
            "memory": {
                "removed_static_qkv_bytes": REMOVED_STATIC_QKV_BYTES,
                "projected_incremental_bytes": PROJECTED_INCREMENTAL_BYTES,
                "actual_peak_allocated": actual_peak_allocated,
                "actual_peak_reserved": actual_peak_reserved,
                "region_staging_peak": self.region_staging_peak_bytes,
                "correction_temp_peak": self.correction_temp_peak_bytes,
                "oom_count": 0,
            },
            "guard": {
                "d2h_bytes": self.guard_d2h_bytes,
                "host_reads": self.host_guard_reads,
                "explicit_hot_path_cpu_sync": self.explicit_hot_path_cpu_sync,
            },
            "rust": {
                "tensor_bytes": 0,
                "per_block_calls": 0,
                "per_token_calls": 0,
            },
            "conditional_graph_used": False,
            "gpu_same_block_guard_used": False,
            "static_qkv_used": False,
            "runtime_capture_count": 0,
            "control_full_output_original": self.mode == CONTROL_MODE,
            "duplicate_subset_attention_calls": (
                self.partial_attention_calls if self.mode == CONTROL_MODE else 0
            ),
            "mapping": prototype_mapping_contract(),
            "per_step": [self.per_step[index] for index in sorted(self.per_step)],
            "full_compute_fallback_preserved": self._original_forward is not None,
        }


def control_opportunity_gate(
    *,
    execution: Mapping[str, Any],
    region_plan: Mapping[str, Any],
    c2_shadow: Mapping[str, Any],
    output_integrity: bool,
    cache_capacity: int,
) -> dict[str, Any]:
    callback_p95 = c2_shadow.get("total_shadow_callback", {}).get("p95_ns")
    memory = execution.get("memory", {})
    cache = execution.get("cache", {})
    checks = {
        "control_full_output_original": execution.get("control_full_output_original") is True,
        "control_partial_attention_zero": int(execution.get("partial_attention_calls", -1)) == 0,
        "conditional_graph_removed": execution.get("conditional_graph_used") is False,
        "same_block_guard_removed": execution.get("gpu_same_block_guard_used") is False,
        "static_qkv_removed": execution.get("static_qkv_used") is False,
        "admitted_blocks": int(execution.get("admitted_block_count", 0)) >= MIN_ADMITTED_BLOCKS,
        "planned_q_reduction": float(execution.get("planned_q_reduction_ratio", 0.0)) >= MIN_PLANNED_Q_REDUCTION,
        "affected_non_anchor_steps": len(execution.get("affected_non_anchor_steps", [])) >= MIN_AFFECTED_NON_ANCHOR_STEPS,
        "stable_plan_events": int(execution.get("stable_plan_event_count", 0)) >= MIN_STABLE_PLAN_EVENTS,
        "false_safe_zero": int(execution.get("false_safe_count", -1)) == 0,
        "cache_capacity": int(cache_capacity) >= MIN_ADMITTED_BLOCKS,
        "output_integrity": bool(output_integrity),
        "full_fallback": execution.get("full_compute_fallback_preserved") is True,
        "callback_p95": isinstance(callback_p95, int) and callback_p95 <= CALLBACK_P95_NS_MAX,
        "tensor_to_rust_zero": region_plan.get("tensor_bytes_to_rust") == 0,
        "per_block_rust_zero": execution.get("rust", {}).get("per_block_calls") == 0,
        "per_token_rust_zero": execution.get("rust", {}).get("per_token_calls") == 0,
        "normal_double_work_zero": int(execution.get("normal_partial_plus_full_count", -1)) == 0,
        "exception_double_work_zero": int(execution.get("exception_partial_then_full_count", -1)) == 0,
        "full_size_staging_zero": int(cache.get("full_size_gpu_staging_count", -1)) == 0,
        "region_staging_bounded": int(cache.get("max_region_staging_bytes", MAX_REGION_STAGING_BYTES + 1)) <= MAX_REGION_STAGING_BYTES,
        "correction_temporary_bounded": int(memory.get("correction_temp_peak", MAX_CORRECTION_TEMP_BYTES + 1)) <= MAX_CORRECTION_TEMP_BYTES,
    }
    if not checks["false_safe_zero"]:
        decision = DECISION_PREPLAN_NOT_SAFE
    elif not checks["correction_temporary_bounded"]:
        decision = DECISION_CORRECTION_MEMORY
    elif not checks["normal_double_work_zero"] or not checks["exception_double_work_zero"]:
        decision = DECISION_DOUBLE_WORK
    elif not all(checks.values()):
        decision = DECISION_REUSE_NOT_ADMITTED
    else:
        decision = "A3_G1C_SELECTIVE_ADMITTED"
    return {"checks": checks, "passed": all(checks.values()), "decision": decision}


__all__ = [
    "A2_RANKED_BLOCKS",
    "attention_path_is_xor",
    "CORRECTION_CHUNK_ROWS",
    "CONTROL_MODE",
    "DECISION_CORRECTION_MEMORY",
    "DECISION_DOUBLE_WORK",
    "DECISION_GUARD_NOT_SAFE",
    "DECISION_ISLAND_NOT_ADMITTED",
    "DECISION_OMISSION_NOT_PROVEN",
    "DECISION_PREPLAN_NOT_SAFE",
    "DECISION_QUALITY_REJECTED",
    "DECISION_READY_FOR_VISUAL",
    "DECISION_REUSE_NOT_ADMITTED",
    "DECISION_RUNTIME_NOT_POSITIVE",
    "EXECUTION_AUTHORITY",
    "FORCE_FULL",
    "H3A3G1Controller",
    "MAX_CORRECTION_TEMP_BYTES",
    "MAX_REGION_STAGING_BYTES",
    "PROJECTED_INCREMENTAL_BYTES",
    "REMOVED_STATIC_QKV_BYTES",
    "SELECTIVE_CANDIDATE",
    "SELECTIVE_MODE",
    "control_opportunity_gate",
    "correction_temp_bytes",
    "fixed_contract",
    "rust_directive",
    "reconstruct_selected_core",
    "settings_digest",
    "work_accounting",
]
