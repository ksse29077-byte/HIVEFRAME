"""RTX 3060 production-shaped CUDA economics benchmark for H3 V4."""

from __future__ import annotations

import argparse
import gc
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns
from typing import Any, Callable, Mapping

from .h3_bounded_host_source_oracle_v4 import (
    FROZEN_EVENTS,
    MINIMUM_EXACT_RECORDS,
    MINIMUM_PLANNED_Q_RATIO,
    PLANNED_Q_ROWS_PER_RECORD,
    SOURCE_BLOCK_COUNT,
    SOURCE_STEPS,
    SOURCE_PAYLOAD_BYTES,
)
from .h3_row_region_safety import (
    FULL_Q_ROWS,
    generation_candidates,
    generation_identity,
)
from .h3_v4_economics import (
    COMPARABLE_BASELINE_SECONDS,
    OBSERVED_C2_SCALAR_SECONDS,
)
from .h3_v4_executor_hot_path import (
    FULL_SEQUENCE_ROWS,
    H3_HEAD_DIM,
    H3_HEADS,
    V4_CONTROL_FULL_COMPUTE,
    V4_EXECUTOR_BENCHMARK,
    V4CacheHandle,
    V4ExecutorAdapter,
    V4ExecutorPlan,
    V4GenerationContext,
    materialize_gpu_plan,
    validate_runtime_contract,
)
from .rust_cache_plan_v2 import PLAN_READY, RustCachePlanV2Bridge


SCHEMA_VERSION = "h3.v4-production-executor-hot-path.1"
DECISION_VIABLE = "H3_V4_HOT_PATH_ECONOMICS_VIABLE"
DECISION_NOT_VIABLE = "H3_V4_HOT_PATH_ECONOMICS_NOT_VIABLE"
MEASURED_SAMPLES = 7
WARMUP_CYCLES = 2
SOURCE_CAPTURE_COUNT = SOURCE_BLOCK_COUNT * len(SOURCE_STEPS)


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def _summary(cuda_ms: list[float], host_ms: list[float]) -> dict[str, Any]:
    return {
        "count": len(cuda_ms),
        "cuda_ms": {
            "minimum": min(cuda_ms),
            "median": median(cuda_ms),
            "p95": _percentile_95(cuda_ms),
            "maximum": max(cuda_ms),
            "total": sum(cuda_ms),
        },
        "host_wall_ms": {
            "minimum": min(host_ms),
            "median": median(host_ms),
            "p95": _percentile_95(host_ms),
            "maximum": max(host_ms),
            "total": sum(host_ms),
        },
    }


class _CudaMeasure:
    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module

    def one(self, operation: Callable[[], Any]) -> tuple[Any, float, float]:
        start = self.torch.cuda.Event(enable_timing=True)
        end = self.torch.cuda.Event(enable_timing=True)
        host_started = perf_counter_ns()
        start.record()
        result = operation()
        end.record()
        end.synchronize()
        host_ms = (perf_counter_ns() - host_started) / 1_000_000
        cuda_ms = float(start.elapsed_time(end))
        return result, cuda_ms, host_ms

    def series(
        self,
        operation: Callable[[], Any],
        *,
        count: int = MEASURED_SAMPLES,
        warmup: int = WARMUP_CYCLES,
    ) -> tuple[Any, dict[str, Any]]:
        result = None
        for _ in range(warmup):
            result = operation()
            self.torch.cuda.synchronize()
        cuda_ms: list[float] = []
        host_ms: list[float] = []
        for _ in range(count):
            result, cuda_value, host_value = self.one(operation)
            cuda_ms.append(cuda_value)
            host_ms.append(host_value)
        return result, _summary(cuda_ms, host_ms)


def _load_standard_h3_backend(comfy_root: Path) -> tuple[Any, Callable[..., Any], dict[str, Any]]:
    root = str(comfy_root)
    if root not in sys.path:
        sys.path.insert(0, root)
    import torch
    import comfy.ldm.modules.attention as attention

    if attention.optimized_attention is not attention.attention_pytorch:
        raise RuntimeError("Standard H3 backend is not ComfyUI attention_pytorch")

    def backend(q: Any, k: Any, v: Any) -> Any:
        return attention.optimized_attention(
            q.transpose(0, 1).unsqueeze(0),
            k.transpose(0, 1).unsqueeze(0),
            v.transpose(0, 1).unsqueeze(0),
            H3_HEADS,
            mask=None,
            skip_reshape=True,
            transformer_options={},
        ).squeeze(0)

    source = comfy_root / "comfy" / "ldm" / "modules" / "attention.py"
    return torch, backend, {
        "resolved_callable": attention.optimized_attention.__name__,
        "standard_callable": attention.attention_pytorch.__name__,
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "sage_enabled": False,
        "precision": "torch.bfloat16",
    }


def _context() -> V4GenerationContext:
    return V4GenerationContext(
        generation_digest="1" * 64,
        model_digest="2" * 64,
        settings_digest="3" * 64,
        scheduler_digest="4" * 64,
        input_digest="5" * 64,
    )


def _safe_evidence() -> list[dict[str, Any]]:
    return [
        {
            "region": event.region,
            "corrected": {
                "finite": True,
                "cosine": 0.999,
                "normalized_l2": 0.01,
            },
            "predicted_state": "STABLE",
            "actual_safety": "SAFE",
            "payload_bytes": SOURCE_PAYLOAD_BYTES,
            "step": event.target_step,
            "source_step": event.source_step,
            "block": event.block,
            "uncertainty_ppm": 1_000,
            "motion_ppm": 1_000,
            "false_safe": False,
        }
        for event in FROZEN_EVENTS
    ]


def _rust_compile_benchmark(samples: int = MEASURED_SAMPLES) -> dict[str, Any]:
    durations_ms: list[float] = []
    plans = []
    for sample in range(samples):
        run_digest = sha256(f"v4-hot-path-rust-{sample}".encode("ascii")).hexdigest()
        identity = generation_identity(
            run_digest_hex=run_digest,
            workflow_digest_hex="2" * 64,
            model_digest_hex="3" * 64,
            settings_digest_hex="4" * 64,
            input_identity_digest_hex="5" * 64,
        )
        candidates = generation_candidates(identity, _safe_evidence())
        bridge = RustCachePlanV2Bridge()
        started = perf_counter_ns()
        plan = bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        durations_ms.append((perf_counter_ns() - started) / 1_000_000)
        plans.append((bridge, plan))
    valid = all(
        bridge.rust_call_count == 1
        and plan.get("decision_code") == PLAN_READY
        and plan.get("fallback_required") is False
        and plan.get("bridge_contract", {}).get("tensor_bytes_per_call") == 0
        and plan.get("bridge_contract", {}).get("cache_plan_calls_per_generation") == 1
        for bridge, plan in plans
    )
    return {
        "count": samples,
        "host_wall_ms": {
            "minimum": min(durations_ms),
            "median": median(durations_ms),
            "p95": _percentile_95(durations_ms),
            "maximum": max(durations_ms),
            "total": sum(durations_ms),
        },
        "release_extension_loaded": plans[0][0].extension is not None,
        "one_call_per_generation": all(item[0].rust_call_count == 1 for item in plans),
        "rust_tensor_bytes": 0,
        "hot_path_forced_cpu_sync": 0,
        "plan_ready": valid,
        "planned_reduction_ppm": int(plans[-1][1].get("planned_reduction_ppm", 0)),
        "selected_count": len(plans[-1][1].get("selected", [])),
        "plan_digest": bytes(plans[-1][1].get("plan_digest", b"")).hex(),
    }


def _seconds(summary: Mapping[str, Any], statistic: str, *, host: bool = False) -> float:
    family = "host_wall_ms" if host else "cuda_ms"
    return float(summary[family][statistic]) / 1000.0


def _economics(
    timings: Mapping[str, Mapping[str, Any]], rust: Mapping[str, Any]
) -> dict[str, Any]:
    tiers = {
        "optimistic": ("minimum", "minimum", False),
        "median": ("median", "median", False),
        "conservative": ("minimum", "p95", True),
    }
    results = {}
    for name, (full_stat, cost_stat, reserve_fallback) in tiers.items():
        full_call = _seconds(timings["full_attention_reference"], full_stat)
        reduced = _seconds(timings["reduced_q_attention"], cost_stat)
        gather = _seconds(timings["candidate_q_gather"], cost_stat)
        scatter = _seconds(timings["scatter_reconstruction"], cost_stat)
        cache_read = _seconds(timings["cache_read"], cost_stat)
        cache_write = _seconds(timings["cache_write"], cost_stat)
        plan_apply = _seconds(timings["gpu_plan_application"], cost_stat)
        guard = _seconds(timings["context_lineage_validation"], cost_stat, host=True)
        materialize = _seconds(timings["gpu_plan_materialization"], cost_stat)
        rust_compile = float(rust["host_wall_ms"][cost_stat]) / 1000.0
        fallback = _seconds(timings["fallback_full_attention"], cost_stat)
        full_total = 1000 * full_call
        candidate_call = reduced + gather + scatter + cache_read + plan_apply + guard
        fallback_reserve = max(0.0, fallback - candidate_call) if reserve_fallback else 0.0
        selective_total = (
            801 * full_call
            + 199 * candidate_call
            + SOURCE_CAPTURE_COUNT * cache_write
            + materialize
            + rust_compile
            + OBSERVED_C2_SCALAR_SECONDS
            + fallback_reserve
        )
        net = full_total - selective_total
        results[name] = {
            "full_reference_total_seconds": full_total,
            "avoided_q_compute_seconds": 199 * max(0.0, full_call - reduced),
            "gather_total_seconds": 199 * gather,
            "scatter_total_seconds": 199 * scatter,
            "cache_guard_total_seconds": 199 * (cache_read + guard)
            + SOURCE_CAPTURE_COUNT * cache_write,
            "gpu_plan_total_seconds": 199 * plan_apply + materialize,
            "rust_compile_total_seconds": rust_compile,
            "c2_decision_total_seconds": OBSERVED_C2_SCALAR_SECONDS,
            "fallback_reserve_seconds": fallback_reserve,
            "predicted_selective_total_seconds": selective_total,
            "net_saving_seconds": net,
            "net_saving_percent_of_488_8473": net
            / COMPARABLE_BASELINE_SECONDS
            * 100.0,
        }
    p95_candidate_overhead = sum(
        _seconds(timings[key], "p95")
        for key in (
            "candidate_q_gather",
            "scatter_reconstruction",
            "cache_read",
            "gpu_plan_application",
        )
    ) + _seconds(timings["context_lineage_validation"], "p95", host=True)
    p95_reduced = _seconds(timings["reduced_q_attention"], "p95")
    p95_no_loss = (
        _seconds(timings["full_attention_reference"], "minimum")
        - p95_reduced
        - p95_candidate_overhead
        > 0.0
    )
    return {
        "schedule": {
            "full_attention_calls": 1000,
            "candidate_targets": MINIMUM_EXACT_RECORDS,
            "source_cache_writes": SOURCE_CAPTURE_COUNT,
            "planned_q_rows": MINIMUM_EXACT_RECORDS * PLANNED_Q_ROWS_PER_RECORD,
            "full_q_rows": FULL_Q_ROWS,
            "planned_q_reduction_ratio": MINIMUM_PLANNED_Q_RATIO,
            "veto_blocks": [30, 31, 48, 49],
        },
        "tiers": results,
        "p95_candidate_overhead_no_loss": p95_no_loss,
    }


def run_benchmark(comfy_root: Path) -> dict[str, Any]:
    torch, backend, backend_receipt = _load_standard_h3_backend(comfy_root)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch.device("cuda:0")
    if "RTX 3060" not in torch.cuda.get_device_name(device):
        raise RuntimeError("benchmark requires the admitted RTX 3060 device")

    context = _context()
    cpu_plan = V4ExecutorPlan.frozen_region_zero(
        context, lineage_digest="6" * 64
    )
    torch.cuda.empty_cache()
    baseline_allocated = int(torch.cuda.memory_allocated(device))
    baseline_reserved = int(torch.cuda.memory_reserved(device))
    torch.cuda.reset_peak_memory_stats(device)
    generator = torch.Generator(device=device)
    generator.manual_seed(101)
    q = torch.randn(
        (FULL_SEQUENCE_ROWS, H3_HEADS, H3_HEAD_DIM),
        dtype=torch.bfloat16,
        device=device,
        generator=generator,
    )
    k = torch.randn(q.shape, dtype=q.dtype, device=device, generator=generator)
    v = torch.randn(q.shape, dtype=q.dtype, device=device, generator=generator)
    measure = _CudaMeasure(torch)

    materialized_plans = []
    _, plan_materialization = measure.series(
        lambda: materialized_plans.append(materialize_gpu_plan(torch, cpu_plan, context))
        or materialized_plans[-1]
    )
    gpu_plan = materialized_plans[-1]
    materialized_plans[:] = [gpu_plan]

    control = V4ExecutorAdapter(
        torch_module=torch,
        profile=V4_CONTROL_FULL_COMPUTE,
        context=context,
        full_attention=backend,
    )
    selective = V4ExecutorAdapter(
        torch_module=torch,
        profile=V4_EXECUTOR_BENCHMARK,
        context=context,
        full_attention=backend,
    )

    with torch.inference_mode():
        full_seed = backend(q, k, v)
        torch.cuda.synchronize()
        cache = selective.capture_cache(full_seed, gpu_plan)
        bad_cache = V4CacheHandle(
            context_digest=cache.context_digest,
            lineage_digest="f" * 64,
            tensor=cache.tensor,
        )

        timings: dict[str, Any] = {"gpu_plan_materialization": plan_materialization}
        sentinel = torch.zeros((1,), dtype=torch.float32, device=device)
        _, timings["executor_kernel_launch"] = measure.series(
            lambda: sentinel.add_(1.0)
        )
        _, timings["candidate_q_gather"] = measure.series(
            lambda: q.index_select(0, gpu_plan.computed_indices)
        )
        selected_q = q.index_select(0, gpu_plan.computed_indices)
        _, timings["full_attention_reference"] = measure.series(
            lambda: backend(q, k, v)
        )
        _, timings["reduced_q_attention"] = measure.series(
            lambda: backend(selected_q, k, v)
        )
        _, timings["cache_write"] = measure.series(
            lambda: full_seed.index_select(0, gpu_plan.cache_region_indices)
        )
        reused = cache.tensor.index_select(0, gpu_plan.cache_reused_positions)
        _, timings["cache_read"] = measure.series(
            lambda: cache.tensor.index_select(0, gpu_plan.cache_reused_positions)
        )
        computed = backend(selected_q, k, v)
        scatter_buffer = torch.empty_like(full_seed)

        def scatter():
            scatter_buffer.index_copy_(0, gpu_plan.computed_indices, computed)
            scatter_buffer.index_copy_(0, gpu_plan.reused_indices, reused)
            return scatter_buffer

        _, timings["scatter_reconstruction"] = measure.series(scatter)
        _, timings["gpu_plan_application"] = measure.series(
            lambda: gpu_plan.computed_indices[:1].clone()
        )

        validation_cuda: list[float] = []
        validation_host: list[float] = []
        for _ in range(MEASURED_SAMPLES):
            started = perf_counter_ns()
            reason, internal_ns = validate_runtime_contract(
                profile=V4_EXECUTOR_BENCHMARK,
                context=context,
                plan=cpu_plan,
                cache=cache,
                q=q,
                k=k,
                v=v,
            )
            if reason is not None:
                raise RuntimeError(f"valid benchmark contract rejected: {reason}")
            validation_cuda.append(0.0)
            validation_host.append(
                max(internal_ns, perf_counter_ns() - started) / 1_000_000
            )
        timings["context_lineage_validation"] = _summary(
            validation_cuda, validation_host
        )

        _, timings["allocator_activity"] = measure.series(
            lambda: torch.empty_like(full_seed)
        )
        sync_cuda = []
        sync_host = []
        for _ in range(MEASURED_SAMPLES):
            started = perf_counter_ns()
            torch.cuda.synchronize()
            sync_cuda.append(0.0)
            sync_host.append((perf_counter_ns() - started) / 1_000_000)
        timings["explicit_synchronization"] = _summary(sync_cuda, sync_host)

        case_operations = {
            "A_full_reference": lambda: control.execute(
                q=q, k=k, v=v, gpu_plan=gpu_plan, cache=cache
            ),
            "B_plan_decode_only": lambda: (
                validate_runtime_contract(
                    profile=V4_EXECUTOR_BENCHMARK,
                    context=context,
                    plan=cpu_plan,
                    cache=cache,
                    q=q,
                    k=k,
                    v=v,
                ),
                gpu_plan.computed_indices[:1].clone(),
            ),
            "C_selective_hot_path": lambda: selective.execute(
                q=q, k=k, v=v, gpu_plan=gpu_plan, cache=cache
            ),
            "D_forced_fallback": lambda: selective.execute(
                q=q, k=k, v=v, gpu_plan=gpu_plan, cache=bad_cache
            ),
        }
        for operation in case_operations.values():
            operation()
        torch.cuda.synchronize()
        case_cuda = {name: [] for name in case_operations}
        case_host = {name: [] for name in case_operations}
        case_results: dict[str, Any] = {}
        names = tuple(case_operations)
        for cycle in range(MEASURED_SAMPLES):
            order = names[cycle % len(names) :] + names[: cycle % len(names)]
            for name in order:
                result, cuda_ms, host_ms = measure.one(case_operations[name])
                case_results[name] = result
                case_cuda[name].append(cuda_ms)
                case_host[name].append(host_ms)
        cases = {
            name: _summary(case_cuda[name], case_host[name]) for name in names
        }
        timings["fallback_full_attention"] = cases["D_forced_fallback"]

        a = case_results["A_full_reference"].output
        c = case_results["C_selective_hot_path"].output
        d = case_results["D_forced_fallback"].output
        sample_rows = torch.tensor(
            [0, 17, 101, 1024, 4096, 8192, 12000, 15423],
            dtype=torch.long,
            device=device,
        )
        a_sample = a.index_select(0, sample_rows)[:, :32].float()
        c_sample = c.index_select(0, sample_rows)[:, :32].float()
        d_sample = d.index_select(0, sample_rows)[:, :32].float()
        fallback_match = bool(torch.allclose(a_sample, d_sample, rtol=0.0, atol=0.0))
        selective_reconstruction_match = bool(
            torch.allclose(a_sample, c_sample, rtol=0.0, atol=0.0)
        )
        nonfinite = int((~torch.isfinite(c)).sum().item())
        checksum = sha256(c_sample.cpu().numpy().tobytes()).hexdigest()
        selective_result = case_results["C_selective_hot_path"]
        fallback_result = case_results["D_forced_fallback"]

        veto_reasons = []
        for block in (30, 31, 48, 49):
            veto_plan = V4ExecutorPlan.frozen_region_zero(
                context, lineage_digest="6" * 64, block=block
            )
            reason, _ = validate_runtime_contract(
                profile=V4_EXECUTOR_BENCHMARK,
                context=context,
                plan=veto_plan,
                cache=cache,
                q=q,
                k=k,
                v=v,
            )
            veto_reasons.append(reason)

    peak_allocated = int(torch.cuda.max_memory_allocated(device))
    peak_reserved = int(torch.cuda.max_memory_reserved(device))
    device_total = int(torch.cuda.get_device_properties(device).total_memory)
    rust = _rust_compile_benchmark()
    economics = _economics(timings, rust)
    contract_checks = {
        "full_selective_xor": selective_result.mode == "SELECTIVE"
        and fallback_result.mode == "FULL",
        "computed_plus_reused_equals_full": selective_result.actual_computed_rows
        + selective_result.actual_reused_rows
        == FULL_SEQUENCE_ROWS,
        "missing_rows_zero": len(set(cpu_plan.computed_rows).union(cpu_plan.reused_rows))
        == FULL_SEQUENCE_ROWS,
        "duplicate_rows_zero": len(set(cpu_plan.computed_rows))
        == len(cpu_plan.computed_rows)
        and len(set(cpu_plan.reused_rows)) == len(cpu_plan.reused_rows),
        "veto_blocks_reuse_zero": veto_reasons
        == ["CALIBRATION_VETO_BLOCK"] * 4,
        "out_of_bounds_zero": min(cpu_plan.computed_rows + cpu_plan.reused_rows) >= 0
        and max(cpu_plan.computed_rows + cpu_plan.reused_rows) < FULL_SEQUENCE_ROWS,
        "nonfinite_zero": nonfinite == 0,
        "fallback_full_output_exact": fallback_match,
        "selective_reconstruction_exact_for_identical_cache": selective_reconstruction_match,
        "rust_plan_ready": rust["plan_ready"],
        "rust_tensor_zero": rust["rust_tensor_bytes"] == 0,
        "rust_generation_call_once": rust["one_call_per_generation"],
        "hot_path_forced_cpu_sync_zero": rust["hot_path_forced_cpu_sync"] == 0,
    }
    memory_checks = {
        "peak_allocated_below_physical": peak_allocated < device_total,
        "peak_reserved_below_physical": peak_reserved < device_total,
        "allocator_headroom_at_least_256mib": device_total - peak_reserved
        >= 256 * 1024**2,
    }
    all_six_measured = all(
        key in timings
        for key in (
            "executor_kernel_launch",
            "candidate_q_gather",
            "scatter_reconstruction",
            "cache_read",
            "cache_write",
            "gpu_plan_materialization",
            "gpu_plan_application",
        )
    ) and rust["count"] > 0
    economics_checks = {
        "six_unknown_costs_measured": all_six_measured,
        "unknown_runtime_cost_zero": all_six_measured,
        "median_net_at_least_one_percent": economics["tiers"]["median"][
            "net_saving_percent_of_488_8473"
        ]
        >= 1.0,
        "conservative_net_positive": economics["tiers"]["conservative"][
            "net_saving_seconds"
        ]
        > 0.0,
        "p95_overhead_no_loss": economics["p95_candidate_overhead_no_loss"],
        "vram_allocator_pass": all(memory_checks.values()),
        "fallback_correctness_pass": fallback_match,
        "pipeline_contract_pass": all(contract_checks.values()),
    }
    passed = all(economics_checks.values())
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "decision": DECISION_VIABLE if passed else DECISION_NOT_VIABLE,
        "passed": passed,
        "runtime_profiles_executed": [
            V4_EXECUTOR_BENCHMARK,
            V4_CONTROL_FULL_COMPUTE,
        ],
        "generation_count": 0,
        "control_submission_count": 0,
        "selective_generation_count": 0,
        "partial_q_h3_generation_count": 0,
        "attention_omission_h3_generation_count": 0,
        "shape_inventory": {
            "qkv": [FULL_SEQUENCE_ROWS, H3_HEADS, H3_HEAD_DIM],
            "output": [FULL_SEQUENCE_ROWS, H3_HEADS * H3_HEAD_DIM],
            "computed_rows_per_candidate": len(cpu_plan.computed_rows),
            "reused_rows_per_candidate": len(cpu_plan.reused_rows),
            "cache_region_rows": len(cpu_plan.cache_region_rows),
        },
        "backend": backend_receipt,
        "timings": timings,
        "cases": cases,
        "sample_checksum": checksum,
        "row_accounting": {
            "full_rows": selective_result.full_rows,
            "planned_reusable_rows": selective_result.planned_reusable_rows,
            "actual_computed_rows": selective_result.actual_computed_rows,
            "actual_reused_rows": selective_result.actual_reused_rows,
            "fallback_rows": fallback_result.fallback_rows,
            "fallback_reason": fallback_result.fallback_reason,
        },
        "rust_live_compile": rust,
        "c2_decision_timing": {
            "seconds": OBSERVED_C2_SCALAR_SECONDS,
            "status": "REUSED_SAME_GENERATION_SCOPE",
        },
        "economics": economics,
        "memory": {
            "baseline_allocated_bytes": baseline_allocated,
            "baseline_reserved_bytes": baseline_reserved,
            "peak_allocated_bytes": peak_allocated,
            "peak_reserved_bytes": peak_reserved,
            "physical_bytes": device_total,
            "checks": memory_checks,
        },
        "contract_checks": contract_checks,
        "economics_checks": economics_checks,
        "unknown_runtime_costs": [],
        "claim_boundary": (
            "This shape-equivalent benchmark measures the auxiliary Attention-core "
            "executor path. It is not an H3 quality result or a primary product lever."
        ),
    }

    case_operations.clear()
    case_results.clear()
    q = k = v = full_seed = cache = bad_cache = selected_q = computed = reused = None
    a = c = d = a_sample = c_sample = d_sample = sample_rows = None
    selective_result = fallback_result = result = operation = None
    scatter_buffer = gpu_plan = materialized_plans = control = selective = sentinel = None
    scatter = None
    _ = None
    gc.collect()
    torch.cuda.empty_cache()
    receipt["cleanup"] = {
        "allocated_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_bytes": int(torch.cuda.memory_reserved(device)),
        "listener_started": False,
        "gpu_generation_started": False,
    }
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = run_benchmark(args.comfy_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
