"""Experimental A3-G0 CUDA conditional-omission capability.

Importing this module performs no build, CUDA, model, or network work. The
native extension is built separately by the repository-owned focused builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any
import json
import sys
import tempfile


MECHANISM_ID = "GPU_NATIVE_CONDITIONAL_KERNEL_OMISSION_V1"
REPLAY_SEQUENCE = ("SAFE", "UNSAFE", "SAFE", "UNSAFE")
DECISION_READY = "A3_G0_GPU_CONDITIONAL_OMISSION_READY"


@dataclass(frozen=True)
class GPUConditionalOmissionCapability:
    mechanism: str = MECHANISM_ID
    state: str = "experimental"
    default_enabled: bool = False
    actual_h3_attention_connected: bool = False
    fallback: str = "standard_full_compute"


def contract_path() -> Path:
    return Path(__file__).resolve().parents[2] / "configs" / "a3_g0_gpu_conditional_omission.json"


def fixed_contract() -> dict[str, Any]:
    return json.loads(contract_path().read_text(encoding="utf-8"))


def settings_digest() -> str:
    encoded = json.dumps(fixed_contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _default_build_root() -> Path:
    marker = sha256(f"{sys.version_info[:3]}|{sys.executable}".encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / "hiveframe-a3-g0" / marker


def load_native_extension(build_root: Path | None = None) -> ModuleType:
    """Import a separately built repository-owned extension."""

    root = (build_root or _default_build_root()).resolve()
    lib_root = root / "lib"
    candidates = list(root.glob("hiveframe_a3_g0_cuda*.pyd"))
    candidates += list(lib_root.glob("hiveframe_a3_g0_cuda*.pyd"))
    if len(candidates) != 1:
        raise RuntimeError(
            "A3-G0 requires exactly one prebuilt native module; run the repository-owned "
            "build_native.ps1 in an x64 Visual C++ developer environment"
        )
    module_path = candidates[0]
    spec = spec_from_file_location("hiveframe_a3_g0_cuda", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("A3-G0 native extension import specification is unavailable")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_native_sequence(extension: ModuleType, input_tensor: Any, flags: Any) -> dict[str, Any]:
    """Allocate all buffers before entering the native graph execution island."""

    import torch

    if not input_tensor.is_cuda or input_tensor.dtype != torch.int32 or not input_tensor.is_contiguous():
        raise ValueError("input_tensor must be a contiguous torch.int32 CUDA tensor")
    if flags.device != input_tensor.device or flags.dtype != torch.int32 or flags.numel() != 4:
        raise ValueError("flags must be four torch.int32 values on the input CUDA device")
    options = {"dtype": torch.int32, "device": input_tensor.device}
    outputs = torch.empty((4, input_tensor.numel()), **options)
    reuse_reference = torch.empty_like(input_tensor)
    exact_reference = torch.empty_like(input_tensor)
    parity = torch.zeros(4, **options)
    body_counts = torch.zeros(2, **options)
    branch_history = torch.full((4,), -1, **options)
    launch_index = torch.zeros(1, **options)
    current_stream = torch.cuda.current_stream(input_tensor.device)
    metadata = extension.run_sequence(
        input_tensor,
        flags,
        outputs,
        reuse_reference,
        exact_reference,
        parity,
        body_counts,
        branch_history,
        launch_index,
        int(current_stream.cuda_stream),
    )
    return {
        **metadata,
        "outputs": outputs,
        "reuse_reference": reuse_reference,
        "exact_reference": exact_reference,
        "parity": parity,
        "body_counts": body_counts,
        "branch_history": branch_history,
        "launch_index": launch_index,
    }
