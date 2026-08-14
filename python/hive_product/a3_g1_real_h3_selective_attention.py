"""A3-G1 source-only gate for real H3 conditional Attention omission."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json


MECHANISM_ID = "REAL_H3_GPU_CONDITIONAL_ATTENTION_OMISSION_V1"
DECISION_READY = "A3_G1_REAL_H3_SELECTIVE_ACCELERATION_READY_FOR_VISUAL_REVIEW"
DECISION_NOT_CONNECTABLE = "A3_G1_REAL_H3_CONDITIONAL_GRAPH_BODY_NOT_CONNECTABLE"
BLOCKER = (
    "G0_CONDITIONAL_BODIES_ARE_FIXED_SYNTHETIC_KERNELS_AND_EXPOSE_NO_"
    "H3_SDPA_GRAPH_REGISTRATION_OR_CAPTURE_BOUNDARY"
)


def contract_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "a3_g1_real_h3_selective_attention.json"


def fixed_contract() -> dict[str, Any]:
    return json.loads(contract_path().read_text(encoding="utf-8"))


def settings_digest() -> str:
    encoded = json.dumps(fixed_contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def inspect_source_texts(
    *,
    h3_model: str,
    comfy_attention: str,
    g0_cuda: str,
    g0_binding: str,
    g0_header: str,
) -> dict[str, Any]:
    """Evaluate only source topology; this function performs no CUDA or model work."""

    h3_exact_boundary = all(
        marker in h3_model
        for marker in (
            "class Attention",
            "optimized_attention(q, k, v",
            "class DiTBlock",
            "self.attn(h, rope_freqs=rope_freqs",
        )
    )
    standard_sdpa_boundary = all(
        marker in comfy_attention
        for marker in (
            "def attention_pytorch",
            "scaled_dot_product_attention(q, k, v",
            "optimized_attention = attention_pytorch",
        )
    )
    g0_conditional_primitive = all(
        marker in g0_cuda
        for marker in (
            "cudaGraphSetConditional",
            "cudaGraphCondTypeIf",
            "reuse_body_kernel",
            "exact_body_kernel",
        )
    )
    g0_body_is_fixed_synthetic = all(
        marker in g0_cuda
        for marker in ("exact_transform", "std::int32_t", "reinterpret_cast<void*>(exact_body_kernel)")
    )
    exposes_h3_body_registration = all(
        marker in (g0_cuda + g0_binding + g0_header)
        for marker in ("register_h3_attention_child_graph", "accepts_float_qkv")
    )
    exposes_capture_or_child_graph = any(
        marker in (g0_cuda + g0_binding + g0_header)
        for marker in ("cudaGraphAddChildGraphNode", "cudaStreamBeginCapture")
    )
    native_full_delegates_existing_exact = any(
        marker in (g0_cuda + g0_binding)
        for marker in ("scaled_dot_product_attention", "attention_pytorch")
    )
    binding_accepts_only_int32 = (
        "tensor_is_int32" in g0_binding
        and "input must be a torch.int32 CUDA tensor" in g0_binding
        and "run_sequence" in g0_binding
    )

    checks = {
        "actual_h3_exact_attention_boundary_identified": h3_exact_boundary,
        "standard_sage_disabled_backend_boundary_identified": standard_sdpa_boundary,
        "g0_gpu_conditional_primitive_present": g0_conditional_primitive,
        "g0_body_is_not_fixed_synthetic": not g0_body_is_fixed_synthetic,
        "g0_accepts_real_h3_qkv": exposes_h3_body_registration and not binding_accepts_only_int32,
        "g0_can_embed_or_capture_existing_h3_attention_graph": exposes_capture_or_child_graph,
        "native_full_branch_delegates_existing_exact_attention": native_full_delegates_existing_exact,
    }
    passed = all(checks.values())
    return {
        "schema_version": "a3-g1.h3.source-structural-gate.1",
        "mechanism": MECHANISM_ID,
        "settings_digest": settings_digest(),
        "source_sha256": {
            "h3_model": _digest(h3_model),
            "comfy_attention": _digest(comfy_attention),
            "g0_cuda": _digest(g0_cuda),
            "g0_binding": _digest(g0_binding),
            "g0_header": _digest(g0_header),
        },
        "checks": checks,
        "passed": passed,
        "decision": DECISION_READY if passed else DECISION_NOT_CONNECTABLE,
        "blocker": None if passed else BLOCKER,
        "stop_required": not passed,
        "generation_attempt_count": 0,
        "control_generation_count": 0,
        "selective_generation_count": 0,
        "retry_count": 0,
        "model_load_count": 0,
        "cuda_execution_count": 0,
        "claim_boundary": {
            "actual_h3_attention_connected": False,
            "actual_attention_work_omission_proven": False,
            "actual_q_reduction": 0.0,
            "quality_pass": False,
            "runtime_speedup_claim": 0,
            "full_compute_fallback_preserved": True,
            "product_default_changed": False,
        },
    }


def inspect_source_paths(paths: Mapping[str, Path]) -> dict[str, Any]:
    required = {"h3_model", "comfy_attention", "g0_cuda", "g0_binding", "g0_header"}
    if set(paths) != required:
        raise ValueError("A3-G1 source Gate requires the exact five-source boundary")
    return inspect_source_texts(
        **{name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    )


__all__ = [
    "BLOCKER",
    "DECISION_NOT_CONNECTABLE",
    "DECISION_READY",
    "MECHANISM_ID",
    "fixed_contract",
    "inspect_source_paths",
    "inspect_source_texts",
    "settings_digest",
]
