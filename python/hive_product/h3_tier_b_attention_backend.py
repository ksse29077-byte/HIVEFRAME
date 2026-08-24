"""Exact Full Attention capability contract for the bounded H3 Tier-B probe.

The candidate deliberately keeps every Q, K, and V row.  It only removes the
generic ComfyUI dispatch layer around the same cuDNN SDPA primitive.  The
manifest therefore does not claim QKV, RoPE, projection, or residual fusion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import inspect
from typing import Any, Callable, Mapping


BASELINE_BACKEND = "attention_pytorch"
CANDIDATE_BACKEND = "h3_exact_fused_v1"
PRODUCT_SEQUENCE_ROWS = 15_424
PRODUCT_HEADS = 56
PRODUCT_HEAD_DIM = 128


@dataclass(frozen=True)
class AttentionBackendManifest:
    """Immutable capability declaration used before backend selection."""

    name: str
    version: str
    device_types: tuple[str, ...]
    dtypes: tuple[str, ...]
    sequence_rows: tuple[int, ...]
    heads: tuple[int, ...]
    head_dims: tuple[int, ...]
    layouts: tuple[str, ...]
    semantics: str
    compile_required: bool
    cache_required: bool
    maximum_incremental_workspace_bytes: int
    fallback_backend: str | None
    quality_contract: str
    timing_counters: tuple[str, ...]
    implemented_components: tuple[str, ...]
    implementation_digest: str
    full_q_percent: int = 100
    full_kv_percent: int = 100
    omission_enabled: bool = False
    fusion_claimed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttentionBackendRequest:
    """Runtime facts required for fail-closed capability admission."""

    name: str
    device_type: str
    dtype: str
    sequence_rows: int
    heads: int
    head_dim: int
    layout: str
    mask_present: bool
    causal: bool
    dropout_p: float


@dataclass(frozen=True)
class AttentionBackendSelection:
    """Result of resolving one requested backend against its manifest."""

    requested: str
    selected: str
    admitted: bool
    fallback_reason: str | None
    manifest: AttentionBackendManifest


def _implementation_digest(callable_: Callable[..., Any]) -> str:
    source = inspect.getsource(callable_).encode("utf-8")
    return sha256(source).hexdigest()


def _candidate_sdpa(torch_module: Any, q: Any, k: Any, v: Any) -> Any:
    from torch.nn.attention import SDPBackend, sdpa_kernel

    with sdpa_kernel(SDPBackend.CUDNN_ATTENTION):
        return torch_module.nn.functional.scaled_dot_product_attention(
            q,
            k,
            v,
            attn_mask=None,
            dropout_p=0.0,
            is_causal=False,
        )


def default_manifests() -> tuple[AttentionBackendManifest, ...]:
    """Return the frozen baseline and bounded candidate capability manifests."""

    timing = (
        "cuda_p50_ms",
        "cuda_p95_ms",
        "cpu_launch_p50_ms",
        "kernel_count",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
    )
    exact_quality = (
        "same Full Attention semantics; shape/dtype/device parity; finite output; "
        "no quality threshold relaxation"
    )
    return (
        AttentionBackendManifest(
            name=BASELINE_BACKEND,
            version="installed-comfyui",
            device_types=("cuda",),
            dtypes=("torch.bfloat16",),
            sequence_rows=(PRODUCT_SEQUENCE_ROWS,),
            heads=(PRODUCT_HEADS,),
            head_dims=(PRODUCT_HEAD_DIM,),
            layouts=("BHSD",),
            semantics="exact full scaled dot product attention",
            compile_required=False,
            cache_required=False,
            maximum_incremental_workspace_bytes=0,
            fallback_backend=None,
            quality_contract=exact_quality,
            timing_counters=timing,
            implemented_components=("installed_comfyui_attention_dispatch",),
            implementation_digest="installed-source-gated",
        ),
        AttentionBackendManifest(
            name=CANDIDATE_BACKEND,
            version="1",
            device_types=("cuda",),
            dtypes=("torch.bfloat16",),
            sequence_rows=(PRODUCT_SEQUENCE_ROWS,),
            heads=(PRODUCT_HEADS,),
            head_dims=(PRODUCT_HEAD_DIM,),
            layouts=("BHSD",),
            semantics="exact full noncausal SDPA with zero dropout and no mask",
            compile_required=False,
            cache_required=False,
            maximum_incremental_workspace_bytes=256 * 1024 * 1024,
            fallback_backend=BASELINE_BACKEND,
            quality_contract=exact_quality,
            timing_counters=timing,
            implemented_components=("direct_cudnn_sdpa_dispatch", "standard_output_reshape"),
            implementation_digest=_implementation_digest(_candidate_sdpa),
            fusion_claimed=False,
        ),
    )


class AttentionBackendCapabilityRegistry:
    """Small extensible registry that resolves one mutually exclusive backend."""

    def __init__(self, manifests: tuple[AttentionBackendManifest, ...] | None = None) -> None:
        entries = default_manifests() if manifests is None else manifests
        self._manifests = {manifest.name: manifest for manifest in entries}
        if BASELINE_BACKEND not in self._manifests:
            raise ValueError("attention_pytorch baseline manifest is required")

    def manifest(self, name: str) -> AttentionBackendManifest:
        return self._manifests[name]

    def resolve(self, request: AttentionBackendRequest) -> AttentionBackendSelection:
        manifest = self._manifests.get(request.name)
        if manifest is None:
            baseline = self._manifests[BASELINE_BACKEND]
            return AttentionBackendSelection(
                request.name, BASELINE_BACKEND, False, "BACKEND_NOT_REGISTERED", baseline
            )
        checks = (
            (request.device_type in manifest.device_types, "UNSUPPORTED_DEVICE"),
            (request.dtype in manifest.dtypes, "UNSUPPORTED_DTYPE"),
            (request.sequence_rows in manifest.sequence_rows, "UNSUPPORTED_SEQUENCE"),
            (request.heads in manifest.heads, "UNSUPPORTED_HEADS"),
            (request.head_dim in manifest.head_dims, "UNSUPPORTED_HEAD_DIM"),
            (request.layout in manifest.layouts, "UNSUPPORTED_LAYOUT"),
            (not request.mask_present, "MASK_UNSUPPORTED"),
            (request.causal is False, "CAUSAL_UNSUPPORTED"),
            (request.dropout_p == 0.0, "DROPOUT_UNSUPPORTED"),
        )
        for passed, reason in checks:
            if not passed:
                fallback = manifest.fallback_backend or BASELINE_BACKEND
                return AttentionBackendSelection(
                    request.name, fallback, False, reason, self._manifests[fallback]
                )
        return AttentionBackendSelection(request.name, manifest.name, True, None, manifest)

    def capability_manifest(self) -> dict[str, Mapping[str, Any]]:
        return {name: manifest.to_dict() for name, manifest in self._manifests.items()}


class H3ExactAttentionBackendAdapter:
    """Execute the bounded exact candidate or immediately use Standard fallback."""

    def __init__(
        self,
        *,
        torch_module: Any,
        baseline: Callable[..., Any],
        candidate: Callable[[Any, Any, Any, Any], Any] = _candidate_sdpa,
        registry: AttentionBackendCapabilityRegistry | None = None,
    ) -> None:
        self.torch = torch_module
        self.baseline = baseline
        self.candidate = candidate
        self.registry = registry or AttentionBackendCapabilityRegistry()
        self.fallback_count = 0
        self.candidate_call_count = 0
        self.baseline_call_count = 0

    @staticmethod
    def _request(name: str, q: Any, mask: Any, heads: int) -> AttentionBackendRequest:
        shape = tuple(int(value) for value in q.shape)
        device = getattr(q, "device", None)
        return AttentionBackendRequest(
            name=name,
            device_type=str(getattr(device, "type", device)),
            dtype=str(q.dtype),
            sequence_rows=shape[2] if len(shape) == 4 else -1,
            heads=heads,
            head_dim=shape[3] if len(shape) == 4 else -1,
            layout="BHSD" if len(shape) == 4 else "UNKNOWN",
            mask_present=mask is not None,
            causal=False,
            dropout_p=0.0,
        )

    def _fallback(
        self,
        q: Any,
        k: Any,
        v: Any,
        heads: int,
        *,
        mask: Any,
        transformer_options: Mapping[str, Any] | None,
    ) -> Any:
        self.baseline_call_count += 1
        return self.baseline(
            q,
            k,
            v,
            heads,
            mask=mask,
            skip_reshape=True,
            transformer_options={} if transformer_options is None else transformer_options,
        )

    def execute(
        self,
        backend_name: str,
        q: Any,
        k: Any,
        v: Any,
        heads: int,
        *,
        mask: Any = None,
        transformer_options: Mapping[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        request = self._request(backend_name, q, mask, heads)
        selection = self.registry.resolve(request)
        receipt = {
            "requested_backend": backend_name,
            "selected_backend": selection.selected,
            "admitted": selection.admitted,
            "fallback_reason": selection.fallback_reason,
            "fallback_count": self.fallback_count,
            "call_position": self.candidate_call_count + self.baseline_call_count,
            "manifest_digest": selection.manifest.implementation_digest,
            "full_q_percent": 100,
            "full_kv_percent": 100,
            "selective_enabled": False,
            "partial_q_enabled": False,
            "attention_omission_count": 0,
        }
        if not selection.admitted or selection.selected == BASELINE_BACKEND:
            if backend_name != BASELINE_BACKEND:
                self.fallback_count += 1
            output = self._fallback(
                q, k, v, heads, mask=mask, transformer_options=transformer_options
            )
            receipt["fallback_count"] = self.fallback_count
            return output, receipt
        q_contract = (tuple(q.shape), str(q.dtype), str(getattr(q.device, "type", q.device)))
        if any(
            (tuple(tensor.shape), str(tensor.dtype), str(getattr(tensor.device, "type", tensor.device)))
            != q_contract
            for tensor in (k, v)
        ):
            self.fallback_count += 1
            receipt["admitted"] = False
            receipt["selected_backend"] = BASELINE_BACKEND
            receipt["fallback_reason"] = "QKV_CONTRACT_MISMATCH"
            receipt["fallback_count"] = self.fallback_count
            output = self._fallback(
                q, k, v, heads, mask=mask, transformer_options=transformer_options
            )
            return output, receipt
        try:
            out = self.candidate(self.torch, q, k, v)
            batch, _, sequence, head_dim = q.shape
            output = out.transpose(1, 2).reshape(batch, sequence, heads * head_dim)
            self.candidate_call_count += 1
            return output, receipt
        except Exception as error:
            self.fallback_count += 1
            receipt["admitted"] = False
            receipt["selected_backend"] = BASELINE_BACKEND
            receipt["fallback_reason"] = f"NATIVE_ERROR:{type(error).__name__}"
            receipt["fallback_count"] = self.fallback_count
            output = self._fallback(
                q, k, v, heads, mask=mask, transformer_options=transformer_options
            )
            return output, receipt


__all__ = [
    "AttentionBackendCapabilityRegistry",
    "AttentionBackendManifest",
    "AttentionBackendRequest",
    "AttentionBackendSelection",
    "BASELINE_BACKEND",
    "CANDIDATE_BACKEND",
    "H3ExactAttentionBackendAdapter",
    "PRODUCT_HEAD_DIM",
    "PRODUCT_HEADS",
    "PRODUCT_SEQUENCE_ROWS",
    "default_manifests",
]
