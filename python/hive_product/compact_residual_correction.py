"""C3-R3 compact channel-affine residual prediction for the H3 adapter.

Generic Core receives fixed-width admission metadata only. H3-specific tensor
layout, block range, CUDA buffers, channel statistics, and correction replay
remain inside this model-adapter module.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Protocol
import copy
import hashlib
import json
import math

from .compound_eye_shadow import AsyncCompoundEyeShadowPipeline
from .segment_residual_replay import (
    BLOCK_COUNT,
    FROZEN_CEILING,
    FULL_COMPUTE_ANCHORS,
    NORMALIZED_RESIDUAL_L2_MAX,
    RESIDUAL_COSINE_MIN,
    SEGMENT_BLOCKS,
    SEGMENT_END,
    SEGMENT_LOGICAL_DIGEST,
    SEGMENT_LOGICAL_ID,
    SEGMENT_START,
    TOTAL_STEPS,
    ResidualCache,
    TorchTensorOps,
    _digest,
    _timing,
)


ABI_VERSION = 1
MECHANISM = "CHANNEL_AFFINE_RESIDUAL_PREDICTION_V1"
CONTROL = "CONTROL_CORRECTION_SHADOW"
SELECTIVE = "SELECTIVE_CORRECTED_RESIDUAL_REPLAY"
STATISTIC_TYPE = "channel_standard_deviation"
STATISTIC_EPSILON = 1.0e-6
GAIN_MIN = 0.90
GAIN_MAX = 1.10
COMPACT_METADATA_MAX_BYTES = 64 * 1024
STATISTIC_CHUNK_ROWS = 256
MIN_CALIBRATED_TARGETS = 2
MIN_TARGET_SPACING = 3

FULL_COMPUTE = 0
REUSE_CORRECTED_TRANSFORM = 1
ESCALATE_FULL_COMPUTE = 2
DECISION_LABELS = {
    FULL_COMPUTE: "FULL_COMPUTE",
    REUSE_CORRECTED_TRANSFORM: "REUSE_CORRECTED_TRANSFORM",
    ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE",
}
REASON_LABELS = {
    0: "correction_admitted",
    1: "abi_mismatch",
    2: "struct_size_mismatch",
    3: "step_range_invalid",
    4: "digest_missing",
    5: "metadata_invalid",
    6: "not_calibrated",
    7: "cache_missing",
    8: "predictor_missing",
    9: "provenance_invalid",
    10: "similarity_rejected",
    11: "source_invalid",
    12: "prediction_invalid",
    13: "stable_count_low",
    14: "active_present",
    15: "global_invalidation",
    16: "overlap_conflict",
    17: "fatal_flag",
    18: "reseed_required",
    19: "fallback_unsupported",
    20: "unsupported_metadata",
    21: "rust_panic",
}


@dataclass(frozen=True)
class CorrectionPlanContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str
    model_revision_digest: str


class CorrectionPlanBridge:
    """One metadata-only Rust admission call per consumed C2 callback."""

    def __init__(
        self,
        context: CorrectionPlanContext,
        calibrated_targets: tuple[int, ...],
        extension: Any | None = None,
    ) -> None:
        validate_calibrated_targets(calibrated_targets)
        self.run_digest = _digest(context.run_digest, "run_digest")
        self.workflow_revision_digest = _digest(
            context.workflow_revision_digest, "workflow_revision_digest"
        )
        self.settings_digest = _digest(context.settings_digest, "settings_digest")
        self.model_revision_digest = _digest(context.model_revision_digest, "model_revision_digest")
        self.segment_logical_digest = bytes.fromhex(SEGMENT_LOGICAL_DIGEST)
        self.calibrated_targets = calibrated_targets
        self.state_provider: Callable[[int], Mapping[str, Any]] | None = None
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
                self.contract = dict(self.extension.correction_plan_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.rust_call_count = 0
        self.fallback_count = 0
        self.events: list[dict[str, Any]] = []
        self.plans: dict[int, dict[str, Any]] = {}
        self.boundary_ns: list[int] = []
        self.rust_policy_ns: list[int] = []

    def set_state_provider(self, provider: Callable[[int], Mapping[str, Any]]) -> None:
        self.state_provider = provider

    @staticmethod
    def _eye_masks(event: Mapping[str, Any]) -> tuple[int, int, int]:
        states = event.get("eye_states")
        if not isinstance(states, list) or len(states) != 5:
            return 0, 0, 0
        masks = {"STABLE": 0, "ACTIVE": 0, "UNCERTAIN": 0}
        for regional, label in enumerate(states[1:]):
            if label in masks:
                masks[str(label)] |= 1 << regional
        return masks["STABLE"], masks["ACTIVE"], masks["UNCERTAIN"]

    def evaluate_event(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        target = event.get("predicted_execution_step")
        if not isinstance(target, int):
            return None
        state = dict(self.state_provider(target)) if self.state_provider else {}
        stable_mask, active_mask, uncertain_mask = self._eye_masks(event)
        first_source = int(state.get("first_source_execution_step", max(0, target - 2)))
        second_source = int(state.get("second_source_execution_step", max(0, target - 1)))
        source_valid = (
            not bool(event.get("fallback_used"))
            and event.get("reason") is None
            and event.get("event_ready") is True
            and event.get("source_dtype") == "torch.float32"
            and event.get("source_device_type") == "cuda"
            and event.get("signal_adapter") == "h3_nested_video_v1"
        )
        prediction_valid = (
            target == int(event.get("sketch_observed_step", -99)) + 2
            and target < int(event.get("total_steps", 0))
        )
        calibrated = target in self.calibrated_targets
        observation = {
            "abi_version": ABI_VERSION,
            "struct_size": int(self.contract["observation_struct_size"]) if self.contract else 0,
            "run_digest": self.run_digest,
            "workflow_revision_digest": self.workflow_revision_digest,
            "settings_digest": self.settings_digest,
            "model_revision_digest": self.model_revision_digest,
            "segment_logical_digest": self.segment_logical_digest,
            "target_execution_step": target,
            "first_source_execution_step": first_source,
            "second_source_execution_step": second_source,
            "total_steps": int(event.get("total_steps", 0)),
            "cache_available": bool(state.get("cache_available", False)),
            "predictor_available": bool(state.get("predictor_available", False)),
            "predictor_provenance_valid": bool(state.get("predictor_provenance_valid", False)),
            "corrected_similarity_admitted": calibrated,
            "correction_metadata_valid": bool(state.get("correction_metadata_valid", False)),
            "calibrated_target": calibrated,
            "full_compute_seed_count": int(state.get("full_compute_seed_count", 0)),
            "reseed_required": bool(state.get("reseed_required", True)),
            "stable_mask": stable_mask,
            "stable_count": stable_mask.bit_count(),
            "active_mask": active_mask,
            "active_count": active_mask.bit_count(),
            "uncertain_mask": uncertain_mask,
            "uncertain_count": uncertain_mask.bit_count(),
            "global_invalidation": bool(event.get("global_invalidation", 1)),
            "overlap_conflict_mask": int(event.get("overlap_conflict_mask", 0)),
            "prediction_valid": prediction_valid,
            "source_valid": source_valid,
            "finite": bool(state.get("finite", False)),
            "fallback_supported": True,
            "fatal_flags": int(bool(event.get("deadline_missed"))),
            "unsupported_flags": 0,
        }
        failure_reason: str | None = None
        response: dict[str, Any] | None = None
        boundary_ns: int | None = None
        if self.extension is None:
            failure_reason = self.extension_error or "rust_extension_unavailable"
        else:
            started = perf_counter_ns()
            self.rust_call_count += 1
            try:
                response = dict(self.extension.evaluate_correction_plan(**observation))
            except Exception as error:
                failure_reason = type(error).__name__
            boundary_ns = perf_counter_ns() - started
            self.boundary_ns.append(boundary_ns)
        decision = ESCALATE_FULL_COMPUTE
        reason_code: int | None = None
        decision_digest: str | None = None
        rust_policy_ns: int | None = None
        if response is not None:
            try:
                decision = int(response["decision_code"])
                reason_code = int(response["reason_code"])
                rust_policy_ns = int(response["rust_policy_ns"])
                raw_digest = bytes(response["decision_digest"])
                if int(response["ffi_status"]) != 0:
                    failure_reason = "rust_nonzero_status"
                elif decision not in DECISION_LABELS:
                    failure_reason = "unknown_decision"
                elif int(response["target_execution_step"]) != target:
                    failure_reason = "target_step_mismatch"
                elif int(response["first_source_execution_step"]) != first_source:
                    failure_reason = "first_source_step_mismatch"
                elif int(response["second_source_execution_step"]) != second_source:
                    failure_reason = "second_source_step_mismatch"
                elif len(raw_digest) != 32:
                    failure_reason = "decision_digest_invalid"
                else:
                    decision_digest = raw_digest.hex()
            except (KeyError, TypeError, ValueError, OverflowError):
                failure_reason = "malformed_response"
        if failure_reason is not None:
            self.fallback_count += 1
            decision = ESCALATE_FULL_COMPUTE
        if rust_policy_ns is not None:
            self.rust_policy_ns.append(rust_policy_ns)
        plan = {
            "target_step": target,
            "first_source_step": first_source,
            "second_source_step": second_source,
            "calibrated_target": calibrated,
            "decision": DECISION_LABELS[decision],
            "decision_code": decision,
            "reason_code": reason_code,
            "reason": failure_reason or REASON_LABELS.get(reason_code, "unknown_reason"),
            "fallback_used": failure_reason is not None,
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": rust_policy_ns,
            "decision_digest": decision_digest,
            "tensor_bytes_to_rust": 0,
            **{key: observation[key] for key in (
                "cache_available", "predictor_available", "predictor_provenance_valid",
                "correction_metadata_valid", "full_compute_seed_count", "reseed_required",
                "stable_count", "active_count", "uncertain_count", "global_invalidation",
                "overlap_conflict_mask", "source_valid", "prediction_valid", "finite",
            )},
        }
        self.plans[target] = plan
        self.events.append(plan)
        return plan

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "c3-r3.correction-plan.1",
            "abi_version": ABI_VERSION,
            "contract": self.contract,
            "calibrated_targets": list(self.calibrated_targets),
            "rust_call_count": self.rust_call_count,
            "fallback_count": self.fallback_count,
            "boundary_roundtrip": _timing(self.boundary_ns),
            "rust_policy": _timing(self.rust_policy_ns),
            "tensor_bytes_to_rust": 0,
            "events": self.events,
        }


class CorrectionShadowPipeline(AsyncCompoundEyeShadowPipeline):
    def __init__(self, bridge: Any, plan_bridge: CorrectionPlanBridge, **kwargs: Any) -> None:
        super().__init__(bridge, **kwargs)
        self.plan_bridge = plan_bridge

    def _consume_ready(self, slot: Any, consumed_callback: int) -> dict[str, Any]:
        event = super()._consume_ready(slot, consumed_callback)
        self.plan_bridge.evaluate_event(event)
        return event


class CorrectionTensorOps(Protocol):
    def clone(self, tensor: Any) -> Any: ...
    def residualize(self, snapshot: Any, output: Any) -> Any: ...
    def metadata(self, tensor: Any) -> Mapping[str, Any]: ...
    def finite(self, tensor: Any) -> bool: ...
    def similarity(self, previous: Any, current: Any) -> Mapping[str, Any]: ...
    def build_correction(self, previous: Any, current: Any) -> Mapping[str, Any]: ...
    def corrected_similarity(
        self, previous: Any, current: Any, gain: Any, bias: Any
    ) -> Mapping[str, Any]: ...
    def apply_corrected(self, current: Any, residual: Any, gain: Any, bias: Any) -> Any: ...
    def cuda_memory(self, tensor: Any) -> Mapping[str, Any]: ...


class TorchCorrectionTensorOps(TorchTensorOps):
    """Bounded-chunk FP32 reductions without a full FP32 residual materialization."""

    @staticmethod
    def _rows(tensor: Any) -> Any:
        if int(tensor.ndim) < 1 or int(tensor.shape[-1]) <= 0:
            raise ValueError("H3 residual requires a non-empty channel-last layout")
        return tensor.reshape(-1, int(tensor.shape[-1]))

    def _channel_stats(self, tensor: Any) -> tuple[Any, Any]:
        import torch

        rows = self._rows(tensor)
        count = int(rows.shape[0])
        channels = int(rows.shape[1])
        total = torch.zeros(channels, dtype=torch.float32, device=tensor.device)
        total_squared = torch.zeros_like(total)
        for start in range(0, count, STATISTIC_CHUNK_ROWS):
            chunk = rows[start : start + STATISTIC_CHUNK_ROWS].to(dtype=torch.float32)
            total.add_(chunk.sum(dim=0))
            total_squared.add_((chunk * chunk).sum(dim=0))
        mean = total / max(1, count)
        variance = (total_squared / max(1, count) - mean * mean).clamp_min_(0.0)
        return mean, variance.sqrt_()

    def build_correction(self, previous: Any, current: Any) -> Mapping[str, Any]:
        import torch

        started = perf_counter_ns()
        previous_mean, previous_scale = self._channel_stats(previous)
        current_mean, current_scale = self._channel_stats(current)
        stats_ns = perf_counter_ns() - started
        creation_started = perf_counter_ns()
        gain, bias = channel_affine_from_stats(
            previous_mean, current_mean, previous_scale, current_scale
        )
        finite = bool(torch.isfinite(gain).all().item() and torch.isfinite(bias).all().item())
        channels = int(gain.numel())
        metadata_bytes = int(gain.numel() * gain.element_size() + bias.numel() * bias.element_size())
        creation_ns = perf_counter_ns() - creation_started
        return {
            "gain": gain,
            "bias": bias,
            "finite": finite,
            "channel_count": channels,
            "metadata_tensor_bytes": metadata_bytes,
            "metadata_bytes": metadata_bytes + 256,
            "gain_min": float(gain.min().item()),
            "gain_max": float(gain.max().item()),
            "clipped_low_count": int((gain <= GAIN_MIN).sum().item()),
            "clipped_high_count": int((gain >= GAIN_MAX).sum().item()),
            "channel_stats_ns": stats_ns,
            "gain_bias_creation_ns": creation_ns,
            "full_size_fp32_materialization_count": 0,
            "full_tensor_host_copy_bytes": 0,
        }

    def corrected_similarity(
        self, previous: Any, current: Any, gain: Any, bias: Any
    ) -> Mapping[str, Any]:
        import torch

        previous_rows = self._rows(previous)
        current_rows = self._rows(current)
        predicted_sq = torch.zeros((), dtype=torch.float64, device=previous.device)
        current_sq = torch.zeros_like(predicted_sq)
        dot = torch.zeros_like(predicted_sq)
        for start in range(0, int(previous_rows.shape[0]), STATISTIC_CHUNK_ROWS):
            left = previous_rows[start : start + STATISTIC_CHUNK_ROWS].to(torch.float32)
            right = current_rows[start : start + STATISTIC_CHUNK_ROWS].to(torch.float32)
            predicted = left.mul(gain).add(bias)
            predicted_sq.add_((predicted * predicted).sum(dtype=torch.float64))
            current_sq.add_((right * right).sum(dtype=torch.float64))
            dot.add_((predicted * right).sum(dtype=torch.float64))
        predicted_norm = math.sqrt(max(0.0, float(predicted_sq.item())))
        current_norm = math.sqrt(max(0.0, float(current_sq.item())))
        dot_value = float(dot.item())
        denominator = predicted_norm * current_norm
        cosine = dot_value / denominator if denominator > 0 else None
        difference_squared = max(
            0.0, predicted_norm**2 + current_norm**2 - 2.0 * dot_value
        )
        normalized_l2 = math.sqrt(difference_squared) / predicted_norm if predicted_norm > 0 else None
        finite = all(
            math.isfinite(value)
            for value in (predicted_norm, current_norm, dot_value)
        )
        return {
            "normalized_residual_l2": normalized_l2,
            "residual_cosine_similarity": cosine,
            "finite": finite,
            "method": "same C3-R2 L2/cosine definitions over bounded-chunk corrected residual reductions",
            "full_tensor_host_copy_bytes": 0,
            "full_size_fp32_materialization_count": 0,
        }

    def apply_corrected(self, current: Any, residual: Any, gain: Any, bias: Any) -> Any:
        current_rows = self._rows(current)
        residual_rows = self._rows(residual)
        typed_gain = gain.to(dtype=current.dtype)
        typed_bias = bias.to(dtype=current.dtype)
        for start in range(0, int(current_rows.shape[0]), STATISTIC_CHUNK_ROWS):
            target = current_rows[start : start + STATISTIC_CHUNK_ROWS]
            source = residual_rows[start : start + STATISTIC_CHUNK_ROWS]
            target.addcmul_(source, typed_gain)
            target.add_(typed_bias)
        return current


def channel_affine_from_stats(
    previous_mean: Any, current_mean: Any, previous_scale: Any, current_scale: Any
) -> tuple[Any, Any]:
    """Frozen V1 formula; works for scalar test doubles and tensor vectors."""
    if hasattr(previous_scale, "clamp_min"):
        gain = (current_scale / previous_scale.clamp_min(STATISTIC_EPSILON)).clamp_(
            GAIN_MIN, GAIN_MAX
        )
    else:
        denominator = max(float(previous_scale), STATISTIC_EPSILON)
        gain = min(GAIN_MAX, max(GAIN_MIN, float(current_scale) / denominator))
    bias = current_mean - gain * previous_mean
    return gain, bias


@dataclass
class CorrectionState:
    gain: Any
    bias: Any
    first_source_execution_step: int
    second_source_execution_step: int
    workflow_revision_digest: str
    model_revision_digest: str
    settings_digest: str
    shape_digest: str
    dtype: str
    device: str
    finite: bool
    channel_count: int
    metadata_bytes: int

    def public(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if key not in {"gain", "bias"}}


class H3CompactResidualCorrectionController:
    """H3-only block 12..48 correction capture and replay adapter."""

    def __init__(
        self,
        mode: str,
        plan_bridge: CorrectionPlanBridge,
        *,
        workflow_revision_digest: str,
        model_revision_digest: str,
        settings_digest: str,
        tensor_ops: CorrectionTensorOps | None = None,
    ) -> None:
        if mode not in {CONTROL, SELECTIVE}:
            raise ValueError("invalid C3-R3 mode")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.workflow_revision_digest = workflow_revision_digest
        self.model_revision_digest = model_revision_digest
        self.settings_digest = settings_digest
        self.ops = tensor_ops or TorchCorrectionTensorOps()
        self.cache: ResidualCache | None = None
        self.correction: CorrectionState | None = None
        self.segment_snapshot: Any | None = None
        self.replay_active_step: int | None = None
        self.full_compute_seed_count = 0
        self.model_forward_count = 0
        self.original_block_call_count = 0
        self.replayed_block_call_count = 0
        self.replay_count = 0
        self.residual_capture_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.expected_block_index = 0
        self.current_execution_step = -1
        self.max_concurrent_residual_sized_buffers = 0
        self.max_additional_gpu_bytes = 0
        self.diagnostics: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.memory_samples: list[dict[str, Any]] = []
        self.per_step: dict[int, dict[str, Any]] = {}
        self.original_ns: list[int] = []
        self.capture_ns: list[int] = []
        self.channel_stats_ns: list[int] = []
        self.gain_bias_ns: list[int] = []
        self.similarity_ns: list[int] = []
        self.correction_application_ns: list[int] = []
        self.plan_bridge.set_state_provider(self.state_for_target)

    def _step(self, step: int) -> dict[str, Any]:
        return self.per_step.setdefault(step, {
            "execution_step": step,
            "original_block_calls": 0,
            "replayed_block_calls": 0,
            "residual_captured": False,
            "correction_applied": False,
            "decision": "FULL_COMPUTE",
            "reason": "plan_unavailable",
        })

    def _provenance_valid(self) -> bool:
        cache, correction = self.cache, self.correction
        return bool(
            cache and correction
            and cache.source_execution_step == correction.second_source_execution_step
            and correction.first_source_execution_step + 1 == correction.second_source_execution_step
            and cache.workflow_revision_digest == correction.workflow_revision_digest == self.workflow_revision_digest
            and cache.model_revision_digest == correction.model_revision_digest == self.model_revision_digest
            and cache.settings_digest == correction.settings_digest == self.settings_digest
            and cache.shape_digest == correction.shape_digest
            and cache.dtype == correction.dtype
            and cache.device == correction.device
            and cache.finite and correction.finite
        )

    def state_for_target(self, target: int) -> Mapping[str, Any]:
        correction = self.correction
        cache = self.cache
        target_match = bool(correction and correction.second_source_execution_step + 1 == target)
        return {
            "first_source_execution_step": (
                correction.first_source_execution_step if correction else max(0, target - 2)
            ),
            "second_source_execution_step": (
                correction.second_source_execution_step if correction else max(0, target - 1)
            ),
            "cache_available": bool(cache and target_match),
            "predictor_available": target_match,
            "predictor_provenance_valid": target_match and self._provenance_valid(),
            "correction_metadata_valid": bool(
                correction and correction.metadata_bytes <= COMPACT_METADATA_MAX_BYTES
            ),
            "full_compute_seed_count": self.full_compute_seed_count,
            "reseed_required": self.full_compute_seed_count < 2,
            "finite": bool(cache and correction and cache.finite and correction.finite),
        }

    def _clear_replay_chain(self, step: int) -> None:
        self.events.append({"event": "replay_chain_invalidated", "step": step})
        self.cache = None
        self.correction = None
        self.full_compute_seed_count = 0

    def _matches(self, tensor: Any, step: int) -> tuple[bool, str]:
        state = self.state_for_target(step)
        if not state["predictor_provenance_valid"]:
            return False, "predictor_provenance_invalid"
        metadata = dict(self.ops.metadata(tensor))
        correction = self.correction
        if correction is None:
            return False, "predictor_missing"
        if metadata["shape_digest"] != correction.shape_digest:
            return False, "shape_mismatch"
        if metadata["dtype"] != correction.dtype or metadata["device"] != correction.device:
            return False, "dtype_or_device_mismatch"
        return True, "correction_valid"

    def _capture(self, output: Any, step: int, record: dict[str, Any]) -> None:
        if self.segment_snapshot is None:
            raise RuntimeError("segment snapshot missing at block 48")
        previous_cache = self.cache
        prior_correction = self.correction
        started = perf_counter_ns()
        current = self.ops.residualize(self.segment_snapshot, output)
        metadata = dict(self.ops.metadata(current))
        finite = bool(self.ops.finite(current))
        if (
            prior_correction is not None
            and previous_cache is not None
            and step in FROZEN_CEILING
            and prior_correction.second_source_execution_step == step - 1
        ):
            similarity_started = perf_counter_ns()
            raw = dict(self.ops.similarity(previous_cache.tensor, current))
            corrected = dict(self.ops.corrected_similarity(
                previous_cache.tensor, current, prior_correction.gain, prior_correction.bias
            ))
            self.similarity_ns.append(perf_counter_ns() - similarity_started)
            raw_cos = raw.get("residual_cosine_similarity")
            raw_l2 = raw.get("normalized_residual_l2")
            corr_cos = corrected.get("residual_cosine_similarity")
            corr_l2 = corrected.get("normalized_residual_l2")
            admitted = bool(
                corrected.get("finite")
                and isinstance(corr_cos, (float, int))
                and isinstance(corr_l2, (float, int))
                and isinstance(raw_cos, (float, int))
                and isinstance(raw_l2, (float, int))
                and corr_cos >= RESIDUAL_COSINE_MIN
                and corr_l2 <= NORMALIZED_RESIDUAL_L2_MAX
                and corr_cos >= raw_cos
                and corr_l2 <= raw_l2
                and prior_correction.metadata_bytes <= COMPACT_METADATA_MAX_BYTES
            )
            self.diagnostics.append({
                "target_step": step,
                "first_source_step": prior_correction.first_source_execution_step,
                "second_source_step": prior_correction.second_source_execution_step,
                "raw": raw,
                "corrected": corrected,
                "cosine_improvement": corr_cos - raw_cos if isinstance(corr_cos, (int, float)) and isinstance(raw_cos, (int, float)) else None,
                "normalized_l2_improvement": raw_l2 - corr_l2 if isinstance(corr_l2, (int, float)) and isinstance(raw_l2, (int, float)) else None,
                "admitted": admitted,
                "metadata_bytes": prior_correction.metadata_bytes,
            })
        next_correction: CorrectionState | None = None
        if previous_cache is not None and previous_cache.source_execution_step == step - 1:
            built = dict(self.ops.build_correction(previous_cache.tensor, current))
            self.channel_stats_ns.append(int(built["channel_stats_ns"]))
            self.gain_bias_ns.append(int(built["gain_bias_creation_ns"]))
            next_correction = CorrectionState(
                gain=built["gain"], bias=built["bias"],
                first_source_execution_step=step - 1,
                second_source_execution_step=step,
                workflow_revision_digest=self.workflow_revision_digest,
                model_revision_digest=self.model_revision_digest,
                settings_digest=self.settings_digest,
                shape_digest=str(metadata["shape_digest"]), dtype=str(metadata["dtype"]),
                device=str(metadata["device"]), finite=bool(built["finite"] and finite),
                channel_count=int(built["channel_count"]), metadata_bytes=int(built["metadata_bytes"]),
            )
            self.events.append({"event": "predictor_created", "target_step": step + 1, **next_correction.public(),
                                "gain_min": built["gain_min"], "gain_max": built["gain_max"],
                                "clipped_low_count": built["clipped_low_count"],
                                "clipped_high_count": built["clipped_high_count"]})
            self.full_compute_seed_count = min(2, self.full_compute_seed_count + 1)
        else:
            self.full_compute_seed_count = 1
        self.cache = ResidualCache(
            tensor=current, source_execution_step=step,
            workflow_revision_digest=self.workflow_revision_digest,
            model_revision_digest=self.model_revision_digest,
            settings_digest=self.settings_digest, segment_logical_id=SEGMENT_LOGICAL_ID,
            block_start=SEGMENT_START, block_end=SEGMENT_END,
            shape_digest=str(metadata["shape_digest"]), dtype=str(metadata["dtype"]),
            device=str(metadata["device"]), finite=finite,
            generation_count=self.residual_capture_count + 1, reuse_count=0,
            tensor_bytes=int(metadata["bytes"]),
        )
        self.correction = next_correction
        self.segment_snapshot = None
        self.residual_capture_count += 1
        record["residual_captured"] = True
        self.capture_ns.append(perf_counter_ns() - started)
        self.max_additional_gpu_bytes = max(
            self.max_additional_gpu_bytes,
            int(metadata["bytes"]) * self.max_concurrent_residual_sized_buffers,
        )
        self.memory_samples.append(dict(self.ops.cuda_memory(current)))

    def block_wrapper(self, block_index: int) -> Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
        if not 0 <= block_index < BLOCK_COUNT:
            raise ValueError("block index outside fixed H3 range")

        def wrapper(args: Mapping[str, Any], extra_options: Mapping[str, Any]) -> Mapping[str, Any]:
            if block_index == 0:
                if self.expected_block_index != 0:
                    self.mapping_error_count += 1
                self.current_execution_step = self.model_forward_count
                self.model_forward_count += 1
                self.replay_active_step = None
            if block_index != self.expected_block_index:
                self.mapping_error_count += 1
            self.expected_block_index = (block_index + 1) % BLOCK_COUNT
            step = self.current_execution_step
            record = self._step(step)
            plan = self.plan_bridge.plans.get(step)
            if plan:
                record["decision"], record["reason"] = plan["decision"], plan["reason"]
            if block_index == SEGMENT_START:
                replay = bool(
                    self.mode == SELECTIVE and plan
                    and int(plan["decision_code"]) == REUSE_CORRECTED_TRANSFORM
                )
                valid, reason = self._matches(args["img"], step) if replay else (False, "full_compute")
                if replay and valid:
                    assert self.cache is not None and self.correction is not None
                    started = perf_counter_ns()
                    try:
                        output = self.ops.apply_corrected(
                            args["img"], self.cache.tensor, self.correction.gain, self.correction.bias
                        )
                    except BaseException:
                        self.wrapper_failure_count += 1
                        self._clear_replay_chain(step)
                        raise
                    self.correction_application_ns.append(perf_counter_ns() - started)
                    self.replay_active_step = step
                    self.replay_count += 1
                    record.update({"decision": "REUSE_CORRECTED_TRANSFORM", "reason": reason,
                                   "correction_applied": True, "replayed_block_calls": 1})
                    self.replayed_block_call_count += 1
                    self._clear_replay_chain(step)
                    return {"img": output}
                metadata = dict(self.ops.metadata(args["img"]))
                self.max_concurrent_residual_sized_buffers = max(
                    self.max_concurrent_residual_sized_buffers, 1 + int(self.cache is not None)
                )
                self.max_additional_gpu_bytes = max(
                    self.max_additional_gpu_bytes,
                    int(metadata["bytes"]) * (1 + int(self.cache is not None)),
                )
                self.segment_snapshot = self.ops.clone(args["img"])
                record["decision"] = "FULL_COMPUTE"
                if replay and not valid:
                    record["reason"] = reason
            if self.replay_active_step == step and SEGMENT_START < block_index <= SEGMENT_END:
                self.replayed_block_call_count += 1
                record["replayed_block_calls"] += 1
                return {"img": args["img"]}
            started = perf_counter_ns()
            try:
                result = extra_options["original_block"](args)
            except BaseException:
                self.wrapper_failure_count += 1
                self.segment_snapshot = None
                self.cache = None
                self.correction = None
                raise
            finally:
                self.original_ns.append(perf_counter_ns() - started)
            self.original_block_call_count += 1
            record["original_block_calls"] += 1
            if block_index == SEGMENT_END:
                self._capture(result["img"], step, record)
            return result

        return wrapper

    def install_on_guider_clone(self, guider: Any) -> Any:
        patched_guider = copy.copy(guider)
        patched_patcher = guider.model_patcher.clone()
        for index in range(BLOCK_COUNT):
            patched_patcher.set_model_patch_replace(
                self.block_wrapper(index), "dit", "double_block", index
            )
        patched_guider.model_patcher = patched_patcher
        patched_guider.model_options = patched_patcher.model_options
        return patched_guider

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "c3-r3.compact-residual-correction.1",
            "mode": self.mode,
            "mechanism": MECHANISM,
            "segment": {"logical_id": SEGMENT_LOGICAL_ID, "block_start": SEGMENT_START,
                        "block_end": SEGMENT_END, "block_count": len(SEGMENT_BLOCKS)},
            "predictor": {"statistic_type": STATISTIC_TYPE, "epsilon": STATISTIC_EPSILON,
                          "gain_min": GAIN_MIN, "gain_max": GAIN_MAX,
                          "metadata_max_bytes": COMPACT_METADATA_MAX_BYTES,
                          "chunk_rows": STATISTIC_CHUNK_ROWS},
            "model_forward_count": self.model_forward_count,
            "original_block_call_count": self.original_block_call_count,
            "replayed_block_call_count": self.replayed_block_call_count,
            "actual_replay_steps": self.replay_count,
            "residual_capture_count": self.residual_capture_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "persistent_residual_cache_count": int(self.cache is not None),
            "persistent_predicted_residual_count": 0,
            "per_block_cache_count": 0,
            "max_concurrent_residual_sized_buffers": self.max_concurrent_residual_sized_buffers,
            "max_additional_gpu_bytes": self.max_additional_gpu_bytes,
            "current_correction": self.correction.public() if self.correction else None,
            "diagnostics": self.diagnostics,
            "events": self.events,
            "per_step": [self.per_step[key] for key in sorted(self.per_step)],
            "memory_samples": self.memory_samples,
            "timing": {"original_block": _timing(self.original_ns), "residual_capture": _timing(self.capture_ns),
                       "channel_stats": _timing(self.channel_stats_ns), "gain_bias_creation": _timing(self.gain_bias_ns),
                       "similarity": _timing(self.similarity_ns),
                       "correction_application": _timing(self.correction_application_ns)},
            "tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "full_size_fp32_materialization_count": 0,
        }


def validate_calibrated_targets(targets: tuple[int, ...]) -> None:
    if targets != tuple(sorted(set(targets))):
        raise ValueError("calibrated targets must be unique and ordered")
    if any(target not in FROZEN_CEILING for target in targets):
        raise ValueError("calibrated targets must stay inside the frozen ceiling")
    if any(right - left < MIN_TARGET_SPACING for left, right in zip(targets, targets[1:])):
        raise ValueError("calibrated targets require two Full Compute re-seed steps")


def select_calibrated_targets(diagnostics: list[Mapping[str, Any]]) -> tuple[int, ...]:
    admitted = sorted(
        int(item["target_step"])
        for item in diagnostics
        if item.get("admitted") is True and int(item["target_step"]) in FROZEN_CEILING
    )
    selected: list[int] = []
    for target in admitted:
        if not selected or target - selected[-1] >= MIN_TARGET_SPACING:
            selected.append(target)
    result = tuple(selected)
    validate_calibrated_targets(result)
    return result


def correction_settings_digest(*, actual_replay_enabled: bool, calibrated_targets: tuple[int, ...]) -> str:
    validate_calibrated_targets(calibrated_targets)
    payload = {
        "mechanism": MECHANISM,
        "mode": SELECTIVE if actual_replay_enabled else CONTROL,
        "actual_corrected_replay_enabled": actual_replay_enabled,
        "calibrated_targets": list(calibrated_targets),
        "candidate_ceiling": list(FROZEN_CEILING),
        "anchors": list(FULL_COMPUTE_ANCHORS),
        "segment": [SEGMENT_START, SEGMENT_END],
        "statistic_type": STATISTIC_TYPE,
        "epsilon": STATISTIC_EPSILON,
        "gain_clip": [GAIN_MIN, GAIN_MAX],
        "metadata_max_bytes": COMPACT_METADATA_MAX_BYTES,
        "chunk_rows": STATISTIC_CHUNK_ROWS,
        "residual_cosine_min": RESIDUAL_COSINE_MIN,
        "normalized_residual_l2_max": NORMALIZED_RESIDUAL_L2_MAX,
        "raw_non_regression_required": True,
        "minimum_target_spacing": MIN_TARGET_SPACING,
        "total_steps": TOTAL_STEPS,
        "block_count": BLOCK_COUNT,
        "persistent_full_residual_max": 1,
        "persistent_predicted_residual_max": 0,
        "max_concurrent_residual_sized_buffers": 2,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
