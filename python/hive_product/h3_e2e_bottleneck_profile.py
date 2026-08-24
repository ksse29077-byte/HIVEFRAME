"""Bounded aggregate CUDA timing for the unchanged Standard H3 sampler."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Callable, Mapping, Sequence
import math
import time

from .h3_subblock_cost_surface import (
    BLOCK_COUNT,
    EXPECTED_BLOCK_CALLS,
    MODEL_SOURCE_SHA256,
    STEP_COUNT,
)


LEAF_CATEGORIES: tuple[str, ...] = (
    "modulation_projection",
    "attention_norm_modulation",
    "attention_qkv_projection",
    "attention_qk_norm_rope",
    "attention_kernel",
    "attention_output_projection",
    "attention_residual_update",
    "ff_norm_modulation",
    "mlp_fc1_projection",
    "mlp_activation_fc2_projection",
    "ff_residual_update",
)
EVENT_PAIR_BOUND = 1 + STEP_COUNT + EXPECTED_BLOCK_CALLS * len(LEAF_CATEGORIES)
EVENT_OBJECT_BOUND = EVENT_PAIR_BOUND * 2


@dataclass
class EventPair:
    start: Any
    end: Any


@dataclass
class TimingRecord:
    category: str
    pair: EventPair


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _summary(values: Sequence[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if math.isfinite(float(value)) and float(value) >= 0.0]
    if len(finite) != len(values) or not finite:
        return {
            "support_status": "not_collected" if not values else "unsupported",
            "unit": "milliseconds",
            "count": len(values),
            "total_ms": None,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }
    return {
        "support_status": "collected",
        "unit": "milliseconds",
        "count": len(finite),
        "total_ms": sum(finite),
        "mean_ms": mean(finite),
        "p50_ms": median(finite),
        "p95_ms": _percentile(finite, 0.95),
    }


class H3AggregateTimingController:
    """Install operation-identical H3 wrappers and resolve events once at finalize."""

    def __init__(
        self,
        *,
        event_factory: Callable[[], Any],
        synchronize: Callable[[], None],
        mod_scale_shift: Callable[..., Any],
        mod_gate: Callable[..., Any],
        optimized_attention: Callable[..., Any],
        cast_to: Callable[..., Any],
        in_training: Callable[[], bool],
        rms_rope: Callable[..., Any],
        rms_rope_in_place: Callable[..., Any],
        linear_input_act: Callable[..., Any],
        events_supported: bool = True,
        unsupported_reason: str | None = None,
    ) -> None:
        self.event_factory = event_factory
        self.synchronize = synchronize
        self.mod_scale_shift = mod_scale_shift
        self.mod_gate = mod_gate
        self.optimized_attention = optimized_attention
        self.cast_to = cast_to
        self.in_training = in_training
        self.rms_rope = rms_rope
        self.rms_rope_in_place = rms_rope_in_place
        self.linear_input_act = linear_input_act
        self.events_supported = events_supported
        self.unsupported_reason = unsupported_reason
        self.records: list[TimingRecord] = []
        self.event_pair_creation_count = 0
        self.synchronization_count = 0
        self.model_forward_count = 0
        self.block_call_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.sampler_pair: EventPair | None = None
        self.sampler_wall_started: float | None = None
        self.sampler_wall_seconds: float | None = None
        self._original_block_forward: Callable[..., Any] | None = None
        self._original_model_forward: Callable[..., Any] | None = None
        self._block_class: Any = None
        self._model_class: Any = None
        self._sampler_active = False
        self._finalized: dict[str, Any] | None = None

    def _pair(self) -> EventPair:
        pair = EventPair(self.event_factory(), self.event_factory())
        self.event_pair_creation_count += 1
        return pair

    def _timed(self, category: str, operation: Callable[[], Any]) -> Any:
        pair = self._pair()
        pair.start.record()
        try:
            return operation()
        finally:
            pair.end.record()
            self.records.append(TimingRecord(category, pair))

    def start_sampler(self) -> None:
        if not self.events_supported:
            return
        if self._sampler_active:
            raise RuntimeError("aggregate sampler timing already active")
        self.sampler_pair = self._pair()
        self.sampler_wall_started = time.monotonic()
        self.sampler_pair.start.record()
        self._sampler_active = True

    def end_sampler(self) -> None:
        if not self.events_supported:
            return
        if not self._sampler_active or self.sampler_pair is None:
            raise RuntimeError("aggregate sampler timing was not started")
        self.sampler_pair.end.record()
        self.sampler_wall_seconds = time.monotonic() - float(self.sampler_wall_started)
        self._sampler_active = False

    def _attention(self, attention: Any, x: Any, rope_freqs: Any, options: Mapping[str, Any]) -> Any:
        s = x.shape[0]
        q, k, v = self._timed(
            "attention_qkv_projection",
            lambda: attention.qkv_proj(x).split(attention.heads * attention.head_dim, dim=-1),
        )
        v = v.view(s, attention.heads, attention.head_dim)

        def qk_norm_rope() -> tuple[Any, Any]:
            if rope_freqs is None:
                return (
                    attention.q_norm(q.view(s, attention.heads, attention.head_dim)),
                    attention.k_norm(k.view(s, attention.heads, attention.head_dim)),
                )
            q_view = q.view(1, s, attention.heads, attention.head_dim)
            k_view = k.view(1, s, attention.heads, attention.head_dim)
            qw = self.cast_to(attention.q_norm.weight, device=x.device)
            kw = self.cast_to(attention.k_norm.weight, device=x.device)
            rot = rope_freqs.shape[-3] * 2
            if self.in_training():
                q_result, k_result = self.rms_rope(
                    q_view,
                    k_view,
                    rope_freqs,
                    qw,
                    kw,
                    epsilon=attention.q_norm.eps,
                    rot_dim=rot,
                )
            else:
                self.rms_rope_in_place(
                    q_view,
                    k_view,
                    rope_freqs,
                    qw,
                    kw,
                    epsilon=attention.q_norm.eps,
                    rot_dim=rot,
                )
                q_result, k_result = q_view, k_view
            return q_result[0], k_result[0]

        q, k = self._timed("attention_qk_norm_rope", qk_norm_rope)
        q = q.transpose(0, 1).unsqueeze(0)
        k = k.transpose(0, 1).unsqueeze(0)
        v = v.transpose(0, 1).unsqueeze(0)
        out = self._timed(
            "attention_kernel",
            lambda: self.optimized_attention(
                q,
                k,
                v,
                attention.heads,
                mask=None,
                skip_reshape=True,
                transformer_options=options,
            ),
        )
        return self._timed(
            "attention_output_projection",
            lambda: attention.out_proj(out.squeeze(0)),
        )

    def _block_forward(
        self,
        block: Any,
        x: Any,
        t_emb: Any,
        mod_segments: Any,
        rope_freqs: Any,
        transformer_options: Mapping[str, Any] | None,
    ) -> Any:
        call_index = self.block_call_count
        step_index, block_index = divmod(call_index, BLOCK_COUNT)
        if step_index >= STEP_COUNT or block_index >= BLOCK_COUNT:
            self.mapping_error_count += 1
        options = {} if transformer_options is None else transformer_options
        try:
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = self._timed(
                "modulation_projection", lambda: block.adaln_proj(t_emb)
            )
            h = self._timed(
                "attention_norm_modulation",
                lambda: self.mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments),
            )
            attention_output = self._attention(block.attn, h, rope_freqs, options)
            x = self._timed(
                "attention_residual_update",
                lambda: self.mod_gate(x, gate_msa, attention_output, mod_segments),
            )
            ff_h = self._timed(
                "ff_norm_modulation",
                lambda: self.mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments),
            )
            fc1_output = self._timed("mlp_fc1_projection", lambda: block.mlp.fc1(ff_h))
            mlp_output = self._timed(
                "mlp_activation_fc2_projection",
                lambda: self.linear_input_act(block.mlp.fc2, fc1_output, "swiglu"),
            )
            return self._timed(
                "ff_residual_update",
                lambda: self.mod_gate(x, gate_mlp, mlp_output, mod_segments),
            )
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            self.block_call_count += 1

    def install(self, block_class: Any, model_class: Any) -> None:
        if not self.events_supported:
            return
        if self._original_block_forward is not None or self._original_model_forward is not None:
            raise RuntimeError("aggregate H3 timing wrappers already installed")
        self._block_class = block_class
        self._model_class = model_class
        self._original_block_forward = block_class.forward
        self._original_model_forward = model_class._forward
        controller = self
        original_model = self._original_model_forward

        def timed_block(
            block: Any,
            x: Any,
            t_emb: Any,
            mod_segments: Any,
            rope_freqs: Any,
            transformer_options: Mapping[str, Any] | None = None,
        ) -> Any:
            return controller._block_forward(
                block, x, t_emb, mod_segments, rope_freqs, transformer_options
            )

        def timed_model(model: Any, *args: Any, **kwargs: Any) -> Any:
            controller.model_forward_count += 1
            return controller._timed("model_forward", lambda: original_model(model, *args, **kwargs))

        block_class.forward = timed_block
        model_class._forward = timed_model

    def restore(self) -> None:
        if self._original_block_forward is not None and self._block_class is not None:
            self._block_class.forward = self._original_block_forward
        if self._original_model_forward is not None and self._model_class is not None:
            self._model_class._forward = self._original_model_forward
        self._original_block_forward = None
        self._original_model_forward = None
        self._block_class = None
        self._model_class = None

    @staticmethod
    def _elapsed(pair: EventPair) -> float:
        return float(pair.start.elapsed_time(pair.end))

    def finalize(self) -> dict[str, Any]:
        if self._finalized is not None:
            return self._finalized
        if not self.events_supported:
            self._finalized = {
                "support_status": "unsupported",
                "reason": self.unsupported_reason or "CUDA events unavailable",
                "value": None,
                "synchronization_count": 0,
                "full_compute_only": True,
            }
            return self._finalized
        if self._sampler_active:
            self.end_sampler()
        sync_started = time.perf_counter()
        self.synchronize()
        self.synchronization_count += 1
        sync_wall = time.perf_counter() - sync_started
        values: dict[str, list[float]] = defaultdict(list)
        for record in self.records:
            values[record.category].append(self._elapsed(record.pair))
        sampler_ms = self._elapsed(self.sampler_pair) if self.sampler_pair is not None else None
        model_total_ms = sum(values["model_forward"])
        leaf_total_ms = sum(sum(values[category]) for category in LEAF_CATEGORIES)
        raw_model_other_ms = model_total_ms - leaf_total_ms
        model_other_ms = max(0.0, raw_model_other_ms)
        raw_sampler_other_ms = float(sampler_ms or 0.0) - model_total_ms
        sampler_other_ms = max(0.0, raw_sampler_other_ms)
        accounted_ms = leaf_total_ms + model_other_ms + sampler_other_ms
        accounting_ratio = accounted_ms / sampler_ms if sampler_ms and sampler_ms > 0 else None
        self._finalized = {
            "support_status": "collected",
            "measurement_method": "deferred aggregate CUDA event spans; one synchronization after Standard sampler completion",
            "measurement_scope": "nested spans: sampler contains model forwards; model forwards contain non-overlapping leaf categories",
            "profiler_enabled": False,
            "tensor_payload_d2h_bytes": 0,
            "per_row_log_count": 0,
            "per_region_log_count": 0,
            "per_call_cpu_sync_count": 0,
            "synchronization_count": self.synchronization_count,
            "synchronization_wall_seconds": sync_wall,
            "event_pair_creation_count": self.event_pair_creation_count,
            "event_pair_bound": EVENT_PAIR_BOUND,
            "event_object_count": self.event_pair_creation_count * 2,
            "event_object_bound": EVENT_OBJECT_BOUND,
            "model_source_sha256": MODEL_SOURCE_SHA256,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "sampler_wall_seconds": self.sampler_wall_seconds,
            "sampler_cuda_event_span_ms": sampler_ms,
            "model_forward": _summary(values["model_forward"]),
            "leaf_categories": {category: _summary(values[category]) for category in LEAF_CATEGORIES},
            "leaf_non_overlapping_sum_ms": leaf_total_ms,
            "model_other_prepost_offload_ms": model_other_ms,
            "model_other_raw_signed_ms": raw_model_other_ms,
            "sampler_non_model_dispatch_wait_ms": sampler_other_ms,
            "sampler_non_model_raw_signed_ms": raw_sampler_other_ms,
            "sampler_accounted_ms": accounted_ms,
            "sampler_accounting_ratio": accounting_ratio,
            "overlap_ledger": {
                "model_forward_overlaps_sampler": True,
                "leaf_categories_overlap_model_forward": True,
                "leaf_categories_mutually_exclusive": True,
                "accounted_union": "leaf categories + model other + sampler non-model",
            },
            "full_compute_only": True,
            "skip_count": 0,
            "reuse_count": 0,
            "prediction_count": 0,
            "regional_execution_count": 0,
            "token_omission_count": 0,
            "attention_omission_count": 0,
            "v4_observer_enabled": False,
            "v4_evidence_transfer_bytes": 0,
        }
        return self._finalized

    @property
    def sampler_timing_active(self) -> bool:
        return self._sampler_active


def profile_mapping_gate(callback: Mapping[str, Any]) -> dict[str, Any]:
    timing = callback.get("timing") if isinstance(callback.get("timing"), Mapping) else {}
    leaves = timing.get("leaf_categories") if isinstance(timing.get("leaf_categories"), Mapping) else {}
    checks = {
        "sampler_succeeded": callback.get("sampler_succeeded") is True,
        "timing_collected": timing.get("support_status") == "collected",
        "model_forward_count_20": timing.get("model_forward_count") == STEP_COUNT,
        "block_call_count_1000": timing.get("block_call_count") == EXPECTED_BLOCK_CALLS,
        "all_leaf_counts_1000": all(
            isinstance(leaves.get(category), Mapping)
            and leaves[category].get("count") == EXPECTED_BLOCK_CALLS
            for category in LEAF_CATEGORIES
        ),
        "mapping_error_zero": timing.get("mapping_error_count") == 0,
        "wrapper_failure_zero": timing.get("wrapper_failure_count") == 0,
        "one_finalize_sync": timing.get("synchronization_count") == 1,
        "no_hot_path_cpu_sync": timing.get("per_call_cpu_sync_count") == 0,
        "event_pair_bound": int(timing.get("event_pair_creation_count", EVENT_PAIR_BOUND + 1))
        <= EVENT_PAIR_BOUND,
        "event_object_bound": int(timing.get("event_object_count", EVENT_OBJECT_BOUND + 1))
        <= EVENT_OBJECT_BOUND,
        "sampler_accounting_95_percent": float(timing.get("sampler_accounting_ratio", 0.0)) >= 0.95,
        "sampler_accounting_no_double_count": float(timing.get("sampler_accounting_ratio", 2.0)) <= 1.05,
        "nested_residuals_nonnegative": float(timing.get("model_other_raw_signed_ms", -1.0)) >= 0.0
        and float(timing.get("sampler_non_model_raw_signed_ms", -1.0)) >= 0.0,
        "tensor_payload_d2h_zero": timing.get("tensor_payload_d2h_bytes") == 0,
        "v4_observer_disabled": timing.get("v4_observer_enabled") is False,
        "v4_transfer_zero": timing.get("v4_evidence_transfer_bytes") == 0,
        "full_compute_only": timing.get("full_compute_only") is True,
        "all_omission_counters_zero": all(
            timing.get(name) == 0
            for name in (
                "skip_count",
                "reuse_count",
                "prediction_count",
                "regional_execution_count",
                "token_omission_count",
                "attention_omission_count",
            )
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}
