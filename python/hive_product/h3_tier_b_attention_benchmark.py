"""Model-free product-shape ablation for the H3 Tier-B Attention candidate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any, Callable, Sequence

from .h3_tier_b_attention_backend import (
    AttentionBackendCapabilityRegistry,
    CANDIDATE_BACKEND,
    H3ExactAttentionBackendAdapter,
    PRODUCT_HEAD_DIM,
    PRODUCT_HEADS,
    PRODUCT_SEQUENCE_ROWS,
)


PRIOR_SAMPLER_SECONDS = 530.4957820000127
PRIOR_E2E_SECONDS = 636.0106800999492
PRIOR_ATTENTION_KERNEL_SECONDS = 314.55162658691406
PRIOR_ATTENTION_SURFACE_SECONDS = 380.23846793174744
PHYSICAL_VRAM_BYTES = 12_884_377_600
PRIOR_PEAK_VRAM_BYTES = 12_458_231_732


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _gpu_snapshot() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=clocks.current.sm,temperature.gpu,utilization.gpu,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, check=True, text=True, timeout=10)
        values = [part.strip() for part in result.stdout.strip().split(",")]
        return {
            "sm_clock_mhz": int(values[0]),
            "temperature_c": int(values[1]),
            "utilization_percent": int(values[2]),
            "memory_used_mib": int(values[3]),
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as error:
        return {"support_status": "unavailable", "reason": type(error).__name__}


@dataclass
class TimedCall:
    name: str
    start: Any
    end: Any


def _cold_call(torch: Any, operation: Callable[[], Any]) -> tuple[Any, float, float]:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    wall = time.perf_counter()
    start.record()
    output = operation()
    end.record()
    torch.cuda.synchronize()
    return output, float(start.elapsed_time(end)), (time.perf_counter() - wall) * 1_000.0


def _interleaved_timing(
    torch: Any,
    operations: Sequence[tuple[str, Callable[[], Any]]],
    *,
    warmups: int,
    repeats: int,
) -> dict[str, dict[str, Any]]:
    for _, operation in operations:
        for _ in range(warmups):
            operation()
    torch.cuda.synchronize()
    events: list[TimedCall] = []
    launch: dict[str, list[float]] = {name: [] for name, _ in operations}
    for repeat in range(repeats):
        ordered = operations if repeat % 2 == 0 else tuple(reversed(operations))
        for name, operation in ordered:
            start = torch.cuda.Event(enable_timing=True)
            end = torch.cuda.Event(enable_timing=True)
            wall = time.perf_counter()
            start.record()
            operation()
            end.record()
            launch[name].append((time.perf_counter() - wall) * 1_000.0)
            events.append(TimedCall(name, start, end))
    torch.cuda.synchronize()
    cuda: dict[str, list[float]] = {name: [] for name, _ in operations}
    for record in events:
        cuda[record.name].append(float(record.start.elapsed_time(record.end)))
    return {
        name: {
            "warmups": warmups,
            "repeats": repeats,
            "cuda_ms": values,
            "cuda_p50_ms": statistics.median(values),
            "cuda_p95_ms": _percentile(values, 0.95),
            "cpu_launch_p50_ms": statistics.median(launch[name]),
            "cpu_launch_p95_ms": _percentile(launch[name], 0.95),
        }
        for name, values in cuda.items()
    }


def _memory_call(torch: Any, operation: Callable[[], Any]) -> dict[str, int]:
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    start_allocated = int(torch.cuda.memory_allocated())
    start_reserved = int(torch.cuda.memory_reserved())
    allocation_before = int(torch.cuda.memory_stats().get("allocation.all.allocated", 0))
    output = operation()
    torch.cuda.synchronize()
    result = {
        "resident_input_bytes": start_allocated,
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        "incremental_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) - start_allocated,
        "incremental_peak_reserved_bytes": int(torch.cuda.max_memory_reserved()) - start_reserved,
        "allocation_count_delta": int(torch.cuda.memory_stats().get("allocation.all.allocated", 0))
        - allocation_before,
    }
    del output
    torch.cuda.synchronize()
    return result


def _kernel_inventory(torch: Any, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        from torch.profiler import ProfilerActivity, profile

        with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as profiler:
            operation()
            torch.cuda.synchronize()
        events = [
            event
            for event in profiler.events()
            if str(getattr(event, "device_type", "")).endswith("CUDA")
        ]
        names = sorted({str(event.name) for event in events})
        return {"support_status": "collected", "kernel_count": len(events), "kernel_names": names}
    except BaseException as error:
        return {"support_status": "unavailable", "kernel_count": None, "reason": type(error).__name__}


def _efficient_operation(torch: Any, q: Any, k: Any, v: Any) -> Any:
    from torch.nn.attention import SDPBackend, sdpa_kernel

    with sdpa_kernel(SDPBackend.EFFICIENT_ATTENTION):
        out = torch.nn.functional.scaled_dot_product_attention(
            q, k, v, attn_mask=None, dropout_p=0.0, is_causal=False
        )
    return out.transpose(1, 2).reshape(1, PRODUCT_SEQUENCE_ROWS, PRODUCT_HEADS * PRODUCT_HEAD_DIM)


def run_benchmark(torch: Any, baseline: Callable[..., Any], *, warmups: int, repeats: int) -> dict[str, Any]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the Tier-B product-shape ablation")
    torch.manual_seed(101)
    shape = (1, PRODUCT_HEADS, PRODUCT_SEQUENCE_ROWS, PRODUCT_HEAD_DIM)
    q = torch.randn(shape, device="cuda", dtype=torch.bfloat16)
    k = torch.randn_like(q)
    v = torch.randn_like(q)
    adapter = H3ExactAttentionBackendAdapter(torch_module=torch, baseline=baseline)

    def baseline_call() -> Any:
        return baseline(
            q,
            k,
            v,
            PRODUCT_HEADS,
            mask=None,
            skip_reshape=True,
            transformer_options={},
        )

    def candidate_call() -> Any:
        return adapter.execute(CANDIDATE_BACKEND, q, k, v, PRODUCT_HEADS)[0]

    def efficient_call() -> Any:
        return _efficient_operation(torch, q, k, v)

    before = _gpu_snapshot()
    cold: dict[str, Any] = {}
    for name, operation in (
        ("attention_pytorch", baseline_call),
        (CANDIDATE_BACKEND, candidate_call),
        ("efficient_sdpa_alternative", efficient_call),
    ):
        output, cuda_ms, wall_ms = _cold_call(torch, operation)
        cold[name] = {"cuda_ms": cuda_ms, "wall_ms": wall_ms, "compile_time_ms": 0.0}
        del output
    timing = _interleaved_timing(
        torch,
        (
            ("attention_pytorch", baseline_call),
            (CANDIDATE_BACKEND, candidate_call),
            ("efficient_sdpa_alternative", efficient_call),
        ),
        warmups=warmups,
        repeats=repeats,
    )

    baseline_output = baseline_call()
    candidate_output, candidate_receipt = adapter.execute(
        CANDIDATE_BACKEND, q, k, v, PRODUCT_HEADS
    )
    torch.cuda.synchronize()
    difference = (baseline_output - candidate_output).abs()
    parity = {
        "shape_equal": tuple(baseline_output.shape) == tuple(candidate_output.shape),
        "dtype_equal": baseline_output.dtype == candidate_output.dtype,
        "device_equal": baseline_output.device == candidate_output.device,
        "bitwise_equal": bool(torch.equal(baseline_output, candidate_output)),
        "max_abs_error": float(difference.max().item()),
        "mean_abs_error": float(difference.float().mean().item()),
        "nonfinite_count": int((~torch.isfinite(candidate_output)).sum().item()),
    }
    del difference, baseline_output, candidate_output
    torch.cuda.synchronize()

    memory = {
        "attention_pytorch": _memory_call(torch, baseline_call),
        CANDIDATE_BACKEND: _memory_call(torch, candidate_call),
        "efficient_sdpa_alternative": _memory_call(torch, efficient_call),
    }
    kernels = {
        "attention_pytorch": _kernel_inventory(torch, baseline_call),
        CANDIDATE_BACKEND: _kernel_inventory(torch, candidate_call),
        "efficient_sdpa_alternative": _kernel_inventory(torch, efficient_call),
    }
    after = _gpu_snapshot()

    baseline_p50 = timing["attention_pytorch"]["cuda_p50_ms"]
    candidate_p50 = timing[CANDIDATE_BACKEND]["cuda_p50_ms"]
    ratio = candidate_p50 / baseline_p50
    saved_kernel_seconds = PRIOR_ATTENTION_KERNEL_SECONDS * (1.0 - ratio)
    predicted_sampler_reduction = saved_kernel_seconds / PRIOR_SAMPLER_SECONDS
    predicted_e2e_reduction = saved_kernel_seconds / PRIOR_E2E_SECONDS
    candidate_workspace_delta = max(
        0,
        memory[CANDIDATE_BACKEND]["incremental_peak_reserved_bytes"]
        - memory["attention_pytorch"]["incremental_peak_reserved_bytes"],
    )
    admission_checks = {
        "baseline_parity": all(
            parity[name]
            for name in ("shape_equal", "dtype_equal", "device_equal", "bitwise_equal")
        ),
        "candidate_nonfinite_zero": parity["nonfinite_count"] == 0,
        "candidate_fallback_zero": candidate_receipt["fallback_count"] == 0,
        "candidate_full_q_100_percent": candidate_receipt["full_q_percent"] == 100,
        "candidate_full_kv_100_percent": candidate_receipt["full_kv_percent"] == 100,
        "candidate_omission_zero": candidate_receipt["attention_omission_count"] == 0,
        "p95_backend_regression_zero": timing[CANDIDATE_BACKEND]["cuda_p95_ms"]
        <= timing["attention_pytorch"]["cuda_p95_ms"],
        "incremental_workspace_within_256_mib": candidate_workspace_delta <= 256 * 1024 * 1024,
        "prior_physical_headroom_at_least_256_mib": PHYSICAL_VRAM_BYTES - PRIOR_PEAK_VRAM_BYTES
        >= 256 * 1024 * 1024,
        "predicted_sampler_reduction_at_least_10_percent": predicted_sampler_reduction >= 0.10,
        "predicted_e2e_reduction_at_least_10_percent": predicted_e2e_reduction >= 0.10,
    }
    admission_passed = all(admission_checks.values())
    return {
        "schema_version": "h3.tier-b-attention-ablation.1",
        "task": "H3_TIER_B_EXACT_ATTENTION_BACKEND_QKV_ROPE_OUT_FUSION_AB",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "torch": str(torch.__version__),
            "cuda": str(torch.version.cuda),
            "device": torch.cuda.get_device_name(0),
            "compute_capability": list(torch.cuda.get_device_capability(0)),
            "dtype": "torch.bfloat16",
            "shape": list(shape),
            "before": before,
            "after": after,
        },
        "cold_first_use": cold,
        "warm_interleaved": timing,
        "memory": memory,
        "kernel_inventory": kernels,
        "parity": parity,
        "candidate_receipt": candidate_receipt,
        "capability_manifest": AttentionBackendCapabilityRegistry().capability_manifest(),
        "ablations": {
            "A0": {"component": "baseline attention_pytorch", "status": "MEASURED"},
            "A1": {
                "component": "QKV projection and packing only",
                "status": "NO_DISTINCT_CANDIDATE",
                "reason": "installed H3 already uses one packed projection; split and views launch no kernels",
            },
            "A2": {
                "component": "Q/K RoPE only",
                "status": "NO_DISTINCT_CANDIDATE",
                "reason": "installed H3 already uses fused in-place CK RMSNorm plus RoPE",
            },
            "A3": {
                "component": "Attention backend only",
                "status": "MEASURED",
                "direct_cudnn": CANDIDATE_BACKEND,
                "distinct_efficient_alternative": "efficient_sdpa_alternative",
            },
            "A4": {
                "component": "output transform and projection only",
                "status": "NO_DISTINCT_CANDIDATE",
                "reason": "no safe fused projection kernel exists in the installed stack; Standard reshape is retained",
            },
            "A5": {
                "component": "combined h3_exact_fused_v1",
                "status": "NOT_A_FUSION_CANDIDATE",
                "reason": "only direct cuDNN dispatch is implemented; manifest fusion_claimed is false",
            },
        },
        "projection": {
            "prior_attention_surface_seconds": PRIOR_ATTENTION_SURFACE_SECONDS,
            "prior_attention_kernel_seconds": PRIOR_ATTENTION_KERNEL_SECONDS,
            "candidate_to_baseline_p50_ratio": ratio,
            "predicted_kernel_seconds_saved": saved_kernel_seconds,
            "predicted_sampler_reduction_fraction": predicted_sampler_reduction,
            "predicted_e2e_reduction_fraction": predicted_e2e_reduction,
        },
        "admission": {"checks": admission_checks, "passed": admission_passed},
        "generation": {
            "baseline_submissions": 0,
            "candidate_submissions": 0,
            "retry": 0,
            "gpu_generation_count": 0,
        },
        "decision": (
            "ADMISSION_READY_FOR_FIXED_AB"
            if admission_passed
            else "H3_TIER_B_FUSION_KERNEL_NOT_VIABLE"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repeats", type=int, default=8)
    args = parser.parse_args()

    import torch
    from comfy.ldm.modules.attention import attention_pytorch

    report = run_benchmark(
        torch, attention_pytorch, warmups=args.warmups, repeats=args.repeats
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "admission": report["admission"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
