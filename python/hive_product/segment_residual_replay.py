"""C3-R2 generic reuse policy and H3 segment-residual model adapter.

Core owns metadata-only reuse semantics.  The H3 adapter owns packed activation
tensors, blocks 12..48, GPU cache lifetime, and the patches_replace wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Protocol
import copy
import hashlib
import math

from .compound_eye_shadow import AsyncCompoundEyeShadowPipeline


ABI_VERSION = 1
TOTAL_STEPS = 20
BLOCK_COUNT = 50
SEGMENT_START = 12
SEGMENT_END = 48
SEGMENT_BLOCKS = tuple(range(SEGMENT_START, SEGMENT_END + 1))
SEGMENT_LOGICAL_ID = "h3.dit.segment.12-48"
SEGMENT_LOGICAL_DIGEST = hashlib.sha256(SEGMENT_LOGICAL_ID.encode()).hexdigest()
FROZEN_CEILING = (5, 6, 8, 13, 16, 17)
FULL_COMPUTE_ANCHORS = (0, 1, 18, 19)
MAX_REUSE_STEPS = 4
MAX_THEORETICAL_REDUCTION = MAX_REUSE_STEPS * len(SEGMENT_BLOCKS) / (TOTAL_STEPS * BLOCK_COUNT)
RESIDUAL_COSINE_MIN = 0.99
NORMALIZED_RESIDUAL_L2_MAX = 0.20
CONTROL = "CONTROL_RESIDUAL_CAPTURE"
SELECTIVE = "SELECTIVE_RESIDUAL_REPLAY"
FULL_COMPUTE = 0
REUSE_TRANSFORM = 1
ESCALATE_FULL_COMPUTE = 2
DECISION_LABELS = {
    FULL_COMPUTE: "FULL_COMPUTE",
    REUSE_TRANSFORM: "REUSE_TRANSFORM",
    ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE",
}
REASON_LABELS = {
    0: "reuse_admitted",
    1: "abi_mismatch",
    2: "struct_size_mismatch",
    3: "step_range_invalid",
    4: "digest_missing",
    5: "metadata_invalid",
    6: "not_calibrated",
    7: "cache_missing",
    8: "cache_age_invalid",
    9: "provenance_invalid",
    10: "similarity_rejected",
    11: "source_invalid",
    12: "prediction_invalid",
    13: "stable_count_low",
    14: "active_present",
    15: "global_invalidation",
    16: "overlap_conflict",
    17: "fatal_flag",
    18: "consecutive_reuse",
    19: "fallback_unsupported",
    20: "unsupported_metadata",
    21: "rust_panic",
}


def _digest(value: str, name: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a hexadecimal SHA-256 digest") from error
    if len(raw) != 32:
        raise ValueError(f"{name} must contain exactly 32 bytes")
    return raw


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _timing(values: list[int]) -> dict[str, int | None]:
    return {
        "p50_ns": _percentile(values, 0.50),
        "p95_ns": _percentile(values, 0.95),
        "max_ns": max(values) if values else None,
        "sum_ns": sum(values),
        "sample_count": len(values),
    }


@dataclass(frozen=True)
class ReusePlanContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str
    model_revision_digest: str


class CacheStateProvider(Protocol):
    def __call__(self, target_step: int) -> Mapping[str, Any]: ...


class ReusePlanBridge:
    """One fixed-width Rust reuse decision per consumed C2 callback event."""

    def __init__(
        self,
        context: ReusePlanContext,
        calibrated_targets: tuple[int, ...],
        extension: Any | None = None,
    ) -> None:
        if any(step not in FROZEN_CEILING for step in calibrated_targets):
            raise ValueError("calibrated targets must stay inside the frozen ceiling")
        if any(right == left + 1 for left, right in zip(calibrated_targets, calibrated_targets[1:])):
            raise ValueError("calibrated targets cannot contain consecutive reuse steps")
        if len(set(calibrated_targets)) != len(calibrated_targets):
            raise ValueError("calibrated targets must be unique")
        if tuple(sorted(calibrated_targets)) != calibrated_targets:
            raise ValueError("calibrated targets must be in execution order")
        self.run_digest = _digest(context.run_digest, "run_digest")
        self.workflow_revision_digest = _digest(
            context.workflow_revision_digest, "workflow_revision_digest"
        )
        self.settings_digest = _digest(context.settings_digest, "settings_digest")
        self.model_revision_digest = _digest(context.model_revision_digest, "model_revision_digest")
        self.segment_logical_digest = bytes.fromhex(SEGMENT_LOGICAL_DIGEST)
        self.calibrated_targets = tuple(sorted(calibrated_targets))
        self.cache_state_provider: CacheStateProvider | None = None
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
                self.contract = dict(self.extension.reuse_plan_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.rust_call_count = 0
        self.fallback_count = 0
        self.events: list[dict[str, Any]] = []
        self.plans: dict[int, dict[str, Any]] = {}
        self.boundary_ns: list[int] = []
        self.rust_policy_ns: list[int] = []

    def set_cache_state_provider(self, provider: CacheStateProvider) -> None:
        self.cache_state_provider = provider

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
        stable_mask, active_mask, uncertain_mask = self._eye_masks(event)
        state = dict(self.cache_state_provider(target)) if self.cache_state_provider else {}
        source_step = int(state.get("source_execution_step", max(0, target - 1)))
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
            "source_execution_step": source_step,
            "total_steps": int(event.get("total_steps", 0)),
            "cache_age": int(state.get("cache_age", 0)),
            "cache_available": bool(state.get("cache_available", False)),
            "cache_provenance_valid": bool(state.get("cache_provenance_valid", False)),
            "residual_similarity_admitted": calibrated,
            "calibrated_target": calibrated,
            "prior_step_reused": bool(state.get("prior_step_reused", False)),
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
                response = dict(self.extension.evaluate_reuse_plan(**observation))
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
                elif int(response["source_execution_step"]) != source_step:
                    failure_reason = "source_step_mismatch"
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
            "source_step": source_step,
            "calibrated_target": calibrated,
            "decision": DECISION_LABELS[decision],
            "decision_code": decision,
            "reason_code": reason_code,
            "reason": failure_reason or REASON_LABELS.get(reason_code, "unknown_reason"),
            "fallback_used": failure_reason is not None,
            "cache_age": observation["cache_age"],
            "cache_available": observation["cache_available"],
            "cache_provenance_valid": observation["cache_provenance_valid"],
            "residual_similarity_admitted": observation["residual_similarity_admitted"],
            "stable_mask": stable_mask,
            "stable_count": stable_mask.bit_count(),
            "active_mask": active_mask,
            "active_count": active_mask.bit_count(),
            "uncertain_mask": uncertain_mask,
            "uncertain_count": uncertain_mask.bit_count(),
            "global_invalidation": observation["global_invalidation"],
            "overlap_conflict_mask": observation["overlap_conflict_mask"],
            "source_valid": source_valid,
            "prediction_valid": prediction_valid,
            "finite": observation["finite"],
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": rust_policy_ns,
            "decision_digest": decision_digest,
            "tensor_bytes_to_rust": 0,
        }
        self.plans[target] = plan
        self.events.append(plan)
        return plan

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "c3-r2.reuse-plan.1",
            "abi_version": ABI_VERSION,
            "contract": self.contract,
            "calibrated_targets": list(self.calibrated_targets),
            "segment_logical_id": SEGMENT_LOGICAL_ID,
            "rust_call_count": self.rust_call_count,
            "fallback_count": self.fallback_count,
            "boundary_roundtrip": _timing(self.boundary_ns),
            "rust_policy": _timing(self.rust_policy_ns),
            "tensor_bytes_to_rust": 0,
            "events": self.events,
        }


class ResidualReplayShadowPipeline(AsyncCompoundEyeShadowPipeline):
    def __init__(self, bridge: Any, plan_bridge: ReusePlanBridge, **kwargs: Any) -> None:
        super().__init__(bridge, **kwargs)
        self.plan_bridge = plan_bridge

    def _consume_ready(self, slot: Any, consumed_callback: int) -> dict[str, Any]:
        event = super()._consume_ready(slot, consumed_callback)
        self.plan_bridge.evaluate_event(event)
        return event


class TensorOps(Protocol):
    def clone(self, tensor: Any) -> Any: ...
    def residualize(self, snapshot: Any, output: Any) -> Any: ...
    def apply(self, current: Any, residual: Any) -> Any: ...
    def metadata(self, tensor: Any) -> Mapping[str, Any]: ...
    def finite(self, tensor: Any) -> bool: ...
    def similarity(self, previous: Any, current: Any) -> Mapping[str, Any]: ...
    def cuda_memory(self, tensor: Any) -> Mapping[str, Any]: ...


class TorchTensorOps:
    """GPU-only tensor operations; only scalar diagnostics cross to host."""

    def clone(self, tensor: Any) -> Any:
        return tensor.clone()

    def residualize(self, snapshot: Any, output: Any) -> Any:
        return snapshot.neg_().add_(output)

    def apply(self, current: Any, residual: Any) -> Any:
        return current.add_(residual)

    def metadata(self, tensor: Any) -> Mapping[str, Any]:
        shape = tuple(int(value) for value in tensor.shape)
        element_size = int(tensor.element_size())
        return {
            "shape": list(shape),
            "shape_digest": hashlib.sha256(repr(shape).encode()).hexdigest(),
            "dtype": str(tensor.dtype),
            "device": str(tensor.device),
            "device_type": str(tensor.device.type),
            "numel": int(tensor.numel()),
            "element_size": element_size,
            "bytes": int(tensor.numel()) * element_size,
        }

    def finite(self, tensor: Any) -> bool:
        import torch

        norm = float(torch.linalg.vector_norm(tensor.reshape(-1)).item())
        return math.isfinite(norm)

    def similarity(self, previous: Any, current: Any) -> Mapping[str, Any]:
        import torch

        previous_flat = previous.reshape(-1)
        current_flat = current.reshape(-1)
        previous_norm_t = torch.linalg.vector_norm(previous_flat)
        current_norm_t = torch.linalg.vector_norm(current_flat)
        dot_t = torch.dot(previous_flat, current_flat)
        previous_norm = float(previous_norm_t.item())
        current_norm = float(current_norm_t.item())
        dot = float(dot_t.item())
        finite = all(math.isfinite(value) for value in (previous_norm, current_norm, dot))
        denominator = previous_norm * current_norm
        cosine = dot / denominator if finite and denominator > 0 else None
        difference_squared = max(0.0, current_norm**2 + previous_norm**2 - 2.0 * dot)
        normalized_l2 = (
            math.sqrt(difference_squared) / previous_norm if finite and previous_norm > 0 else None
        )
        return {
            "normalized_residual_l2": normalized_l2,
            "residual_cosine_similarity": cosine,
            "finite": finite,
            "method": (
                "GPU scalar reductions: ||current-previous||_2 / ||previous||_2; "
                "difference norm derived from ||a||^2+||b||^2-2<a,b>; cosine=<a,b>/(||a||||b||)"
            ),
            "full_tensor_host_copy_bytes": 0,
        }

    def cuda_memory(self, tensor: Any) -> Mapping[str, Any]:
        try:
            import torch

            device = tensor.device
            properties = torch.cuda.get_device_properties(device)
            return {
                "memory_allocated_bytes": int(torch.cuda.memory_allocated(device)),
                "memory_reserved_bytes": int(torch.cuda.memory_reserved(device)),
                "max_memory_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
                "max_memory_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
                "device_total_memory_bytes": int(properties.total_memory),
            }
        except Exception as error:
            return {"support_status": "unavailable", "reason": type(error).__name__}


@dataclass
class ResidualCache:
    tensor: Any
    source_execution_step: int
    workflow_revision_digest: str
    model_revision_digest: str
    settings_digest: str
    segment_logical_id: str
    block_start: int
    block_end: int
    shape_digest: str
    dtype: str
    device: str
    finite: bool
    generation_count: int
    reuse_count: int
    tensor_bytes: int

    def public(self) -> dict[str, Any]:
        return {key: value for key, value in vars(self).items() if key != "tensor"}


class H3SegmentResidualController:
    """H3 adapter for one-shot block-12..48 transform residual replay."""

    def __init__(
        self,
        mode: str,
        plan_bridge: ReusePlanBridge,
        *,
        workflow_revision_digest: str,
        model_revision_digest: str,
        settings_digest: str,
        tensor_ops: TensorOps | None = None,
    ) -> None:
        if mode not in {CONTROL, SELECTIVE}:
            raise ValueError("mode must be CONTROL_RESIDUAL_CAPTURE or SELECTIVE_RESIDUAL_REPLAY")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.workflow_revision_digest = workflow_revision_digest
        self.model_revision_digest = model_revision_digest
        self.settings_digest = settings_digest
        self.ops = tensor_ops or TorchTensorOps()
        self.cache: ResidualCache | None = None
        self.segment_snapshot: Any | None = None
        self.reuse_active_step: int | None = None
        self.previous_step_reused = False
        self.model_forward_count = 0
        self.original_block_call_count = 0
        self.replayed_block_call_count = 0
        self.residual_application_count = 0
        self.residual_capture_count = 0
        self.cache_generation_count = 0
        self.cache_invalidation_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.expected_block_index = 0
        self.current_execution_step = -1
        self.max_concurrent_residual_sized_buffers = 0
        self.max_additional_gpu_bytes = 0
        self.original_ns: list[int] = []
        self.replay_ns: list[int] = []
        self.capture_ns: list[int] = []
        self.similarity_ns: list[int] = []
        self.similarity_diagnostics: list[dict[str, Any]] = []
        self.cache_events: list[dict[str, Any]] = []
        self.memory_samples: list[dict[str, Any]] = []
        self.per_step: dict[int, dict[str, Any]] = {}
        self.plan_bridge.set_cache_state_provider(self.cache_state_for_target)

    def _step_record(self, step: int) -> dict[str, Any]:
        return self.per_step.setdefault(
            step,
            {
                "execution_step": step,
                "original_block_calls": 0,
                "replayed_block_calls": 0,
                "residual_applied": False,
                "residual_captured": False,
                "decision": "FULL_COMPUTE",
                "reason": "plan_unavailable",
            },
        )

    def _provenance_valid(self, cache: ResidualCache) -> bool:
        return (
            cache.workflow_revision_digest == self.workflow_revision_digest
            and cache.model_revision_digest == self.model_revision_digest
            and cache.settings_digest == self.settings_digest
            and cache.segment_logical_id == SEGMENT_LOGICAL_ID
            and cache.block_start == SEGMENT_START
            and cache.block_end == SEGMENT_END
            and cache.finite
            and cache.reuse_count == 0
        )

    def cache_state_for_target(self, target_step: int) -> Mapping[str, Any]:
        cache = self.cache
        prior_step_reused = self.reuse_active_step == int(target_step) - 1
        if cache is None:
            return {
                "source_execution_step": max(0, int(target_step) - 1),
                "cache_age": 0,
                "cache_available": False,
                "cache_provenance_valid": False,
                "finite": False,
                "prior_step_reused": prior_step_reused,
            }
        return {
            "source_execution_step": cache.source_execution_step,
            "cache_age": int(target_step) - cache.source_execution_step,
            "cache_available": True,
            "cache_provenance_valid": self._provenance_valid(cache),
            "finite": cache.finite,
            "prior_step_reused": prior_step_reused,
        }

    def _invalidate_cache(self, reason: str, step: int) -> None:
        if self.cache is not None:
            self.cache_invalidation_count += 1
            self.cache_events.append({"event": "invalidated", "step": step, "reason": reason})
        self.cache = None

    def _cache_matches_tensor(self, cache: ResidualCache, tensor: Any, step: int) -> tuple[bool, str]:
        metadata = dict(self.ops.metadata(tensor))
        if step - cache.source_execution_step != 1:
            return False, "cache_age_invalid"
        if not self._provenance_valid(cache):
            return False, "cache_provenance_invalid"
        if metadata["shape_digest"] != cache.shape_digest:
            return False, "cache_shape_mismatch"
        if metadata["dtype"] != cache.dtype:
            return False, "cache_dtype_mismatch"
        if metadata["device"] != cache.device:
            return False, "cache_device_mismatch"
        return True, "cache_valid"

    def _should_reuse(self, step: int, tensor: Any) -> tuple[bool, str]:
        if self.mode != SELECTIVE:
            return False, "control_never_reuses"
        plan = self.plan_bridge.plans.get(step)
        if plan is None or int(plan["decision_code"]) != REUSE_TRANSFORM:
            return False, str(plan.get("reason", "plan_unavailable")) if plan else "plan_unavailable"
        if self.cache is None:
            return False, "cache_missing_at_execution"
        return self._cache_matches_tensor(self.cache, tensor, step)

    def _capture_residual(self, output: Any, step: int, record: dict[str, Any]) -> None:
        if self.segment_snapshot is None:
            raise RuntimeError("segment snapshot missing at block 48")
        previous = self.cache
        started = perf_counter_ns()
        current = self.ops.residualize(self.segment_snapshot, output)
        metadata = dict(self.ops.metadata(current))
        finite = bool(self.ops.finite(current))
        diagnostic: dict[str, Any] | None = None
        if previous is not None and previous.source_execution_step == step - 1 and step in FROZEN_CEILING:
            similarity_started = perf_counter_ns()
            diagnostic = dict(self.ops.similarity(previous.tensor, current))
            self.similarity_ns.append(perf_counter_ns() - similarity_started)
            finite = bool(diagnostic["finite"])
            cosine = diagnostic.get("residual_cosine_similarity")
            normalized_l2 = diagnostic.get("normalized_residual_l2")
            admitted = (
                finite
                and isinstance(cosine, (float, int))
                and isinstance(normalized_l2, (float, int))
                and float(cosine) >= RESIDUAL_COSINE_MIN
                and float(normalized_l2) <= NORMALIZED_RESIDUAL_L2_MAX
            )
            diagnostic.update(
                {
                    "target_step": step,
                    "source_step": step - 1,
                    "cache_age": 1,
                    "admitted": admitted,
                    "reason": "fixed_similarity_gate_passed" if admitted else "fixed_similarity_gate_failed",
                    "cosine_min": RESIDUAL_COSINE_MIN,
                    "normalized_l2_max": NORMALIZED_RESIDUAL_L2_MAX,
                }
            )
            self.similarity_diagnostics.append(diagnostic)
        self.cache_generation_count += 1
        self.cache = ResidualCache(
            tensor=current,
            source_execution_step=step,
            workflow_revision_digest=self.workflow_revision_digest,
            model_revision_digest=self.model_revision_digest,
            settings_digest=self.settings_digest,
            segment_logical_id=SEGMENT_LOGICAL_ID,
            block_start=SEGMENT_START,
            block_end=SEGMENT_END,
            shape_digest=str(metadata["shape_digest"]),
            dtype=str(metadata["dtype"]),
            device=str(metadata["device"]),
            finite=finite,
            generation_count=self.cache_generation_count,
            reuse_count=0,
            tensor_bytes=int(metadata["bytes"]),
        )
        self.segment_snapshot = None
        self.residual_capture_count += 1
        record["residual_captured"] = True
        self.capture_ns.append(perf_counter_ns() - started)
        self.max_additional_gpu_bytes = max(
            self.max_additional_gpu_bytes,
            int(metadata["bytes"]) * self.max_concurrent_residual_sized_buffers,
        )
        self.cache_events.append({"event": "captured", **self.cache.public()})
        self.memory_samples.append(dict(self.ops.cuda_memory(current)))

    def block_wrapper(
        self, block_index: int
    ) -> Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
        if block_index < 0 or block_index >= BLOCK_COUNT:
            raise ValueError("block index outside the fixed H3 range")

        def wrapper(args: Mapping[str, Any], extra_options: Mapping[str, Any]) -> Mapping[str, Any]:
            if block_index == 0:
                if self.expected_block_index != 0:
                    self.mapping_error_count += 1
                self.current_execution_step = self.model_forward_count
                self.model_forward_count += 1
                self.previous_step_reused = self.reuse_active_step == self.current_execution_step - 1
                self.reuse_active_step = None
            if block_index != self.expected_block_index:
                self.mapping_error_count += 1
            self.expected_block_index = (block_index + 1) % BLOCK_COUNT
            step = self.current_execution_step
            record = self._step_record(step)
            plan = self.plan_bridge.plans.get(step)
            if plan is not None:
                record["decision"] = plan["decision"]
                record["reason"] = plan["reason"]
            if block_index == SEGMENT_START:
                invalid_cache_reason: str | None = None
                if self.cache is not None:
                    valid, validation_reason = self._cache_matches_tensor(
                        self.cache, args["img"], step
                    )
                    if not valid:
                        invalid_cache_reason = validation_reason
                        self._invalidate_cache(invalid_cache_reason, step)
                reuse, reason = self._should_reuse(step, args["img"])
                if invalid_cache_reason is not None:
                    reason = invalid_cache_reason
                if reuse:
                    cache = self.cache
                    if cache is None:
                        raise RuntimeError("admitted residual cache disappeared")
                    started = perf_counter_ns()
                    try:
                        output = self.ops.apply(args["img"], cache.tensor)
                    except BaseException:
                        self.wrapper_failure_count += 1
                        self._invalidate_cache("residual_application_failure", step)
                        raise
                    cache.reuse_count += 1
                    self.cache_events.append({"event": "consumed", **cache.public(), "target_step": step})
                    self.cache = None
                    self.reuse_active_step = step
                    self.residual_application_count += 1
                    self.replay_ns.append(perf_counter_ns() - started)
                    record["decision"] = "REUSE_TRANSFORM"
                    record["reason"] = reason
                    record["residual_applied"] = True
                    record["replayed_block_calls"] += 1
                    self.replayed_block_call_count += 1
                    return {"img": output}
                metadata = dict(self.ops.metadata(args["img"]))
                self.max_concurrent_residual_sized_buffers = max(
                    self.max_concurrent_residual_sized_buffers,
                    1 + int(self.cache is not None),
                )
                self.max_additional_gpu_bytes = max(
                    self.max_additional_gpu_bytes,
                    int(metadata["bytes"]) * (1 + int(self.cache is not None)),
                )
                self.segment_snapshot = self.ops.clone(args["img"])
                record["decision"] = "FULL_COMPUTE"
                record["reason"] = reason
            if self.reuse_active_step == step and SEGMENT_START < block_index <= SEGMENT_END:
                self.replayed_block_call_count += 1
                record["replayed_block_calls"] += 1
                return {"img": args["img"]}
            started = perf_counter_ns()
            try:
                result = extra_options["original_block"](args)
            except BaseException:
                self.wrapper_failure_count += 1
                self.segment_snapshot = None
                self._invalidate_cache("wrapper_failure", step)
                raise
            finally:
                self.original_ns.append(perf_counter_ns() - started)
            self.original_block_call_count += 1
            record["original_block_calls"] += 1
            if block_index == SEGMENT_END:
                self._capture_residual(result["img"], step, record)
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
            "schema_version": "c3-r2.segment-residual-replay.1",
            "mode": self.mode,
            "mechanism": "SEGMENT_RESIDUAL_REPLAY_V1",
            "segment": {
                "logical_id": SEGMENT_LOGICAL_ID,
                "block_start": SEGMENT_START,
                "block_end": SEGMENT_END,
                "block_count": len(SEGMENT_BLOCKS),
            },
            "model_forward_count": self.model_forward_count,
            "original_block_call_count": self.original_block_call_count,
            "replayed_block_call_count": self.replayed_block_call_count,
            "residual_application_count": self.residual_application_count,
            "residual_capture_count": self.residual_capture_count,
            "cache_generation_count": self.cache_generation_count,
            "cache_invalidation_count": self.cache_invalidation_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "persistent_residual_cache_count": int(self.cache is not None),
            "transient_segment_snapshot_count": int(self.segment_snapshot is not None),
            "max_concurrent_residual_sized_buffers": self.max_concurrent_residual_sized_buffers,
            "max_additional_gpu_bytes": self.max_additional_gpu_bytes,
            "current_cache": self.cache.public() if self.cache is not None else None,
            "similarity_gate": {
                "residual_cosine_min": RESIDUAL_COSINE_MIN,
                "normalized_residual_l2_max": NORMALIZED_RESIDUAL_L2_MAX,
                "cache_age_required": 1,
            },
            "similarity_diagnostics": self.similarity_diagnostics,
            "cache_events": self.cache_events,
            "memory_samples": self.memory_samples,
            "tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "per_block_cache_count": 0,
            "rust_calls_per_block": 0,
            "original_block_wrapper": _timing(self.original_ns),
            "residual_replay": _timing(self.replay_ns),
            "residual_capture": _timing(self.capture_ns),
            "residual_similarity": _timing(self.similarity_ns),
            "per_step": [self.per_step[key] for key in sorted(self.per_step)],
        }


def select_maximum_safe_targets(diagnostics: list[Mapping[str, Any]]) -> tuple[int, ...]:
    admitted = {
        int(item["target_step"])
        for item in diagnostics
        if item.get("admitted") is True and int(item.get("target_step", -1)) in FROZEN_CEILING
    }
    selected: list[int] = []
    for target in FROZEN_CEILING:
        if target in admitted and (not selected or target != selected[-1] + 1):
            selected.append(target)
    return tuple(selected[:MAX_REUSE_STEPS])


def residual_settings_digest(*, actual_residual_replay_enabled: bool, calibrated_targets: tuple[int, ...]) -> str:
    payload = (
        "c3-r2|mechanism=SEGMENT_RESIDUAL_REPLAY_V1|ceiling=5,6,8,13,16,17|"
        "anchors=0,1,18,19|segment=12-48|cache_age=1|cosine_min=0.99|normalized_l2_max=0.20|"
        f"actual_residual_replay_enabled={str(actual_residual_replay_enabled).lower()}|"
        f"calibrated_targets={','.join(str(value) for value in calibrated_targets)}|"
        "steps=20|seed=101|width=864|height=480|frames=124|fps=24|"
        "scheduler=simple|sampler=res_multistep|denoise=1|sage=0"
    )
    return hashlib.sha256(payload.encode()).hexdigest()
