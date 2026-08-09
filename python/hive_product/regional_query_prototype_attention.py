"""A2 GPU-resident regional query-prototype attention for Local H3.

The existing A1 Rust ABI owns semantic region decisions.  This H3 adapter
precomputes fixed packed-row mappings, evaluates exact representative Q rows
against full/global K/V, and reconstructs only stable-region interior attention
core outputs.  Every unsupported state fails open to Full Compute.
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
    CONTROL_MODE as A1_CONTROL_MODE,
    ESCALATE_FULL_COMPUTE,
    FULL_COMPUTE,
    HALO_PATCHES,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    REGION_COUNT,
    REGION_LOCAL_ROWS,
    REGION_MASK,
    REGIONAL_ACTIVE_QUERY,
    SELECTIVE_MODE as A1_SELECTIVE_MODE,
    TOTAL_STEPS,
    VIDEO_LATENT_TIME,
    VIDEO_PATCH_HEIGHT,
    VIDEO_PATCH_WIDTH,
    VIDEO_TOKEN_COUNT,
    AttentionRegionPlanBridge,
    RegionPlanContext,
    inspect_installed_attention_source,
)


MECHANISM_ID = "GPU_RESIDENT_REGIONAL_QUERY_PROTOTYPE_ATTENTION_V1"
CONTROL_MODE = "CONTROL_QUERY_PROTOTYPE_DIAGNOSTIC"
SELECTIVE_MODE = "SELECTIVE_QUERY_PROTOTYPE"
SPATIAL_STRIDE = (2, 2)
TEMPORAL_STRIDE = 1
REFERENCE_SAMPLER_SECONDS = 488.847320
COMPARABILITY_RELATIVE_LIMIT = 0.05
COMBINED_CALLBACK_P95_NS_MAX = 3_000_000
MIN_PLANNED_QUERY_REDUCTION = 0.05
MIN_AFFECTED_NON_ANCHOR_STEPS = 3
MIN_ADMITTED_BLOCKS = 3
MAX_ADMITTED_BLOCKS = 20
MIN_STABLE_PLAN_EVENTS = 3
BLOCK_REGION_OBSERVATIONS_MIN = 3
MEAN_COSINE_MIN = 0.980
P05_COSINE_MIN = 0.950
MEAN_NORMALIZED_L2_MAX = 0.120
P95_NORMALIZED_L2_MAX = 0.250
MEAN_ENERGY_RATIO_MIN = 0.85
MEAN_ENERGY_RATIO_MAX = 1.15


def _percentile(values: Sequence[float | int], fraction: float) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def fixed_contract() -> dict[str, Any]:
    return {
        "mechanism": MECHANISM_ID,
        "rust_abi": "A1_ATTENTION_REGION_PLAN_ABI_V1",
        "prototype_source": "EXACT_ORIGINAL_Q_AFTER_NORM_AND_ROPE",
        "spatial_stride": list(SPATIAL_STRIDE),
        "temporal_stride": TEMPORAL_STRIDE,
        "reconstruction": "BILINEAR_SAME_TIME_SAME_STABLE_REGION",
        "reconstruction_stage": "ATTENTION_CORE_OUTPUT_BEFORE_FULL_OUTPUT_PROJECTION",
        "all_kv": "GLOBAL_FULL",
        "qkv_projection": "GLOBAL_FULL",
        "output_projection": "GLOBAL_FULL",
        "non_video_queries": "FULL_QUERY",
        "active_queries": "FULL_QUERY",
        "uncertain_queries": "FULL_QUERY",
        "halo_queries": "FULL_QUERY",
        "anchors": list(ANCHOR_STEPS),
        "halo_patches": HALO_PATCHES,
        "consecutive_region_prototype": False,
        "refresh_after_prototype": True,
        "tensor_bytes_to_rust": 0,
        "rust_calls_per_block": 0,
        "rust_calls_per_token": 0,
        "full_compute_fallback": True,
    }


def prototype_settings_digest(*, mode: str, admitted_blocks: Sequence[int] = ()) -> str:
    if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
        raise ValueError("unsupported A2 mode")
    payload = {
        "contract": fixed_contract(),
        "mode": mode,
        "admitted_blocks": list(admitted_blocks),
        "model_source_sha256": MODEL_SOURCE_SHA256,
        "reference_sampler_seconds": REFERENCE_SAMPLER_SECONDS,
        "comparability_relative_limit": COMPARABILITY_RELATIVE_LIMIT,
        "block_gate": {
            "minimum_observations": BLOCK_REGION_OBSERVATIONS_MIN,
            "mean_cosine_min": MEAN_COSINE_MIN,
            "p05_cosine_min": P05_COSINE_MIN,
            "mean_normalized_l2_max": MEAN_NORMALIZED_L2_MAX,
            "p95_normalized_l2_max": P95_NORMALIZED_L2_MAX,
            "mean_energy_ratio": [MEAN_ENERGY_RATIO_MIN, MEAN_ENERGY_RATIO_MAX],
            "nonfinite_count": 0,
            "maximum_blocks": MAX_ADMITTED_BLOCKS,
        },
        "opportunity_gate": {
            "query_reduction_min": MIN_PLANNED_QUERY_REDUCTION,
            "affected_non_anchor_steps_min": MIN_AFFECTED_NON_ANCHOR_STEPS,
            "admitted_blocks_min": MIN_ADMITTED_BLOCKS,
            "stable_plan_events_min": MIN_STABLE_PLAN_EVENTS,
        },
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _region_axes(region: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if region not in range(REGION_COUNT):
        raise ValueError("region must be in [0, 3]")
    top = region < 2
    left = region % 2 == 0
    h_split = (VIDEO_PATCH_HEIGHT + 1) // 2
    w_split = (VIDEO_PATCH_WIDTH + 1) // 2
    h_values = tuple(range(0, h_split - HALO_PATCHES)) if top else tuple(range(h_split + HALO_PATCHES, VIDEO_PATCH_HEIGHT))
    w_values = tuple(range(0, w_split - HALO_PATCHES)) if left else tuple(range(w_split + HALO_PATCHES, VIDEO_PATCH_WIDTH))
    return h_values, w_values


def _representative_axis(values: Sequence[int]) -> tuple[int, ...]:
    selected = list(values[::2])
    if values and selected[-1] != values[-1]:
        selected.append(values[-1])
    return tuple(selected)


def _bracket(value: int, representatives: Sequence[int]) -> tuple[int, int, float]:
    if value <= representatives[0]:
        return representatives[0], representatives[0], 0.0
    if value >= representatives[-1]:
        return representatives[-1], representatives[-1], 0.0
    for lower, upper in zip(representatives, representatives[1:]):
        if lower <= value <= upper:
            fraction = (value - lower) / (upper - lower) if upper != lower else 0.0
            return lower, upper, fraction
    raise ValueError("representative bracket unavailable")


@dataclass(frozen=True)
class CPUPrototypePlan:
    stable_region_mask: int
    kernel_local_rows: tuple[int, ...]
    representative_local_rows: tuple[int, ...]
    omitted_local_rows: tuple[int, ...]
    neighbor_local_rows: tuple[tuple[int, int, int, int], ...]
    neighbor_weights: tuple[tuple[float, float, float, float], ...]
    region_rows: Mapping[int, Mapping[str, tuple[Any, ...]]]


@dataclass(frozen=True)
class GPUPrototypePlan:
    stable_region_mask: int
    kernel_indices: Any
    representative_indices: Any
    omitted_indices: Any
    neighbor_indices: Any
    neighbor_weights: Any
    region_rows: Mapping[int, Mapping[str, Any]]
    persistent_bytes: int


def build_cpu_prototype_plan(stable_region_mask: int) -> CPUPrototypePlan:
    if stable_region_mask & ~REGION_MASK:
        raise ValueError("stable region mask is out of range")
    representatives: set[int] = set()
    omitted: list[int] = []
    neighbors: list[tuple[int, int, int, int]] = []
    weights: list[tuple[float, float, float, float]] = []
    region_rows: dict[int, dict[str, tuple[Any, ...]]] = {}
    frame_stride = VIDEO_PATCH_HEIGHT * VIDEO_PATCH_WIDTH
    for region in range(REGION_COUNT):
        if not stable_region_mask & (1 << region):
            continue
        h_values, w_values = _region_axes(region)
        rep_h, rep_w = _representative_axis(h_values), _representative_axis(w_values)
        region_reps: list[int] = []
        region_omitted: list[int] = []
        region_neighbors: list[tuple[int, int, int, int]] = []
        region_weights: list[tuple[float, float, float, float]] = []
        for time_index in range(VIDEO_LATENT_TIME):
            base = time_index * frame_stride
            for height in h_values:
                for width in w_values:
                    row = base + height * VIDEO_PATCH_WIDTH + width
                    if height in rep_h and width in rep_w:
                        representatives.add(row)
                        region_reps.append(row)
                        continue
                    h0, h1, fy = _bracket(height, rep_h)
                    w0, w1, fx = _bracket(width, rep_w)
                    source = (
                        base + h0 * VIDEO_PATCH_WIDTH + w0,
                        base + h0 * VIDEO_PATCH_WIDTH + w1,
                        base + h1 * VIDEO_PATCH_WIDTH + w0,
                        base + h1 * VIDEO_PATCH_WIDTH + w1,
                    )
                    coefficient = (
                        (1.0 - fy) * (1.0 - fx),
                        (1.0 - fy) * fx,
                        fy * (1.0 - fx),
                        fy * fx,
                    )
                    omitted.append(row)
                    neighbors.append(source)
                    weights.append(coefficient)
                    region_omitted.append(row)
                    region_neighbors.append(source)
                    region_weights.append(coefficient)
        region_rows[region] = {
            "representative": tuple(region_reps),
            "omitted": tuple(region_omitted),
            "neighbors": tuple(region_neighbors),
            "weights": tuple(region_weights),
        }
    omitted_set = set(omitted)
    kernel = tuple(row for row in range(VIDEO_TOKEN_COUNT) if row not in omitted_set)
    return CPUPrototypePlan(
        stable_region_mask=stable_region_mask,
        kernel_local_rows=kernel,
        representative_local_rows=tuple(sorted(representatives)),
        omitted_local_rows=tuple(omitted),
        neighbor_local_rows=tuple(neighbors),
        neighbor_weights=tuple(weights),
        region_rows=region_rows,
    )


CPU_PROTOTYPE_PLANS = tuple(build_cpu_prototype_plan(mask) for mask in range(REGION_MASK + 1))


def prototype_mapping_contract() -> dict[str, Any]:
    per_region = []
    for region in range(REGION_COUNT):
        plan = CPU_PROTOTYPE_PLANS[1 << region]
        region_plan = plan.region_rows[region]
        rep = set(region_plan["representative"])
        omitted = set(region_plan["omitted"])
        local = set(REGION_LOCAL_ROWS[region])
        neighbor_same_region = all(set(group).issubset(rep) for group in region_plan["neighbors"])
        per_region.append(
            {
                "region": region,
                "interior_rows": len(local),
                "representative_rows": len(rep),
                "omitted_rows": len(omitted),
                "exact_partition": rep | omitted == local and not rep & omitted,
                "neighbor_rows_same_region": neighbor_same_region,
            }
        )
    all_in_range = all(
        0 <= row < VIDEO_TOKEN_COUNT
        for plan in CPU_PROTOTYPE_PLANS
        for row in (*plan.kernel_local_rows, *plan.representative_local_rows, *plan.omitted_local_rows)
    )
    return {
        "grid": [VIDEO_LATENT_TIME, VIDEO_PATCH_HEIGHT, VIDEO_PATCH_WIDTH],
        "spatial_stride": list(SPATIAL_STRIDE),
        "temporal_stride": TEMPORAL_STRIDE,
        "semantic_mask_count": len(CPU_PROTOTYPE_PLANS),
        "all_rows_in_range": all_in_range,
        "regions": per_region,
    }


class GPUPrototypePlanCache:
    """Materialize all fixed semantic masks once per packed layout/device."""

    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module
        self._key: tuple[str, int, int, int] | None = None
        self._plans: dict[int, GPUPrototypePlan] = {}
        self.materialization_count = 0
        self.persistent_gpu_bytes = 0
        self.hot_path_materialization_count = 0

    @staticmethod
    def _tensor_bytes(tensor: Any) -> int:
        return int(tensor.numel()) * int(tensor.element_size())

    def materialize_all(self, *, sequence_length: int, video_start: int, video_stop: int, device: Any) -> None:
        if video_stop - video_start != VIDEO_TOKEN_COUNT or video_start < 0 or video_stop > sequence_length:
            raise ValueError("fixed H3 video token layout changed")
        key = (str(device), sequence_length, video_start, video_stop)
        if self._key == key and len(self._plans) == REGION_MASK + 1:
            return
        if self._key is not None:
            raise ValueError("A2 packed layout or device changed during one sampler run")
        plans: dict[int, GPUPrototypePlan] = {}
        total_bytes = 0
        for cpu in CPU_PROTOTYPE_PLANS:
            omitted_local = set(cpu.omitted_local_rows)
            kernel_global = [row for row in range(sequence_length) if not (video_start <= row < video_stop and row - video_start in omitted_local)]
            representative = [video_start + row for row in cpu.representative_local_rows]
            omitted = [video_start + row for row in cpu.omitted_local_rows]
            neighbor = [[video_start + value for value in group] for group in cpu.neighbor_local_rows]
            kernel_tensor = self.torch.tensor(kernel_global, dtype=self.torch.long, device=device)
            representative_tensor = self.torch.tensor(representative, dtype=self.torch.long, device=device)
            omitted_tensor = self.torch.tensor(omitted, dtype=self.torch.long, device=device)
            neighbor_tensor = self.torch.tensor(neighbor, dtype=self.torch.long, device=device).reshape(-1, 4)
            weight_tensor = self.torch.tensor(cpu.neighbor_weights, dtype=self.torch.float32, device=device).reshape(-1, 4)
            region_gpu: dict[int, dict[str, Any]] = {}
            tensors = [kernel_tensor, representative_tensor, omitted_tensor, neighbor_tensor, weight_tensor]
            for region, rows in cpu.region_rows.items():
                rep_tensor = self.torch.tensor([video_start + value for value in rows["representative"]], dtype=self.torch.long, device=device)
                omit_tensor = self.torch.tensor([video_start + value for value in rows["omitted"]], dtype=self.torch.long, device=device)
                neighbor_region = self.torch.tensor(
                    [[video_start + value for value in group] for group in rows["neighbors"]],
                    dtype=self.torch.long,
                    device=device,
                ).reshape(-1, 4)
                weight_region = self.torch.tensor(rows["weights"], dtype=self.torch.float32, device=device).reshape(-1, 4)
                region_gpu[region] = {
                    "representative_indices": rep_tensor,
                    "omitted_indices": omit_tensor,
                    "neighbor_indices": neighbor_region,
                    "neighbor_weights": weight_region,
                }
                tensors.extend([rep_tensor, omit_tensor, neighbor_region, weight_region])
            persistent = sum(self._tensor_bytes(tensor) for tensor in tensors)
            total_bytes += persistent
            plans[cpu.stable_region_mask] = GPUPrototypePlan(
                stable_region_mask=cpu.stable_region_mask,
                kernel_indices=kernel_tensor,
                representative_indices=representative_tensor,
                omitted_indices=omitted_tensor,
                neighbor_indices=neighbor_tensor,
                neighbor_weights=weight_tensor,
                region_rows=region_gpu,
                persistent_bytes=persistent,
            )
        self._key = key
        self._plans = plans
        self.materialization_count = len(plans)
        self.persistent_gpu_bytes = total_bytes

    def get(self, stable_region_mask: int) -> GPUPrototypePlan:
        if stable_region_mask not in self._plans:
            raise ValueError("A2 GPU plan cache is unavailable")
        return self._plans[stable_region_mask]


def _project_qkv(
    attention: Any,
    x: Any,
    rope_freqs: Any,
    *,
    cast_to: Any,
    in_training: bool,
    rms_rope: Any,
    rms_rope_in_place: Any,
) -> tuple[Any, Any, Any]:
    sequence = int(x.shape[0])
    q, k, v = attention.qkv_proj(x).split(attention.heads * attention.head_dim, dim=-1)
    v = v.view(sequence, attention.heads, attention.head_dim)
    if rope_freqs is not None:
        q = q.view(1, sequence, attention.heads, attention.head_dim)
        k = k.view(1, sequence, attention.heads, attention.head_dim)
        qw = cast_to(attention.q_norm.weight, device=x.device)
        kw = cast_to(attention.k_norm.weight, device=x.device)
        rot = rope_freqs.shape[-3] * 2
        if in_training:
            q, k = rms_rope(q, k, rope_freqs, qw, kw, epsilon=attention.q_norm.eps, rot_dim=rot)
        else:
            rms_rope_in_place(q, k, rope_freqs, qw, kw, epsilon=attention.q_norm.eps, rot_dim=rot)
        q, k = q[0], k[0]
    else:
        q = attention.q_norm(q.view(sequence, attention.heads, attention.head_dim))
        k = attention.k_norm(k.view(sequence, attention.heads, attention.head_dim))
    return q, k, v


def attention_core(
    *,
    q: Any,
    k: Any,
    v: Any,
    q_indices: Any | None,
    attention: Any,
    optimized_attention: Any,
    transformer_options: Mapping[str, Any],
) -> Any:
    selected_q = q if q_indices is None else q.index_select(0, q_indices)
    selected_q = selected_q.transpose(0, 1).unsqueeze(0)
    full_k = k.transpose(0, 1).unsqueeze(0)
    full_v = v.transpose(0, 1).unsqueeze(0)
    return optimized_attention(
        selected_q,
        full_k,
        full_v,
        attention.heads,
        mask=None,
        skip_reshape=True,
        transformer_options=transformer_options,
    ).squeeze(0)


def _predicted_omitted(full_core: Any, neighbor_indices: Any, weights: Any) -> Any:
    if int(neighbor_indices.numel()) == 0:
        return full_core.new_empty((0, int(full_core.shape[-1])))
    sources = full_core.index_select(0, neighbor_indices.flatten()).reshape(neighbor_indices.shape[0], 4, full_core.shape[-1])
    return (sources * weights.to(dtype=full_core.dtype).unsqueeze(-1)).sum(dim=1)


def reconstruct_full_core(selected_core: Any, plan: GPUPrototypePlan, sequence_length: int) -> Any:
    full = selected_core.new_empty((sequence_length, int(selected_core.shape[-1])))
    full.index_copy_(0, plan.kernel_indices, selected_core)
    if int(plan.omitted_indices.numel()):
        predicted = _predicted_omitted(full, plan.neighbor_indices, plan.neighbor_weights)
        full.index_copy_(0, plan.omitted_indices, predicted)
    return full


def _metric_tensors(actual: Any, predicted: Any, torch_module: Any) -> dict[str, Any]:
    actual32, predicted32 = actual.float(), predicted.float()
    flat_actual, flat_predicted = actual32.flatten(), predicted32.flatten()
    denominator = torch_module.linalg.vector_norm(flat_actual).clamp_min(1e-12)
    predicted_norm = torch_module.linalg.vector_norm(flat_predicted)
    cosine = torch_module.dot(flat_actual, flat_predicted) / (denominator * predicted_norm.clamp_min(1e-12))
    normalized_l2 = torch_module.linalg.vector_norm(flat_actual - flat_predicted) / denominator
    normalized_mae = (flat_actual - flat_predicted).abs().mean() / flat_actual.abs().mean().clamp_min(1e-12)
    energy_ratio = predicted_norm / denominator
    finite = torch_module.isfinite(torch_module.stack((cosine, normalized_l2, normalized_mae, energy_ratio))).all()
    return {
        "cosine": cosine.detach(),
        "normalized_l2": normalized_l2.detach(),
        "normalized_mae": normalized_mae.detach(),
        "energy_ratio": energy_ratio.detach(),
        "finite": finite.detach(),
    }


class H3RegionalQueryPrototypeController:
    """Installed H3 block wrapper with exact Full Compute fail-open semantics."""

    def __init__(
        self,
        *,
        mode: str,
        plan_bridge: AttentionRegionPlanBridge,
        h3_model: Any,
        torch_module: Any,
        admitted_blocks: Sequence[int] = (),
    ) -> None:
        if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
            raise ValueError("unsupported A2 mode")
        if any(index < 0 or index >= BLOCK_COUNT for index in admitted_blocks):
            raise ValueError("admitted block outside fixed H3 range")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.h3 = h3_model
        self.torch = torch_module
        self.admitted_blocks = tuple(sorted(set(int(index) for index in admitted_blocks)))
        self.plan_cache = GPUPrototypePlanCache(torch_module)
        self._original_forward: Any | None = None
        self._dit_class: Any | None = None
        self.block_call_count = 0
        self.model_forward_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.fail_open_count = 0
        self.full_attention_call_count = 0
        self.prototype_attention_call_count = 0
        self.full_q_row_count = 0
        self.actual_kernel_q_row_count = 0
        self.representative_q_row_count = 0
        self.omitted_q_row_count = 0
        self.full_kv_row_count = 0
        self.actual_kv_row_count = 0
        self.qkv_projection_full_row_count = 0
        self.output_projection_full_row_count = 0
        self.non_video_omission_count = 0
        self.halo_omission_count = 0
        self.explicit_cuda_synchronization_count = 0
        self.hot_path_host_tensor_transfer_count = 0
        self.per_block_rust_call_count = 0
        self.per_token_rust_call_count = 0
        self.counterfactual_observation_count = 0
        self.block_region_metrics: dict[int, list[dict[str, Any]]] = {index: [] for index in range(BLOCK_COUNT)}
        self.per_step: dict[int, dict[str, Any]] = {}

    @property
    def is_selective(self) -> bool:
        return self.mode == SELECTIVE_MODE

    @staticmethod
    def _video_segment(x: Any, mod_segments: Sequence[Sequence[int]]) -> tuple[int, int, int]:
        if not mod_segments or len(mod_segments[-1]) != 3:
            raise ValueError("H3 video segment unavailable")
        start, stop, row = map(int, mod_segments[-1])
        if stop - start != VIDEO_TOKEN_COUNT or start < 0 or stop > int(x.shape[0]):
            raise ValueError("H3 packed video layout changed")
        return start, stop, row

    def _step_record(self, step: int) -> dict[str, Any]:
        return self.per_step.setdefault(
            step,
            {
                "execution_step": step,
                "decision": "FULL_COMPUTE",
                "stable_region_mask": 0,
                "full_attention_calls": 0,
                "prototype_attention_calls": 0,
                "full_q_rows": 0,
                "actual_kernel_q_rows": 0,
                "representative_q_rows": 0,
                "omitted_q_rows": 0,
            },
        )

    def _attention_kwargs(self) -> dict[str, Any]:
        return {
            "cast_to": self.h3.comfy.model_management.cast_to,
            "in_training": bool(self.h3.comfy.model_management.in_training),
            "rms_rope": self.h3.comfy.quant_ops.ck.rms_rope_split_half,
            "rms_rope_in_place": self.h3.comfy.quant_ops.ck.rms_rope_split_half_,
        }

    def _counterfactual_metrics(self, *, block_index: int, stable_mask: int, full_core: Any, plan: GPUPrototypePlan) -> None:
        for region in range(REGION_COUNT):
            if not stable_mask & (1 << region):
                continue
            rows = plan.region_rows[region]
            omitted = rows["omitted_indices"]
            if int(omitted.numel()) == 0:
                continue
            actual = full_core.index_select(0, omitted)
            predicted = _predicted_omitted(full_core, rows["neighbor_indices"], rows["neighbor_weights"])
            metrics = _metric_tensors(actual, predicted, self.torch)
            metrics.update(
                {
                    "region": region,
                    "representative_count": int(rows["representative_indices"].numel()),
                    "omitted_count": int(omitted.numel()),
                }
            )
            self.block_region_metrics[block_index].append(metrics)
            self.counterfactual_observation_count += 1

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
        step_index, block_index = divmod(call_index, BLOCK_COUNT)
        if block_index == 0:
            self.model_forward_count += 1
        if step_index >= TOTAL_STEPS:
            self.mapping_error_count += 1
        options = {} if transformer_options is None else transformer_options
        record = self._step_record(step_index)
        plan_directive = self.plan_bridge.plans.get(step_index)
        if plan_directive is not None:
            record["decision"] = plan_directive["decision"]
            record["stable_region_mask"] = int(plan_directive["stable_region_mask"])
        state_mutated = False
        try:
            video_start, video_stop, _video_row = self._video_segment(x, mod_segments)
            sequence = int(x.shape[0])
            self.plan_cache.materialize_all(
                sequence_length=sequence,
                video_start=video_start,
                video_stop=video_stop,
                device=x.device,
            )
        except (IndexError, RuntimeError, TypeError, ValueError):
            self.mapping_error_count += 1
            self.fail_open_count += 1
            self.block_call_count += 1
            if self._original_forward is None:
                raise RuntimeError("A2 Full Compute fallback is unavailable")
            return self._original_forward(block, x, t_emb, mod_segments, rope_freqs, options)
        try:
            stable_mask = (
                int(plan_directive["stable_region_mask"])
                if plan_directive is not None and int(plan_directive["decision_code"]) == REGIONAL_ACTIVE_QUERY
                else 0
            )
            regional = self.is_selective and block_index in self.admitted_blocks and stable_mask != 0
            prototype_plan = self.plan_cache.get(stable_mask)
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = block.adaln_proj(t_emb)
            attention_h = self.h3._mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments)
            q, k, v = _project_qkv(block.attn, attention_h, rope_freqs, **self._attention_kwargs())
            if regional:
                selected_core = attention_core(
                    q=q,
                    k=k,
                    v=v,
                    q_indices=prototype_plan.kernel_indices,
                    attention=block.attn,
                    optimized_attention=self.h3.optimized_attention,
                    transformer_options=options,
                )
                full_core = reconstruct_full_core(selected_core, prototype_plan, sequence)
                attention_output = block.attn.out_proj(full_core)
                actual_q = int(prototype_plan.kernel_indices.numel())
                representatives = int(prototype_plan.representative_indices.numel())
                omitted = int(prototype_plan.omitted_indices.numel())
                self.prototype_attention_call_count += 1
                self.representative_q_row_count += representatives
                self.omitted_q_row_count += omitted
                record["prototype_attention_calls"] += 1
                record["representative_q_rows"] += representatives
                record["omitted_q_rows"] += omitted
            else:
                full_core = attention_core(
                    q=q,
                    k=k,
                    v=v,
                    q_indices=None,
                    attention=block.attn,
                    optimized_attention=self.h3.optimized_attention,
                    transformer_options=options,
                )
                attention_output = block.attn.out_proj(full_core)
                actual_q = sequence
                self.full_attention_call_count += 1
                record["full_attention_calls"] += 1
                if self.mode == CONTROL_MODE and stable_mask:
                    self._counterfactual_metrics(
                        block_index=block_index,
                        stable_mask=stable_mask,
                        full_core=full_core,
                        plan=prototype_plan,
                    )
            x = self.h3._mod_gate(x, gate_msa, attention_output, mod_segments)
            state_mutated = True
            self.full_q_row_count += sequence
            self.actual_kernel_q_row_count += actual_q
            self.full_kv_row_count += sequence * 2
            self.actual_kv_row_count += sequence * 2
            self.qkv_projection_full_row_count += sequence
            self.output_projection_full_row_count += sequence
            record["full_q_rows"] += sequence
            record["actual_kernel_q_rows"] += actual_q
            h = self.h3._mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
            return self.h3._mod_gate(x, gate_mlp, block.mlp(h), mod_segments)
        except (IndexError, RuntimeError, TypeError, ValueError):
            if state_mutated:
                self.wrapper_failure_count += 1
                raise
            self.fail_open_count += 1
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
            raise RuntimeError("A2 H3 wrapper already installed")
        self._dit_class = dit_class
        self._original_forward = dit_class.forward
        controller = self

        def wrapped(block: Any, x: Any, t_emb: Any, mod_segments: Any, rope_freqs: Any, transformer_options: Any = None) -> Any:
            return controller.instrumented_forward(block, x, t_emb, mod_segments, rope_freqs, transformer_options)

        dit_class.forward = wrapped

    def restore(self) -> None:
        if self._original_forward is not None and self._dit_class is not None:
            self._dit_class.forward = self._original_forward
        self._original_forward = None
        self._dit_class = None

    def _block_calibration(self) -> tuple[list[dict[str, Any]], tuple[int, ...]]:
        rows: list[dict[str, Any]] = []
        admitted: list[tuple[float, float, float, int]] = []
        for block_index in range(BLOCK_COUNT):
            observations = self.block_region_metrics[block_index]
            values: list[dict[str, float | bool]] = []
            for observation in observations:
                scalars = self.torch.stack(
                    (
                        observation["cosine"],
                        observation["normalized_l2"],
                        observation["normalized_mae"],
                        observation["energy_ratio"],
                        observation["finite"].to(dtype=self.torch.float32),
                    )
                ).float().cpu().tolist()
                values.append(
                    {
                        "cosine": float(scalars[0]),
                        "normalized_l2": float(scalars[1]),
                        "normalized_mae": float(scalars[2]),
                        "energy_ratio": float(scalars[3]),
                        "finite": bool(scalars[4]),
                    }
                )
            finite = [value for value in values if value["finite"] and all(math.isfinite(float(value[name])) for name in ("cosine", "normalized_l2", "normalized_mae", "energy_ratio"))]
            cosine = [float(value["cosine"]) for value in finite]
            l2 = [float(value["normalized_l2"]) for value in finite]
            mae = [float(value["normalized_mae"]) for value in finite]
            energy = [float(value["energy_ratio"]) for value in finite]
            mean_cosine = sum(cosine) / len(cosine) if cosine else None
            p05_cosine = _percentile(cosine, 0.05)
            mean_l2 = sum(l2) / len(l2) if l2 else None
            p95_l2 = _percentile(l2, 0.95)
            mean_mae = sum(mae) / len(mae) if mae else None
            mean_energy = sum(energy) / len(energy) if energy else None
            passed = (
                len(values) >= BLOCK_REGION_OBSERVATIONS_MIN
                and len(finite) == len(values)
                and mean_cosine is not None and mean_cosine >= MEAN_COSINE_MIN
                and p05_cosine is not None and p05_cosine >= P05_COSINE_MIN
                and mean_l2 is not None and mean_l2 <= MEAN_NORMALIZED_L2_MAX
                and p95_l2 is not None and p95_l2 <= P95_NORMALIZED_L2_MAX
                and mean_energy is not None and MEAN_ENERGY_RATIO_MIN <= mean_energy <= MEAN_ENERGY_RATIO_MAX
            )
            row = {
                "block_index": block_index,
                "regional_observation_count": len(values),
                "finite_count": len(finite),
                "nonfinite_count": len(values) - len(finite),
                "mean_cosine": mean_cosine,
                "p05_cosine": p05_cosine,
                "mean_normalized_l2": mean_l2,
                "p95_normalized_l2": p95_l2,
                "mean_normalized_mae": mean_mae,
                "mean_energy_ratio": mean_energy,
                "passed": passed,
            }
            rows.append(row)
            if passed:
                admitted.append((float(mean_l2), -float(mean_cosine), float(p95_l2), block_index))
        selected = tuple(item[3] for item in sorted(admitted)[:MAX_ADMITTED_BLOCKS])
        return rows, selected

    def finalize(self) -> dict[str, Any]:
        calibration, selected = self._block_calibration()
        stable_plans = [
            plan for plan in self.plan_bridge.events
            if int(plan["decision_code"]) == REGIONAL_ACTIVE_QUERY and int(plan["stable_region_mask"]) != 0
        ]
        planned_omitted = sum(
            len(CPU_PROTOTYPE_PLANS[int(plan["stable_region_mask"])].omitted_local_rows) * len(selected)
            for plan in stable_plans
        )
        full_rows = max(1, self.full_q_row_count)
        affected_steps = sorted({int(plan["target_step"]) for plan in stable_plans if int(plan["target_step"]) not in ANCHOR_STEPS})
        return {
            "schema_version": "a2.h3.query-prototype-execution.1",
            "mode": self.mode,
            "mechanism": MECHANISM_ID,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "fail_open_count": self.fail_open_count,
            "full_attention_call_count": self.full_attention_call_count,
            "prototype_attention_call_count": self.prototype_attention_call_count,
            "counterfactual_observation_count": self.counterfactual_observation_count,
            "full_q_row_count": self.full_q_row_count,
            "actual_kernel_q_row_count": self.actual_kernel_q_row_count,
            "representative_q_row_count": self.representative_q_row_count,
            "omitted_q_row_count": self.omitted_q_row_count,
            "full_kv_row_count": self.full_kv_row_count,
            "actual_kv_row_count": self.actual_kv_row_count,
            "global_kv_preserved": self.actual_kv_row_count == self.full_kv_row_count,
            "qkv_projection_full_row_count": self.qkv_projection_full_row_count,
            "qkv_projection_reduction_claimed": False,
            "output_projection_full_row_count": self.output_projection_full_row_count,
            "output_projection_reduction_claimed": False,
            "non_video_omission_count": self.non_video_omission_count,
            "halo_omission_count": self.halo_omission_count,
            "explicit_cuda_synchronization_count": self.explicit_cuda_synchronization_count,
            "hot_path_host_tensor_transfer_count": self.hot_path_host_tensor_transfer_count,
            "per_block_rust_call_count": self.per_block_rust_call_count,
            "per_token_rust_call_count": self.per_token_rust_call_count,
            "tensor_bytes_to_rust": 0,
            "gpu_plan_materialization_count": self.plan_cache.materialization_count,
            "dynamic_per_block_gpu_plan_allocation_count": self.plan_cache.hot_path_materialization_count,
            "persistent_gpu_plan_bytes": self.plan_cache.persistent_gpu_bytes,
            "feed_forward_execution": "FULL_COMPUTE",
            "mapping": prototype_mapping_contract(),
            "block_calibration": calibration,
            "admitted_blocks": list(selected),
            "admitted_block_count": len(selected),
            "stable_region_plan_event_count": len(stable_plans),
            "affected_non_anchor_steps": affected_steps,
            "planned_query_reduction": planned_omitted / full_rows,
            "actual_query_reduction": 1.0 - (self.actual_kernel_q_row_count / self.full_q_row_count) if self.full_q_row_count else 0.0,
            "per_step": [self.per_step[index] for index in sorted(self.per_step)],
        }


def control_admission(
    *,
    execution: Mapping[str, Any],
    region_plan: Mapping[str, Any],
    c2_shadow: Mapping[str, Any],
    sampler_seconds: float,
    output_integrity_passed: bool,
    source_admitted: bool,
) -> dict[str, Any]:
    callback_p95 = c2_shadow.get("total_shadow_callback", {}).get("p95_ns")
    rust_p95 = region_plan.get("boundary_roundtrip", {}).get("p95_ns")
    relative_delta = (sampler_seconds - REFERENCE_SAMPLER_SECONDS) / REFERENCE_SAMPLER_SECONDS
    checks = {
        "source_structural": source_admitted,
        "combined_compound_eye_plan_p95": isinstance(callback_p95, int) and callback_p95 <= COMBINED_CALLBACK_P95_NS_MAX,
        "explicit_cuda_sync_zero": execution.get("explicit_cuda_synchronization_count") == 0,
        "full_tensor_host_copy_zero": c2_shadow.get("full_tensor_host_copy_bytes") == 0,
        "tensor_to_rust_zero": region_plan.get("tensor_bytes_to_rust") == 0,
        "per_block_rust_zero": execution.get("per_block_rust_call_count") == 0,
        "per_token_rust_zero": execution.get("per_token_rust_call_count") == 0,
        "dynamic_per_block_plan_allocation_zero": execution.get("dynamic_per_block_gpu_plan_allocation_count") == 0,
        "output_integrity": output_integrity_passed,
        "sampler_comparable": relative_delta <= COMPARABILITY_RELATIVE_LIMIT,
        "admitted_blocks": int(execution.get("admitted_block_count", 0)) >= MIN_ADMITTED_BLOCKS,
        "planned_query_reduction": float(execution.get("planned_query_reduction", 0.0)) >= MIN_PLANNED_QUERY_REDUCTION,
        "affected_steps": len(execution.get("affected_non_anchor_steps", [])) >= MIN_AFFECTED_NON_ANCHOR_STEPS,
        "stable_plan_events": int(execution.get("stable_region_plan_event_count", 0)) >= MIN_STABLE_PLAN_EVENTS,
    }
    if not checks["source_structural"]:
        decision = "A2_QUERY_PROTOTYPE_STRUCTURALLY_NOT_ADMITTED"
        next_candidate = "FULL_COMPUTE_FALLBACK"
    elif not checks["sampler_comparable"]:
        decision = "A2_PROTOTYPE_CONTROL_OVERHEAD_TOO_HIGH"
        next_candidate = "REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1"
    elif not (
        checks["admitted_blocks"]
        and checks["planned_query_reduction"]
        and checks["affected_steps"]
        and checks["stable_plan_events"]
    ):
        decision = "A2_QUERY_PROTOTYPE_OPPORTUNITY_TOO_LOW"
        next_candidate = "REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1"
    elif all(checks.values()):
        decision = "A2_CONTROL_ADMITTED"
        next_candidate = "RUN_CONDITIONAL_SELECTIVE"
    else:
        decision = "A2_QUERY_PROTOTYPE_STRUCTURALLY_NOT_ADMITTED"
        next_candidate = "FULL_COMPUTE_FALLBACK"
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "decision": decision,
        "next_candidate": next_candidate,
        "sampler_reference_seconds": REFERENCE_SAMPLER_SECONDS,
        "sampler_relative_delta": relative_delta,
        "sampler_relative_limit": COMPARABILITY_RELATIVE_LIMIT,
        "combined_compound_eye_plan_p95_ns": callback_p95,
        "combined_measurement_method": "inclusive C2 callback CPU span; A1 Rust boundary is a child span and is not added twice",
        "a1_rust_boundary_p95_ns_record_only": rust_p95,
    }


def a1_mode_for(mode: str) -> str:
    if mode == CONTROL_MODE:
        return A1_CONTROL_MODE
    if mode == SELECTIVE_MODE:
        return A1_SELECTIVE_MODE
    raise ValueError("unsupported A2 mode")


__all__ = [
    "CONTROL_MODE",
    "SELECTIVE_MODE",
    "MECHANISM_ID",
    "MODEL_SOURCE_RELATIVE",
    "MODEL_SOURCE_SHA256",
    "AttentionRegionPlanBridge",
    "RegionPlanContext",
    "H3RegionalQueryPrototypeController",
    "GPUPrototypePlanCache",
    "CPU_PROTOTYPE_PLANS",
    "attention_core",
    "build_cpu_prototype_plan",
    "control_admission",
    "fixed_contract",
    "inspect_installed_attention_source",
    "prototype_mapping_contract",
    "prototype_settings_digest",
    "reconstruct_full_core",
]
