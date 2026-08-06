"""Metadata-only Rust sampler step policy bridge for the C1 parity gate."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any
import hashlib
import math


ABI_VERSION = 1
FULL_COMPUTE = 0
ESCALATE_FULL_COMPUTE = 1
ALLOWED_DECISIONS = {FULL_COMPUTE, ESCALATE_FULL_COMPUTE}
DECISION_LABELS = {
    FULL_COMPUTE: "FULL_COMPUTE",
    ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE",
}
REASON_LABELS = {
    0: "normal_full_compute",
    1: "abi_mismatch",
    2: "struct_size_mismatch",
    3: "step_range_invalid",
    4: "digest_missing",
    5: "full_compute_unsupported",
    6: "uncertainty_present",
    7: "invalidation_present",
    8: "unsupported_metadata",
    9: "fallback_unsupported",
    10: "rust_panic",
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


def _timing_summary(values: list[int]) -> dict[str, int | None]:
    return {
        "p50_ns": _percentile(values, 0.50),
        "p95_ns": _percentile(values, 0.95),
        "max_ns": max(values) if values else None,
        "sum_ns": sum(values),
        "sample_count": len(values),
    }


@dataclass(frozen=True)
class PolicyContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str
    sampler_logical_id: int = 1
    scheduler_logical_id: int = 1


class RustStepPolicyBridge:
    """Calls Rust at most once for each sampler progress callback.

    Any unavailable, malformed, unknown, or panicking boundary response fails
    open to ordinary full compute. The bridge never receives a tensor.
    """

    def __init__(self, context: PolicyContext, extension: Any | None = None) -> None:
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
                self.contract = dict(self.extension.step_policy_contract())
            except Exception as error:  # boundary validation must fail open
                self.extension_error = type(error).__name__
                self.extension = None
        self.callback_count = 0
        self.rust_call_count = 0
        self.full_compute_count = 0
        self.escalate_count = 0
        self.fallback_count = 0
        self.events: list[dict[str, Any]] = []

    def evaluate(self, step_index: int, total_steps: int) -> dict[str, Any]:
        observation_started = perf_counter_ns()
        observation = {
            "abi_version": ABI_VERSION,
            "struct_size": int(self.contract["observation_struct_size"]) if self.contract else 0,
            "run_digest": self.run_digest,
            "workflow_revision_digest": self.workflow_revision_digest,
            "settings_digest": self.settings_digest,
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "sampler_logical_id": int(self.context.sampler_logical_id),
            "scheduler_logical_id": int(self.context.scheduler_logical_id),
            "timestep_available": False,
            "timestep_bits": 0,
            "sigma_available": False,
            "sigma_bits": 0,
            "uncertainty_flags": 0,
            "invalidation_flags": 0,
            "full_compute_supported": True,
            "fallback_supported": True,
            "cache_available": False,
            "receipt_required": True,
            "unsupported_flags": 0,
        }
        observation_ns = perf_counter_ns() - observation_started
        self.callback_count += 1
        response: dict[str, Any] | None = None
        failure_reason: str | None = None
        boundary_ns = 0
        if self.extension is None:
            failure_reason = self.extension_error or "rust_extension_unavailable"
        else:
            boundary_started = perf_counter_ns()
            self.rust_call_count += 1
            try:
                response = dict(self.extension.evaluate_step_policy(**observation))
            except Exception as error:  # fail-open boundary
                failure_reason = type(error).__name__
            boundary_ns = perf_counter_ns() - boundary_started

        decision = ESCALATE_FULL_COMPUTE
        reason_code: int | None = None
        rust_policy_ns: int | None = None
        decision_digest: str | None = None
        fallback = failure_reason is not None
        if response is not None:
            try:
                status = int(response["ffi_status"])
                parsed_decision = int(response["decision_code"])
                reason_code = int(response["reason_code"])
                rust_policy_ns = int(response["rust_policy_ns"])
                raw_digest = bytes(response["decision_digest"])
                counters = (
                    int(response["skipped_step_count"]),
                    int(response["skipped_block_count"]),
                    int(response["skipped_token_count"]),
                    int(response["skipped_latent_count"]),
                    int(response["reused_cache_count"]),
                    int(response["partial_compute_count"]),
                )
                if status != 0:
                    failure_reason = "rust_nonzero_status"
                    fallback = True
                elif parsed_decision not in ALLOWED_DECISIONS:
                    failure_reason = "unknown_decision"
                    fallback = True
                elif int(response.get("unsupported_flags", 0)) != 0:
                    failure_reason = "unsupported_directive_flags"
                    fallback = True
                elif any(counters):
                    failure_reason = "selective_compute_directive_rejected"
                    fallback = True
                elif len(raw_digest) != 32:
                    failure_reason = "malformed_decision_digest"
                    fallback = True
                else:
                    decision = parsed_decision
                    decision_digest = raw_digest.hex()
            except (KeyError, TypeError, ValueError, OverflowError):
                failure_reason = "malformed_response"
                fallback = True

        if fallback:
            self.fallback_count += 1
            decision = ESCALATE_FULL_COMPUTE
        if decision == FULL_COMPUTE:
            self.full_compute_count += 1
        else:
            self.escalate_count += 1
        event = {
            "step_index": int(step_index),
            "total_steps": int(total_steps),
            "decision": DECISION_LABELS[decision],
            "reason_code": reason_code,
            "reason": failure_reason or REASON_LABELS.get(reason_code, "unknown_reason"),
            "fallback_used": fallback,
            "observation_build_ns": observation_ns,
            "boundary_roundtrip_ns": boundary_ns if self.extension is not None else None,
            "rust_policy_ns": rust_policy_ns,
            "decision_digest": decision_digest,
            "tensor_bytes_transferred": 0,
        }
        self.events.append(event)
        return event

    def receipt(self) -> dict[str, Any]:
        observation = [int(item["observation_build_ns"]) for item in self.events]
        boundary = [
            int(item["boundary_roundtrip_ns"])
            for item in self.events
            if item["boundary_roundtrip_ns"] is not None
        ]
        rust = [
            int(item["rust_policy_ns"])
            for item in self.events
            if item["rust_policy_ns"] is not None
        ]
        observation_size = int(self.contract["observation_struct_size"]) if self.contract else None
        directive_size = int(self.contract["directive_struct_size"]) if self.contract else None
        bytes_per_call = (
            observation_size + directive_size
            if observation_size is not None and directive_size is not None
            else None
        )
        cumulative_ns = sum(observation) + sum(boundary) + sum(rust)
        return {
            "schema_version": "0.1.0",
            "policy": "rust_full_compute_parity",
            "abi_version": ABI_VERSION,
            "bridge": "pyo3_in_process_abi3_py312",
            "contract": self.contract,
            "callback_count": self.callback_count,
            "rust_call_count": self.rust_call_count,
            "full_compute_count": self.full_compute_count,
            "escalate_full_compute_count": self.escalate_count,
            "fallback_count": self.fallback_count,
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "metadata_bytes_per_rust_call": bytes_per_call,
            "metadata_bytes_transferred": (
                bytes_per_call * self.rust_call_count if bytes_per_call is not None else None
            ),
            "tensor_bytes_transferred": 0,
            "observation_build": _timing_summary(observation),
            "boundary_roundtrip": _timing_summary(boundary),
            "rust_policy": _timing_summary(rust),
            "cumulative_policy_overhead_ns": cumulative_ns,
            "cumulative_definition": (
                "sum(observation_build) + sum(boundary_roundtrip) + sum(rust_policy); "
                "rust_policy is nested within boundary_roundtrip and is intentionally retained as the predeclared conservative gate"
            ),
            "events": self.events,
        }


def wrap_progress_callback(original_callback: Any, bridge: RustStepPolicyBridge):
    """Observe one step, then delegate the unchanged callback arguments."""

    def callback(step: int, x0: Any, x: Any, total_steps: int) -> None:
        bridge.evaluate(step, total_steps)
        original_callback(step, x0, x, total_steps)

    return callback


def stable_digest(value: Any) -> str:
    """Return a public-safe deterministic digest for small logical metadata."""

    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
