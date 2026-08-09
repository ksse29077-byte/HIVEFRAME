"""C4-S1-R1 minimal-telemetry variant of the fixed H3 FF selector.

Only measurement-only work is removed.  Selector inputs, causal history,
policies, anchors, the ten-percent per-block guard, and fail-open execution
are inherited from the immutable C4-S1 contract.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .ff_token_selective import (
    ANCHOR_STEPS,
    BLOCK_COUNT,
    MIN_BLOCK_VIDEO_SKIP_RATIO,
    POLICIES,
    SCALAR_METADATA_BUDGET_BYTES,
    STEP_COUNT,
    H3FFTokenSelectiveController,
)


CONTROL_MODE = "CONTROL_FF_TOKEN_MINIMAL"
SELECTIVE_MODE = "SELECTIVE_FF_TOKEN_MINIMAL"
_LEGACY_CONTROL_MODE = "CONTROL_FF_TOKEN_SHADOW"
_LEGACY_SELECTIVE_MODE = "SELECTIVE_FF_TOKEN"
_TIMING_REASON = "measurement-only per-block CUDA events were removed by C4-S1-R1"


class _BoundedImpactAggregate:
    """Fixed-shape GPU scalar aggregation with no histogram or compaction."""

    def __init__(self, torch_module: Any, device: Any) -> None:
        self.torch = torch_module
        self.count = torch_module.zeros((), dtype=torch_module.int64, device=device)
        self.total = torch_module.zeros((), dtype=torch_module.float64, device=device)
        self.maximum = torch_module.zeros((), dtype=torch_module.float32, device=device)
        self.over_point_zero_one = torch_module.zeros((), dtype=torch_module.int64, device=device)
        self.nonfinite = torch_module.zeros((), dtype=torch_module.int64, device=device)

    def add_masked(self, values: Any, candidate_mask: Any) -> None:
        values = values.detach().float()
        finite = values.isfinite()
        admitted = candidate_mask & finite
        zeros = self.torch.zeros_like(values)
        admitted_values = self.torch.where(admitted, values, zeros)
        self.count.add_(admitted.sum())
        self.total.add_(admitted_values.double().sum())
        self.maximum.copy_(self.torch.maximum(self.maximum, admitted_values.max()))
        self.over_point_zero_one.add_((admitted & (values > 0.010)).sum())
        self.nonfinite.add_((candidate_mask & ~finite).sum())

    def result(self) -> dict[str, Any]:
        count = int(self.count.item())
        nonfinite = int(self.nonfinite.item())
        over = int(self.over_point_zero_one.item())
        mean = float(self.total.item() / count) if count else None
        maximum = float(self.maximum.item()) if count else None
        over_rate = float(over / count) if count else None
        p99_gate_pass = over_rate is not None and over_rate <= 0.005
        return {
            "count": count,
            "mean": mean,
            "p50": None,
            "p95": None,
            "p99": None,
            "p99_support_status": "derived_from_stricter_tail_gate",
            "p99_reason": (
                "The frozen >0.010 tail-rate gate of <=0.005 implies the nearest-rank "
                "p99 is <=0.010; no histogram is collected."
            ),
            "p99_gate_pass": p99_gate_pass,
            "max": maximum,
            "impact_sum": float(self.total.item()),
            "over_0_010_count": over,
            "over_0_010_rate": over_rate,
            "nonfinite_count": nonfinite,
            "aggregation": "fixed-shape GPU scalar reductions; host reads at finalize only",
        }


def tail_gate_implies_p99(*, count: int, over_threshold_count: int) -> bool:
    """Conservative nearest-rank proof used by the frozen p99 admission gate."""

    if count <= 0 or over_threshold_count < 0 or over_threshold_count > count:
        return False
    return (over_threshold_count / count) <= 0.005


class H3FFTokenMinimalController(H3FFTokenSelectiveController):
    """Same selector, without detailed measurement-only hot-path telemetry."""

    def __init__(
        self,
        *,
        mode: str,
        selected_policy: str | None,
        mod_scale_shift: Any,
        mod_gate: Any,
        torch_module: Any,
    ) -> None:
        if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
            raise ValueError("unsupported C4-S1-R1 mode")
        internal_mode = _LEGACY_CONTROL_MODE if mode == CONTROL_MODE else _LEGACY_SELECTIVE_MODE
        super().__init__(
            mode=internal_mode,
            selected_policy=selected_policy,
            event_factory=lambda: None,
            synchronize=lambda: None,
            mod_scale_shift=mod_scale_shift,
            mod_gate=mod_gate,
            torch_module=torch_module,
            events_supported=False,
            unsupported_reason=_TIMING_REASON,
        )
        self.public_mode = mode
        self.impact: dict[str, _BoundedImpactAggregate] = {}
        self.hot_path_item_count = 0
        self.hot_path_explicit_synchronization_count = 0
        self.hot_path_host_tensor_transfer_count = 0
        self.per_block_cuda_event_pair_count = 0
        self.histogram_bin_count = 0

    @property
    def is_control(self) -> bool:
        return self.mode == _LEGACY_CONTROL_MODE

    def start_sampler(self) -> None:
        self._sampler_started = True

    def end_sampler(self) -> None:
        if not self._sampler_started:
            raise RuntimeError("sampler timing lifecycle was not started")
        self._sampler_started = False

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
            h = self.mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)

            try:
                video_start, video_stop, video_row = self._video_segment(x, mod_segments)
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
                    if self.is_control:
                        bucket = self.policy_counts[policy.policy_id]
                        if bucket["predicted_skip_rows"] is None:
                            bucket["predicted_skip_rows"] = self.torch.zeros((), dtype=self.torch.int64, device=mask.device)
                            bucket["step_flags"] = self.torch.zeros(STEP_COUNT, dtype=self.torch.bool, device=mask.device)
                            bucket["block_flags"] = self.torch.zeros(BLOCK_COUNT, dtype=self.torch.bool, device=mask.device)
                        bucket["predicted_skip_rows"].add_(mask.sum())
                        bucket["total_video_rows"] += int(mask.numel())
                        bucket["step_flags"][step_index] |= mask.any()
                        bucket["block_flags"][block_index] |= mask.any()
                if not self.is_control:
                    actual_mask = masks[str(self.selected_policy)]
                    self.hot_path_item_count += 2
                    block_ratio = float(actual_mask.float().mean().item())
                    use_selective = block_ratio >= MIN_BLOCK_VIDEO_SKIP_RATIO and int(actual_mask.sum().item()) > 0

            if use_selective and actual_mask is not None:
                active_video = (~actual_mask).nonzero().flatten() + video_start
                non_video = self.torch.arange(video_start, device=h.device)
                active_indices = self.torch.cat((non_video, active_video))
                active_h = h.index_select(0, active_indices)
                active_output = block.mlp(active_h)
                for start, stop, row in mod_segments:
                    positions = ((active_indices >= int(start)) & (active_indices < int(stop))).nonzero().flatten()
                    if int(positions.numel()) == 0:
                        continue
                    original_rows = active_indices.index_select(0, positions)
                    delta = active_output.index_select(0, positions) * gate_mlp[int(row)].to(active_output.dtype)
                    x.index_add_(0, original_rows, delta)
                self.mlp_call_count += 1
                self.actual_mlp_row_count += int(active_indices.numel())
                self.full_mlp_row_count += total_rows
                omitted = int(actual_mask.sum().item())
                self.hot_path_item_count += 1
                self.omitted_video_row_count += omitted
                rows = int(active_indices.numel())
                self.mlp_input_rows_min = rows if self.mlp_input_rows_min is None else min(self.mlp_input_rows_min, rows)
                self.mlp_input_rows_max = rows if self.mlp_input_rows_max is None else max(self.mlp_input_rows_max, rows)
                active_video_count = int(active_video.numel())
                video_active_output = active_output[-active_video_count:] if active_video_count else active_output[:0]
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
                mlp_output = block.mlp(h)
                x = self.mod_gate(x, gate_mlp, mlp_output, mod_segments)
                self.mlp_call_count += 1
                self.actual_mlp_row_count += total_rows
                self.full_mlp_row_count += total_rows
                self.mlp_input_rows_min = total_rows if self.mlp_input_rows_min is None else min(self.mlp_input_rows_min, total_rows)
                self.mlp_input_rows_max = total_rows if self.mlp_input_rows_max is None else max(self.mlp_input_rows_max, total_rows)
                if current_h_norm is not None:
                    delta = mlp_output[video_start:video_stop] * gate_mlp[video_row].to(mlp_output.dtype)
                    actual_ratio = self.torch.linalg.vector_norm(delta.float(), dim=-1) / base_video_norm
                    computed_mask = self.torch.ones_like(current_h_norm, dtype=self.torch.bool)
                    if self.is_control:
                        for policy in POLICIES:
                            if policy.policy_id not in self.impact:
                                self.impact[policy.policy_id] = _BoundedImpactAggregate(self.torch, actual_ratio.device)
                            self.impact[policy.policy_id].add_masked(actual_ratio, masks[policy.policy_id])
                    self._update_history(
                        block_index=block_index,
                        current_h_norm=current_h_norm,
                        current_gate_norm=current_gate_norm,
                        actual_ratio=actual_ratio,
                        computed_mask=computed_mask,
                        counterfactual_masks=masks,
                    )
            return x
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            self.block_call_count += 1

    @staticmethod
    def _not_collected_timing() -> dict[str, Any]:
        return {
            "value": None,
            "unit": "seconds",
            "support_status": "not_collected",
            "reason": _TIMING_REASON,
            "count": 0,
        }

    def finalize(self) -> dict[str, Any]:
        policies: dict[str, Any] = {}
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
        timing = {
            name: self._not_collected_timing()
            for name in ("sampler", "full_ff_group", "actual_mlp", "gather_mask", "scatter_residual")
        }
        return {
            "schema_version": "c4-s1-r1.h3.ff-token-minimal.callback.1",
            "mode": self.public_mode,
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
            "actual_all_token_mlp_row_reduction": (
                (self.full_mlp_row_count - self.actual_mlp_row_count) / self.full_mlp_row_count
                if self.full_mlp_row_count else 0.0
            ),
            "observed_video_segment": list(self.observed_video_segment) if self.observed_video_segment else None,
            "observed_video_token_count": (
                self.observed_video_segment[1] - self.observed_video_segment[0]
                if self.observed_video_segment else None
            ),
            "observed_hidden_width": self.observed_hidden_width,
            "mlp_input_rows_min": self.mlp_input_rows_min,
            "mlp_input_rows_max": self.mlp_input_rows_max,
            "policy_shadow": policies,
            "timing": timing,
            "synchronization_count": 0,
            "profiler_enabled": False,
            "gpu_kernel_seconds": {
                "value": None,
                "support_status": "not_collected",
                "reason": "profiler and CUPTI were disabled",
            },
            "minimal_telemetry_audit": {
                "per_block_cuda_event_pair_count": self.per_block_cuda_event_pair_count,
                "explicit_hot_path_synchronization_count": self.hot_path_explicit_synchronization_count,
                "control_hot_path_item_count": 0 if self.is_control else None,
                "hot_path_host_tensor_transfer_count": self.hot_path_host_tensor_transfer_count,
                "histogram_bin_count": self.histogram_bin_count,
                "resource_sampler_enabled": False,
                "selector_required_work_retained": True,
            },
            "memory_contract": {
                "persistent_scalar_metadata_bytes": history_bytes,
                "budget_bytes": SCALAR_METADATA_BUDGET_BYTES,
                "budget_passed": history_bytes <= SCALAR_METADATA_BUDGET_BYTES,
                "full_tensor_cache_count": self.full_tensor_cache_count,
                "host_full_tensor_copy_bytes": self.host_full_tensor_copy_bytes,
                "tensor_bytes_to_rust": self.tensor_bytes_to_rust,
            },
        }
