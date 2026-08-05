"""Lazy, injectable MiniMax H3 pipeline boundary.

Importing this module never imports torch/diffusers and never touches a model.
The default loader is used only after an operator configures and admits a local
artifact in a separately approved task.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import importlib
import os
import sys

from .contracts import BackendFailure


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LocalH3Config:
    model_source: str | None
    revision: str | None
    local_enabled: bool
    local_files_only: bool
    dtype: str
    device_map: str
    trust_remote_code: bool
    model_root: str | None

    @classmethod
    def from_env(cls) -> "LocalH3Config":
        return cls(
            model_source=os.environ.get("HIVEFRAME_H3_MODEL_SOURCE") or None,
            revision=os.environ.get("HIVEFRAME_H3_MODEL_REVISION") or None,
            local_enabled=_env_bool("HIVEFRAME_H3_LOCAL_ENABLED", False),
            local_files_only=_env_bool("HIVEFRAME_H3_LOCAL_FILES_ONLY", True),
            dtype=os.environ.get("HIVEFRAME_H3_DTYPE", "bfloat16"),
            device_map=os.environ.get("HIVEFRAME_H3_DEVICE_MAP", "auto"),
            trust_remote_code=_env_bool("HIVEFRAME_H3_TRUST_REMOTE_CODE", False),
            model_root=os.environ.get("HIVEFRAME_H3_MODEL_ROOT") or None,
        )

    def public_status(self) -> dict[str, Any]:
        return {
            "model_source": "configured" if self.model_source else "not_configured",
            "revision": "configured" if self.revision else "not_configured",
            "model_root": "configured" if self.model_root else "not_configured",
            "local_enabled": self.local_enabled,
            "local_files_only": self.local_files_only,
            "dtype": self.dtype if self.dtype in {"bfloat16", "float16", "float32"} else "invalid",
            "device_map": self.device_map if self.device_map else "invalid",
            "trust_remote_code": self.trust_remote_code,
        }

    def resolve_local_source(self) -> Path | None:
        """Resolve an existing path or revision-pinned HF cache snapshot offline."""
        if not self.model_source:
            return None
        direct = Path(self.model_source).expanduser()
        if direct.is_dir():
            return direct.resolve()
        if "/" not in self.model_source or not self.revision:
            return None
        cache_root = os.environ.get("HF_HUB_CACHE")
        if cache_root:
            hub = Path(cache_root).expanduser()
        else:
            hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")).expanduser()
            hub = hf_home / "hub"
        repository = "models--" + self.model_source.replace("/", "--")
        snapshot = hub / repository / "snapshots" / self.revision
        return snapshot.resolve() if snapshot.is_dir() else None


class LocalPipelineFactory:
    """One coarse factory boundary, with optional fake injection for tests."""

    def __init__(self, loader: Callable[..., Any] | None = None) -> None:
        self._loader = loader

    def create(
        self,
        *,
        model_source: str | None,
        revision: str | None,
        dtype: str,
        device_map: str,
        local_files_only: bool,
        trust_remote_code: bool,
        resolved_local_source: Path | None = None,
    ) -> Any:
        if not model_source:
            raise BackendFailure("model_source_not_configured", "Local H3 model source is not configured.")
        if not local_files_only:
            raise BackendFailure("runtime_incompatible", "Automatic model download is disabled in P0-LR.")
        if local_files_only:
            if resolved_local_source is None:
                raise BackendFailure("artifact_not_found", "The configured local H3 artifact is not available.")
        if self._loader is not None:
            try:
                return self._loader(
                    model_source=model_source,
                    revision=revision,
                    dtype=dtype,
                    device_map=device_map,
                    local_files_only=local_files_only,
                    trust_remote_code=trust_remote_code,
                    resolved_local_source=resolved_local_source,
                )
            except BackendFailure:
                raise
            except Exception as error:
                raise BackendFailure("model_load_failed", "The injected Local H3 pipeline could not be loaded.") from error

        # This is the single provisional future integration point. It is not
        # reached while P0 is artifact_pending and was not invoked by this task.
        try:
            torch = importlib.import_module("torch")
            diffusers = importlib.import_module("diffusers")
        except (ImportError, OSError) as error:
            raise BackendFailure("runtime_unavailable", "The Local H3 runtime is unavailable.") from error
        resolved_dtype = getattr(torch, dtype, None)
        if resolved_dtype is None:
            raise BackendFailure("runtime_incompatible", "The configured Local H3 dtype is unsupported.")
        try:
            return diffusers.DiffusionPipeline.from_pretrained(
                str(resolved_local_source) if resolved_local_source is not None else model_source,
                revision=None if resolved_local_source is not None else revision,
                dtype=resolved_dtype,
                device_map=device_map,
                local_files_only=True,
                trust_remote_code=trust_remote_code,
            )
        except Exception as error:
            raise BackendFailure("model_load_failed", "The configured Local H3 model could not be loaded.") from error


def release_optional_cuda_cache() -> None:
    """Release an existing torch CUDA cache without importing torch."""
    torch = sys.modules.get("torch")
    cuda = getattr(torch, "cuda", None) if torch is not None else None
    if cuda is None:
        return
    try:
        if cuda.is_available():
            cuda.empty_cache()
    except Exception:
        # Unload must remain safe on CPU-only or partially initialized runtimes.
        return
