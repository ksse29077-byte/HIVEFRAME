"""Quality-first H3 positionwise feed-forward token selection.

The module is intentionally H3-adapter code.  It leaves global attention
untouched, keeps only scalar per-block/video-token history, and fails open to
the installed full-compute ``DiTBlock`` semantics whenever the packed layout
or selector contract is not exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
import ast
import math


MODEL_SOURCE_SHA256 = "882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024"
SELECTOR_ID = "FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1"
BLOCK_COUNT = 50
STEP_COUNT = 20
ANCHOR_STEPS = (0, 1, 18, 19)
EXPECTED_VIDEO_SHAPE = (1, 24, 37, 30, 54)
VIDEO_TOKEN_COUNT = 37 * 15 * 27
HIDDEN_WIDTH = 5376
MIN_BLOCK_VIDEO_SKIP_RATIO = 0.10
SCALAR_METADATA_BUDGET_BYTES = 64 * 1024 * 1024
HISTOGRAM_BINS = 4096
HISTOGRAM_MAX = 0.05


@dataclass(frozen=True)
class SelectorPolicy:
    policy_id: str
    prev_ff_delta_ratio_max: float
    h_norm_change_max: float
    gate_norm_change_max: float

    def public(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "prev_ff_delta_ratio_max": self.prev_ff_delta_ratio_max,
            "h_norm_change_max": self.h_norm_change_max,
            "gate_norm_change_max": self.gate_norm_change_max,
        }


POLICIES: tuple[SelectorPolicy, ...] = (
    SelectorPolicy("P0", 0.0025, 0.005, 0.005),
    SelectorPolicy("P1", 0.0050, 0.010, 0.010),
    SelectorPolicy("P2", 0.0100, 0.020, 0.020),
)
POLICY_BY_ID = {policy.policy_id: policy for policy in POLICIES}


def scalar_metadata_bytes(video_tokens: int = VIDEO_TOKEN_COUNT, blocks: int = BLOCK_COUNT) -> int:
    """Three fp32 scalars and one bool per block/video-token row."""

    return blocks * video_tokens * (3 * 4 + 1)


def fixed_contract() -> dict[str, Any]:
    return {
        "selector_id": SELECTOR_ID,
        "policies": [policy.public() for policy in POLICIES],
        "anchor_steps": list(ANCHOR_STEPS),
        "minimum_block_video_skip_ratio": MIN_BLOCK_VIDEO_SKIP_RATIO,
        "attention_execution": "ALWAYS_FULL_COMPUTE",
        "eligible_rows": "target_video_segment_only",
        "non_video_rows": "ALWAYS_FULL_COMPUTE",
        "history": {
            "values": ["prev_h_norm", "prev_ff_delta_ratio", "prev_gate_norm", "history_valid"],
            "source": "previous actual Full Compute evidence only",
            "skipped_row_history": "invalid_immediately",
            "consecutive_skip": "prohibited_without_intervening_actual_full_compute",
        },
        "persistent_scalar_metadata_bytes": scalar_metadata_bytes(),
        "persistent_scalar_metadata_budget_bytes": SCALAR_METADATA_BUDGET_BYTES,
        "full_tensor_cache": False,
        "tensor_bytes_to_rust": 0,
        "host_full_tensor_copy_bytes": 0,
        "rust_abi": "unchanged",
        "profiler_enabled": False,
    }


def inspect_installed_ff_source(source: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "admitted": False,
        "source_sha256": None,
        "reason": None,
        "video_segment": None,
        "token_order": None,
        "mlp_row_execution": None,
        "hidden_width": None,
    }
    if not source.is_file():
        result["reason"] = "installed H3 model source is missing"
        return result
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    result["source_sha256"] = digest
    if digest != MODEL_SOURCE_SHA256:
        result["reason"] = "installed H3 model source hash changed"
        return result
    text = raw.decode("utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        result["reason"] = "installed H3 model source does not parse"
        return result

    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    required = {"MLP", "DiTBlock", "PackedLayout", "MiniMaxH3Model"}
    if not required.issubset(classes):
        result["reason"] = "required H3 source classes are missing"
        return result
    source_checks = {
        "packed_order_declared": "[text | cond rows | audio | video]" in text,
        "video_appended_last": 'segments.append(("video", n_video))' in text,
        "video_rows_contiguous": "self.segments = seg_abs" in text,
        "patchify_order_nthw": 'torch.einsum("nctrhpwq->nthwcrpq", x)' in text,
        "mlp_is_positionwise": 'return comfy.ops.linear_input_act(self.fc2, self.fc1(x), "swiglu")' in text,
        "block_mlp_exactly_once": "return _mod_gate(x, gate_mlp, self.mlp(h), mod_segments)" in text,
        "target_segments_last": "target audio then target video, always the last two" in text,
        "video_segment_forward_lookup": 'if k == "video"' in text,
        "hidden_width_5376": "hidden_size=5376" in text,
    }
    if not all(source_checks.values()):
        result["reason"] = "installed H3 row/layout contract changed"
        result["source_checks"] = source_checks
        return result
    result.update(
        {
            "admitted": True,
            "source_checks": source_checks,
            "video_segment": {
                "kind": "video",
                "position": "final contiguous packed segment",
                "expected_video_shape": list(EXPECTED_VIDEO_SHAPE),
                "expected_token_count": VIDEO_TOKEN_COUNT,
            },
            "token_order": "batch-latent_time-patch_h-patch_w (nthw), stable for fixed layout signature",
            "mlp_row_execution": "independent Linear-SwiGLU-Linear over the leading row dimension",
            "hidden_width": HIDDEN_WIDTH,
        }
    )
    return result


def relative_change(current: Any, previous: Any, *, epsilon: float = 1e-6) -> Any:
    return (current - previous).abs() / previous.abs().clamp_min(epsilon)


def causal_candidate_mask(
    *,
    policy: SelectorPolicy,
    history_valid: Any,
    prev_h_norm: Any,
    prev_ff_delta_ratio: Any,
    prev_gate_norm: Any,
    current_h_norm: Any,
    current_gate_norm: Any,
) -> Any:
    """Return a causal candidate mask without current MLP output access."""

    finite = (
        prev_h_norm.isfinite()
        & prev_ff_delta_ratio.isfinite()
        & prev_gate_norm.isfinite()
        & current_h_norm.isfinite()
        & current_gate_norm.isfinite()
    )
    return (
        history_valid
        & finite
        & (prev_ff_delta_ratio <= policy.prev_ff_delta_ratio_max)
        & (relative_change(current_h_norm, prev_h_norm) <= policy.h_norm_change_max)
        & (relative_change(current_gate_norm, prev_gate_norm) <= policy.gate_norm_change_max)
    )


def execute_active_rows(
    *,
    x: Any,
    h: Any,
    mlp: Callable[[Any], Any],
    gate_mlp: Any,
    mod_segments: Sequence[Sequence[int]],
    active_indices: Any,
) -> tuple[Any, Any]:
    """Run one MLP call over active rows and scatter gated deltas in-place."""

    active_h = h.index_select(0, active_indices)
    active_output = mlp(active_h)
    for start, stop, row in mod_segments:
        positions = ((active_indices >= int(start)) & (active_indices < int(stop))).nonzero().flatten()
        if int(positions.numel()) == 0:
            continue
        original_rows = active_indices.index_select(0, positions)
        delta = active_output.index_select(0, positions) * gate_mlp[int(row)].to(active_output.dtype)
        x.index_add_(0, original_rows, delta)
    return x, active_output


@dataclass
class _History:
    prev_h_norm: Any
    prev_ff_delta_ratio: Any
    prev_gate_norm: Any
    valid_by_policy: dict[str, Any]


@dataclass
class _EventPair:
    start: Any
    end: Any


class _ImpactAccumulator:
    def __init__(self, torch_module: Any, device: Any) -> None:
        self.torch = torch_module
        self.histogram = torch_module.zeros(HISTOGRAM_BINS, dtype=torch_module.float64, device=device)
        self.count = torch_module.zeros((), dtype=torch_module.float64, device=device)
        self.total = torch_module.zeros((), dtype=torch_module.float64, device=device)
        self.maximum = torch_module.zeros((), dtype=torch_module.float32, device=device)
        self.over_point_zero_one = torch_module.zeros((), dtype=torch_module.float64, device=device)
        self.nonfinite = torch_module.zeros((), dtype=torch_module.int64, device=device)

    def add(self, values: Any) -> None:
        if int(values.numel()) == 0:
            return
        values = values.detach().float()
        finite_mask = values.isfinite()
        self.nonfinite.add_((~finite_mask).sum())
        finite_values = self.torch.where(finite_mask, values, self.torch.zeros_like(values))
        self.count.add_(finite_mask.sum())
        self.total.add_(finite_values.double().sum())
        self.maximum.copy_(self.torch.maximum(self.maximum, finite_values.max()))
        self.over_point_zero_one.add_((finite_mask & (values > 0.010)).sum())
        # Non-finite rows are placed at the conservative upper edge.  Their
        # separate count makes the policy fail regardless of quantiles, while
        # preserving a fixed-shape GPU path with no boolean-compaction sync.
        clipped = self.torch.where(
            finite_mask,
            values.clamp(min=0.0, max=HISTOGRAM_MAX),
            self.torch.full_like(values, HISTOGRAM_MAX),
        )
        self.histogram.add_(self.torch.histc(clipped, bins=HISTOGRAM_BINS, min=0.0, max=HISTOGRAM_MAX).double())

    def result(self) -> dict[str, Any]:
        count = int(self.count.item())
        if count == 0:
            return {"count": 0, "mean": None, "p50": None, "p95": None, "p99": None, "max": None, "over_0_010_rate": None, "nonfinite_count": int(self.nonfinite.item())}
        cumulative = self.histogram.cumsum(0)

        def percentile(q: float) -> float:
            target = max(1, math.ceil(count * q))
            index = int((cumulative >= target).nonzero()[0].item())
            return (index + 1) * HISTOGRAM_MAX / HISTOGRAM_BINS

        return {
            "count": count,
            "mean": float(self.total.item() / count),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": float(self.maximum.item()),
            "over_0_010_rate": float(self.over_point_zero_one.item() / count),
            "nonfinite_count": int(self.nonfinite.item()),
            "quantile_method": f"conservative upper edge of {HISTOGRAM_BINS}-bin [0,{HISTOGRAM_MAX}] GPU histogram",
        }


class H3FFTokenSelectiveController:
    """Temporarily replace H3 ``DiTBlock.forward`` with the fixed C4-S1 path."""

    def __init__(
        self,
        *,
        mode: str,
        selected_policy: str | None,
        event_factory: Callable[[], Any],
        synchronize: Callable[[], None],
        mod_scale_shift: Callable[..., Any],
        mod_gate: Callable[..., Any],
        torch_module: Any,
        events_supported: bool = True,
        unsupported_reason: str | None = None,
    ) -> None:
        if mode not in {"CONTROL_FF_TOKEN_SHADOW", "SELECTIVE_FF_TOKEN"}:
            raise ValueError("unsupported C4-S1 mode")
        if mode == "SELECTIVE_FF_TOKEN" and selected_policy not in POLICY_BY_ID:
            raise ValueError("SELECTIVE requires one frozen policy")
        self.mode = mode
        self.selected_policy = selected_policy
        self.event_factory = event_factory
        self.synchronize = synchronize
        self.mod_scale_shift = mod_scale_shift
        self.mod_gate = mod_gate
        self.torch = torch_module
        self.events_supported = events_supported
        self.unsupported_reason = unsupported_reason
        self.block_call_count = 0
        self.model_forward_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.fail_open_count = 0
        self.mlp_call_count = 0
        self.full_mlp_row_count = 0
        self.actual_mlp_row_count = 0
        self.omitted_video_row_count = 0
        self.attention_omission_count = 0
        self.non_video_omission_count = 0
        self.host_full_tensor_copy_bytes = 0
        self.tensor_bytes_to_rust = 0
        self.full_tensor_cache_count = 0
        self.history: dict[int, _History] = {}
        self.policy_counts = {
            policy.policy_id: {
                "predicted_skip_rows": None,
                "total_video_rows": 0,
                "step_flags": None,
                "block_flags": None,
            }
            for policy in POLICIES
        }
        self.impact: dict[str, _ImpactAccumulator] = {}
        self.events: dict[str, list[_EventPair]] = {name: [] for name in ("sampler", "full_ff_group", "actual_mlp", "gather_mask", "scatter_residual")}
        self.synchronization_count = 0
        self._original_forward: Callable[..., Any] | None = None
        self._dit_class: Any = None
        self._sampler_started = False
        self.observed_video_segment: tuple[int, int, int] | None = None
        self.observed_hidden_width: int | None = None
        self.mlp_input_rows_min: int | None = None
        self.mlp_input_rows_max: int | None = None
        self.global_invalidation_count = 0

    def _pair(self, group: str) -> _EventPair | None:
        if not self.events_supported:
            return None
        pair = _EventPair(self.event_factory(), self.event_factory())
        self.events[group].append(pair)
        pair.start.record()
        return pair

    @staticmethod
    def _end(pair: _EventPair | None) -> None:
        if pair is not None:
            pair.end.record()

    def start_sampler(self) -> None:
        pair = self._pair("sampler")
        self._sampler_started = pair is not None

    def end_sampler(self) -> None:
        if self.events_supported and (not self._sampler_started or not self.events["sampler"]):
            raise RuntimeError("sampler timing was not started")
        if self.events_supported:
            self.events["sampler"][-1].end.record()
        self._sampler_started = False

    @property
    def sampler_timing_active(self) -> bool:
        return self._sampler_started

    def _video_segment(self, x: Any, mod_segments: Sequence[Sequence[int]]) -> tuple[int, int, int]:
        if not mod_segments or len(mod_segments[-1]) != 3:
            raise ValueError("video segment missing")
        start, stop, row = map(int, mod_segments[-1])
        if start < 0 or stop != int(x.shape[0]) or stop <= start or row % 3 != 0:
            raise ValueError("target video is not the final admitted packed segment")
        segment = (start, stop, row)
        hidden = int(x.shape[-1])
        if self.observed_video_segment is None:
            self.observed_video_segment = segment
            self.observed_hidden_width = hidden
        elif self.observed_video_segment != segment or self.observed_hidden_width != hidden:
            raise ValueError("packed token identity changed during sampling")
        return segment

    def _new_history(self, current_h_norm: Any, current_gate_norm: Any) -> _History:
        zeros = self.torch.zeros_like(current_h_norm, dtype=self.torch.float32)
        gate = self.torch.zeros_like(current_h_norm, dtype=self.torch.float32)
        valid = {
            policy.policy_id: self.torch.zeros_like(current_h_norm, dtype=self.torch.bool)
            for policy in POLICIES
        }
        return _History(zeros.clone(), zeros.clone(), gate, valid)

    def _candidate_masks(
        self,
        *,
        block_index: int,
        step_index: int,
        current_h_norm: Any,
        current_gate_norm: Any,
    ) -> dict[str, Any]:
        history = self.history.get(block_index)
        if history is None:
            history = self._new_history(current_h_norm, current_gate_norm)
            self.history[block_index] = history
        if step_index in ANCHOR_STEPS:
            return {policy.policy_id: self.torch.zeros_like(current_h_norm, dtype=self.torch.bool) for policy in POLICIES}
        return {
            policy.policy_id: causal_candidate_mask(
                policy=policy,
                history_valid=history.valid_by_policy[policy.policy_id],
                prev_h_norm=history.prev_h_norm,
                prev_ff_delta_ratio=history.prev_ff_delta_ratio,
                prev_gate_norm=history.prev_gate_norm,
                current_h_norm=current_h_norm,
                current_gate_norm=current_gate_norm,
            )
            for policy in POLICIES
        }

    def _update_history(
        self,
        *,
        block_index: int,
        current_h_norm: Any,
        current_gate_norm: Any,
        actual_ratio: Any,
        computed_mask: Any,
        counterfactual_masks: Mapping[str, Any],
    ) -> None:
        history = self.history[block_index]
        history.prev_h_norm[computed_mask] = current_h_norm[computed_mask].detach().float()
        history.prev_ff_delta_ratio[computed_mask] = actual_ratio[computed_mask].detach().float()
        history.prev_gate_norm[computed_mask] = current_gate_norm[computed_mask].detach().float()
        if self.mode == "CONTROL_FF_TOKEN_SHADOW":
            for policy in POLICIES:
                history.valid_by_policy[policy.policy_id] = (~counterfactual_masks[policy.policy_id]).detach()
        else:
            policy_id = str(self.selected_policy)
            history.valid_by_policy[policy_id] = computed_mask.detach()

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
        if step_index >= STEP_COUNT:
            self.mapping_error_count += 1
        options = {} if transformer_options is None else transformer_options
        try:
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = block.adaln_proj(t_emb)
            attention_h = self.mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments)
            attention_output = block.attn(attention_h, rope_freqs=rope_freqs, transformer_options=options)
            x = self.mod_gate(x, gate_msa, attention_output, mod_segments)

            ff_pair = self._pair("full_ff_group")
            h = self.mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
            try:
                video_start, video_stop, video_row = self._video_segment(x, mod_segments)
                mask_pair = self._pair("gather_mask")
                video_h = h[video_start:video_stop]
                current_h_norm = self.torch.linalg.vector_norm(video_h.float(), dim=-1)
                gate_scalar = self.torch.linalg.vector_norm(gate_mlp[video_row].float())
                current_gate_norm = gate_scalar.expand_as(current_h_norm)
                masks = self._candidate_masks(
                    block_index=block_index,
                    step_index=step_index,
                    current_h_norm=current_h_norm,
                    current_gate_norm=current_gate_norm,
                )
                base_video_norm = self.torch.linalg.vector_norm(
                    x[video_start:video_stop].float(), dim=-1
                ).clamp_min(1e-6)
                self._end(mask_pair)
            except (IndexError, RuntimeError, TypeError, ValueError):
                self.fail_open_count += 1
                self.global_invalidation_count += 1
                video_start, video_stop, video_row = 0, 0, 0
                current_h_norm = current_gate_norm = None
                base_video_norm = None
                masks = {}

            total_rows = int(h.shape[0])
            actual_mask = None
            use_selective = False
            if current_h_norm is not None:
                for policy in POLICIES:
                    mask = masks[policy.policy_id]
                    if self.mode == "CONTROL_FF_TOKEN_SHADOW":
                        bucket = self.policy_counts[policy.policy_id]
                        if bucket["predicted_skip_rows"] is None:
                            bucket["predicted_skip_rows"] = self.torch.zeros((), dtype=self.torch.int64, device=mask.device)
                            bucket["step_flags"] = self.torch.zeros(STEP_COUNT, dtype=self.torch.bool, device=mask.device)
                            bucket["block_flags"] = self.torch.zeros(BLOCK_COUNT, dtype=self.torch.bool, device=mask.device)
                        bucket["predicted_skip_rows"].add_(mask.sum())
                        bucket["total_video_rows"] += int(mask.numel())
                        bucket["step_flags"][step_index] |= mask.any()
                        bucket["block_flags"][block_index] |= mask.any()
                if self.mode == "SELECTIVE_FF_TOKEN":
                    actual_mask = masks[str(self.selected_policy)]
                    block_ratio = float(actual_mask.float().mean().item())
                    use_selective = block_ratio >= MIN_BLOCK_VIDEO_SKIP_RATIO and int(actual_mask.sum().item()) > 0

            if use_selective and actual_mask is not None:
                mask_pair = self._pair("gather_mask")
                active_video = (~actual_mask).nonzero().flatten() + video_start
                non_video = self.torch.arange(video_start, device=h.device)
                active_indices = self.torch.cat((non_video, active_video))
                active_h = h.index_select(0, active_indices)
                self._end(mask_pair)
                mlp_pair = self._pair("actual_mlp")
                active_output = block.mlp(active_h)
                self._end(mlp_pair)
                scatter_pair = self._pair("scatter_residual")
                for start, stop, row in mod_segments:
                    positions = ((active_indices >= int(start)) & (active_indices < int(stop))).nonzero().flatten()
                    if int(positions.numel()) == 0:
                        continue
                    original_rows = active_indices.index_select(0, positions)
                    delta = active_output.index_select(0, positions) * gate_mlp[int(row)].to(active_output.dtype)
                    x.index_add_(0, original_rows, delta)
                self._end(scatter_pair)
                self.mlp_call_count += 1
                self.actual_mlp_row_count += int(active_indices.numel())
                self.full_mlp_row_count += total_rows
                omitted = int(actual_mask.sum().item())
                self.omitted_video_row_count += omitted
                rows = int(active_indices.numel())
                self.mlp_input_rows_min = rows if self.mlp_input_rows_min is None else min(self.mlp_input_rows_min, rows)
                self.mlp_input_rows_max = rows if self.mlp_input_rows_max is None else max(self.mlp_input_rows_max, rows)
                video_active_output = active_output[-int(active_video.numel()):] if int(active_video.numel()) else active_output[:0]
                active_delta = video_active_output * gate_mlp[video_row].to(active_output.dtype)
                actual_ratio = self.torch.zeros_like(current_h_norm, dtype=self.torch.float32)
                active_local = active_video - video_start
                actual_ratio[active_local] = self.torch.linalg.vector_norm(active_delta.float(), dim=-1) / base_video_norm[active_local]
                computed_mask = ~actual_mask
                self._update_history(
                    block_index=block_index,
                    current_h_norm=current_h_norm,
                    current_gate_norm=current_gate_norm,
                    actual_ratio=actual_ratio,
                    computed_mask=computed_mask,
                    counterfactual_masks=masks,
                )
            else:
                mlp_pair = self._pair("actual_mlp")
                mlp_output = block.mlp(h)
                self._end(mlp_pair)
                scatter_pair = self._pair("scatter_residual")
                result = self.mod_gate(x, gate_mlp, mlp_output, mod_segments)
                self._end(scatter_pair)
                self.mlp_call_count += 1
                self.actual_mlp_row_count += total_rows
                self.full_mlp_row_count += total_rows
                self.mlp_input_rows_min = total_rows if self.mlp_input_rows_min is None else min(self.mlp_input_rows_min, total_rows)
                self.mlp_input_rows_max = total_rows if self.mlp_input_rows_max is None else max(self.mlp_input_rows_max, total_rows)
                x = result
                if current_h_norm is not None:
                    delta = mlp_output[video_start:video_stop] * gate_mlp[video_row].to(mlp_output.dtype)
                    actual_ratio = self.torch.linalg.vector_norm(delta.float(), dim=-1) / base_video_norm
                    computed_mask = self.torch.ones_like(current_h_norm, dtype=self.torch.bool)
                    if self.mode == "CONTROL_FF_TOKEN_SHADOW":
                        for policy in POLICIES:
                            mask = masks[policy.policy_id]
                            if policy.policy_id not in self.impact:
                                self.impact[policy.policy_id] = _ImpactAccumulator(self.torch, actual_ratio.device)
                            self.impact[policy.policy_id].add(actual_ratio[mask])
                    self._update_history(
                        block_index=block_index,
                        current_h_norm=current_h_norm,
                        current_gate_norm=current_gate_norm,
                        actual_ratio=actual_ratio,
                        computed_mask=computed_mask,
                        counterfactual_masks=masks,
                    )
            self._end(ff_pair)
            return x
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            self.block_call_count += 1

    def install(self, dit_class: Any) -> None:
        if self._original_forward is not None:
            raise RuntimeError("C4-S1 wrapper already installed")
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

    def _event_summary(self, group: str) -> dict[str, Any]:
        pairs = self.events[group]
        if not self.events_supported:
            return {"value": None, "unit": "seconds", "support_status": "not_collected", "reason": self.unsupported_reason, "count": 0}
        values = [float(pair.start.elapsed_time(pair.end)) / 1000.0 for pair in pairs]
        values.sort()
        if not values:
            return {"value": 0.0, "unit": "seconds", "support_status": "collected", "count": 0, "p50": None, "p95": None}
        def pct(q: float) -> float:
            return values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]
        return {"value": sum(values), "unit": "seconds", "support_status": "collected", "count": len(values), "p50": pct(0.5), "p95": pct(0.95)}

    def finalize(self) -> dict[str, Any]:
        if self.events_supported:
            self.synchronize()
            self.synchronization_count += 1
        policies = {}
        for policy in POLICIES:
            counts = self.policy_counts[policy.policy_id]
            total_video = counts["total_video_rows"]
            predicted = int(counts["predicted_skip_rows"].item()) if counts["predicted_skip_rows"] is not None else 0
            step_flags = counts["step_flags"]
            block_flags = counts["block_flags"]
            steps = step_flags.nonzero().flatten().tolist() if step_flags is not None else []
            blocks = block_flags.nonzero().flatten().tolist() if block_flags is not None else []
            policies[policy.policy_id] = {
                **policy.public(),
                "total_video_rows": total_video,
                "predicted_skip_rows": predicted,
                "video_token_skip_ratio": predicted / total_video if total_video else 0.0,
                "all_token_mlp_row_reduction": predicted / self.full_mlp_row_count if self.full_mlp_row_count else 0.0,
                "affected_step_count": len(steps),
                "affected_block_count": len(blocks),
                "affected_steps": steps,
                "actual_impact": self.impact[policy.policy_id].result() if policy.policy_id in self.impact else None,
            }
        history_bytes = sum(
            value.numel() * value.element_size()
            for history in self.history.values()
            for value in (history.prev_h_norm, history.prev_ff_delta_ratio, history.prev_gate_norm, *history.valid_by_policy.values())
        )
        return {
            "schema_version": "c4-s1.h3.ff-token-selective.callback.1",
            "mode": self.mode,
            "selected_policy": self.selected_policy,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "fail_open_count": self.fail_open_count,
            "global_invalidation_count": self.global_invalidation_count,
            "attention_omission_count": self.attention_omission_count,
            "non_video_omission_count": self.non_video_omission_count,
            "mlp_call_count": self.mlp_call_count,
            "full_mlp_row_count": self.full_mlp_row_count,
            "actual_mlp_row_count": self.actual_mlp_row_count,
            "omitted_video_row_count": self.omitted_video_row_count,
            "actual_all_token_mlp_row_reduction": (self.full_mlp_row_count - self.actual_mlp_row_count) / self.full_mlp_row_count if self.full_mlp_row_count else 0.0,
            "observed_video_segment": list(self.observed_video_segment) if self.observed_video_segment else None,
            "observed_video_token_count": (self.observed_video_segment[1] - self.observed_video_segment[0]) if self.observed_video_segment else None,
            "observed_hidden_width": self.observed_hidden_width,
            "mlp_input_rows_min": self.mlp_input_rows_min,
            "mlp_input_rows_max": self.mlp_input_rows_max,
            "policy_shadow": policies,
            "timing": {name: self._event_summary(name) for name in self.events},
            "synchronization_count": self.synchronization_count,
            "profiler_enabled": False,
            "gpu_kernel_seconds": {"value": None, "support_status": "not_collected", "reason": "profiler and CUPTI were disabled"},
            "memory_contract": {
                "persistent_scalar_metadata_bytes": history_bytes,
                "budget_bytes": SCALAR_METADATA_BUDGET_BYTES,
                "budget_passed": history_bytes <= SCALAR_METADATA_BUDGET_BYTES,
                "full_tensor_cache_count": self.full_tensor_cache_count,
                "host_full_tensor_copy_bytes": self.host_full_tensor_copy_bytes,
                "tensor_bytes_to_rust": self.tensor_bytes_to_rust,
            },
        }
