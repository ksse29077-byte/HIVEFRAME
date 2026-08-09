"""A1 regional active-query attention for the fixed Local H3 adapter.

The Compound Eye and Rust own semantic region decisions.  Only this H3
adapter maps those regions to packed query rows.  K/V remain global and full,
non-video rows remain full, and every malformed or late plan fails open to the
installed Full Compute implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Mapping, Sequence
import ast
import hashlib
import json
import math

from .compound_eye_shadow import AsyncCompoundEyeShadowPipeline


ABI_VERSION = 1
MECHANISM_ID = "REGIONAL_ACTIVE_QUERY_GLOBAL_KV_ZERO_UPDATE_V1"
CONTROL_MODE = "CONTROL_ACTIVE_QUERY_SHADOW"
SELECTIVE_MODE = "SELECTIVE_ACTIVE_QUERY"
FULL_COMPUTE = 0
REGIONAL_ACTIVE_QUERY = 1
ESCALATE_FULL_COMPUTE = 2
DECISION_LABELS = {
    FULL_COMPUTE: "FULL_COMPUTE",
    REGIONAL_ACTIVE_QUERY: "REGIONAL_ACTIVE_QUERY",
    ESCALATE_FULL_COMPUTE: "ESCALATE_FULL_COMPUTE",
}
REASON_LABELS = {
    0: "regional_query_admitted",
    1: "abi_mismatch",
    2: "struct_size_mismatch",
    3: "step_range_invalid",
    4: "digest_missing",
    5: "eye_metadata_invalid",
    6: "source_invalid",
    7: "prediction_invalid",
    8: "global_invalidation",
    9: "overlap_conflict",
    10: "anchor_step",
    11: "refresh_required",
    12: "no_stable_region",
    13: "selective_unsupported",
    14: "fallback_unsupported",
    15: "fatal_flag",
    16: "unsupported_metadata",
    17: "rust_panic",
}
ANCHOR_STEPS = (0, 1, 18, 19)
TOTAL_STEPS = 20
BLOCK_COUNT = 50
REGION_COUNT = 4
REGION_MASK = 0x0F
PREDICTION_HORIZON_STEPS = 2
HALO_PATCHES = 1
VIDEO_LATENT_TIME = 37
VIDEO_PATCH_HEIGHT = 15
VIDEO_PATCH_WIDTH = 27
VIDEO_TOKEN_COUNT = VIDEO_LATENT_TIME * VIDEO_PATCH_HEIGHT * VIDEO_PATCH_WIDTH
MODEL_SOURCE_SHA256 = "882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024"
MODEL_SOURCE_RELATIVE = Path("comfy/ldm/minimax/model.py")
ATTENTION_SOURCE_RELATIVE = Path("comfy/ldm/modules/attention.py")
REFERENCE_SAMPLER_SECONDS = 488.847320
COMPARABILITY_RELATIVE_LIMIT = 0.05
RUST_P95_NS_MAX = 100_000
CALLBACK_P95_NS_MAX = 3_000_000
MIN_PLANNED_QUERY_REDUCTION = 0.05
MIN_AFFECTED_NON_ANCHOR_STEPS = 3
MIN_ADMITTED_BLOCKS = 3
MAX_ADMITTED_BLOCKS = 20
MIN_STABLE_PLAN_EVENTS = 3
BLOCK_REGION_OBSERVATIONS_MIN = 3
IMPACT_MEAN_MAX = 0.020
IMPACT_P95_MAX = 0.040
IMPACT_MAX_MAX = 0.080


def _digest(value: str, name: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a hexadecimal SHA-256 digest") from error
    if len(raw) != 32:
        raise ValueError(f"{name} must contain exactly 32 bytes")
    return raw


def _percentile(values: Sequence[float | int], fraction: float) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _timing(values: Sequence[int]) -> dict[str, int | None]:
    return {
        "p50_ns": _percentile(values, 0.50),
        "p95_ns": _percentile(values, 0.95),
        "max_ns": max(values) if values else None,
        "sum_ns": sum(values),
        "sample_count": len(values),
    }


def fixed_contract() -> dict[str, Any]:
    return {
        "abi": "A1_ATTENTION_REGION_PLAN_ABI_V1",
        "mechanism": MECHANISM_ID,
        "prediction_horizon_steps": PREDICTION_HORIZON_STEPS,
        "anchors": list(ANCHOR_STEPS),
        "topology": "overlap_2x2",
        "exclusive_output_regions": 4,
        "halo_patches": HALO_PATCHES,
        "video_grid": [VIDEO_LATENT_TIME, VIDEO_PATCH_HEIGHT, VIDEO_PATCH_WIDTH],
        "all_kv": "GLOBAL_FULL",
        "non_video_queries": "FULL_COMPUTE",
        "uncertain_queries": "FULL_COMPUTE",
        "stable_query_action": "ZERO_ATTENTION_RESIDUAL_UPDATE",
        "feed_forward": "FULL_COMPUTE",
        "consecutive_region_selective": False,
        "refresh_after_selective": True,
        "tensor_bytes_to_rust": 0,
        "rust_calls_per_block": 0,
        "rust_calls_per_token": 0,
    }


def active_query_settings_digest(*, mode: str, admitted_blocks: Sequence[int] = ()) -> str:
    payload = {
        "contract": fixed_contract(),
        "mode": mode,
        "admitted_blocks": list(admitted_blocks),
        "model_source_sha256": MODEL_SOURCE_SHA256,
        "reference_sampler_seconds": REFERENCE_SAMPLER_SECONDS,
        "comparability_relative_limit": COMPARABILITY_RELATIVE_LIMIT,
        "block_gate": {
            "minimum_observations": BLOCK_REGION_OBSERVATIONS_MIN,
            "mean_max": IMPACT_MEAN_MAX,
            "p95_max": IMPACT_P95_MAX,
            "max_max": IMPACT_MAX_MAX,
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


def inspect_installed_attention_source(model_source: Path, attention_source: Path) -> dict[str, Any]:
    """Prove the fixed H3 source exposes a variable-Q/global-KV adapter boundary."""

    if not model_source.is_file() or not attention_source.is_file():
        return {"admitted": False, "reason": "installed_source_missing"}
    model_raw = model_source.read_bytes()
    attention_raw = attention_source.read_bytes()
    model_digest = sha256(model_raw).hexdigest()
    try:
        model_tree = ast.parse(model_raw.decode("utf-8"))
        attention_tree = ast.parse(attention_raw.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as error:
        return {
            "admitted": False,
            "reason": "installed_source_parse_failed",
            "error_type": type(error).__name__,
            "model_source_sha256": model_digest,
        }
    attention_class = next(
        (node for node in model_tree.body if isinstance(node, ast.ClassDef) and node.name == "Attention"),
        None,
    )
    block_class = next(
        (node for node in model_tree.body if isinstance(node, ast.ClassDef) and node.name == "DiTBlock"),
        None,
    )
    optimized_functions = {
        node.name: ast.unparse(node)
        for node in attention_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("attention_")
    }
    model_text = model_raw.decode("utf-8", errors="replace")
    checks = {
        "model_digest_fixed": model_digest == MODEL_SOURCE_SHA256,
        "attention_class_present": attention_class is not None,
        "dit_block_present": block_class is not None,
        "packed_qkv_projection_present": "self.qkv_proj(x).split" in model_text,
        "optimized_attention_boundary_present": "optimized_attention(q, k, v" in model_text,
        "output_projection_separate": "return self.out_proj(out.squeeze(0))" in model_text,
        "attention_residual_separate": "_mod_gate(x, gate_msa, self.attn(h" in model_text,
        "feed_forward_separate": "self.mlp(h)" in model_text,
        "video_segment_last": "target audio then target video, always the last two segments" in model_text,
        "pytorch_backend_uses_query_length": "q.shape[2]" in optimized_functions.get("attention_pytorch", ""),
        "basic_backend_uses_independent_qk_axes": "b i d, b j d" in optimized_functions.get("attention_basic", ""),
    }
    return {
        "admitted": all(checks.values()),
        "reason": None if all(checks.values()) else "active_query_source_contract_not_proven",
        "model_source_sha256": model_digest,
        "attention_source_sha256": sha256(attention_raw).hexdigest(),
        "checks": checks,
        "claim_boundary": {
            "qkv_projection_reduction": False,
            "attention_core_query_reduction": True,
            "global_kv_preserved": True,
            "active_row_output_projection": True,
            "installed_source_modified": False,
        },
    }


@dataclass(frozen=True)
class RegionPlanContext:
    run_digest: str
    workflow_revision_digest: str
    settings_digest: str
    model_revision_digest: str


class AttentionRegionPlanBridge:
    """One metadata-only Rust call per ready C2 observation."""

    def __init__(self, context: RegionPlanContext, extension: Any | None = None) -> None:
        self.run_digest = _digest(context.run_digest, "run_digest")
        self.workflow_revision_digest = _digest(context.workflow_revision_digest, "workflow_revision_digest")
        self.settings_digest = _digest(context.settings_digest, "settings_digest")
        self.model_revision_digest = _digest(context.model_revision_digest, "model_revision_digest")
        self.extension = extension
        self.extension_error: str | None = None
        if extension is None:
            try:
                import _hive_retina_boundary as boundary

                self.extension = boundary
            except (ImportError, OSError) as error:
                self.extension_error = type(error).__name__
        self.contract: dict[str, Any] | None = None
        if self.extension is not None:
            try:
                self.contract = dict(self.extension.attention_region_plan_contract())
            except Exception as error:
                self.extension_error = type(error).__name__
                self.extension = None
        self.plans: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.rust_call_count = 0
        self.fallback_count = 0
        self.boundary_ns: list[int] = []
        self.rust_policy_ns: list[int] = []
        self._last_target: int | None = None
        self._refresh_due_mask = 0

    @staticmethod
    def _state_values(event: Mapping[str, Any]) -> tuple[list[int], int, int, int]:
        labels = event.get("eye_states")
        if not isinstance(labels, list) or len(labels) != 5:
            return [2] * 5, 0, 0, REGION_MASK
        mapping = {"STABLE": 0, "ACTIVE": 1, "UNCERTAIN": 2}
        values = [mapping.get(str(label), 2) for label in labels]
        masks = {0: 0, 1: 0, 2: 0}
        for region, state in enumerate(values[1:]):
            masks[state] |= 1 << region
        return values, masks[0], masks[1], masks[2]

    def evaluate_event(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        target = event.get("predicted_execution_step")
        observed = event.get("sketch_observed_step")
        if not isinstance(target, int) or not isinstance(observed, int):
            return None
        states, stable_mask, active_mask, uncertain_mask = self._state_values(event)
        refresh_mask = self._refresh_due_mask if self._last_target is not None and target == self._last_target + 1 else 0
        source_valid = (
            not bool(event.get("fallback_used"))
            and event.get("reason") is None
            and event.get("event_ready") is True
            and event.get("source_dtype") == "torch.float32"
            and event.get("source_device_type") == "cuda"
            and event.get("signal_adapter") == "h3_nested_video_v1"
        )
        prediction_valid = target == observed + PREDICTION_HORIZON_STEPS and target < int(event.get("total_steps", 0))
        confidences = event.get("eye_confidence_ppm")
        changes = event.get("eye_change_ppm")
        if not isinstance(confidences, list) or len(confidences) != 5:
            confidences = [0] * 5
            source_valid = False
        if not isinstance(changes, list) or len(changes) != 5:
            changes = [0] * 5
            source_valid = False
        observation = {
            "abi_version": ABI_VERSION,
            "struct_size": int(self.contract["observation_struct_size"]) if self.contract else 0,
            "run_digest": self.run_digest,
            "workflow_revision_digest": self.workflow_revision_digest,
            "settings_digest": self.settings_digest,
            "model_revision_digest": self.model_revision_digest,
            "observed_step": observed,
            "predicted_execution_step": target,
            "total_steps": int(event.get("total_steps", 0)),
            "topology_id": 1,
            "eye_state": states,
            "eye_confidence_ppm": [int(value) for value in confidences],
            "eye_change_ppm": [int(value) for value in changes],
            "stable_mask": stable_mask,
            "stable_count": stable_mask.bit_count(),
            "active_mask": active_mask,
            "active_count": active_mask.bit_count(),
            "uncertain_mask": uncertain_mask,
            "uncertain_count": uncertain_mask.bit_count(),
            "global_invalidation": bool(event.get("global_invalidation", 1)),
            "overlap_conflict_mask": int(event.get("overlap_conflict_mask", 0)),
            "anchor_step": target in ANCHOR_STEPS,
            "cooldown_mask": refresh_mask,
            "refresh_required_mask": refresh_mask,
            "source_valid": source_valid,
            "prediction_valid": prediction_valid,
            "selective_supported": True,
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
                response = dict(self.extension.evaluate_attention_region_plan(**observation))
            except Exception as error:
                failure_reason = type(error).__name__
            boundary_ns = perf_counter_ns() - started
            self.boundary_ns.append(boundary_ns)
        decision = ESCALATE_FULL_COMPUTE
        reason_code: int | None = None
        admitted_mask = 0
        full_mask = REGION_MASK
        rust_ns: int | None = None
        digests: dict[str, str | None] = {
            "shared_visual_state_digest": None,
            "compute_plan_digest": None,
            "decision_digest": None,
        }
        if response is not None:
            try:
                decision = int(response["decision_code"])
                reason_code = int(response["reason_code"])
                admitted_mask = int(response["stable_region_mask"])
                full_mask = int(response["full_compute_region_mask"])
                rust_ns = int(response["rust_policy_ns"])
                digests = {
                    name: bytes(response[name]).hex()
                    for name in digests
                }
                if int(response["ffi_status"]) != 0:
                    failure_reason = "rust_nonzero_status"
                elif decision not in DECISION_LABELS:
                    failure_reason = "unknown_decision"
                elif int(response["target_step"]) != target:
                    failure_reason = "target_step_mismatch"
                elif admitted_mask & ~REGION_MASK or full_mask & ~REGION_MASK:
                    failure_reason = "region_mask_out_of_range"
                elif admitted_mask & full_mask or (admitted_mask | full_mask) != REGION_MASK:
                    failure_reason = "region_partition_invalid"
                elif decision != REGIONAL_ACTIVE_QUERY and admitted_mask != 0:
                    failure_reason = "full_compute_plan_has_selective_region"
                elif decision == REGIONAL_ACTIVE_QUERY and admitted_mask == 0:
                    failure_reason = "selective_plan_empty"
                elif any(value is None or len(value) != 64 for value in digests.values()):
                    failure_reason = "malformed_digest"
            except (KeyError, TypeError, ValueError, OverflowError):
                failure_reason = "malformed_response"
        if failure_reason is not None:
            self.fallback_count += 1
            decision = ESCALATE_FULL_COMPUTE
            admitted_mask = 0
            full_mask = REGION_MASK
        if rust_ns is not None:
            self.rust_policy_ns.append(rust_ns)
        plan = {
            "observed_step": observed,
            "target_step": target,
            "decision_code": decision,
            "decision": DECISION_LABELS[decision],
            "reason_code": reason_code,
            "reason": failure_reason or REASON_LABELS.get(reason_code, "unknown_reason"),
            "fallback_used": failure_reason is not None,
            "stable_region_mask": admitted_mask,
            "full_compute_region_mask": full_mask,
            "refresh_region_mask": refresh_mask,
            "stable_count": admitted_mask.bit_count(),
            "active_mask": active_mask,
            "uncertain_mask": uncertain_mask,
            "global_invalidation": bool(event.get("global_invalidation", 1)),
            "overlap_conflict_mask": int(event.get("overlap_conflict_mask", 0)),
            "anchor_step": target in ANCHOR_STEPS,
            "source_valid": source_valid,
            "prediction_valid": prediction_valid,
            "boundary_roundtrip_ns": boundary_ns,
            "rust_policy_ns": rust_ns,
            "tensor_bytes_to_rust": 0,
            **digests,
        }
        self.plans[target] = plan
        self.events.append(plan)
        self._last_target = target
        self._refresh_due_mask = admitted_mask if decision == REGIONAL_ACTIVE_QUERY else 0
        return plan

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "a1.attention-region-plan.1",
            "abi": "A1_ATTENTION_REGION_PLAN_ABI_V1",
            "contract": self.contract,
            "rust_call_count": self.rust_call_count,
            "rust_calls_per_ready_observation_max": 1,
            "rust_calls_per_block": 0,
            "rust_calls_per_token": 0,
            "fallback_count": self.fallback_count,
            "boundary_roundtrip": _timing(self.boundary_ns),
            "rust_policy": _timing(self.rust_policy_ns),
            "tensor_bytes_to_rust": 0,
            "events": self.events,
        }


class ActiveQueryShadowPipeline(AsyncCompoundEyeShadowPipeline):
    def __init__(self, bridge: Any, plan_bridge: AttentionRegionPlanBridge, **kwargs: Any) -> None:
        super().__init__(bridge, **kwargs)
        self.plan_bridge = plan_bridge

    def _consume_ready(self, slot: Any, consumed_callback: int) -> dict[str, Any]:
        event = super()._consume_ready(slot, consumed_callback)
        self.plan_bridge.evaluate_event(event)
        return event


def region_local_rows(region: int) -> tuple[int, ...]:
    """Return one exclusive quadrant interior; internal seams keep a 1-patch halo."""

    if region not in range(REGION_COUNT):
        raise ValueError("region must be in [0, 3]")
    top = region < 2
    left = region % 2 == 0
    h_split = (VIDEO_PATCH_HEIGHT + 1) // 2
    w_split = (VIDEO_PATCH_WIDTH + 1) // 2
    h_range = range(0, h_split - HALO_PATCHES) if top else range(h_split + HALO_PATCHES, VIDEO_PATCH_HEIGHT)
    w_range = range(0, w_split - HALO_PATCHES) if left else range(w_split + HALO_PATCHES, VIDEO_PATCH_WIDTH)
    rows = []
    frame_stride = VIDEO_PATCH_HEIGHT * VIDEO_PATCH_WIDTH
    for time_index in range(VIDEO_LATENT_TIME):
        for height_index in h_range:
            base = time_index * frame_stride + height_index * VIDEO_PATCH_WIDTH
            rows.extend(base + width_index for width_index in w_range)
    return tuple(rows)


REGION_LOCAL_ROWS = tuple(region_local_rows(region) for region in range(REGION_COUNT))


def region_mapping_contract() -> dict[str, Any]:
    flattened = [row for rows in REGION_LOCAL_ROWS for row in rows]
    return {
        "grid": [VIDEO_LATENT_TIME, VIDEO_PATCH_HEIGHT, VIDEO_PATCH_WIDTH],
        "video_token_count": VIDEO_TOKEN_COUNT,
        "halo_patches": HALO_PATCHES,
        "region_row_counts": [len(rows) for rows in REGION_LOCAL_ROWS],
        "exclusive": len(flattened) == len(set(flattened)),
        "in_range": all(0 <= row < VIDEO_TOKEN_COUNT for row in flattened),
        "boundary_rows_full_compute": VIDEO_TOKEN_COUNT - len(flattened),
    }


def active_query_row_indices(
    *,
    sequence_length: int,
    video_start: int,
    video_stop: int,
    stable_region_mask: int,
    torch_module: Any,
    device: Any,
) -> tuple[Any, int]:
    if video_stop - video_start != VIDEO_TOKEN_COUNT:
        raise ValueError("fixed H3 video token layout changed")
    if video_start < 0 or video_stop > sequence_length or stable_region_mask & ~REGION_MASK:
        raise ValueError("packed sequence or region mask is invalid")
    omitted_local = sorted(
        row
        for region, rows in enumerate(REGION_LOCAL_ROWS)
        if stable_region_mask & (1 << region)
        for row in rows
    )
    keep = torch_module.ones(sequence_length, dtype=torch_module.bool, device=device)
    if omitted_local:
        omitted = torch_module.tensor(omitted_local, dtype=torch_module.long, device=device) + video_start
        keep[omitted] = False
    return keep.nonzero().flatten(), len(omitted_local)


def subset_query_attention(
    attention: Any,
    x: Any,
    rope_freqs: Any,
    active_indices: Any,
    *,
    transformer_options: Mapping[str, Any],
    optimized_attention: Any,
    cast_to: Any,
    in_training: bool,
    rms_rope: Any,
    rms_rope_in_place: Any,
) -> Any:
    """Run smaller Q against full/global K/V and project active rows only."""

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
    q = q.index_select(0, active_indices).transpose(0, 1).unsqueeze(0)
    k = k.transpose(0, 1).unsqueeze(0)
    v = v.transpose(0, 1).unsqueeze(0)
    out = optimized_attention(
        q,
        k,
        v,
        attention.heads,
        mask=None,
        skip_reshape=True,
        transformer_options=transformer_options,
    )
    return attention.out_proj(out.squeeze(0))


class H3ActiveQueryAttentionController:
    """H3-specific packed-row mapping and Full Compute fail-open execution."""

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
            raise ValueError("unsupported A1 mode")
        if any(index < 0 or index >= BLOCK_COUNT for index in admitted_blocks):
            raise ValueError("admitted block outside fixed H3 range")
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.h3 = h3_model
        self.torch = torch_module
        self.admitted_blocks = tuple(sorted(set(int(index) for index in admitted_blocks)))
        self._original_forward: Any | None = None
        self._dit_class: Any | None = None
        self.block_call_count = 0
        self.model_forward_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.fail_open_count = 0
        self.full_attention_call_count = 0
        self.regional_attention_call_count = 0
        self.full_q_row_count = 0
        self.actual_q_row_count = 0
        self.full_kv_row_count = 0
        self.actual_kv_row_count = 0
        self.omitted_q_row_count = 0
        self.qkv_projection_full_row_count = 0
        self.output_projection_row_count = 0
        self.non_video_omission_count = 0
        self.boundary_omission_count = 0
        self.explicit_cuda_synchronization_count = 0
        self.hot_path_host_tensor_transfer_count = 0
        self.per_block_rust_call_count = 0
        self.per_token_rust_call_count = 0
        self.block_ratios: dict[int, list[Any]] = {index: [] for index in range(BLOCK_COUNT)}
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
                "regional_attention_calls": 0,
                "full_q_rows": 0,
                "actual_q_rows": 0,
                "omitted_q_rows": 0,
            },
        )

    def _regional_ratios(
        self,
        *,
        block_index: int,
        stable_mask: int,
        video_start: int,
        video_row: int,
        x: Any,
        attention_output: Any,
        gate_msa: Any,
    ) -> None:
        gate = gate_msa[video_row].to(attention_output.dtype)
        for region, local_rows in enumerate(REGION_LOCAL_ROWS):
            if not (stable_mask & (1 << region)):
                continue
            indices = self.torch.tensor(local_rows, dtype=self.torch.long, device=x.device) + video_start
            base = self.torch.linalg.vector_norm(x.index_select(0, indices).float()).clamp_min(1e-6)
            delta = attention_output.index_select(0, indices) * gate
            ratio = self.torch.linalg.vector_norm(delta.float()) / base
            self.block_ratios[block_index].append(ratio.detach())

    def _apply_active_attention(
        self,
        *,
        x: Any,
        attention_h: Any,
        attention: Any,
        gate_msa: Any,
        mod_segments: Sequence[Sequence[int]],
        rope_freqs: Any,
        transformer_options: Mapping[str, Any],
        active_indices: Any,
    ) -> Any:
        active_output = subset_query_attention(
            attention,
            attention_h,
            rope_freqs,
            active_indices,
            transformer_options=transformer_options,
            optimized_attention=self.h3.optimized_attention,
            cast_to=self.h3.comfy.model_management.cast_to,
            in_training=bool(self.h3.comfy.model_management.in_training),
            rms_rope=self.h3.comfy.quant_ops.ck.rms_rope_split_half,
            rms_rope_in_place=self.h3.comfy.quant_ops.ck.rms_rope_split_half_,
        )
        covered = 0
        for start, stop, row in mod_segments:
            positions = ((active_indices >= int(start)) & (active_indices < int(stop))).nonzero().flatten()
            if int(positions.numel()) == 0:
                continue
            active_output[positions] = active_output[positions] * gate_msa[int(row)].to(active_output.dtype)
            covered += int(positions.numel())
        if covered != int(active_indices.numel()):
            raise ValueError("active query rows are not covered by modulation segments")
        x.index_add_(0, active_indices, active_output)
        return x

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
        plan = self.plan_bridge.plans.get(step_index)
        if plan is not None:
            record["decision"] = plan["decision"]
            record["stable_region_mask"] = int(plan["stable_region_mask"])
        try:
            video_start, video_stop, video_row = self._video_segment(x, mod_segments)
        except (IndexError, TypeError, ValueError):
            self.mapping_error_count += 1
            self.fail_open_count += 1
            self.block_call_count += 1
            if self._original_forward is None:
                raise RuntimeError("A1 Full Compute fallback is unavailable")
            return self._original_forward(block, x, t_emb, mod_segments, rope_freqs, options)
        try:
            sequence = int(x.shape[0])
            stable_mask = (
                int(plan["stable_region_mask"])
                if plan is not None and int(plan["decision_code"]) == REGIONAL_ACTIVE_QUERY
                else 0
            )
            regional = self.is_selective and block_index in self.admitted_blocks and stable_mask != 0
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = block.adaln_proj(t_emb)
            attention_h = self.h3._mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments)
            if regional:
                active_indices, omitted = active_query_row_indices(
                    sequence_length=sequence,
                    video_start=video_start,
                    video_stop=video_stop,
                    stable_region_mask=stable_mask,
                    torch_module=self.torch,
                    device=x.device,
                )
                try:
                    x = self._apply_active_attention(
                        x=x,
                        attention_h=attention_h,
                        attention=block.attn,
                        gate_msa=gate_msa,
                        mod_segments=mod_segments,
                        rope_freqs=rope_freqs,
                        transformer_options=options,
                        active_indices=active_indices,
                    )
                except (IndexError, RuntimeError, TypeError, ValueError):
                    self.fail_open_count += 1
                    if self._original_forward is None:
                        raise
                    return self._original_forward(block, x, t_emb, mod_segments, rope_freqs, options)
                actual_q = sequence - omitted
                self.regional_attention_call_count += 1
                self.omitted_q_row_count += omitted
                self.output_projection_row_count += actual_q
                record["regional_attention_calls"] += 1
                record["omitted_q_rows"] += omitted
            else:
                attention_output = block.attn(attention_h, rope_freqs=rope_freqs, transformer_options=options)
                if self.mode == CONTROL_MODE and stable_mask:
                    self._regional_ratios(
                        block_index=block_index,
                        stable_mask=stable_mask,
                        video_start=video_start,
                        video_row=video_row,
                        x=x,
                        attention_output=attention_output,
                        gate_msa=gate_msa,
                    )
                x = self.h3._mod_gate(x, gate_msa, attention_output, mod_segments)
                actual_q = sequence
                self.full_attention_call_count += 1
                self.output_projection_row_count += sequence
                record["full_attention_calls"] += 1
            self.full_q_row_count += sequence
            self.actual_q_row_count += actual_q
            self.full_kv_row_count += sequence * 2
            self.actual_kv_row_count += sequence * 2
            self.qkv_projection_full_row_count += sequence
            record["full_q_rows"] += sequence
            record["actual_q_rows"] += actual_q
            h = self.h3._mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
            return self.h3._mod_gate(x, gate_mlp, block.mlp(h), mod_segments)
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            self.block_call_count += 1

    def install(self, dit_class: Any) -> None:
        if self._original_forward is not None:
            raise RuntimeError("A1 H3 wrapper already installed")
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
        admitted: list[tuple[float, float, int]] = []
        for block_index in range(BLOCK_COUNT):
            tensors = self.block_ratios[block_index]
            values = [float(value) for value in self.torch.stack(tensors).float().cpu().tolist()] if tensors else []
            finite = [value for value in values if math.isfinite(value)]
            mean_value = sum(finite) / len(finite) if finite else None
            p95 = _percentile(finite, 0.95)
            maximum = max(finite) if finite else None
            passed = (
                len(finite) >= BLOCK_REGION_OBSERVATIONS_MIN
                and len(finite) == len(values)
                and mean_value is not None
                and mean_value <= IMPACT_MEAN_MAX
                and p95 is not None
                and p95 <= IMPACT_P95_MAX
                and maximum is not None
                and maximum <= IMPACT_MAX_MAX
            )
            rows.append(
                {
                    "block_index": block_index,
                    "regional_observation_count": len(values),
                    "finite_count": len(finite),
                    "nonfinite_count": len(values) - len(finite),
                    "mean": mean_value,
                    "p95": p95,
                    "max": maximum,
                    "passed": passed,
                }
            )
            if passed:
                admitted.append((float(mean_value), float(p95), block_index))
        selected = tuple(item[2] for item in sorted(admitted)[:MAX_ADMITTED_BLOCKS])
        return rows, selected

    def finalize(self) -> dict[str, Any]:
        calibration, selected = self._block_calibration()
        stable_plans = [
            plan for plan in self.plan_bridge.events
            if int(plan["decision_code"]) == REGIONAL_ACTIVE_QUERY and int(plan["stable_region_mask"]) != 0
        ]
        planned_omitted = sum(
            sum(len(REGION_LOCAL_ROWS[region]) for region in range(REGION_COUNT) if int(plan["stable_region_mask"]) & (1 << region))
            * len(selected)
            for plan in stable_plans
        )
        full_rows = max(1, self.full_q_row_count)
        planned_reduction = planned_omitted / full_rows
        affected_steps = sorted({int(plan["target_step"]) for plan in stable_plans if int(plan["target_step"]) not in ANCHOR_STEPS})
        return {
            "schema_version": "a1.h3.active-query-execution.1",
            "mode": self.mode,
            "mechanism": MECHANISM_ID,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "fail_open_count": self.fail_open_count,
            "full_attention_call_count": self.full_attention_call_count,
            "regional_attention_call_count": self.regional_attention_call_count,
            "full_q_row_count": self.full_q_row_count,
            "actual_q_row_count": self.actual_q_row_count,
            "omitted_q_row_count": self.omitted_q_row_count,
            "full_kv_row_count": self.full_kv_row_count,
            "actual_kv_row_count": self.actual_kv_row_count,
            "qkv_projection_full_row_count": self.qkv_projection_full_row_count,
            "qkv_projection_reduction_claimed": False,
            "output_projection_row_count": self.output_projection_row_count,
            "non_video_omission_count": self.non_video_omission_count,
            "boundary_omission_count": self.boundary_omission_count,
            "explicit_cuda_synchronization_count": self.explicit_cuda_synchronization_count,
            "hot_path_host_tensor_transfer_count": self.hot_path_host_tensor_transfer_count,
            "per_block_rust_call_count": self.per_block_rust_call_count,
            "per_token_rust_call_count": self.per_token_rust_call_count,
            "tensor_bytes_to_rust": 0,
            "global_kv_preserved": self.actual_kv_row_count == self.full_kv_row_count,
            "feed_forward_execution": "FULL_COMPUTE",
            "region_mapping": region_mapping_contract(),
            "block_calibration": calibration,
            "admitted_blocks": list(selected),
            "admitted_block_count": len(selected),
            "stable_region_plan_event_count": len(stable_plans),
            "affected_non_anchor_steps": affected_steps,
            "planned_query_reduction": planned_reduction,
            "actual_query_reduction": 1.0 - (self.actual_q_row_count / self.full_q_row_count) if self.full_q_row_count else 0.0,
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
    rust_p95 = region_plan.get("boundary_roundtrip", {}).get("p95_ns")
    callback_p95 = c2_shadow.get("total_shadow_callback", {}).get("p95_ns")
    relative_delta = (sampler_seconds - REFERENCE_SAMPLER_SECONDS) / REFERENCE_SAMPLER_SECONDS
    checks = {
        "source_structural": source_admitted,
        "rust_p95": isinstance(rust_p95, int) and rust_p95 <= RUST_P95_NS_MAX,
        "callback_p95": isinstance(callback_p95, int) and callback_p95 <= CALLBACK_P95_NS_MAX,
        "explicit_cuda_sync_zero": execution.get("explicit_cuda_synchronization_count") == 0,
        "full_tensor_host_copy_zero": c2_shadow.get("full_tensor_host_copy_bytes") == 0,
        "tensor_to_rust_zero": region_plan.get("tensor_bytes_to_rust") == 0,
        "output_integrity": output_integrity_passed,
        "sampler_comparable": abs(relative_delta) <= COMPARABILITY_RELATIVE_LIMIT,
        "admitted_blocks": int(execution.get("admitted_block_count", 0)) >= MIN_ADMITTED_BLOCKS,
        "planned_query_reduction": float(execution.get("planned_query_reduction", 0.0)) >= MIN_PLANNED_QUERY_REDUCTION,
        "affected_steps": len(execution.get("affected_non_anchor_steps", [])) >= MIN_AFFECTED_NON_ANCHOR_STEPS,
        "stable_plan_events": int(execution.get("stable_region_plan_event_count", 0)) >= MIN_STABLE_PLAN_EVENTS,
    }
    if not checks["source_structural"]:
        decision = "A1_ACTIVE_QUERY_STRUCTURALLY_NOT_ADMITTED"
        next_candidate = "KERNEL_NATIVE_VARIABLE_Q_ATTENTION"
    elif not checks["rust_p95"] or not checks["callback_p95"]:
        decision = "A1_CONTROL_PLANE_OVERHEAD_TOO_HIGH"
        next_candidate = "GPU_RESIDENT_PLAN_MASK"
    elif not checks["sampler_comparable"]:
        decision = "A1_ACTIVE_QUERY_PATH_OVERHEAD_TOO_HIGH"
        next_candidate = "KERNEL_NATIVE_PLAN_HOOK"
    elif not (
        checks["admitted_blocks"]
        and checks["planned_query_reduction"]
        and checks["affected_steps"]
        and checks["stable_plan_events"]
    ):
        decision = "A1_REGIONAL_QUERY_OPPORTUNITY_TOO_LOW"
        next_candidate = "COARSE_REGION_ATTENTION_OUTPUT_REUSE"
    elif all(checks.values()):
        decision = "A1_CONTROL_ADMITTED"
        next_candidate = "RUN_CONDITIONAL_SELECTIVE"
    else:
        decision = "A1_CONTROL_REJECTED"
        next_candidate = "FULL_COMPUTE_FALLBACK"
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "decision": decision,
        "next_candidate": next_candidate,
        "sampler_reference_seconds": REFERENCE_SAMPLER_SECONDS,
        "sampler_relative_delta": relative_delta,
        "sampler_relative_limit": COMPARABILITY_RELATIVE_LIMIT,
    }
