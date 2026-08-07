"""C3-R1 frozen-replay H3 transformer-block mechanism validation.

The immutable schedule is a ceiling.  Live C2 metadata may veto a frozen
target to Full Compute, but it cannot add a selective execution step.  Rust
receives fixed scalar metadata once per consumed callback observation; block
activations and tensors never cross the language boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable, Mapping
import copy
import hashlib
import math

from .compound_eye_shadow import AsyncCompoundEyeShadowPipeline


ABI_VERSION = 1
TOTAL_STEPS = 20
BLOCK_COUNT = 50
FROZEN_SCHEDULE = (5, 6, 8, 13, 16, 17)
FULL_COMPUTE_ANCHORS = (0, 1, 18, 19)
CANDIDATE_BLOCKS = tuple(range(12, 49))
CANDIDATE_BLOCK_MASK = sum(1 << index for index in CANDIDATE_BLOCKS)
THEORETICAL_BYPASS_CALLS = len(FROZEN_SCHEDULE) * len(CANDIDATE_BLOCKS)
THEORETICAL_TOTAL_CALLS = TOTAL_STEPS * BLOCK_COUNT
THEORETICAL_OPPORTUNITY = THEORETICAL_BYPASS_CALLS / THEORETICAL_TOTAL_CALLS
CONTROL = "CONTROL"
SELECTIVE = "SELECTIVE"
FULL_COMPUTE = 0
SELECTIVE_BLOCK_BYPASS = 1
ESCALATE_FULL_COMPUTE = 2
DECISION_LABELS = {
    FULL_COMPUTE: "FULL_COMPUTE",
    SELECTIVE_BLOCK_BYPASS: "SELECTIVE_BLOCK_BYPASS",
    ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE",
}
REASON_LABELS = {
    0: "selective_admitted",
    1: "abi_mismatch",
    2: "struct_size_mismatch",
    3: "step_range_invalid",
    4: "digest_missing",
    5: "execution_contract_mismatch",
    6: "eye_metadata_invalid",
    7: "selective_unsupported",
    8: "fallback_unsupported",
    9: "unsupported_metadata",
    10: "schedule_flag_mismatch",
    11: "not_frozen_target",
    12: "source_invalid",
    13: "prediction_invalid",
    14: "stable_count_low",
    15: "active_present",
    16: "global_invalidation",
    17: "overlap_conflict",
    18: "fatal_flag",
    19: "rust_panic",
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
class FrozenPlanContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str
    model_revision_digest: str


class FrozenBlockPlanBridge:
    """Build one metadata-only Rust plan from each usable lagged C2 event."""

    def __init__(self, context: FrozenPlanContext, extension: Any | None = None) -> None:
        self.run_digest = _digest(context.run_digest, "run_digest")
        self.workflow_revision_digest = _digest(
            context.workflow_revision_digest, "workflow_revision_digest"
        )
        self.settings_digest = _digest(context.settings_digest, "settings_digest")
        self.model_revision_digest = _digest(context.model_revision_digest, "model_revision_digest")
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
                self.contract = dict(self.extension.c3_frozen_block_plan_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.rust_call_count = 0
        self.fallback_count = 0
        self.events: list[dict[str, Any]] = []
        self.plans: dict[int, dict[str, Any]] = {}
        self.boundary_ns: list[int] = []
        self.rust_policy_ns: list[int] = []

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
        fatal_flags = int(bool(event.get("deadline_missed")))
        observation = {
            "abi_version": ABI_VERSION,
            "struct_size": int(self.contract["observation_struct_size"]) if self.contract else 0,
            "run_digest": self.run_digest,
            "workflow_revision_digest": self.workflow_revision_digest,
            "settings_digest": self.settings_digest,
            "model_revision_digest": self.model_revision_digest,
            "predicted_execution_step": target,
            "total_steps": int(event.get("total_steps", 0)),
            "block_count": BLOCK_COUNT,
            "frozen_schedule_member": target in FROZEN_SCHEDULE,
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
            "selective_supported": True,
            "fallback_supported": True,
            "fatal_flags": fatal_flags,
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
                response = dict(self.extension.evaluate_c3_frozen_block_plan(**observation))
            except Exception as error:
                failure_reason = type(error).__name__
            boundary_ns = perf_counter_ns() - started
            self.boundary_ns.append(boundary_ns)

        decision = ESCALATE_FULL_COMPUTE
        reason_code: int | None = None
        bypass_mask = 0
        bypass_count = 0
        decision_digest: str | None = None
        rust_policy_ns: int | None = None
        if response is not None:
            try:
                decision = int(response["decision_code"])
                reason_code = int(response["reason_code"])
                bypass_mask = int(response["bypass_mask"])
                bypass_count = int(response["bypass_count"])
                rust_policy_ns = int(response["rust_policy_ns"])
                raw_digest = bytes(response["decision_digest"])
                if int(response["ffi_status"]) != 0:
                    failure_reason = "rust_nonzero_status"
                elif decision not in DECISION_LABELS:
                    failure_reason = "unknown_decision"
                elif int(response["target_step"]) != target:
                    failure_reason = "target_step_mismatch"
                elif bypass_count != bypass_mask.bit_count():
                    failure_reason = "bypass_count_mismatch"
                elif decision == SELECTIVE_BLOCK_BYPASS and (
                    bypass_mask != CANDIDATE_BLOCK_MASK or bypass_count != len(CANDIDATE_BLOCKS)
                ):
                    failure_reason = "selective_mask_mismatch"
                elif decision != SELECTIVE_BLOCK_BYPASS and bypass_mask != 0:
                    failure_reason = "full_compute_mask_nonzero"
                elif len(raw_digest) != 32:
                    failure_reason = "decision_digest_invalid"
                else:
                    decision_digest = raw_digest.hex()
            except (KeyError, TypeError, ValueError, OverflowError):
                failure_reason = "malformed_response"
        if failure_reason is not None:
            self.fallback_count += 1
            decision = ESCALATE_FULL_COMPUTE
            bypass_mask = 0
            bypass_count = 0
        if rust_policy_ns is not None:
            self.rust_policy_ns.append(rust_policy_ns)
        plan = {
            "target_step": target,
            "frozen_schedule_member": target in FROZEN_SCHEDULE,
            "decision": DECISION_LABELS[decision],
            "decision_code": decision,
            "reason_code": reason_code,
            "reason": failure_reason or REASON_LABELS.get(reason_code, "unknown_reason"),
            "fallback_used": failure_reason is not None,
            "bypass_mask": bypass_mask,
            "bypass_count": bypass_count,
            "stable_mask": stable_mask,
            "stable_count": stable_mask.bit_count(),
            "active_mask": active_mask,
            "active_count": active_mask.bit_count(),
            "uncertain_mask": uncertain_mask,
            "uncertain_count": uncertain_mask.bit_count(),
            "global_invalidation": bool(event.get("global_invalidation", 1)),
            "overlap_conflict_mask": int(event.get("overlap_conflict_mask", 0)),
            "source_valid": source_valid,
            "prediction_valid": prediction_valid,
            "fatal_flags": fatal_flags,
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": rust_policy_ns,
            "decision_digest": decision_digest,
            "tensor_bytes_to_rust": 0,
        }
        self.plans[target] = plan
        self.events.append(plan)
        return plan

    def receipt(self) -> dict[str, Any]:
        selective = [event["target_step"] for event in self.events if event["decision_code"] == SELECTIVE_BLOCK_BYPASS]
        frozen = [event for event in self.events if event["frozen_schedule_member"]]
        return {
            "schema_version": "c3-r1.frozen-block-plan.1",
            "abi_version": ABI_VERSION,
            "contract": self.contract,
            "frozen_schedule": list(FROZEN_SCHEDULE),
            "full_compute_anchors": list(FULL_COMPUTE_ANCHORS),
            "candidate_blocks": list(CANDIDATE_BLOCKS),
            "theoretical_bypass_calls": THEORETICAL_BYPASS_CALLS,
            "theoretical_total_calls": THEORETICAL_TOTAL_CALLS,
            "theoretical_opportunity": THEORETICAL_OPPORTUNITY,
            "rust_call_count": self.rust_call_count,
            "fallback_count": self.fallback_count,
            "actual_selective_steps": selective,
            "vetoed_frozen_steps": [
                event["target_step"] for event in frozen if event["decision_code"] != SELECTIVE_BLOCK_BYPASS
            ],
            "boundary_roundtrip": _timing(self.boundary_ns),
            "rust_policy": _timing(self.rust_policy_ns),
            "tensor_bytes_to_rust": 0,
            "events": self.events,
        }


class FrozenReplayShadowPipeline(AsyncCompoundEyeShadowPipeline):
    """Preserve C2 and attach a separate C3-R1 plan to each consumed event."""

    def __init__(self, bridge: Any, plan_bridge: FrozenBlockPlanBridge, **kwargs: Any) -> None:
        super().__init__(bridge, **kwargs)
        self.plan_bridge = plan_bridge

    def _consume_ready(self, slot: Any, consumed_callback: int) -> dict[str, Any]:
        event = super()._consume_ready(slot, consumed_callback)
        self.plan_bridge.evaluate_event(event)
        return event


class H3BlockExecutionController:
    """One wrapper per H3 block, with no per-block Rust call or tensor copy."""

    def __init__(self, mode: str, plan_bridge: FrozenBlockPlanBridge) -> None:
        if mode not in {CONTROL, SELECTIVE}:
            raise ValueError("mode must be CONTROL or SELECTIVE")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.model_forward_count = 0
        self.original_block_call_count = 0
        self.bypass_block_call_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.expected_block_index = 0
        self.current_execution_step = -1
        self.original_ns: list[int] = []
        self.bypass_ns: list[int] = []
        self.per_step: dict[int, dict[str, Any]] = {}

    def _step_record(self, step: int) -> dict[str, Any]:
        return self.per_step.setdefault(
            step,
            {
                "execution_step": step,
                "original_block_calls": 0,
                "bypass_block_calls": 0,
                "decision": "FULL_COMPUTE",
                "reason": "plan_unavailable",
            },
        )

    def block_wrapper(self, block_index: int) -> Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
        if block_index < 0 or block_index >= BLOCK_COUNT:
            raise ValueError("block index outside the fixed H3 range")

        def wrapper(args: Mapping[str, Any], extra_options: Mapping[str, Any]) -> Mapping[str, Any]:
            if block_index == 0:
                if self.expected_block_index != 0:
                    self.mapping_error_count += 1
                self.current_execution_step = self.model_forward_count
                self.model_forward_count += 1
            if block_index != self.expected_block_index:
                self.mapping_error_count += 1
            self.expected_block_index = (block_index + 1) % BLOCK_COUNT
            step = self.current_execution_step
            plan = self.plan_bridge.plans.get(step)
            record = self._step_record(step)
            if plan is not None:
                record["decision"] = plan["decision"]
                record["reason"] = plan["reason"]
            bypass = (
                self.mode == SELECTIVE
                and plan is not None
                and int(plan["decision_code"]) == SELECTIVE_BLOCK_BYPASS
                and bool(int(plan["bypass_mask"]) & (1 << block_index))
            )
            if bypass:
                started = perf_counter_ns()
                result = {"img": args["img"]}
                self.bypass_ns.append(perf_counter_ns() - started)
                self.bypass_block_call_count += 1
                record["bypass_block_calls"] += 1
                return result
            started = perf_counter_ns()
            try:
                result = extra_options["original_block"](args)
            except BaseException:
                self.wrapper_failure_count += 1
                raise
            finally:
                self.original_ns.append(perf_counter_ns() - started)
            self.original_block_call_count += 1
            record["original_block_calls"] += 1
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
        total_calls = self.original_block_call_count + self.bypass_block_call_count
        return {
            "mode": self.mode,
            "actual_block_bypass_enabled": self.mode == SELECTIVE,
            "model_forward_count": self.model_forward_count,
            "expected_block_count_per_forward": BLOCK_COUNT,
            "observed_block_call_count": total_calls,
            "original_block_call_count": self.original_block_call_count,
            "bypass_block_call_count": self.bypass_block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "identity_bypass": "return_same_packed_img_reference",
            "tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "persistent_c3_gpu_cache_bytes": 0,
            "rust_calls_per_block": 0,
            "original_block_wrapper": _timing(self.original_ns),
            "identity_bypass_wrapper": _timing(self.bypass_ns),
            "per_step": [self.per_step[key] for key in sorted(self.per_step)],
        }


def frozen_settings_digest(*, actual_block_bypass_enabled: bool) -> str:
    payload = (
        "c3-r1|frozen=5,6,8,13,16,17|anchors=0,1,18,19|blocks=12-48|"
        f"actual_block_bypass_enabled={str(actual_block_bypass_enabled).lower()}|"
        "steps=20|seed=101|width=864|height=480|frames=124|fps=24|"
        "scheduler=simple|sampler=res_multistep|denoise=1|sage=0"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
