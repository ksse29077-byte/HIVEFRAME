"""A3-G1 real-H3 attention reuse with GPU-native conditional omission.

The generic Rust plan remains coarse: it can force Full Compute or request a
GPU check.  The H3 adapter owns tensor layout, the one-generation cache, the
representative guard, and the exact PyTorch SDPA execution island.  Ambiguous
state always falls back to the unmodified Full Attention call.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence
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
    ATTENTION_CORE_WIDTH,
    BLOCK_OBSERVATIONS_MIN,
    CACHE_LOCAL_ROWS,
    CACHE_ROW_POSITION,
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
    CORRECTION_ID,
    MAX_GPU_STAGING_BYTES,
    MEAN_COSINE_MIN,
    MEAN_ENERGY_RATIO_MAX,
    MEAN_ENERGY_RATIO_MIN,
    MEAN_NORMALIZED_L2_MAX,
    MECHANISM_ID,
    P05_COSINE_MIN,
    P95_NORMALIZED_L2_MAX,
    REPRESENTATIVE_COSINE_MIN,
    REPRESENTATIVE_NORMALIZED_L2_MAX,
    cache_budget_plan,
    correction_tensors,
    metric_tensors,
)
from .gpu_conditional_omission import DECISION_READY as G0_READY_DECISION
from .regional_query_prototype_attention import (
    CPU_PROTOTYPE_PLANS,
    GPUPrototypePlanCache,
    _project_qkv,
    attention_core,
    prototype_mapping_contract,
)


CONTROL_MODE = "CONTROL_A3_G1_REAL_H3"
SELECTIVE_MODE = "SELECTIVE_A3_G1_REAL_H3"
EXECUTION_AUTHORITY = "GPU_NATIVE_CONDITIONAL_KERNEL_OMISSION_V1"
EXECUTION_ISLAND = "PYTORCH_CUDAGRAPH_CONDITIONAL_IF_EXACT_SDPA_V1"
FORCE_FULL = "FORCE_FULL"
GPU_CHECK = "GPU_CHECK"
SAFE_REUSE = "SAFE_REUSE"
FULL_COMPUTE = "FULL_COMPUTE"

DECISION_ISLAND_NOT_ADMITTED = "A3_G1_REAL_H3_EXECUTION_ISLAND_NOT_ADMITTED"
DECISION_PARITY_FAILED = "A3_G1_NATIVE_FULL_ATTENTION_PARITY_FAILED"
DECISION_GUARD_NOT_SAFE = "A3_G1_RUNTIME_GUARD_NOT_SAFE"
DECISION_REUSE_NOT_ADMITTED = "A3_G1_REUSE_NOT_ADMITTED"
DECISION_OMISSION_NOT_PROVEN = "A3_G1_REAL_WORK_OMISSION_NOT_PROVEN"
DECISION_QUALITY_REJECTED = "A3_G1_QUALITY_REJECTED"
DECISION_RUNTIME_NOT_POSITIVE = "A3_G1_WORK_REDUCTION_VERIFIED_RUNTIME_NOT_POSITIVE"
DECISION_READY_FOR_VISUAL = "A3_G1_REAL_H3_SELECTIVE_ACCELERATION_READY_FOR_VISUAL_REVIEW"

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
        "execution_island": EXECUTION_ISLAND,
        "g0_required_decision": G0_READY_DECISION,
        "product_default_enabled": False,
        "rust_directives": [FORCE_FULL, GPU_CHECK],
        "gpu_results": [SAFE_REUSE, FULL_COMPUTE],
        "block_decision": "ALL_ELIGIBLE_STABLE_REGIONS_MUST_PASS",
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
        "runtime_guard": {
            "representative_cosine_min": REPRESENTATIVE_COSINE_MIN,
            "representative_normalized_l2_max": REPRESENTATIVE_NORMALIZED_L2_MAX,
            "nonfinite_count": 0,
        },
        "conditional_graph": {
            "capture_tracing": "FAKE_TENSOR_NO_KERNEL_EXECUTION",
            "predicate": "CUDA_BOOL_SCALAR",
            "host_predicate_read": False,
            "static_address_required": True,
            "address_mismatch": FORCE_FULL,
            "recapture_on_hot_path": False,
        },
        "maximum_gpu_staging_bytes": MAX_GPU_STAGING_BYTES,
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


def execution_island_source_admission(torch_module: Any, optimized_attention: Any) -> dict[str, Any]:
    graph_type = getattr(getattr(torch_module, "cuda", None), "CUDAGraph", None)
    checks = {
        "cuda_available": bool(torch_module.cuda.is_available()),
        "cuda_if_capture_api": bool(graph_type and hasattr(graph_type, "begin_capture_to_if_node")),
        "cuda_conditional_end_api": bool(graph_type and hasattr(graph_type, "end_capture_to_conditional_node")),
        "cuda_runtime_at_least_12_8": _cuda_version_at_least(getattr(torch_module.version, "cuda", None), (12, 8)),
        "exact_attention_backend": getattr(optimized_attention, "__name__", "") == "attention_pytorch",
        "g0_authority_ready": G0_READY_DECISION == "A3_G0_GPU_CONDITIONAL_OMISSION_READY",
    }
    return {
        "method": EXECUTION_ISLAND,
        "exact_attention_backend": getattr(optimized_attention, "__name__", type(optimized_attention).__name__),
        "torch_version": str(torch_module.__version__),
        "torch_cuda_build": getattr(torch_module.version, "cuda", None),
        "checks": checks,
        "admitted": all(checks.values()),
        "fallback": FULL_COMPUTE,
    }


def _cuda_version_at_least(value: str | None, required: tuple[int, int]) -> bool:
    if not value:
        return False
    try:
        parts = tuple(int(item) for item in value.split(".")[:2])
    except ValueError:
        return False
    return parts >= required


def rust_directive(
    *,
    plan: Mapping[str, Any] | None,
    step: int,
    block_index: int,
    candidate_blocks: Sequence[int],
    cache_ready: bool,
) -> tuple[str, str]:
    """Map the existing metadata-only A1 ABI to the two fixed G1 directives."""

    if block_index not in candidate_blocks:
        return FORCE_FULL, "block_not_candidate"
    if step in ANCHOR_STEPS:
        return FORCE_FULL, "anchor_step"
    if plan is None:
        return FORCE_FULL, "plan_missing_or_late"
    if int(plan.get("decision_code", ESCALATE_FULL_COMPUTE)) != REGIONAL_ACTIVE_QUERY:
        return FORCE_FULL, "plan_requires_full"
    stable = int(plan.get("stable_region_mask", 0))
    if stable == 0 or stable & ~REGION_MASK:
        return FORCE_FULL, "stable_mask_missing_or_invalid"
    if int(plan.get("uncertain_mask", 0)) != 0:
        return FORCE_FULL, "uncertain_region_present"
    if int(plan.get("refresh_region_mask", 0)) & stable:
        return FORCE_FULL, "refresh_required"
    if not cache_ready:
        return FORCE_FULL, "cache_missing_stale_or_not_ready"
    return GPU_CHECK, "stable_cache_candidate"


def gpu_guard_metrics(current: Any, cached: Any, torch_module: Any) -> dict[str, Any]:
    metrics = metric_tensors(current, cached, torch_module)
    safe = (
        metrics["finite"]
        & (metrics["cosine"] >= REPRESENTATIVE_COSINE_MIN)
        & (metrics["normalized_l2"] <= REPRESENTATIVE_NORMALIZED_L2_MAX)
    )
    return {**metrics, "safe": safe}


def aggregate_all_safe(guards: Sequence[Any], torch_module: Any) -> Any:
    if not guards:
        raise ValueError("A3-G1 block guard requires at least one stable region")
    result = guards[0]
    for guard in guards[1:]:
        result = torch_module.logical_and(result, guard)
    return result


def work_accounting(
    *,
    full_q_rows_theoretical: int,
    forced_full_q_rows: int,
    representative_and_required_q_rows: int,
    conditional_full_q_rows: int,
    reused_omitted_rows: int,
) -> dict[str, Any]:
    actual = forced_full_q_rows + representative_and_required_q_rows + conditional_full_q_rows
    reduction = 1.0 - actual / full_q_rows_theoretical if full_q_rows_theoretical else 0.0
    return {
        "full_q_rows_theoretical": int(full_q_rows_theoretical),
        "actual_current_q_rows": int(actual),
        "representative_and_required_q_rows": int(representative_and_required_q_rows),
        "reused_omitted_rows": int(reused_omitted_rows),
        "actual_q_reduction_ratio": float(reduction),
    }


class GPUConditionalAttentionIsland:
    """One fixed-address exact-SDPA/reuse conditional CUDA graph.

    The graph is captured from fake-traced branch GraphModules, so capture does
    not execute the exact Full body.  Rebinding or hot-path recapture is not
    attempted.  Any address, shape, dtype, device, or backend mismatch is a
    structural Full Compute fallback owned by the caller.
    """

    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module
        self.graph: Any | None = None
        self.output: Any | None = None
        self.predicate: Any | None = None
        self.omitted_rows: Any | None = None
        self.full_count: Any | None = None
        self.reuse_count: Any | None = None
        self.reused_rows: Any | None = None
        self.conditional_full_q_rows: Any | None = None
        self.parity_equal: Any | None = None
        self._signature: tuple[Any, ...] | None = None
        self.capture_count = 0
        self.replay_count = 0
        self.capture_error: str | None = None

    @staticmethod
    def _tensor_signature(tensor: Any) -> tuple[Any, ...]:
        return (
            int(tensor.data_ptr()),
            tuple(int(value) for value in tensor.shape),
            tuple(int(value) for value in tensor.stride()),
            str(tensor.dtype),
            str(tensor.device),
        )

    def compatible(self, q: Any, k: Any, v: Any, safe_core: Any) -> bool:
        return self._signature == tuple(
            value
            for tensor in (q, k, v, safe_core)
            for value in self._tensor_signature(tensor)
        )

    def capture(
        self,
        *,
        q: Any,
        k: Any,
        v: Any,
        safe_core: Any,
        full_callable: Callable[[Any, Any, Any], Any],
        parity_reference: Any | None,
    ) -> None:
        if self.graph is not None:
            raise RuntimeError("A3-G1 conditional graph is already captured")
        if not (q.is_cuda and k.is_cuda and v.is_cuda and safe_core.is_cuda):
            raise RuntimeError("A3-G1 conditional graph requires CUDA tensors")
        if safe_core.numel() * safe_core.element_size() > MAX_GPU_STAGING_BYTES:
            raise RuntimeError("A3-G1 safe staging exceeds the frozen GPU budget")
        try:
            from torch.fx.experimental.proxy_tensor import make_fx
            from torch._higher_order_ops.cudagraph_conditional_nodes import (
                CUDAGraphCaptureControlFlowOpDispatchMode,
            )

            device = q.device
            self.predicate = self.torch.zeros((), dtype=self.torch.bool, device=device)
            self.omitted_rows = self.torch.zeros((), dtype=self.torch.int64, device=device)
            self.full_count = self.torch.zeros((), dtype=self.torch.int64, device=device)
            self.reuse_count = self.torch.zeros((), dtype=self.torch.int64, device=device)
            self.reused_rows = self.torch.zeros((), dtype=self.torch.int64, device=device)
            self.conditional_full_q_rows = self.torch.zeros((), dtype=self.torch.int64, device=device)

            def full_branch(qt, kt, vt, safe, full_count, reuse_count, reused_rows, omitted_rows, full_q_rows):
                full_count.add_(1)
                full_q_rows.add_(qt.shape[0])
                return full_callable(qt, kt, vt)

            def reuse_branch(qt, kt, vt, safe, full_count, reuse_count, reused_rows, omitted_rows, full_q_rows):
                reuse_count.add_(1)
                reused_rows.add_(omitted_rows)
                return safe

            operands = (
                q,
                k,
                v,
                safe_core,
                self.full_count,
                self.reuse_count,
                self.reused_rows,
                self.omitted_rows,
                self.conditional_full_q_rows,
            )
            full_graph = make_fx(full_branch, tracing_mode="fake")(*operands)
            reuse_graph = make_fx(reuse_branch, tracing_mode="fake")(*operands)
            graph = self.torch.cuda.CUDAGraph(keep_graph=True)
            with self.torch.cuda.graph(graph), CUDAGraphCaptureControlFlowOpDispatchMode():
                output = self.torch.ops.higher_order.cond(
                    self.predicate,
                    full_graph,
                    reuse_graph,
                    operands,
                )
            graph.instantiate()
            self.graph = graph
            self.output = output
            self._signature = tuple(
                value
                for tensor in (q, k, v, safe_core)
                for value in self._tensor_signature(tensor)
            )
            self.capture_count = 1
            if parity_reference is not None:
                if (
                    tuple(output.shape) != tuple(parity_reference.shape)
                    or output.dtype != parity_reference.dtype
                    or output.device != parity_reference.device
                ):
                    raise RuntimeError("A3-G1 native Full parity metadata differs")
                self.predicate.fill_(True)
                self.omitted_rows.zero_()
                graph.replay()
                self.replay_count += 1
                self.parity_equal = self.torch.all(output == parity_reference)
        except BaseException as error:
            self.capture_error = type(error).__name__
            self.graph = None
            self.output = None
            raise

    def dispatch(self, *, unsafe: Any, omitted_rows: int, q: Any, k: Any, v: Any, safe_core: Any) -> Any:
        if self.graph is None or self.output is None or self.predicate is None or self.omitted_rows is None:
            raise RuntimeError("A3-G1 conditional graph is unavailable")
        if not self.compatible(q, k, v, safe_core):
            raise RuntimeError("A3-G1 conditional graph static address contract changed")
        if not (unsafe.is_cuda and unsafe.dtype == self.torch.bool and unsafe.numel() == 1):
            raise RuntimeError("A3-G1 guard predicate must remain a CUDA bool scalar")
        self.predicate.copy_(unsafe)
        self.omitted_rows.fill_(int(omitted_rows))
        self.graph.replay()
        self.replay_count += 1
        return self.output

    def receipt(self) -> dict[str, Any]:
        counters = None
        if self.full_count is not None:
            stacked = self.torch.stack(
                (
                    self.full_count,
                    self.reuse_count,
                    self.reused_rows,
                    self.conditional_full_q_rows,
                )
            ).cpu().tolist()
            counters = {
                "full_body_executions": int(stacked[0]),
                "reuse_body_executions": int(stacked[1]),
                "reused_omitted_rows": int(stacked[2]),
                "conditional_full_q_rows": int(stacked[3]),
            }
        parity = None if self.parity_equal is None else bool(self.parity_equal.cpu())
        return {
            "method": EXECUTION_ISLAND,
            "capture_count": self.capture_count,
            "replay_count": self.replay_count,
            "capture_error": self.capture_error,
            "static_address_contract": self._signature is not None,
            "native_full_parity_bit_exact": parity,
            "counters": counters,
        }


@dataclass
class HostCacheEntry:
    tensor: Any
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
    """H3-specific block wrapper for one bounded CONTROL or SELECTIVE run."""

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
            raise ValueError("unsupported A3-G1 mode")
        candidates = tuple(int(value) for value in candidate_blocks)
        if len(set(candidates)) != len(candidates) or any(not 0 <= value < BLOCK_COUNT for value in candidates):
            raise ValueError("A3-G1 candidate block list is malformed")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.h3 = h3_model
        self.torch = torch_module
        self.candidate_blocks = candidates
        self.plan_cache = GPUPrototypePlanCache(torch_module)
        self.island = GPUConditionalAttentionIsland(torch_module)
        self._original_forward: Any | None = None
        self._dit_class: Any | None = None
        self._cache_indices: Any | None = None
        self._cache_staging: Any | None = None
        self._safe_core: Any | None = None
        self._region_cache_positions: dict[int, dict[str, Any]] = {}
        self._host_cache: dict[int, HostCacheEntry] = {}
        self._observations: dict[int, list[dict[str, Any]]] = {index: [] for index in candidates}
        self.block_call_count = 0
        self.model_forward_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.forced_full_blocks = 0
        self.gpu_check_blocks = 0
        self.pointer_mismatch_fallbacks = 0
        self.native_error_fallbacks = 0
        self.full_attention_eager_calls = 0
        self.partial_attention_calls = 0
        self.full_q_rows_theoretical = 0
        self.forced_full_q_rows = 0
        self.partial_q_rows = 0
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
        self.gpu_staging_peak_bytes = 0
        self.guard_d2h_bytes = 0
        self.host_guard_reads = 0
        self.explicit_hot_path_cpu_sync = 0
        self.per_step: dict[int, dict[str, Any]] = {}

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
        if self._cache_indices is not None:
            if self._safe_core is None or self._safe_core.shape != full_core.shape or self._safe_core.dtype != full_core.dtype:
                raise ValueError("A3-G1 runtime tensor metadata changed")
            return
        device = full_core.device
        self._cache_indices = self.torch.tensor(
            [video_start + row for row in CACHE_LOCAL_ROWS], dtype=self.torch.long, device=device
        )
        self._cache_staging = self.torch.empty(
            (len(CACHE_LOCAL_ROWS), int(full_core.shape[-1])), dtype=full_core.dtype, device=device
        )
        self._safe_core = self.torch.empty_like(full_core)
        for region in range(REGION_COUNT):
            rows = CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]
            self._region_cache_positions[region] = {
                "representative": self.torch.tensor(
                    [CACHE_ROW_POSITION[row] for row in rows["representative"]],
                    dtype=self.torch.long,
                    device=device,
                ),
                "omitted": self.torch.tensor(
                    [CACHE_ROW_POSITION[row] for row in rows["omitted"]],
                    dtype=self.torch.long,
                    device=device,
                ),
            }
        staging = int(self._cache_staging.numel()) * int(self._cache_staging.element_size())
        self.gpu_staging_peak_bytes = max(self.gpu_staging_peak_bytes, staging)
        if staging > MAX_GPU_STAGING_BYTES:
            raise RuntimeError("A3-G1 GPU cache staging exceeds the frozen budget")

    def _cache_entry(self, block_index: int, full_core: Any) -> HostCacheEntry:
        entry = self._host_cache.get(block_index)
        if entry is None:
            tensor = self.torch.empty(
                (len(CACHE_LOCAL_ROWS), int(full_core.shape[-1])),
                dtype=full_core.dtype,
                device="cpu",
                pin_memory=True,
            )
            entry = HostCacheEntry(tensor=tensor, event=self.torch.cuda.Event(blocking=False))
            self._host_cache[block_index] = entry
            self.host_cache_bytes += int(tensor.numel()) * int(tensor.element_size())
        return entry

    def _cache_ready(self, block_index: int, step: int) -> bool:
        entry = self._host_cache.get(block_index)
        return bool(entry and entry.ready_for(target_step=step))

    def _upload_cache(self, block_index: int, step: int) -> HostCacheEntry:
        entry = self._host_cache.get(block_index)
        if entry is None or not entry.ready_for(target_step=step):
            self.cache_misses += 1
            raise RuntimeError("A3-G1 host cache is missing, stale, or not ready")
        self._cache_staging.copy_(entry.tensor, non_blocking=True)
        transferred = int(entry.tensor.numel()) * int(entry.tensor.element_size())
        self.h2d_bytes += transferred
        self.cache_hits += 1
        return entry

    def _refresh_cache(self, *, block_index: int, step: int, full_core: Any) -> None:
        entry = self._cache_entry(block_index, full_core)
        self.torch.index_select(full_core, 0, self._cache_indices, out=self._cache_staging)
        entry.tensor.copy_(self._cache_staging, non_blocking=True)
        entry.event.record(self.torch.cuda.current_stream(device=full_core.device))
        entry.source_step = step
        entry.source_kind = "ACTUAL_FULL_ATTENTION_CORE_OUTPUT"
        entry.valid = True
        transferred = int(entry.tensor.numel()) * int(entry.tensor.element_size())
        self.d2h_bytes += transferred
        self.full_refreshes += 1

    def _region_tensors(self, *, full_or_safe: Any, stable_mask: int, video_start: int):
        for region in range(REGION_COUNT):
            if not stable_mask & (1 << region):
                continue
            rows = self.plan_cache.get(1 << region).region_rows[region]
            positions = self._region_cache_positions[region]
            yield (
                region,
                full_or_safe.index_select(0, rows["representative_indices"]),
                self._cache_staging.index_select(0, positions["representative"]),
                rows,
                positions,
            )

    def _observe_control(self, *, block_index: int, step: int, stable_mask: int, full_core: Any, video_start: int) -> None:
        if stable_mask == 0 or not self._cache_ready(block_index, step):
            return
        self._upload_cache(block_index, step)
        for region, current_rep, cached_rep, rows, positions in self._region_tensors(
            full_or_safe=full_core, stable_mask=stable_mask, video_start=video_start
        ):
            actual_omitted = full_core.index_select(0, rows["omitted_indices"])
            cached_omitted = self._cache_staging.index_select(0, positions["omitted"])
            _, corrected = correction_tensors(
                current_representative=current_rep,
                cached_representative=cached_rep,
                cached_omitted=cached_omitted,
            )
            guard = gpu_guard_metrics(current_rep, cached_rep, self.torch)
            raw = metric_tensors(actual_omitted, cached_omitted, self.torch)
            corrected_metrics = metric_tensors(actual_omitted, corrected, self.torch)
            catastrophic = (
                (~corrected_metrics["finite"])
                | (corrected_metrics["cosine"] < CATASTROPHIC_COSINE_MIN)
                | (corrected_metrics["normalized_l2"] > CATASTROPHIC_NORMALIZED_L2_MAX)
            )
            self._observations[block_index].append(
                {
                    "step": step,
                    "region": region,
                    "guard": guard,
                    "raw": raw,
                    "corrected": corrected_metrics,
                    "false_safe": guard["safe"] & catastrophic,
                }
            )

    def _prepare_safe(
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
    ) -> tuple[Any, Any, int]:
        entry = self._upload_cache(block_index, step)
        plan = self.plan_cache.get(stable_mask)
        selected = attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=plan.kernel_indices,
            attention=attention,
            optimized_attention=self.h3.optimized_attention,
            transformer_options=options,
        )
        self.partial_attention_calls += 1
        self.partial_q_rows += int(plan.kernel_indices.numel())
        self._safe_core.index_copy_(0, plan.kernel_indices, selected)
        guards = []
        omitted_total = 0
        for region, current_rep, cached_rep, rows, positions in self._region_tensors(
            full_or_safe=self._safe_core, stable_mask=stable_mask, video_start=0
        ):
            cached_omitted = self._cache_staging.index_select(0, positions["omitted"])
            _, corrected = correction_tensors(
                current_representative=current_rep,
                cached_representative=cached_rep,
                cached_omitted=cached_omitted,
            )
            self._safe_core.index_copy_(0, rows["omitted_indices"], corrected)
            guards.append(gpu_guard_metrics(current_rep, cached_rep, self.torch)["safe"])
            omitted_total += int(rows["omitted_indices"].numel())
        all_safe = aggregate_all_safe(guards, self.torch)
        unsafe = self.torch.logical_not(all_safe)
        entry.invalidate()
        self.cache_invalidations += 1
        return self._safe_core, unsafe, omitted_total

    def _exact_full(self, *, q: Any, k: Any, v: Any, attention: Any, options: Mapping[str, Any]) -> Any:
        self.full_attention_eager_calls += 1
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
        try:
            if step >= TOTAL_STEPS or options.get("optimized_attention_override") is not None:
                raise ValueError("A3-G1 execution mapping or attention backend changed")
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
                    "gpu_check_blocks": 0,
                },
            )

            if self.mode == CONTROL_MODE:
                full_core = self._exact_full(q=q, k=k, v=v, attention=block.attn, options=options)
                self.forced_full_q_rows += sequence
                self.forced_full_blocks += 1
                record["forced_full_blocks"] += 1
                self._ensure_buffers(full_core=full_core, video_start=video_start)
                if step == 0 and block_index == 0:
                    self._safe_core.copy_(full_core)
                    full_callable = lambda qt, kt, vt: attention_core(
                        q=qt,
                        k=kt,
                        v=vt,
                        q_indices=None,
                        attention=block.attn,
                        optimized_attention=self.h3.optimized_attention,
                        transformer_options=options,
                    )
                    self.island.capture(
                        q=q,
                        k=k,
                        v=v,
                        safe_core=self._safe_core,
                        full_callable=full_callable,
                        parity_reference=full_core,
                    )
                    full_core = self.island.output
                if block_index in self.candidate_blocks:
                    self._observe_control(
                        block_index=block_index,
                        step=step,
                        stable_mask=stable_mask,
                        full_core=full_core,
                        video_start=video_start,
                    )
                    self._refresh_cache(block_index=block_index, step=step, full_core=full_core)
            else:
                cache_ready = self._cache_ready(block_index, step)
                directive, reason = rust_directive(
                    plan=plan,
                    step=step,
                    block_index=block_index,
                    candidate_blocks=self.candidate_blocks,
                    cache_ready=cache_ready,
                )
                record["last_directive_reason"] = reason
                if directive == FORCE_FULL:
                    full_core = self._exact_full(q=q, k=k, v=v, attention=block.attn, options=options)
                    self.forced_full_blocks += 1
                    self.forced_full_q_rows += sequence
                    record["forced_full_blocks"] += 1
                    if block_index in self.candidate_blocks:
                        self._ensure_buffers(full_core=full_core, video_start=video_start)
                        self._refresh_cache(block_index=block_index, step=step, full_core=full_core)
                else:
                    self.gpu_check_blocks += 1
                    record["gpu_check_blocks"] += 1
                    if self._safe_core is None:
                        raise RuntimeError("A3-G1 staging must be initialized by a prior Full refresh")
                    safe_core, unsafe, omitted_rows = self._prepare_safe(
                        block_index=block_index,
                        step=step,
                        stable_mask=stable_mask,
                        q=q,
                        k=k,
                        v=v,
                        attention=block.attn,
                        options=options,
                    )
                    full_callable = lambda qt, kt, vt: attention_core(
                        q=qt,
                        k=kt,
                        v=vt,
                        q_indices=None,
                        attention=block.attn,
                        optimized_attention=self.h3.optimized_attention,
                        transformer_options=options,
                    )
                    if self.island.graph is None:
                        self.island.capture(
                            q=q,
                            k=k,
                            v=v,
                            safe_core=safe_core,
                            full_callable=full_callable,
                            parity_reference=None,
                        )
                    if not self.island.compatible(q, k, v, safe_core):
                        self.pointer_mismatch_fallbacks += 1
                        full_core = self._exact_full(q=q, k=k, v=v, attention=block.attn, options=options)
                        self.forced_full_q_rows += sequence
                        self._refresh_cache(block_index=block_index, step=step, full_core=full_core)
                    else:
                        full_core = self.island.dispatch(
                            unsafe=unsafe,
                            omitted_rows=omitted_rows,
                            q=q,
                            k=k,
                            v=v,
                            safe_core=safe_core,
                        )

            attention_output = block.attn.out_proj(full_core)
            x = self.h3._mod_gate(x, gate_msa, attention_output, mod_segments)
            state_mutated = True
            h = self.h3._mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
            return self.h3._mod_gate(x, gate_mlp, block.mlp(h), mod_segments)
        except (IndexError, RuntimeError, TypeError, ValueError):
            if state_mutated:
                self.wrapper_failure_count += 1
                raise
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
        for group in ("guard", "raw", "corrected"):
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
        for group in ("guard", "raw", "corrected"):
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
        island = self.island.receipt()
        calibration, admitted, false_safe = self._block_calibration()
        counters = island.get("counters") or {
            "full_body_executions": 0,
            "reuse_body_executions": 0,
            "reused_omitted_rows": 0,
            "conditional_full_q_rows": 0,
        }
        accounting = work_accounting(
            full_q_rows_theoretical=self.full_q_rows_theoretical,
            forced_full_q_rows=self.forced_full_q_rows,
            representative_and_required_q_rows=self.partial_q_rows,
            conditional_full_q_rows=int(counters["conditional_full_q_rows"]),
            reused_omitted_rows=int(counters["reused_omitted_rows"]),
        )
        stable_events = [
            record for record in self.per_step.values() if int(record["stable_region_mask"]) != 0
        ]
        affected = sorted(
            record["step"] for record in stable_events if record["step"] not in ANCHOR_STEPS
        )
        planned_omitted = sum(
            len(CPU_PROTOTYPE_PLANS[int(record["stable_region_mask"])].omitted_local_rows)
            * len(admitted)
            for record in stable_events
        )
        return {
            "schema_version": "a3-g1.h3.conditional-reuse-execution.1",
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
            "stable_plan_event_count": len(stable_events),
            "affected_non_anchor_steps": affected,
            "planned_q_reduction_ratio": planned_omitted / max(1, self.full_q_rows_theoretical),
            "forced_full_blocks": self.forced_full_blocks,
            "gpu_check_blocks": self.gpu_check_blocks,
            "safe_reuse_blocks": int(counters["reuse_body_executions"]),
            "unsafe_fallback_blocks": int(counters["full_body_executions"]),
            "full_attention_eager_calls": self.full_attention_eager_calls,
            "full_attention_body_executions": self.full_attention_eager_calls + int(counters["full_body_executions"]),
            "reuse_body_executions": int(counters["reuse_body_executions"]),
            "pointer_mismatch_fallbacks": self.pointer_mismatch_fallbacks,
            "native_error_fallbacks": self.native_error_fallbacks,
            "work": {
                **accounting,
                "representative_q_rows": self.partial_q_rows,
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
                "gpu_staging_peak_bytes": self.gpu_staging_peak_bytes,
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
            "execution_island": island,
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
    checks = {
        "native_full_parity": execution.get("execution_island", {}).get("native_full_parity_bit_exact") is True,
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
    }
    if not checks["native_full_parity"]:
        decision = DECISION_PARITY_FAILED
    elif not checks["false_safe_zero"]:
        decision = DECISION_GUARD_NOT_SAFE
    elif not all(checks.values()):
        decision = DECISION_REUSE_NOT_ADMITTED
    else:
        decision = "A3_G1_SELECTIVE_ADMITTED"
    return {"checks": checks, "passed": all(checks.values()), "decision": decision}


__all__ = [
    "A2_RANKED_BLOCKS",
    "CONTROL_MODE",
    "DECISION_GUARD_NOT_SAFE",
    "DECISION_ISLAND_NOT_ADMITTED",
    "DECISION_OMISSION_NOT_PROVEN",
    "DECISION_PARITY_FAILED",
    "DECISION_QUALITY_REJECTED",
    "DECISION_READY_FOR_VISUAL",
    "DECISION_REUSE_NOT_ADMITTED",
    "DECISION_RUNTIME_NOT_POSITIVE",
    "EXECUTION_AUTHORITY",
    "EXECUTION_ISLAND",
    "FORCE_FULL",
    "FULL_COMPUTE",
    "GPU_CHECK",
    "GPUConditionalAttentionIsland",
    "H3A3G1Controller",
    "SAFE_REUSE",
    "SELECTIVE_MODE",
    "aggregate_all_safe",
    "control_opportunity_gate",
    "execution_island_source_admission",
    "fixed_contract",
    "gpu_guard_metrics",
    "rust_directive",
    "settings_digest",
    "work_accounting",
]
