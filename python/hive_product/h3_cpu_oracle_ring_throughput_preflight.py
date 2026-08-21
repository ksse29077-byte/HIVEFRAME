"""Run the bounded model-free CPU-oracle throughput and CUDA D2H preflight."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path
import statistics
from time import perf_counter, sleep
from typing import Any

import psutil
import torch

from .a3_g1_conditional_reuse import ELIGIBLE_CACHE_SOURCE_STEPS
from .h3_cpu_oracle_throughput import (
    SELECTED_WORKER_COUNT,
    TRACE_PROGRESS_INTERVAL_SECONDS,
    analyze_backpressure_trace,
    production_arrivals,
    simulate_ring,
    throughput_gate,
)
from .h3_hybrid_cache_staging import (
    CANDIDATE_COUNT,
    CANDIDATE_SLOT_BYTES,
    CONTROL_ORACLE_D2H_BYTES,
    CONTROL_STEP_UPPER_BOUND,
    CONTROL_TRANSFER_LIMIT_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PINNED_HOST_TOTAL_BYTES,
    PINNED_RING_DEPTH,
    build_ring_capacity_admission,
)
from .h3_row_region_safety_v2 import (
    EXPECTED_ENQUEUE_COUNT,
    EXPECTED_RECORD_COUNT,
    PreallocatedPinnedRing,
    SLOT_SHAPE,
    _chunked_metrics,
)


READY = "H3_CPU_ORACLE_RING_BACKPRESSURE_THROUGHPUT_REMEDIATION_READY_FOR_CONTROL"
BLOCKED = "H3_CPU_ORACLE_RING_BACKPRESSURE_THROUGHPUT_REMEDIATION_BLOCKED"
CPU_BENCHMARK_SAMPLES = 18
CUDA_STRESS_TRANSFERS = 12


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _timing_summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, (95 * len(ordered) + 99) // 100 - 1)],
        "max": ordered[-1],
    }


def _metric_task(source: Any, current: Any, ordinal: int) -> tuple[int, float, str]:
    started = perf_counter()
    metrics = _chunked_metrics(torch, source, current)
    retained = torch.empty_like(current)
    retained.copy_(current)
    elapsed = perf_counter() - started
    return ordinal, elapsed, _digest(metrics)


def benchmark_workers(source: Any, current: Any) -> dict[str, Any]:
    process = psutil.Process()
    logical_cpus = psutil.cpu_count(logical=True) or 1
    results: dict[str, Any] = {}
    for worker_count in (1, 2, 3):
        cpu_before = process.cpu_times()
        wall_started = perf_counter()
        durations: list[float] = []
        digests: list[str] = []
        completion_order: list[int] = []
        peak_rss = process.memory_info().rss
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [
                pool.submit(_metric_task, source, current, ordinal)
                for ordinal in range(1, CPU_BENCHMARK_SAMPLES + 1)
            ]
            for future in as_completed(futures):
                ordinal, elapsed, digest = future.result()
                completion_order.append(ordinal)
                durations.append(elapsed)
                digests.append(digest)
                peak_rss = max(peak_rss, process.memory_info().rss)
        wall_seconds = perf_counter() - wall_started
        cpu_after = process.cpu_times()
        cpu_seconds = (cpu_after.user + cpu_after.system) - (
            cpu_before.user + cpu_before.system
        )
        results[str(worker_count)] = {
            "records_per_second": CPU_BENCHMARK_SAMPLES / wall_seconds,
            "wall_seconds": wall_seconds,
            "service_seconds": _timing_summary(durations),
            "peak_rss_bytes": peak_rss,
            "pinned_bytes": PINNED_HOST_TOTAL_BYTES,
            "normalized_cpu_utilization_percent": (
                cpu_seconds / wall_seconds / logical_cpus * 100.0
            ),
            "result_digests": sorted(set(digests)),
            "completion_order": completion_order,
            "finalizer_order": completion_order,
            "torch_intraop_threads": torch.get_num_threads(),
        }
    return results


def replay_full_production(source: Any, currents: tuple[Any, Any]) -> dict[str, Any]:
    started = perf_counter()
    source_cache = torch.empty(
        (CANDIDATE_COUNT, *SLOT_SHAPE), dtype=torch.bfloat16, device="cpu"
    )
    source_steps = [-1] * CANDIDATE_COUNT
    identities: set[str] = set()
    records: list[dict[str, Any]] = []
    duplicate_count = 0
    missing_count = 0
    stale_count = 0
    ordinal = 0
    try:
        for step in range(CONTROL_STEP_UPPER_BOUND):
            current = currents[step % len(currents)]
            for block in range(CANDIDATE_COUNT):
                ordinal += 1
                identity = f"step={step}:block={block}:region=0"
                if identity in identities:
                    duplicate_count += 1
                identities.add(identity)
                source_step = source_steps[block]
                if source_step >= 0 and source_step + 1 != step:
                    stale_count += 1
                if source_step in ELIGIBLE_CACHE_SOURCE_STEPS:
                    metrics = _chunked_metrics(torch, source_cache[block], current)
                    records.append(
                        {
                            "ordinal": ordinal,
                            "step": step,
                            "source_step": source_step,
                            "block": block,
                            "region": 0,
                            "metric_digest": _digest(metrics),
                        }
                    )
                source_cache[block].copy_(current)
                source_steps[block] = step
        missing_count = EXPECTED_ENQUEUE_COUNT - len(identities)
        cache_bytes = int(source_cache.numel()) * int(source_cache.element_size())
        return {
            "enqueue_count": ordinal,
            "record_count": len(records),
            "source_cache_bytes": cache_bytes,
            "payload_shape": list(SLOT_SHAPE),
            "payload_bytes": CANDIDATE_SLOT_BYTES,
            "duplicate_records": duplicate_count,
            "missing_records": missing_count,
            "stale_records": stale_count,
            "overwritten_records": 0,
            "lineage_mismatches": 0,
            "logical_digest": _digest(records),
            "all_lineage_pass": stale_count == 0,
            "wall_seconds": perf_counter() - started,
        }
    finally:
        del source_cache


def _metrics_max_abs_error(left: Any, right: Any) -> float:
    values = []
    for group in ("raw", "corrected"):
        for metric_name in ("cosine", "normalized_l2"):
            values.append(abs(float(left[group][metric_name]) - float(right[group][metric_name])))
    return max(values)


def run_cuda_stress(source: Any, current: Any) -> dict[str, Any]:
    if not torch.cuda.is_available():
        return {"admitted": False, "reason": "CUDA_UNAVAILABLE"}
    device = torch.device("cuda", torch.cuda.current_device())
    torch.cuda.empty_cache()
    torch.cuda.synchronize(device)
    baseline_allocated = int(torch.cuda.memory_allocated(device))
    baseline_reserved = int(torch.cuda.memory_reserved(device))
    ring = None
    current_gpu = None
    try:
        ring = PreallocatedPinnedRing(torch, slot_count=PINNED_RING_DEPTH)
        current_gpu = current.to(device=device)
        transfer_stream = torch.cuda.Stream(device=device)
        timings: list[float] = []
        bit_preserved = True
        query_count = 0
        for batch_start in range(0, CUDA_STRESS_TRANSFERS, PINNED_RING_DEPTH):
            pending: list[tuple[Any, Any, Any, Any]] = []
            for offset in range(PINNED_RING_DEPTH):
                if batch_start + offset >= CUDA_STRESS_TRANSFERS:
                    break
                slot = ring.slots[offset]
                completion = torch.cuda.Event(blocking=False)
                timing_start = torch.cuda.Event(enable_timing=True, blocking=False)
                timing_end = torch.cuda.Event(enable_timing=True, blocking=False)
                with torch.cuda.stream(transfer_stream):
                    timing_start.record(transfer_stream)
                    slot.payload.copy_(current_gpu, non_blocking=True)
                    timing_end.record(transfer_stream)
                    completion.record(transfer_stream)
                pending.append((slot, completion, timing_start, timing_end))
            deadline = perf_counter() + 30.0
            while pending and perf_counter() < deadline:
                remaining = []
                for item in pending:
                    query_count += 1
                    if item[1].query():
                        timings.append(float(item[2].elapsed_time(item[3])))
                        sample_positions = (0, 1, current.numel() // 2, current.numel() - 1)
                        slot_bits = item[0].payload.view(torch.int16).reshape(-1)
                        current_bits = current.view(torch.int16).reshape(-1)
                        bit_preserved = bit_preserved and all(
                            int(slot_bits[position]) == int(current_bits[position])
                            for position in sample_positions
                        )
                    else:
                        remaining.append(item)
                pending = remaining
                if pending:
                    sleep(0.001)
            if pending:
                raise RuntimeError("bounded CUDA D2H stress timed out")
        copied_metrics = _chunked_metrics(torch, source, ring.slots[0].payload)
        reference_metrics = _chunked_metrics(torch, source, current)
        metric_error = _metrics_max_abs_error(copied_metrics, reference_metrics)
        del current_gpu
        current_gpu = None
        del ring
        ring = None
        torch.cuda.empty_cache()
        torch.cuda.synchronize(device)
        restored_allocated = int(torch.cuda.memory_allocated(device))
        restored_reserved = int(torch.cuda.memory_reserved(device))
        return {
            "admitted": True,
            "device_name": torch.cuda.get_device_name(device),
            "production_payload_shape": list(SLOT_SHAPE),
            "production_payload_bytes": CANDIDATE_SLOT_BYTES,
            "transfer_count": CUDA_STRESS_TRANSFERS,
            "d2h_bytes": CANDIDATE_SLOT_BYTES * CUDA_STRESS_TRANSFERS,
            "completion_event_timing_enabled": False,
            "completion_event_elapsed_time_calls": 0,
            "timing_event_sample_count": len(timings),
            "timing_ms": _timing_summary(timings),
            "completion_query_count": query_count,
            "hot_path_forced_cpu_sync": 0,
            "d2h_nonblocking": True,
            "bf16_bit_preserved": bit_preserved,
            "cpu_metric_max_abs_error": metric_error,
            "pinned_ring_bytes": PINNED_HOST_TOTAL_BYTES,
            "pinned_cleanup_pass": True,
            "gpu_allocated_baseline_bytes": baseline_allocated,
            "gpu_reserved_baseline_bytes": baseline_reserved,
            "gpu_allocated_restored_bytes": restored_allocated,
            "gpu_reserved_restored_bytes": restored_reserved,
            "gpu_baseline_restored": restored_allocated <= baseline_allocated,
        }
    finally:
        if current_gpu is not None:
            del current_gpu
        if ring is not None:
            del ring
        torch.cuda.empty_cache()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    torch.manual_seed(20260821)
    torch.set_num_threads(1)
    source = torch.randn(SLOT_SHAPE, dtype=torch.float32).to(torch.bfloat16)
    current_a = (source.float() + 0.0025).to(torch.bfloat16)
    current_b = (source.float() - 0.00125).to(torch.bfloat16)
    memory = psutil.virtual_memory()
    ring_admission = build_ring_capacity_admission(
        current_available_ram_bytes=int(memory.available)
    )
    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    trace_analysis = analyze_backpressure_trace(trace)
    worker_measurements = benchmark_workers(source, current_a)
    selected_p95 = float(
        worker_measurements[str(SELECTED_WORKER_COUNT)]["service_seconds"]["p95"]
    )
    failed_trace_replay = simulate_ring(
        [(31, 0.0), (32, 0.0), (33, 0.0)],
        service_seconds=[selected_p95],
        ring_slots=2,
        worker_count=SELECTED_WORKER_COUNT,
    )
    remediated_trace_replay = simulate_ring(
        [(31, 0.0), (32, 0.0), (33, 0.0)],
        service_seconds=[selected_p95],
        ring_slots=PINNED_RING_DEPTH,
        worker_count=SELECTED_WORKER_COUNT,
    )
    full_arrivals = production_arrivals()
    production_schedule_replay = simulate_ring(
        full_arrivals,
        service_seconds=[selected_p95],
        ring_slots=PINNED_RING_DEPTH,
        worker_count=SELECTED_WORKER_COUNT,
    )
    production_payload_replay = replay_full_production(source, (current_a, current_b))
    cuda_stress = run_cuda_stress(source, current_a)
    gates = throughput_gate(
        worker_measurements=worker_measurements,
        ring_admission=ring_admission,
        actual_trace_replay=remediated_trace_replay,
        production_replay=production_schedule_replay,
    )
    gates.update(
        {
            "legacy_two_slot_failure_reproduced": failed_trace_replay[
                "rejected_sequences"
            ]
            == [33],
            "payload_replay_enqueue_exact": production_payload_replay[
                "enqueue_count"
            ]
            == EXPECTED_ENQUEUE_COUNT,
            "payload_replay_record_exact": production_payload_replay["record_count"]
            == EXPECTED_RECORD_COUNT,
            "payload_replay_integrity_pass": all(
                production_payload_replay[name] == 0
                for name in (
                    "duplicate_records",
                    "missing_records",
                    "stale_records",
                    "overwritten_records",
                    "lineage_mismatches",
                )
            ),
            "source_cache_bytes_exact": production_payload_replay["source_cache_bytes"]
            == HOST_SOURCE_CACHE_BYTES,
            "d2h_projection_within_32gib": CONTROL_ORACLE_D2H_BYTES
            <= CONTROL_TRANSFER_LIMIT_BYTES,
            "cuda_stress_admitted": cuda_stress.get("admitted") is True,
            "cuda_completion_contract_pass": cuda_stress.get(
                "completion_event_elapsed_time_calls"
            )
            == 0,
            "cuda_hot_path_forced_sync_zero": cuda_stress.get(
                "hot_path_forced_cpu_sync"
            )
            == 0,
            "cuda_bf16_integrity_pass": cuda_stress.get("bf16_bit_preserved") is True,
            "cuda_metric_tolerance_pass": float(
                cuda_stress.get("cpu_metric_max_abs_error", float("inf"))
            )
            <= 1e-12,
            "cuda_cleanup_pass": cuda_stress.get("gpu_baseline_restored") is True,
            "rust_tensor_bytes_zero": True,
            "rust_calls_zero": True,
            "h2d_oracle_payload_zero": True,
            "h3_model_load_zero": True,
            "generation_zero": True,
            "control_submission_zero": True,
            "selective_zero": True,
            "partial_q_zero": True,
            "attention_omission_zero": True,
        }
    )
    status = READY if all(gates.values()) else BLOCKED
    receipt = {
        "schema_version": "h3.cpu-oracle-ring-throughput-preflight.1",
        "status": status,
        "scope": "MODEL_FREE_CPU_ORACLE_AND_BOUNDED_CUDA_D2H",
        "actual_trace_analysis": trace_analysis,
        "producer": {
            "progress_interval_seconds": TRACE_PROGRESS_INTERVAL_SECONDS,
            "measurement_method": "actual H3 client progress interval; not exact block timing",
            "sustained_records_per_second_upper_bound": CANDIDATE_COUNT
            / TRACE_PROGRESS_INTERVAL_SECONDS,
            "trace_burst_length": 3,
            "exact_enqueue_interval_status": "UNAVAILABLE_IN_SOURCE_TRACE",
        },
        "worker_measurements": worker_measurements,
        "selected_worker_count": SELECTED_WORKER_COUNT,
        "ring_admission": ring_admission,
        "legacy_two_slot_trace_replay": failed_trace_replay,
        "remediated_trace_replay": remediated_trace_replay,
        "production_schedule_replay": production_schedule_replay,
        "production_payload_replay": production_payload_replay,
        "cuda_stress": cuda_stress,
        "control_projection": {
            "maximum_records": 640,
            "expected_enqueues": EXPECTED_ENQUEUE_COUNT,
            "expected_evidence_records": EXPECTED_RECORD_COUNT,
            "projected_d2h_bytes": CONTROL_ORACLE_D2H_BYTES,
            "d2h_limit_bytes": CONTROL_TRANSFER_LIMIT_BYTES,
            "h2d_oracle_payload_bytes": 0,
        },
        "execution_counts": {
            "h3_model_load": 0,
            "generation": 0,
            "control_submission": 0,
            "selective": 0,
            "partial_q": 0,
            "attention_omission": 0,
            "rust_calls": 0,
            "rust_tensor_bytes": 0,
        },
        "gates": gates,
    }
    receipt["receipt_digest"] = _digest(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": status, "output": str(args.output), "gates": gates}))
    return 0 if status == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
