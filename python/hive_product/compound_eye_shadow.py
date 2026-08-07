"""C2 Compound Eye shadow-only policy for the Local H3 sampler callback.

The module observes only ``x0`` (ComfyUI's denoised callback state), builds one
fixed 4x4x3 sketch, and sends 48 fixed-point integers to Rust.  Directives are
counterfactual: the wrapped sampler always receives its original arguments and
always performs full compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, perf_counter_ns, sleep
from typing import Any, Callable
import ctypes
import hashlib
import math


ABI_VERSION = 1
TOPOLOGY_ID = 1
TOPOLOGY_NAME = "overlap_2x2"
SKETCH_SOURCE_ID = 1
SKETCH_SOURCE_NAME = "x0"
H3_SIGNAL_ADAPTER = "h3_nested_video_v1"
H3_NESTED_TYPE = "comfy.nested_tensor.NestedTensor"
H3_VIDEO_SHAPE = (1, 24, 37, 30, 54)
H3_AUDIO_SHAPE = (1, 32, 2, 207)
H3_CALLBACK_VIDEO_DTYPE = "torch.float32"
H3_CALLBACK_DEVICE_TYPE = "cuda"
ASYNC_RING_SIZE = 3
ASYNC_DRAIN_TIMEOUT_SECONDS = 15.0
PREDICTION_HORIZON_STEPS = 2
SKETCH_GRID = (4, 4)
SKETCH_METRICS = ("mean", "mean_abs", "rms")
SKETCH_VALUE_COUNT = 48
EYE_COUNT = 5
QUANTIZATION_SCALE = 4096
STABLE_VALIDATION_LIMIT_PPM = 30_000
FULL_COMPUTE = 0
ESCALATE_FULL_COMPUTE = 1
EYE_STABLE = 0
EYE_ACTIVE = 1
EYE_UNCERTAIN = 2
EYE_LABELS = {EYE_STABLE: "STABLE", EYE_ACTIVE: "ACTIVE", EYE_UNCERTAIN: "UNCERTAIN"}
DECISION_LABELS = {FULL_COMPUTE: "FULL_COMPUTE", ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE"}


class ShadowSignalNotAdmitted(RuntimeError):
    """Raised when the callback does not provide a safe fixed-size x0 signal."""


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
class ShadowContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str


@dataclass(frozen=True)
class SketchResult:
    values_q: tuple[int, ...]
    source_shape: tuple[int, ...]
    source_dtype: str
    source_device_type: str
    reduction_enqueue_ns: int
    gpu_to_host_ns: int
    host_quantization_ns: int
    host_transfer_count: int = 1
    host_transfer_bytes: int = SKETCH_VALUE_COUNT * 4
    persistent_gpu_bytes: int = 0
    signal_adapter: str = "direct_tensor"
    container_type: str = "torch.Tensor"
    container_tensor_count: int = 1
    cuda_sketch_ns: int | None = None
    sketch_observed_step: int | None = None
    sketch_consumed_callback: int | None = None
    event_ready: bool = True
    ready_lag_callbacks: int | None = None
    deadline_missed: bool = False


@dataclass(frozen=True)
class AdmittedH3Signal:
    video: Any
    source_shape: tuple[int, ...]
    source_dtype: str
    source_device_type: str
    signal_adapter: str
    container_type: str
    container_tensor_count: int


def admit_h3_x0_video(x0: Any, torch: Any) -> AdmittedH3Signal:
    """Strictly admit the source-proven FP32 CUDA H3 video slot before CUDA or Rust work."""

    x0_type = type(x0)
    container_type = f"{x0_type.__module__}.{x0_type.__qualname__}"
    if container_type != H3_NESTED_TYPE or not bool(getattr(x0, "is_nested", False)):
        raise ShadowSignalNotAdmitted("x0_not_supported_h3_nested_tensor")
    tensors = getattr(x0, "tensors", None)
    if not isinstance(tensors, list) or len(tensors) != 2:
        raise ShadowSignalNotAdmitted("h3_nested_tensor_contract_mismatch")
    video, audio = tensors
    if not isinstance(video, torch.Tensor) or not isinstance(audio, torch.Tensor):
        raise ShadowSignalNotAdmitted("h3_nested_member_not_tensor")
    if tuple(int(value) for value in video.shape) != H3_VIDEO_SHAPE:
        raise ShadowSignalNotAdmitted("h3_video_shape_mismatch")
    if tuple(int(value) for value in audio.shape) != H3_AUDIO_SHAPE:
        raise ShadowSignalNotAdmitted("h3_audio_shape_mismatch")
    if str(video.dtype) != H3_CALLBACK_VIDEO_DTYPE:
        raise ShadowSignalNotAdmitted("h3_video_dtype_not_float32")
    if str(audio.dtype) != H3_CALLBACK_VIDEO_DTYPE:
        raise ShadowSignalNotAdmitted("h3_audio_dtype_not_float32")
    if str(video.device.type) != H3_CALLBACK_DEVICE_TYPE:
        raise ShadowSignalNotAdmitted("h3_video_device_not_cuda")
    if str(audio.device.type) != H3_CALLBACK_DEVICE_TYPE or audio.device != video.device:
        raise ShadowSignalNotAdmitted("h3_audio_device_mismatch")
    return AdmittedH3Signal(
        video=video,
        source_shape=tuple(int(value) for value in video.shape),
        source_dtype=str(video.dtype),
        source_device_type=str(video.device.type),
        signal_adapter=H3_SIGNAL_ADAPTER,
        container_type=container_type,
        container_tensor_count=len(tensors),
    )


@dataclass
class AsyncSketchSlot:
    index: int
    host_buffer: Any
    state: str = "FREE"
    observed_step: int | None = None
    device_sketch: Any = None
    start_event: Any = None
    completion_event: Any = None
    enqueue_cpu_ns: int = 0
    logical_digest: str | None = None
    deadline_missed: bool = False
    next_callback_checked: bool = False
    source_shape: tuple[int, ...] | None = None
    source_dtype: str | None = None
    source_device_type: str | None = None
    signal_adapter: str | None = None
    container_type: str | None = None
    container_tensor_count: int | None = None


class TorchAsyncSketchBackend:
    """Current-stream, bounded, non-blocking CUDA sketch backend."""

    def __init__(self) -> None:
        try:
            import torch
            import torch.nn.functional as functional
        except ImportError as error:
            raise ShadowSignalNotAdmitted("torch_unavailable") from error
        self.torch = torch
        self.functional = functional

    def allocate_pinned(self) -> Any:
        buffer = self.torch.empty(SKETCH_VALUE_COUNT, dtype=self.torch.float32, pin_memory=True)
        if not bool(buffer.is_pinned()):
            raise ShadowSignalNotAdmitted("pinned_host_buffer_unavailable")
        return buffer

    def admit(self, x0: Any) -> AdmittedH3Signal:
        return admit_h3_x0_video(x0, self.torch)

    def enqueue(self, slot: AsyncSketchSlot, signal: AdmittedH3Signal) -> int:
        started = perf_counter_ns()
        stream = self.torch.cuda.current_stream(device=signal.video.device)
        slot.start_event = self.torch.cuda.Event(enable_timing=True)
        slot.completion_event = self.torch.cuda.Event(enable_timing=True)
        slot.start_event.record(stream)
        detached = signal.video.detach()
        leading_axes = (0, 1, 2)
        mean_map = detached.mean(dim=leading_axes, dtype=self.torch.float32)
        mean_abs_map = detached.abs().mean(dim=leading_axes, dtype=self.torch.float32)
        rms_map = detached.square().mean(dim=leading_axes).sqrt()
        pooled = self.functional.adaptive_avg_pool2d(
            self.torch.stack((mean_map, mean_abs_map, rms_map), dim=0), SKETCH_GRID
        )
        slot.device_sketch = pooled.reshape(-1).contiguous()
        slot.host_buffer.copy_(slot.device_sketch, non_blocking=True)
        slot.completion_event.record(stream)
        return perf_counter_ns() - started

    @staticmethod
    def ready(slot: AsyncSketchSlot) -> bool:
        return bool(slot.completion_event.query())

    @staticmethod
    def cuda_elapsed_ns(slot: AsyncSketchSlot) -> int:
        return int(round(float(slot.start_event.elapsed_time(slot.completion_event)) * 1_000_000))

    @staticmethod
    def host_values(slot: AsyncSketchSlot) -> tuple[float, ...]:
        array_type = ctypes.c_float * SKETCH_VALUE_COUNT
        view = array_type.from_address(int(slot.host_buffer.data_ptr()))
        return tuple(float(view[index]) for index in range(SKETCH_VALUE_COUNT))

    @staticmethod
    def release(slot: AsyncSketchSlot) -> None:
        slot.device_sketch = None
        slot.start_event = None
        slot.completion_event = None


class CompoundEyeShadowBridge:
    """One-call-per-ready-sketch bridge with explicit two-step prediction."""

    def __init__(self, context: ShadowContext, extension: Any | None = None) -> None:
        self.context = context
        self.run_digest = _digest(context.run_digest, "run_digest")
        self.workflow_revision_digest = _digest(
            context.workflow_revision_digest, "workflow_revision_digest"
        )
        self.settings_digest = _digest(context.settings_digest, "settings_digest")
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
                self.contract = dict(self.extension.compound_eye_shadow_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.callback_count = 0
        self.rust_call_count = 0
        self.full_compute_count = 0
        self.escalate_count = 0
        self.fallback_count = 0
        self.stable_candidate_count = 0
        self.validated_stable_count = 0
        self.contradicted_stable_count = 0
        self.not_validated_stable_count = 0
        self.active_candidate_count = 0
        self.uncertain_candidate_count = 0
        self.eligible_lagged_eye_steps = 0
        self.previous_sketch_q: tuple[int, ...] | None = None
        self.pending_predictions: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def _validate_pending(
        self, current: dict[str, Any], observed_step: int, *, usable: bool
    ) -> dict[str, Any]:
        expired = [
            item for item in self.pending_predictions
            if int(item["predicted_execution_step"]) < int(observed_step)
        ]
        due = [
            item for item in self.pending_predictions
            if int(item["predicted_execution_step"]) == int(observed_step)
        ]
        self.pending_predictions = [
            item for item in self.pending_predictions
            if int(item["predicted_execution_step"]) > int(observed_step)
        ]
        expired_count = sum(len(item["stable_regional_eyes"]) for item in expired)
        if expired_count:
            self.not_validated_stable_count += expired_count
        if not due:
            return {
                "status": "not_applicable" if not expired_count else "not_validated",
                "validated": 0,
                "contradicted": 0,
                "not_validated": expired_count,
                "prediction_sources": [],
            }
        stable_eyes = [
            int(eye) for item in due for eye in item["stable_regional_eyes"]
        ]
        sources = [int(item["sketch_observed_step"]) for item in due]
        if not stable_eyes:
            return {
                "status": "no_candidate",
                "validated": 0,
                "contradicted": 0,
                "not_validated": expired_count,
                "prediction_sources": sources,
            }
        if not usable:
            count = len(stable_eyes)
            self.not_validated_stable_count += count
            return {
                "status": "not_validated",
                "validated": 0,
                "contradicted": 0,
                "not_validated": expired_count + count,
                "prediction_sources": sources,
            }
        changes = current.get("eye_change_ppm")
        if not isinstance(changes, list) or len(changes) != EYE_COUNT:
            count = len(stable_eyes)
            self.not_validated_stable_count += count
            return {
                "status": "not_validated",
                "validated": 0,
                "contradicted": 0,
                "not_validated": expired_count + count,
                "prediction_sources": sources,
            }
        global_invalid = int(current.get("global_invalidation", 1)) != 0
        conflict_mask = int(current.get("overlap_conflict_mask", 0))
        contradicted = 0
        for eye in stable_eyes:
            regional_bit = int(eye) - 1
            if (
                global_invalid
                or int(changes[eye]) > STABLE_VALIDATION_LIMIT_PPM
                or bool(conflict_mask & (1 << regional_bit))
            ):
                contradicted += 1
        validated = len(stable_eyes) - contradicted
        self.validated_stable_count += validated
        self.contradicted_stable_count += contradicted
        return {
            "status": "contradicted" if contradicted else "validated_stable",
            "validated": validated,
            "contradicted": contradicted,
            "not_validated": expired_count,
            "prediction_sources": sources,
        }

    def evaluate(
        self,
        step_index: int,
        total_steps: int,
        sketch: SketchResult,
        *,
        consumed_callback: int | None = None,
        prediction_horizon_steps: int = PREDICTION_HORIZON_STEPS,
    ) -> dict[str, Any]:
        observation_started = perf_counter_ns()
        current = list(sketch.values_q)
        previous = list(self.previous_sketch_q or (0,) * SKETCH_VALUE_COUNT)
        observation = {
            "abi_version": ABI_VERSION,
            "struct_size": int(self.contract["observation_struct_size"]) if self.contract else 0,
            "run_digest": self.run_digest,
            "workflow_revision_digest": self.workflow_revision_digest,
            "settings_digest": self.settings_digest,
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "topology_id": TOPOLOGY_ID,
            "sketch_source_id": SKETCH_SOURCE_ID,
            "quantization_scale": QUANTIZATION_SCALE,
            "previous_available": self.previous_sketch_q is not None,
            "uncertainty_flags": 0,
            "invalidation_flags": 0,
            "full_compute_supported": True,
            "fallback_supported": True,
            "receipt_required": True,
            "unsupported_flags": 0,
            "current_sketch_q": current,
            "previous_sketch_q": previous,
        }
        observation_ns = perf_counter_ns() - observation_started
        response: dict[str, Any] | None = None
        failure_reason: str | None = None
        boundary_ns: int | None = None
        if self.extension is None:
            failure_reason = self.extension_error or "rust_extension_unavailable"
        else:
            boundary_started = perf_counter_ns()
            self.rust_call_count += 1
            try:
                response = dict(self.extension.evaluate_compound_eye_shadow_policy(**observation))
            except Exception as error:
                failure_reason = type(error).__name__
            boundary_ns = perf_counter_ns() - boundary_started

        parsed: dict[str, Any] = {}
        decision = ESCALATE_FULL_COMPUTE
        fallback = failure_reason is not None
        if response is not None:
            try:
                eye_state = [int(value) for value in response["eye_state"]]
                eye_confidence = [int(value) for value in response["eye_confidence_ppm"]]
                eye_change = [int(value) for value in response["eye_change_ppm"]]
                counters = [
                    int(response[name])
                    for name in (
                        "skipped_step_count",
                        "skipped_block_count",
                        "skipped_token_count",
                        "skipped_latent_count",
                        "reused_cache_count",
                        "partial_compute_count",
                    )
                ]
                decision = int(response["decision_code"])
                digests = {
                    name: bytes(response[name]).hex()
                    for name in (
                        "shared_visual_state_digest",
                        "compute_plan_digest",
                        "decision_digest",
                    )
                }
                if int(response["ffi_status"]) != 0:
                    failure_reason = "rust_nonzero_status"
                elif decision not in {FULL_COMPUTE, ESCALATE_FULL_COMPUTE}:
                    failure_reason = "unknown_decision"
                elif len(eye_state) != EYE_COUNT or len(eye_confidence) != EYE_COUNT or len(eye_change) != EYE_COUNT:
                    failure_reason = "malformed_eye_metadata"
                elif any(state not in EYE_LABELS for state in eye_state):
                    failure_reason = "unknown_eye_state"
                elif any(counters):
                    failure_reason = "actual_selective_compute_directive_rejected"
                elif any(len(value) != 64 for value in digests.values()):
                    failure_reason = "malformed_digest"
                if failure_reason is None:
                    parsed = {
                        "reason_code": int(response["reason_code"]),
                        "eye_state": eye_state,
                        "eye_confidence_ppm": eye_confidence,
                        "eye_change_ppm": eye_change,
                        "stable_eye_count": int(response["stable_eye_count"]),
                        "active_eye_count": int(response["active_eye_count"]),
                        "uncertain_eye_count": int(response["uncertain_eye_count"]),
                        "candidate_generate_count": int(response["candidate_generate_count"]),
                        "candidate_reuse_count": int(response["candidate_reuse_count"]),
                        "candidate_reconcile_count": int(response["candidate_reconcile_count"]),
                        "global_invalidation": int(response["global_invalidation"]),
                        "overlap_conflict_mask": int(response["overlap_conflict_mask"]),
                        "rust_policy_ns": int(response["rust_policy_ns"]),
                        **digests,
                    }
            except (KeyError, TypeError, ValueError, OverflowError):
                failure_reason = "malformed_response"
        fallback = failure_reason is not None
        if fallback:
            self.fallback_count += 1
            decision = ESCALATE_FULL_COMPUTE
            parsed = {
                "reason_code": None,
                "eye_state": [EYE_UNCERTAIN] * EYE_COUNT,
                "eye_confidence_ppm": [0] * EYE_COUNT,
                "eye_change_ppm": [0] * EYE_COUNT,
                "stable_eye_count": 0,
                "active_eye_count": 0,
                "uncertain_eye_count": 4,
                "candidate_generate_count": 0,
                "candidate_reuse_count": 0,
                "candidate_reconcile_count": 4,
                "global_invalidation": 1,
                "overlap_conflict_mask": 0,
                "rust_policy_ns": None,
                "shared_visual_state_digest": None,
                "compute_plan_digest": None,
                "decision_digest": None,
            }
        if decision == FULL_COMPUTE:
            self.full_compute_count += 1
        else:
            self.escalate_count += 1
        validation = self._validate_pending(parsed, int(step_index), usable=not fallback)
        stable_eyes = [
            eye for eye in range(1, EYE_COUNT) if parsed["eye_state"][eye] == EYE_STABLE
        ]
        active_eyes = [
            eye for eye in range(1, EYE_COUNT) if parsed["eye_state"][eye] == EYE_ACTIVE
        ]
        uncertain_eyes = [
            eye for eye in range(1, EYE_COUNT) if parsed["eye_state"][eye] == EYE_UNCERTAIN
        ]
        predicted_execution_step = int(step_index) + int(prediction_horizon_steps)
        prediction_eligible = predicted_execution_step < int(total_steps)
        if prediction_eligible:
            self.eligible_lagged_eye_steps += EYE_COUNT - 1
            self.stable_candidate_count += len(stable_eyes)
            self.active_candidate_count += len(active_eyes)
            self.uncertain_candidate_count += len(uncertain_eyes)
            self.pending_predictions.append(
                {
                    "sketch_observed_step": int(step_index),
                    "predicted_execution_step": predicted_execution_step,
                    "stable_regional_eyes": stable_eyes,
                }
            )
        event = {
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "decision": DECISION_LABELS[decision],
            "reason": failure_reason,
            "fallback_used": fallback,
            "eye_states": [EYE_LABELS[state] for state in parsed["eye_state"]],
            "eye_confidence_ppm": parsed["eye_confidence_ppm"],
            "eye_change_ppm": parsed["eye_change_ppm"],
            "stable_regional_eyes": stable_eyes if prediction_eligible else [],
            "candidate_generate_count": parsed["candidate_generate_count"],
            "candidate_reuse_count": parsed["candidate_reuse_count"],
            "candidate_reconcile_count": parsed["candidate_reconcile_count"],
            "global_invalidation": parsed["global_invalidation"],
            "overlap_conflict_mask": parsed["overlap_conflict_mask"],
            "validation_of_previous": validation,
            "validation_of_lagged_prediction": validation,
            "sketch_observed_step": int(step_index),
            "sketch_consumed_callback": consumed_callback,
            "predicted_execution_step": predicted_execution_step if prediction_eligible else None,
            "observation_lag_callbacks": (
                int(consumed_callback) - int(step_index) if consumed_callback is not None else None
            ),
            "prediction_horizon_steps": int(prediction_horizon_steps),
            "event_ready": bool(sketch.event_ready),
            "ready_lag_callbacks": sketch.ready_lag_callbacks,
            "deadline_missed": bool(sketch.deadline_missed),
            "observation_build_ns": observation_ns,
            "sketch_reduction_enqueue_ns": sketch.reduction_enqueue_ns,
            "gpu_to_host_ns": sketch.gpu_to_host_ns,
            "cuda_sketch_ns": sketch.cuda_sketch_ns,
            "host_quantization_ns": sketch.host_quantization_ns,
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": parsed["rust_policy_ns"],
            "host_transfer_count": sketch.host_transfer_count,
            "host_transfer_bytes": sketch.host_transfer_bytes,
                "tensor_bytes_to_rust": 0,
                "raw_tensor_bytes_to_rust": 0,
                "full_tensor_host_copy_bytes": 0,
            "source_shape": list(sketch.source_shape),
            "source_dtype": sketch.source_dtype,
            "source_device_type": sketch.source_device_type,
            "signal_adapter": sketch.signal_adapter,
            "container_type": sketch.container_type,
            "container_tensor_count": sketch.container_tensor_count,
            "shared_visual_state_digest": parsed["shared_visual_state_digest"],
            "compute_plan_digest": parsed["compute_plan_digest"],
            "decision_digest": parsed["decision_digest"],
        }
        self.previous_sketch_q = sketch.values_q
        self.events.append(event)
        return event

    def record_missing_observation(self, step_index: int, reason: str) -> None:
        pending = list(self.pending_predictions)
        self.pending_predictions.clear()
        self.not_validated_stable_count += sum(
            len(item["stable_regional_eyes"]) for item in pending
        )
        self.previous_sketch_q = None

    def finalize_pending(self) -> int:
        count = sum(len(item["stable_regional_eyes"]) for item in self.pending_predictions)
        self.not_validated_stable_count += count
        self.pending_predictions.clear()
        return count

    def receipt(self) -> dict[str, Any]:
        def values(name: str) -> list[int]:
            return [int(event[name]) for event in self.events if isinstance(event.get(name), int)]

        per_callback_total = [
            sum(
                int(event.get(name) or 0)
                for name in (
                    "sketch_reduction_enqueue_ns",
                    "gpu_to_host_ns",
                    "host_quantization_ns",
                    "observation_build_ns",
                    "boundary_roundtrip_ns",
                )
            )
            for event in self.events
        ]
        persistent_host_estimate = (
            SKETCH_VALUE_COUNT * 4
            + EYE_COUNT * 12
            + len(self.events) * 1_536
        )
        return {
            "schema_version": "c2.compound-eye-shadow.2",
            "policy": "compound_eye_shadow_full_compute",
            "abi_version": ABI_VERSION,
            "topology": TOPOLOGY_NAME,
            "eye_count": EYE_COUNT,
            "sketch": {
                "source": SKETCH_SOURCE_NAME,
                "signal_adapter": H3_SIGNAL_ADAPTER,
                "container_path": "x0.tensors[0]",
                "grid": list(SKETCH_GRID),
                "metrics": list(SKETCH_METRICS),
                "value_count": SKETCH_VALUE_COUNT,
                "quantization_scale": QUANTIZATION_SCALE,
                "raw_sketch_persisted": False,
            },
            "contract": self.contract,
            "callback_count": self.callback_count,
            "rust_call_count": self.rust_call_count,
            "full_compute_count": self.full_compute_count,
            "escalate_full_compute_count": self.escalate_count,
            "fallback_count": self.fallback_count,
            "stable_candidate_count": self.stable_candidate_count,
            "validated_stable_count": self.validated_stable_count,
            "contradicted_stable_count": self.contradicted_stable_count,
            "not_validated_stable_count": self.not_validated_stable_count,
            "eligible_lagged_eye_steps": self.eligible_lagged_eye_steps,
            "lagged_stable_candidate_count": self.stable_candidate_count,
            "lagged_active_candidate_count": self.active_candidate_count,
            "lagged_uncertain_candidate_count": self.uncertain_candidate_count,
            "lagged_validated_stable_count": self.validated_stable_count,
            "lagged_contradicted_stable_count": self.contradicted_stable_count,
            "lagged_unvalidated_stable_count": self.not_validated_stable_count,
            "lagged_stable_coverage": (
                self.validated_stable_count
                / max(
                    1,
                    self.validated_stable_count
                    + self.contradicted_stable_count
                    + self.not_validated_stable_count,
                )
            ),
            "lagged_contradiction_rate": (
                self.contradicted_stable_count
                / max(1, self.validated_stable_count + self.contradicted_stable_count)
            ),
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "actual_selective_compute_enabled": False,
            "host_transfer_count": sum(int(event.get("host_transfer_count", 0)) for event in self.events),
            "host_transfer_bytes": sum(int(event.get("host_transfer_bytes", 0)) for event in self.events),
            "max_host_transfers_per_callback": max(
                (int(event.get("host_transfer_count", 0)) for event in self.events), default=0
            ),
            "tensor_bytes_to_rust": 0,
            "raw_tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "persistent_host_state_estimate_bytes": persistent_host_estimate,
            "persistent_rust_state_bytes": 0,
            "persistent_gpu_state_bytes": 0,
            "sketch_reduction_enqueue": _timing(values("sketch_reduction_enqueue_ns")),
            "gpu_to_host": _timing(values("gpu_to_host_ns")),
            "host_quantization": _timing(values("host_quantization_ns")),
            "observation_build": _timing(values("observation_build_ns")),
            "boundary_roundtrip": _timing(values("boundary_roundtrip_ns")),
            "rust_policy": _timing(values("rust_policy_ns")),
            "total_shadow_callback": _timing(per_callback_total),
            "cumulative_shadow_overhead_ns": sum(per_callback_total),
            "gpu_synchronization": {
                "value": 0,
                "unit": "callback synchronizations",
                "support_status": "verified_by_implementation",
                "measurement_method": "CUDA Event query only; no callback synchronization API",
                "unsupported_reason": None,
            },
            "gpu_kernel_seconds": {
                "value": None,
                "unit": "seconds",
                "support_status": "not_collected",
                "measurement_method": "torch profiler/CUPTI not enabled",
                "unsupported_reason": "C2 authorizes no profiler execution",
            },
            "events": self.events,
        }


class AsyncCompoundEyeShadowPipeline:
    """Bounded async sketch pipeline; callback work never waits for CUDA."""

    def __init__(
        self,
        bridge: CompoundEyeShadowBridge,
        *,
        backend: Any | None = None,
        ring_size: int = ASYNC_RING_SIZE,
    ) -> None:
        if int(ring_size) != ASYNC_RING_SIZE:
            raise ValueError("C2-R2 requires exactly three async sketch slots")
        self.bridge = bridge
        self.backend = backend
        self.initialization_error: str | None = None
        if self.backend is None:
            try:
                self.backend = TorchAsyncSketchBackend()
            except Exception as error:
                self.initialization_error = str(error) or type(error).__name__
        self.slots: list[AsyncSketchSlot] = []
        if self.backend is not None:
            try:
                self.slots = [
                    AsyncSketchSlot(index=index, host_buffer=self.backend.allocate_pinned())
                    for index in range(ASYNC_RING_SIZE)
                ]
            except Exception as error:
                self.initialization_error = str(error) or type(error).__name__
                self.slots = []
        self.callback_count = 0
        self.sketch_enqueue_count = 0
        self.sketch_consume_count = 0
        self.event_ready_count = 0
        self.event_not_ready_count = 0
        self.ring_overflow_count = 0
        self.callback_synchronization_count = 0
        self.non_blocking_copy_count = 0
        self.signal_rejection_count = 0
        self.structural_admission_count = 0
        self.dtype_admission_count = 0
        self.dtype_rejection_count = 0
        self.rejected_dtype_rust_call_count = 0
        self.processing_failure_count = 0
        self.processing_failure_reasons: list[str] = []
        self.next_callback_verifiable_count = 0
        self.next_callback_event_ready_count = 0
        self.deadline_miss_count = 0
        self.drained_slot_count = 0
        self.drain_timeout_count = 0
        self.drain_wait_seconds = 0.0
        self._total_steps = 0
        self.callback_cpu_ns: list[int] = []
        self.cuda_sketch_ns: list[int] = []
        self.enqueue_cpu_ns: list[int] = []
        self.callback_events: list[dict[str, Any]] = []

    def _oldest_in_flight(self) -> AsyncSketchSlot | None:
        pending = [slot for slot in self.slots if slot.state == "IN_FLIGHT"]
        return min(pending, key=lambda slot: int(slot.observed_step or 0), default=None)

    def _free_slot(self) -> AsyncSketchSlot | None:
        return next((slot for slot in self.slots if slot.state == "FREE"), None)

    @staticmethod
    def _quantize(values: tuple[float, ...]) -> tuple[int, ...]:
        if len(values) != SKETCH_VALUE_COUNT or not all(math.isfinite(value) for value in values):
            raise ShadowSignalNotAdmitted("x0_sketch_nonfinite")
        return tuple(
            max(-(2**31), min(2**31 - 1, int(round(value * QUANTIZATION_SCALE))))
            for value in values
        )

    def _release(self, slot: AsyncSketchSlot) -> None:
        self.backend.release(slot)
        slot.state = "FREE"
        slot.observed_step = None
        slot.enqueue_cpu_ns = 0
        slot.logical_digest = None
        slot.deadline_missed = False
        slot.next_callback_checked = False
        slot.source_shape = None
        slot.source_dtype = None
        slot.source_device_type = None
        slot.signal_adapter = None
        slot.container_type = None
        slot.container_tensor_count = None

    def _consume_ready(self, slot: AsyncSketchSlot, consumed_callback: int) -> dict[str, Any]:
        quantization_started = perf_counter_ns()
        values_q = self._quantize(tuple(self.backend.host_values(slot)))
        quantization_ns = perf_counter_ns() - quantization_started
        cuda_ns = int(self.backend.cuda_elapsed_ns(slot))
        self.cuda_sketch_ns.append(cuda_ns)
        ready_lag = int(consumed_callback) - int(slot.observed_step)
        sketch = SketchResult(
            values_q=values_q,
            source_shape=tuple(slot.source_shape or ()),
            source_dtype=str(slot.source_dtype),
            source_device_type=str(slot.source_device_type),
            reduction_enqueue_ns=int(slot.enqueue_cpu_ns),
            gpu_to_host_ns=cuda_ns,
            host_quantization_ns=quantization_ns,
            signal_adapter=str(slot.signal_adapter),
            container_type=str(slot.container_type),
            container_tensor_count=int(slot.container_tensor_count or 0),
            cuda_sketch_ns=cuda_ns,
            sketch_observed_step=int(slot.observed_step),
            sketch_consumed_callback=int(consumed_callback),
            event_ready=True,
            ready_lag_callbacks=ready_lag,
            deadline_missed=bool(slot.deadline_missed or ready_lag > 1),
        )
        event = self.bridge.evaluate(
            int(slot.observed_step),
            self._total_steps,
            sketch,
            consumed_callback=int(consumed_callback),
        )
        self.sketch_consume_count += 1
        self.event_ready_count += 1
        self._release(slot)
        return event

    def _consume(self, slot: AsyncSketchSlot, consumed_callback: int) -> dict[str, Any] | None:
        observed_step = int(slot.observed_step or 0)
        try:
            return self._consume_ready(slot, consumed_callback)
        except Exception as error:
            reason = type(error).__name__
            self.signal_rejection_count += 1
            self.processing_failure_count += 1
            self.processing_failure_reasons.append(reason)
            self.bridge.record_missing_observation(observed_step, reason)
            self._release(slot)
            return None

    def _query_and_consume_one(self, callback_step: int) -> dict[str, Any] | None:
        slot = self._oldest_in_flight()
        if slot is None:
            return None
        next_callback = int(callback_step) == int(slot.observed_step) + 1
        ready = bool(self.backend.ready(slot))
        if next_callback and not slot.next_callback_checked:
            slot.next_callback_checked = True
            self.next_callback_verifiable_count += 1
            if ready:
                self.next_callback_event_ready_count += 1
            else:
                slot.deadline_missed = True
                self.deadline_miss_count += 1
        if not ready:
            self.event_not_ready_count += 1
            return None
        return self._consume(slot, callback_step)

    def observe_callback(self, step: int, x0: Any, total_steps: int) -> None:
        started = perf_counter_ns()
        self.callback_count += 1
        self._total_steps = int(total_steps)
        callback_event: dict[str, Any] = {
            "callback_step": int(step),
            "actual_execution": "FULL_COMPUTE",
            "shadow_state": "UNCERTAIN",
            "sketch_enqueued": False,
            "consumed_observed_step": None,
            "reason": None,
        }
        slot: AsyncSketchSlot | None = None
        try:
            if self.initialization_error is not None or self.backend is None:
                raise ShadowSignalNotAdmitted(self.initialization_error or "async_backend_unavailable")
            signal = self.backend.admit(x0)
            self.structural_admission_count += 1
            self.dtype_admission_count += 1
            consumed = self._query_and_consume_one(int(step))
            if consumed is not None:
                callback_event["consumed_observed_step"] = consumed["sketch_observed_step"]
            slot = self._free_slot()
            if slot is None:
                self.ring_overflow_count += 1
                callback_event["reason"] = "async_ring_overflow"
                self.bridge.record_missing_observation(int(step), "async_ring_overflow")
                return
            slot.state = "IN_FLIGHT"
            slot.observed_step = int(step)
            slot.logical_digest = hashlib.sha256(
                self.bridge.run_digest + int(step).to_bytes(4, "little", signed=False)
            ).hexdigest()
            slot.source_shape = signal.source_shape
            slot.source_dtype = signal.source_dtype
            slot.source_device_type = signal.source_device_type
            slot.signal_adapter = signal.signal_adapter
            slot.container_type = signal.container_type
            slot.container_tensor_count = signal.container_tensor_count
            slot.enqueue_cpu_ns = int(self.backend.enqueue(slot, signal))
            self.enqueue_cpu_ns.append(slot.enqueue_cpu_ns)
            self.sketch_enqueue_count += 1
            self.non_blocking_copy_count += 1
            callback_event["sketch_enqueued"] = True
            callback_event["source_dtype"] = signal.source_dtype
            callback_event["source_device_type"] = signal.source_device_type
            callback_event["source_shape"] = list(signal.source_shape)
        except ShadowSignalNotAdmitted as error:
            if slot is not None and slot.state == "IN_FLIGHT":
                self._release(slot)
            reason = str(error)
            self.signal_rejection_count += 1
            if "dtype" in reason:
                self.dtype_rejection_count += 1
            callback_event["reason"] = reason
            self.bridge.record_missing_observation(int(step), reason)
        except Exception as error:
            if slot is not None and slot.state == "IN_FLIGHT":
                self._release(slot)
            self.signal_rejection_count += 1
            callback_event["reason"] = type(error).__name__
            self.bridge.record_missing_observation(int(step), type(error).__name__)
        finally:
            elapsed = perf_counter_ns() - started
            callback_event["callback_shadow_cpu_ns"] = elapsed
            self.callback_cpu_ns.append(elapsed)
            self.callback_events.append(callback_event)

    def drain(self, timeout_seconds: float = ASYNC_DRAIN_TIMEOUT_SECONDS) -> None:
        started = perf_counter()
        deadline = started + min(float(timeout_seconds), ASYNC_DRAIN_TIMEOUT_SECONDS)
        while self._oldest_in_flight() is not None and perf_counter() < deadline:
            slot = self._oldest_in_flight()
            if slot is not None and bool(self.backend.ready(slot)):
                self._consume(slot, self._total_steps)
                self.drained_slot_count += 1
            else:
                sleep(0.001)
        remaining = [slot for slot in self.slots if slot.state == "IN_FLIGHT"]
        if remaining:
            self.drain_timeout_count = len(remaining)
            for slot in remaining:
                self.bridge.record_missing_observation(
                    int(slot.observed_step or self._total_steps), "drain_timeout"
                )
                self._release(slot)
        self.bridge.finalize_pending()
        self.drain_wait_seconds = perf_counter() - started

    def receipt(self) -> dict[str, Any]:
        payload = self.bridge.receipt()
        verifiable = self.next_callback_verifiable_count
        payload.update(
            {
                "schema_version": "c2.compound-eye-shadow.2",
                "callback_count": self.callback_count,
                "full_compute_count": self.callback_count,
                "rust_full_compute_directive_count": self.bridge.full_compute_count,
                "strict_signal_contract": {
                    "container_type": H3_NESTED_TYPE,
                    "tensor_count": 2,
                    "video_path": "x0.tensors[0]",
                    "audio_path": "x0.tensors[1]",
                    "video_shape": list(H3_VIDEO_SHAPE),
                    "audio_shape": list(H3_AUDIO_SHAPE),
                    "video_dtype": H3_CALLBACK_VIDEO_DTYPE,
                    "audio_dtype": H3_CALLBACK_VIDEO_DTYPE,
                    "device_type": H3_CALLBACK_DEVICE_TYPE,
                    "axis_contract": "B,C,T,H,W",
                    "admission_before_cuda_or_rust": True,
                },
                "async_pipeline": {
                    "ring_size": ASYNC_RING_SIZE,
                    "pinned_buffer_count": len(self.slots),
                    "pinned_buffer_bytes": len(self.slots) * SKETCH_VALUE_COUNT * 4,
                    "stream_method": "current_cuda_stream",
                    "source_tensor_retained": False,
                    "record_stream_required": False,
                    "sketch_enqueue_count": self.sketch_enqueue_count,
                    "sketch_consume_count": self.sketch_consume_count,
                    "event_ready_count": self.event_ready_count,
                    "event_not_ready_count": self.event_not_ready_count,
                    "ring_overflow_count": self.ring_overflow_count,
                    "callback_synchronization_count": self.callback_synchronization_count,
                    "non_blocking_copy_count": self.non_blocking_copy_count,
                    "signal_rejection_count": self.signal_rejection_count,
                    "structural_admission_count": self.structural_admission_count,
                    "dtype_admission_count": self.dtype_admission_count,
                    "dtype_rejection_count": self.dtype_rejection_count,
                    "rejected_dtype_rust_call_count": self.rejected_dtype_rust_call_count,
                    "processing_failure_count": self.processing_failure_count,
                    "processing_failure_reasons": self.processing_failure_reasons,
                    "next_callback_verifiable_count": verifiable,
                    "next_callback_event_ready_count": self.next_callback_event_ready_count,
                    "next_callback_event_ready_rate": (
                        self.next_callback_event_ready_count / verifiable if verifiable else None
                    ),
                    "deadline_miss_count": self.deadline_miss_count,
                    "drained_slot_count": self.drained_slot_count,
                    "drain_timeout_count": self.drain_timeout_count,
                    "drain_wait_seconds": self.drain_wait_seconds,
                    "drain_count": 1,
                    "max_in_flight_gpu_bytes": ASYNC_RING_SIZE * SKETCH_VALUE_COUNT * 4,
                },
                "callback_shadow_cpu": _timing(self.callback_cpu_ns),
                "cumulative_callback_shadow_cpu_ns": sum(self.callback_cpu_ns),
                "cuda_async_sketch": _timing(self.cuda_sketch_ns),
                "sketch_enqueue_cpu": _timing(self.enqueue_cpu_ns),
                "host_transfer_count": self.sketch_enqueue_count,
                "host_transfer_bytes": self.sketch_enqueue_count * SKETCH_VALUE_COUNT * 4,
                "max_host_transfers_per_callback": 1 if self.sketch_enqueue_count else 0,
                "persistent_host_state_estimate_bytes": len(self.slots) * SKETCH_VALUE_COUNT * 4,
                "persistent_gpu_state_bytes": 0,
                "max_in_flight_gpu_bytes": ASYNC_RING_SIZE * SKETCH_VALUE_COUNT * 4,
                "callback_synchronization_count": self.callback_synchronization_count,
                "signal_rejection_count": self.signal_rejection_count,
                "structural_admission_count": self.structural_admission_count,
                "dtype_admission_count": self.dtype_admission_count,
                "dtype_rejection_count": self.dtype_rejection_count,
                "rust_metadata_bytes": (
                    self.bridge.rust_call_count * int((self.bridge.contract or {}).get("observation_struct_size", 0))
                ),
                "region_skip_count": 0,
                "callback_events": self.callback_events,
            }
        )
        payload["gpu_synchronization"] = {
            "value": self.callback_synchronization_count,
            "unit": "callback synchronizations",
            "support_status": "verified_by_implementation",
            "measurement_method": "CUDA Event query only in callback; bounded wait only after sampler",
            "unsupported_reason": None,
        }
        return payload


def wrap_async_shadow_callback(
    original_callback: Callable[..., Any], pipeline: AsyncCompoundEyeShadowPipeline
) -> Callable[..., Any]:
    """Observe x0 without blocking and delegate all arguments unchanged."""

    def callback(step: int, x0: Any, x: Any, total_steps: int) -> Any:
        pipeline.observe_callback(step, x0, total_steps)
        return original_callback(step, x0, x, total_steps)

    return callback


def stable_digest(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
