"""Focused A3-G0 synthetic CUDA conditional-omission probe."""

from __future__ import annotations

from array import array
from hashlib import sha256
from pathlib import Path
from typing import Any
import argparse
import json
import sys

from .gpu_conditional_omission import (
    DECISION_READY,
    GPUConditionalOmissionCapability,
    REPLAY_SEQUENCE,
    load_native_extension,
    run_native_sequence,
    fixed_contract,
    settings_digest,
)


def _tensor_digest(tensor: Any) -> str:
    values = array("i", tensor.detach().cpu().contiguous().tolist())
    return sha256(values.tobytes()).hexdigest()


def run_probe(*, build_root: Path | None = None) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("A3-G0 requires the admitted PyTorch CUDA runtime")
    device = torch.device("cuda:0")
    input_tensor = torch.arange(4096, dtype=torch.int32, device=device)
    flags = torch.tensor([1, 0, 1, 0], dtype=torch.int32, device=device)
    extension = load_native_extension(build_root)
    result = run_native_sequence(extension, input_tensor, flags)

    counts = result["body_counts"].cpu().tolist()
    history = result["branch_history"].cpu().tolist()
    parity = result["parity"].cpu().tolist()
    launch_index = result["launch_index"].cpu().tolist()[0]
    output_digests = [_tensor_digest(result["outputs"][index]) for index in range(4)]
    reuse_digest = _tensor_digest(result["reuse_reference"])
    exact_digest = _tensor_digest(result["exact_reference"])
    safe_reference_bit_exact = output_digests[0] == reuse_digest and output_digests[2] == reuse_digest
    unsafe_bit_exact = output_digests[1] == exact_digest and output_digests[3] == exact_digest
    omission_proven = counts == [2, 2] and history == [0, 1, 0, 1] and launch_index == 4
    decision = (
        DECISION_READY
        if omission_proven and safe_reference_bit_exact and unsafe_bit_exact and parity == [0, 0, 0, 0]
        else "A3_G0_KERNEL_OMISSION_NOT_PROVEN"
    )
    capability = GPUConditionalOmissionCapability()
    return {
        "schema_version": "a3-g0.conditional-omission-evidence.1",
        "settings_digest": settings_digest(),
        "contract": fixed_contract(),
        "environment": {
            "python": sys.version.split()[0],
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability(0)),
        },
        "integration": {
            "same_device": True,
            "same_context": True,
            "current_pytorch_stream": bool(result["current_pytorch_stream_used"]),
            "separate_cuda_context_created": bool(result["separate_cuda_context_created"]),
            "redundant_tensor_copy_bytes": 0,
            "host_materialization_in_hot_path": False,
        },
        "replay": {
            "sequence": list(REPLAY_SEQUENCE),
            "graph_launch_count": int(result["graph_launch_count"]),
            "reuse_body_execution_count": counts[0],
            "exact_body_execution_count": counts[1],
            "branch_history": history,
            "launch_index": launch_index,
            "branch_state_leak": history != [0, 1, 0, 1],
        },
        "parity": {
            "device_parity_flags": parity,
            "safe_reference_bit_exact": safe_reference_bit_exact,
            "unsafe_exact_control_bit_exact": unsafe_bit_exact,
            "safe_output_sha256": [output_digests[0], output_digests[2]],
            "unsafe_output_sha256": [output_digests[1], output_digests[3]],
            "reuse_reference_sha256": reuse_digest,
            "exact_reference_sha256": exact_digest,
        },
        "synchronization": {
            "guard_d2h_bytes": 0,
            "host_guard_read_count": 0,
            "explicit_hot_path_cpu_sync_count": int(result["explicit_hot_path_cpu_sync_count"]),
            "final_evidence_sync_count": int(result["final_evidence_sync_count"]),
        },
        "memory": {
            "conditional_body_allocation_count": int(result["conditional_body_allocation_count"]),
            "conditional_body_free_count": 0,
            "required_buffers_preallocated": True,
        },
        "counter_semantics": "body_execution_evidence_not_directly_measured_kernel_launch_count",
        "capability": {
            "state": capability.state,
            "default_enabled": capability.default_enabled,
            "actual_h3_attention_connected": capability.actual_h3_attention_connected,
            "fallback": capability.fallback,
        },
        "model_load_count": 0,
        "generation_count": 0,
        "actual_h3_attention_omission_count": 0,
        "speedup_claim": 0,
        "quality_success": False,
        "product_promotion": 0,
        "decision": decision,
        "disposition": "INTEGRATE" if decision == DECISION_READY else "DROP_FOR_CURRENT_STACK",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path)
    args = parser.parse_args(argv)
    result = run_probe(build_root=args.build_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["decision"] == DECISION_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
