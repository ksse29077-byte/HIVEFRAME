"""C2 Compound Eye shadow-only policy for the Local H3 sampler callback.

The module observes only ``x0`` (ComfyUI's denoised callback state), builds one
fixed 4x4x3 sketch, and sends 48 fixed-point integers to Rust.  Directives are
counterfactual: the wrapped sampler always receives its original arguments and
always performs full compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable
import hashlib
import math


ABI_VERSION = 1
TOPOLOGY_ID = 1
TOPOLOGY_NAME = "overlap_2x2"
SKETCH_SOURCE_ID = 1
SKETCH_SOURCE_NAME = "x0"
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


def extract_x0_sketch(x0: Any) -> SketchResult:
    """Reduce a five-dimensional H3 x0 tensor to 48 host float scalars once.

    Spatial axes are admitted only for the observed H3 layout ``[B,C,T,H,W]``.
    Batch, channel, and temporal axes are reduced before one 4x4 spatial pool.
    The pooled float32 block is transferred to host once and quantized there;
    neither the full latent nor a CUDA pointer crosses the Rust boundary.
    """

    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as error:
        raise ShadowSignalNotAdmitted("torch_unavailable") from error
    if not isinstance(x0, torch.Tensor):
        raise ShadowSignalNotAdmitted("x0_not_tensor")
    if bool(getattr(x0, "is_nested", False)):
        raise ShadowSignalNotAdmitted("nested_x0_unsupported")
    if x0.ndim != 5 or min(int(value) for value in x0.shape) <= 0:
        raise ShadowSignalNotAdmitted("x0_spatial_axes_not_safely_identified")
    if not (x0.dtype.is_floating_point or x0.dtype.is_complex):
        raise ShadowSignalNotAdmitted("x0_dtype_unsupported")
    if x0.dtype.is_complex:
        raise ShadowSignalNotAdmitted("x0_complex_dtype_unsupported")

    reduction_started = perf_counter_ns()
    detached = x0.detach()
    leading_axes = (0, 1, 2)
    mean_map = detached.mean(dim=leading_axes, dtype=torch.float32)
    mean_abs_map = detached.abs().mean(dim=leading_axes, dtype=torch.float32)
    rms_map = detached.float().square().mean(dim=leading_axes).sqrt()
    pooled = functional.adaptive_avg_pool2d(
        torch.stack((mean_map, mean_abs_map, rms_map), dim=0), SKETCH_GRID
    )
    reduction_enqueue_ns = perf_counter_ns() - reduction_started

    transfer_started = perf_counter_ns()
    # This is the sole GPU-to-host transfer: 48 float32 values (192 bytes).
    host_values = pooled.reshape(-1).contiguous().to(device="cpu", dtype=torch.float32)
    gpu_to_host_ns = perf_counter_ns() - transfer_started
    quantization_started = perf_counter_ns()
    values = [float(value) for value in host_values.tolist()]
    if len(values) != SKETCH_VALUE_COUNT or not all(math.isfinite(value) for value in values):
        raise ShadowSignalNotAdmitted("x0_sketch_nonfinite")
    quantized = tuple(
        max(-(2**31), min(2**31 - 1, int(round(value * QUANTIZATION_SCALE))))
        for value in values
    )
    host_quantization_ns = perf_counter_ns() - quantization_started
    return SketchResult(
        values_q=quantized,
        source_shape=tuple(int(value) for value in x0.shape),
        source_dtype=str(x0.dtype),
        source_device_type=str(x0.device.type),
        reduction_enqueue_ns=reduction_enqueue_ns,
        gpu_to_host_ns=gpu_to_host_ns,
        host_quantization_ns=host_quantization_ns,
    )


class CompoundEyeShadowBridge:
    """One-call-per-callback metadata bridge with next-step validation."""

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
        self.previous_sketch_q: tuple[int, ...] | None = None
        self.previous_event: dict[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    def _validate_previous(self, current: dict[str, Any], step_index: int) -> dict[str, Any]:
        previous = self.previous_event
        if previous is None:
            return {"status": "not_applicable", "validated": 0, "contradicted": 0, "not_validated": 0}
        stable_eyes = list(previous.get("stable_regional_eyes", []))
        if not stable_eyes:
            return {"status": "no_candidate", "validated": 0, "contradicted": 0, "not_validated": 0}
        if int(previous["step_index"]) + 1 != int(step_index):
            count = len(stable_eyes)
            self.not_validated_stable_count += count
            return {"status": "not_validated", "validated": 0, "contradicted": 0, "not_validated": count}
        changes = current.get("eye_change_ppm")
        if not isinstance(changes, list) or len(changes) != EYE_COUNT:
            count = len(stable_eyes)
            self.not_validated_stable_count += count
            return {"status": "not_validated", "validated": 0, "contradicted": 0, "not_validated": count}
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
            "not_validated": 0,
        }

    def evaluate(self, step_index: int, total_steps: int, sketch: SketchResult) -> dict[str, Any]:
        self.callback_count += 1
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
        validation = self._validate_previous(parsed, int(step_index))
        stable_eyes = [
            eye for eye in range(1, EYE_COUNT) if parsed["eye_state"][eye] == EYE_STABLE
        ]
        if int(step_index) < int(total_steps) - 1:
            self.stable_candidate_count += len(stable_eyes)
        event = {
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "decision": DECISION_LABELS[decision],
            "reason": failure_reason,
            "fallback_used": fallback,
            "eye_states": [EYE_LABELS[state] for state in parsed["eye_state"]],
            "eye_confidence_ppm": parsed["eye_confidence_ppm"],
            "eye_change_ppm": parsed["eye_change_ppm"],
            "stable_regional_eyes": stable_eyes if int(step_index) < int(total_steps) - 1 else [],
            "candidate_generate_count": parsed["candidate_generate_count"],
            "candidate_reuse_count": parsed["candidate_reuse_count"],
            "candidate_reconcile_count": parsed["candidate_reconcile_count"],
            "global_invalidation": parsed["global_invalidation"],
            "overlap_conflict_mask": parsed["overlap_conflict_mask"],
            "validation_of_previous": validation,
            "observation_build_ns": observation_ns,
            "sketch_reduction_enqueue_ns": sketch.reduction_enqueue_ns,
            "gpu_to_host_ns": sketch.gpu_to_host_ns,
            "host_quantization_ns": sketch.host_quantization_ns,
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": parsed["rust_policy_ns"],
            "host_transfer_count": sketch.host_transfer_count,
            "host_transfer_bytes": sketch.host_transfer_bytes,
            "tensor_bytes_to_rust": 0,
            "source_shape": list(sketch.source_shape),
            "source_dtype": sketch.source_dtype,
            "source_device_type": sketch.source_device_type,
            "shared_visual_state_digest": parsed["shared_visual_state_digest"],
            "compute_plan_digest": parsed["compute_plan_digest"],
            "decision_digest": parsed["decision_digest"],
        }
        self.previous_sketch_q = sketch.values_q
        self.previous_event = event
        self.events.append(event)
        return event

    def record_signal_failure(self, step_index: int, total_steps: int, reason: str) -> dict[str, Any]:
        self.callback_count += 1
        pending = len(self.previous_event.get("stable_regional_eyes", [])) if self.previous_event else 0
        self.not_validated_stable_count += pending
        self.fallback_count += 1
        self.escalate_count += 1
        event = {
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "decision": "ESCALATE_FULL_COMPUTE",
            "reason": reason,
            "fallback_used": True,
            "eye_states": ["UNCERTAIN"] * EYE_COUNT,
            "stable_regional_eyes": [],
            "validation_of_previous": {
                "status": "not_validated",
                "validated": 0,
                "contradicted": 0,
                "not_validated": pending,
            },
            "boundary_roundtrip_ns": None,
            "rust_policy_ns": None,
            "host_transfer_count": 0,
            "host_transfer_bytes": 0,
            "tensor_bytes_to_rust": 0,
        }
        self.previous_sketch_q = None
        self.previous_event = event
        self.events.append(event)
        return event

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
            "schema_version": "c2.compound-eye-shadow.1",
            "policy": "compound_eye_shadow_full_compute",
            "abi_version": ABI_VERSION,
            "topology": TOPOLOGY_NAME,
            "eye_count": EYE_COUNT,
            "sketch": {
                "source": SKETCH_SOURCE_NAME,
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
                "value": self.callback_count - self.fallback_count,
                "unit": "blocking small host transfers",
                "support_status": "inferred",
                "measurement_method": "one pooled float32 block transfer per admitted callback",
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


def wrap_shadow_callback(
    original_callback: Callable[..., Any],
    bridge: CompoundEyeShadowBridge,
    *,
    extractor: Callable[[Any], SketchResult] = extract_x0_sketch,
) -> Callable[..., Any]:
    """Observe x0 in shadow mode and delegate all original arguments unchanged."""

    def callback(step: int, x0: Any, x: Any, total_steps: int) -> Any:
        try:
            sketch = extractor(x0)
            bridge.evaluate(step, total_steps, sketch)
        except ShadowSignalNotAdmitted as error:
            bridge.record_signal_failure(step, total_steps, str(error))
        except Exception as error:
            bridge.record_signal_failure(step, total_steps, type(error).__name__)
        return original_callback(step, x0, x, total_steps)

    return callback


def stable_digest(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
