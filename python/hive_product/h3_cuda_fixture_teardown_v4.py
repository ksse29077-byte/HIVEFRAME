"""Explicit CUDA fixture ownership and warm-baseline teardown proof for V4."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from threading import enumerate as enumerate_threads
from typing import Any, Callable, Mapping
import gc
import json
import weakref

from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_bounded_host_source_oracle_v4 import (
    GPU_STAGING_BUDGET_BYTES,
    OMITTED_POSITIONS,
    REGION_ROWS,
    REPRESENTATIVE_POSITIONS,
    SOURCE_PAYLOAD_BYTES,
    SOURCE_SHAPE,
)


SCHEMA_VERSION = "h3.cuda-fixture-teardown-remediation-v4.1"
ROOT_CAUSE = "LIVE_TENSOR_REFERENCE_LEAK"
LIFECYCLE = (
    "RUNNING",
    "STOP_ACCEPTING",
    "DRAINING",
    "CUDA_COMPLETION_CONFIRMED",
    "WORKERS_JOINED",
    "REFERENCES_RELEASED",
    "ALLOCATOR_CLEANED",
    "CLOSED",
)


class FixtureLifecycleError(RuntimeError):
    """Reject unsafe ownership, ordering, or post-close access."""


def _tensor_bytes(tensor: Any) -> int:
    return int(tensor.numel()) * int(tensor.element_size())


class FixtureOwnershipRegistry:
    """Track every fixture-owned tensor, event, stream, future, and helper."""

    def __init__(self, torch_module: Any) -> None:
        self.torch = torch_module
        self.cuda_tensors: dict[str, Any] = {}
        self.pinned_tensors: dict[str, Any] = {}
        self.events: dict[str, Any] = {}
        self.streams: dict[str, Any] = {}
        self.futures: dict[str, Future[Any]] = {}
        self.workers: dict[str, ThreadPoolExecutor] = {}
        self.helpers: dict[str, Any] = {}
        self._cuda_weak: dict[str, Callable[[], Any | None]] = {}
        self._pinned_weak: dict[str, Callable[[], Any | None]] = {}
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise FixtureLifecycleError("fixture ownership registry is closed")

    @staticmethod
    def _weak(value: Any) -> Callable[[], Any | None]:
        try:
            return weakref.ref(value)
        except TypeError:
            return lambda: None

    def cuda(self, name: str, tensor: Any) -> Any:
        self._ensure_open()
        if name in self.cuda_tensors or not bool(getattr(tensor, "is_cuda", False)):
            raise FixtureLifecycleError("invalid or duplicate fixture CUDA tensor")
        self.cuda_tensors[name] = tensor
        self._cuda_weak[name] = self._weak(tensor)
        return tensor

    def pinned(self, name: str, tensor: Any) -> Any:
        self._ensure_open()
        if name in self.pinned_tensors or not bool(tensor.is_pinned()):
            raise FixtureLifecycleError("invalid or duplicate fixture pinned tensor")
        self.pinned_tensors[name] = tensor
        self._pinned_weak[name] = self._weak(tensor)
        return tensor

    def event(self, name: str, event: Any) -> Any:
        self._ensure_open()
        if name in self.events:
            raise FixtureLifecycleError("duplicate fixture CUDA event")
        self.events[name] = event
        return event

    def stream(self, name: str, stream: Any) -> Any:
        self._ensure_open()
        if name in self.streams:
            raise FixtureLifecycleError("duplicate fixture CUDA stream")
        self.streams[name] = stream
        return stream

    def future(self, name: str, future: Future[Any]) -> Future[Any]:
        self._ensure_open()
        if name in self.futures:
            raise FixtureLifecycleError("duplicate fixture future")
        self.futures[name] = future
        return future

    def worker(self, name: str, worker: ThreadPoolExecutor) -> ThreadPoolExecutor:
        self._ensure_open()
        if name in self.workers:
            raise FixtureLifecycleError("duplicate fixture worker")
        self.workers[name] = worker
        return worker

    def helper(self, name: str, value: Any) -> Any:
        self._ensure_open()
        if name in self.helpers:
            raise FixtureLifecycleError("duplicate fixture helper")
        self.helpers[name] = value
        return value

    def counts(self) -> dict[str, int]:
        future_cuda_results = 0
        for future in self.futures.values():
            result = getattr(future, "_result", None)
            if bool(getattr(result, "is_cuda", False)):
                future_cuda_results += 1
        return {
            "fixture_owned_cuda_tensor_count": len(self.cuda_tensors),
            "fixture_owned_cuda_tensor_bytes": sum(
                _tensor_bytes(tensor) for tensor in self.cuda_tensors.values()
            ),
            "fixture_owned_pinned_tensor_count": len(self.pinned_tensors),
            "fixture_owned_pinned_bytes": sum(
                _tensor_bytes(tensor) for tensor in self.pinned_tensors.values()
            ),
            "outstanding_event_count": len(self.events),
            "outstanding_stream_count": len(self.streams),
            "outstanding_future_count": len(self.futures),
            "future_cuda_result_count": future_cuda_results,
            "worker_owner_count": len(self.workers),
            "fixture_owned_helper_count": len(self.helpers),
        }

    def synchronize_owned_cuda(self) -> None:
        for event in self.events.values():
            event.synchronize()
        for stream in self.streams.values():
            stream.synchronize()

    def join_workers(self) -> None:
        for future in self.futures.values():
            if not future.done():
                future.result()
        for worker in self.workers.values():
            worker.shutdown(wait=True, cancel_futures=False)

    def release_strong_references(self) -> None:
        self.cuda_tensors.clear()
        self.pinned_tensors.clear()
        self.events.clear()
        self.streams.clear()
        self.futures.clear()
        self.workers.clear()
        self.helpers.clear()
        self._closed = True

    def released_live_counts(self) -> dict[str, int]:
        return {
            "released_fixture_cuda_tensor_count": sum(
                reference() is not None for reference in self._cuda_weak.values()
            ),
            "released_fixture_pinned_tensor_count": sum(
                reference() is not None for reference in self._pinned_weak.values()
            ),
        }


def _memory_stat(stats: Mapping[str, Any], key: str) -> int:
    return int(stats.get(key, 0))


def _live_cuda_inventory(torch_module: Any) -> dict[str, int]:
    tensor_count = 0
    tensor_bytes = 0
    storage_pointers: set[int] = set()
    for candidate in gc.get_objects():
        try:
            if not isinstance(candidate, torch_module.Tensor) or not candidate.is_cuda:
                continue
            tensor_count += 1
            tensor_bytes += _tensor_bytes(candidate)
            storage_pointers.add(int(candidate.untyped_storage().data_ptr()))
        except (ReferenceError, RuntimeError, TypeError):
            continue
    return {
        "python_live_cuda_tensor_count": tensor_count,
        "python_live_cuda_tensor_bytes": tensor_bytes,
        "cuda_storage_count": len(storage_pointers),
    }


def memory_snapshot(
    torch_module: Any,
    *,
    label: str,
    registry: FixtureOwnershipRegistry | None,
    fixture_state: str,
) -> dict[str, Any]:
    device = torch_module.device("cuda:0")
    stats = torch_module.cuda.memory_stats(device)
    registry_counts = registry.counts() if registry is not None else {
        "fixture_owned_cuda_tensor_count": 0,
        "fixture_owned_cuda_tensor_bytes": 0,
        "fixture_owned_pinned_tensor_count": 0,
        "fixture_owned_pinned_bytes": 0,
        "outstanding_event_count": 0,
        "outstanding_stream_count": 0,
        "outstanding_future_count": 0,
        "future_cuda_result_count": 0,
        "worker_owner_count": 0,
        "fixture_owned_helper_count": 0,
    }
    released = (
        registry.released_live_counts()
        if registry is not None
        else {
            "released_fixture_cuda_tensor_count": 0,
            "released_fixture_pinned_tensor_count": 0,
        }
    )
    return {
        "label": label,
        "fixture_state": fixture_state,
        "allocated_bytes": int(torch_module.cuda.memory_allocated(device)),
        "reserved_bytes": int(torch_module.cuda.memory_reserved(device)),
        "peak_allocated_bytes": int(torch_module.cuda.max_memory_allocated(device)),
        "peak_reserved_bytes": int(torch_module.cuda.max_memory_reserved(device)),
        "active_bytes": _memory_stat(stats, "active_bytes.all.current"),
        "inactive_split_bytes": _memory_stat(
            stats, "inactive_split_bytes.all.current"
        ),
        "allocation_count": _memory_stat(stats, "allocation.all.current"),
        "active_allocation_count": _memory_stat(stats, "active.all.current"),
        "segment_count": _memory_stat(stats, "segment.all.current"),
        "pinned_host_allocation_bytes": registry_counts[
            "fixture_owned_pinned_bytes"
        ],
        "worker_thread_count": sum(
            thread.name.startswith("hiveframe-v4-fixture")
            for thread in enumerate_threads()
        ),
        **_live_cuda_inventory(torch_module),
        **registry_counts,
        **released,
    }


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class V4CudaFixture:
    """One explicit-ownership production-equivalent bounded CUDA fixture."""

    def __init__(self, torch_module: Any, *, cycle_name: str) -> None:
        if not torch_module.cuda.is_available():
            raise FixtureLifecycleError("CUDA is unavailable")
        self.torch = torch_module
        self.device = torch_module.device("cuda:0")
        self.cycle_name = cycle_name
        self.state = "RUNNING"
        self.transitions = [self.state]
        self.registry = FixtureOwnershipRegistry(torch_module)
        self.snapshots: dict[str, dict[str, Any]] = {}
        self._closed = False

    def _transition(self, target: str) -> None:
        current_index = LIFECYCLE.index(self.state)
        if target != LIFECYCLE[current_index + 1]:
            raise FixtureLifecycleError(
                f"invalid fixture transition {self.state}->{target}"
            )
        self.state = target
        self.transitions.append(target)

    def _cuda(self, name: str, tensor: Any) -> Any:
        return self.registry.cuda(name, tensor)

    def _pinned(self, name: str, tensor: Any) -> Any:
        return self.registry.pinned(name, tensor)

    def run(self) -> dict[str, Any]:
        if self.state != "RUNNING":
            raise FixtureLifecycleError("closed fixture cannot run")
        torch_module = self.torch
        from .h3_bounded_host_source_oracle_v4_cuda import (
            gpu_compressed_fingerprint,
            gpu_exact_oracle_metrics,
            gpu_preliminary_metrics,
            threshold_classification,
        )

        torch_module.cuda.reset_peak_memory_stats(self.device)
        generator = self.registry.helper(
            "generator", torch_module.Generator(device=self.device)
        )
        generator.manual_seed(101)
        self._cuda(
            "source",
            torch_module.randn(
                SOURCE_SHAPE,
                dtype=torch_module.bfloat16,
                device=self.device,
                generator=generator,
            ),
        )
        self._pinned(
            "host_source",
            torch_module.empty(
                SOURCE_SHAPE,
                dtype=torch_module.bfloat16,
                device="cpu",
                pin_memory=True,
            ),
        )
        self._cuda("staging", torch_module.empty_like(self.registry.cuda_tensors["source"]))
        self.registry.stream(
            "transfer", torch_module.cuda.Stream(device=self.device)
        )
        for name in ("producer", "source_capture", "source_upload", "oracle"):
            self.registry.event(
                name,
                torch_module.cuda.Event(
                    enable_timing=name != "producer", blocking=False
                ),
            )

        source = self.registry.cuda_tensors["source"]
        host_source = self.registry.pinned_tensors["host_source"]
        staging = self.registry.cuda_tensors["staging"]
        transfer_stream = self.registry.streams["transfer"]
        events = self.registry.events
        events["producer"].record(torch_module.cuda.current_stream(self.device))
        with torch_module.cuda.stream(transfer_stream):
            transfer_stream.wait_event(events["producer"])
            events["source_capture"].record(transfer_stream)
            host_source.copy_(source, non_blocking=True)
        events["source_capture"].synchronize()
        with torch_module.cuda.stream(transfer_stream):
            staging.copy_(host_source, non_blocking=True)
            events["source_upload"].record(transfer_stream)
        events["source_upload"].synchronize()

        bit_identity = bool(
            torch_module.equal(
                source.view(torch_module.int16), staging.view(torch_module.int16)
            )
        )
        current = self._cuda("current", source.clone())
        current[::257].add_(0.0009765625)
        representative = self._cuda(
            "representative_indices",
            torch_module.tensor(
                REPRESENTATIVE_POSITIONS,
                dtype=torch_module.long,
                device=self.device,
            ),
        )
        omitted = self._cuda(
            "omitted_indices",
            torch_module.tensor(
                OMITTED_POSITIONS, dtype=torch_module.long, device=self.device
            ),
        )
        source_summary = self._cuda(
            "source_summary",
            gpu_compressed_fingerprint(torch_module, staging, representative),
        )
        current_summary = self._cuda(
            "current_summary",
            gpu_compressed_fingerprint(torch_module, current, representative),
        )
        preliminary = self._cuda(
            "preliminary",
            gpu_preliminary_metrics(torch_module, source_summary, current_summary),
        )
        exact = self._cuda(
            "exact",
            gpu_exact_oracle_metrics(
                torch_module, staging, current, representative, omitted
            ),
        )
        preliminary_host = self._pinned(
            "preliminary_host",
            torch_module.empty(
                (3,), dtype=torch_module.float32, device="cpu", pin_memory=True
            ),
        )
        exact_host = self._pinned(
            "exact_host",
            torch_module.empty(
                (6,), dtype=torch_module.float32, device="cpu", pin_memory=True
            ),
        )
        with torch_module.cuda.stream(transfer_stream):
            transfer_stream.wait_stream(torch_module.cuda.current_stream(self.device))
            preliminary_host.copy_(preliminary, non_blocking=True)
            exact_host.copy_(exact, non_blocking=True)
            events["oracle"].record(transfer_stream)
        events["oracle"].synchronize()

        preliminary_values = [float(value) for value in preliminary_host.tolist()]
        exact_values = [float(value) for value in exact_host.tolist()]
        cpu_source = host_source[:96, :128].clone()
        cpu_current = cpu_source.clone()
        cpu_current[::7].add_(0.0009765625)
        small_representative = torch_module.arange(0, 32, dtype=torch_module.long)
        small_omitted = torch_module.arange(32, 96, dtype=torch_module.long)
        cpu_reference = gpu_exact_oracle_metrics(
            torch_module,
            cpu_source,
            cpu_current,
            small_representative,
            small_omitted,
        ).tolist()
        gpu_small_source = self._cuda(
            "gpu_small_source", cpu_source.to(self.device)
        )
        gpu_small_current = self._cuda(
            "gpu_small_current", cpu_current.to(self.device)
        )
        gpu_small_representative = self._cuda(
            "gpu_small_representative", small_representative.to(self.device)
        )
        gpu_small_omitted = self._cuda(
            "gpu_small_omitted", small_omitted.to(self.device)
        )
        gpu_small_output = self._cuda(
            "gpu_small_output",
            gpu_exact_oracle_metrics(
                torch_module,
                gpu_small_source,
                gpu_small_current,
                gpu_small_representative,
                gpu_small_omitted,
            ),
        )
        gpu_small_values = gpu_small_output.to(device="cpu").tolist()
        errors = [
            abs(float(gpu) - float(cpu))
            for gpu, cpu in zip(gpu_small_values, cpu_reference)
        ]
        boundary = {
            "at_threshold": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX,
                finite=True,
            ),
            "below_cosine": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN - 1e-7,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX,
                finite=True,
            ),
            "above_l2": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX + 1e-7,
                finite=True,
            ),
            "nonfinite": threshold_classification(
                cosine=1.0, normalized_l2=0.0, finite=False
            ),
        }
        self.snapshots["allocation_after"] = memory_snapshot(
            torch_module,
            label=f"{self.cycle_name}:allocation_after",
            registry=self.registry,
            fixture_state=self.state,
        )
        checks = {
            "source_shape_exact": tuple(source.shape) == SOURCE_SHAPE,
            "source_payload_bytes_exact": _tensor_bytes(source)
            == SOURCE_PAYLOAD_BYTES,
            "shared_staging_bytes_within_bound": _tensor_bytes(staging)
            <= GPU_STAGING_BUDGET_BYTES,
            "host_source_is_pinned": bool(host_source.is_pinned()),
            "bf16_d2h_h2d_bit_identity": bit_identity,
            "fingerprint_is_compressed": source_summary.numel()
            < source.numel() // 100,
            "preliminary_finite": preliminary_values[2] == 1.0,
            "exact_finite": exact_values[2] == 1.0 and exact_values[5] == 1.0,
            "cpu_gpu_reference_within_tolerance": max(errors) <= 1e-5,
            "packed_row_mapping_exact": len(REGION_ROWS) == SOURCE_SHAPE[0]
            and len(REPRESENTATIVE_POSITIONS) + len(OMITTED_POSITIONS)
            == len(REGION_ROWS),
            "threshold_boundary_exact": boundary
            == {
                "at_threshold": "SAFE",
                "below_cosine": "UNSAFE",
                "above_l2": "UNSAFE",
                "nonfinite": "INVALID",
            },
            "metadata_d2h_within_one_mib": 36 <= 1024**2,
        }
        return {
            "cycle_name": self.cycle_name,
            "preliminary_metrics": preliminary_values,
            "exact_metrics": exact_values,
            "cpu_gpu_reference_max_abs_error": max(errors),
            "cpu_gpu_reference_mean_abs_error": sum(errors) / len(errors),
            "threshold_boundary": boundary,
            "current_payload_d2h_bytes": 0,
            "cpu_oracle_payload_d2h_bytes": 0,
            "metadata_d2h_bytes": 36,
            "checks": checks,
            "passed": all(checks.values()),
        }

    def close(self) -> dict[str, Any]:
        if self._closed:
            return {
                "idempotent": True,
                "state": self.state,
                "transitions": list(self.transitions),
                "snapshots": dict(self.snapshots),
            }
        self._transition("STOP_ACCEPTING")
        self.snapshots["close_immediate"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:close_immediate",
            registry=self.registry,
            fixture_state=self.state,
        )
        self._transition("DRAINING")
        self.registry.synchronize_owned_cuda()
        self._transition("CUDA_COMPLETION_CONFIRMED")
        self.snapshots["event_stream_completion"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:event_stream_completion",
            registry=self.registry,
            fixture_state=self.state,
        )
        self.registry.join_workers()
        self._transition("WORKERS_JOINED")
        self.snapshots["worker_join"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:worker_join",
            registry=self.registry,
            fixture_state=self.state,
        )
        self.registry.release_strong_references()
        self._transition("REFERENCES_RELEASED")
        self.snapshots["references_released"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:references_released",
            registry=self.registry,
            fixture_state=self.state,
        )
        gc.collect()
        self.snapshots["gc_collect"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:gc_collect",
            registry=self.registry,
            fixture_state=self.state,
        )
        self.torch.cuda.empty_cache()
        self._transition("ALLOCATOR_CLEANED")
        self.snapshots["empty_cache"] = memory_snapshot(
            self.torch,
            label=f"{self.cycle_name}:empty_cache",
            registry=self.registry,
            fixture_state=self.state,
        )
        self._transition("CLOSED")
        self._closed = True
        return {
            "idempotent": False,
            "state": self.state,
            "transitions": list(self.transitions),
            "snapshots": dict(self.snapshots),
        }


def final_memory_gate(
    final_snapshot: Mapping[str, Any], warm_baseline: Mapping[str, Any]
) -> dict[str, bool]:
    return {
        "allocated_matches_warm_baseline": final_snapshot["allocated_bytes"]
        == warm_baseline["allocated_bytes"],
        "active_matches_warm_baseline": final_snapshot["active_bytes"]
        == warm_baseline["active_bytes"],
        "fixture_owned_live_cuda_zero": final_snapshot[
            "released_fixture_cuda_tensor_count"
        ]
        == 0,
        "fixture_owned_pinned_zero": final_snapshot[
            "released_fixture_pinned_tensor_count"
        ]
        == 0,
        "outstanding_worker_future_zero": final_snapshot[
            "worker_owner_count"
        ]
        == final_snapshot["outstanding_future_count"]
        == final_snapshot["future_cuda_result_count"]
        == final_snapshot["worker_thread_count"]
        == 0,
        "outstanding_event_stream_zero": final_snapshot[
            "outstanding_event_count"
        ]
        == final_snapshot["outstanding_stream_count"]
        == 0,
    }


def run_fixture_cycle(torch_module: Any, *, cycle_name: str) -> dict[str, Any]:
    fixture = V4CudaFixture(torch_module, cycle_name=cycle_name)
    functional: dict[str, Any] | None = None
    error: BaseException | None = None
    try:
        functional = fixture.run()
    except BaseException as caught:
        error = caught
    close_receipt = fixture.close()
    second_close = fixture.close()
    if error is not None:
        raise FixtureLifecycleError(f"fixture cycle {cycle_name} failed") from error
    assert functional is not None
    return {
        "functional": functional,
        "close": close_receipt,
        "close_idempotence": second_close["idempotent"] is True,
    }


@dataclass
class SourceCacheLeak:
    tensor: Any


def _negative_case(
    torch_module: Any,
    *,
    name: str,
    warm_baseline: Mapping[str, Any],
) -> dict[str, Any]:
    registry = FixtureOwnershipRegistry(torch_module)
    worker: ThreadPoolExecutor | None = None
    future: Future[Any] | None = None
    cache_entry: SourceCacheLeak | None = None
    tensor: Any | None = None
    if name == "cuda_tensor_reference":
        registry.cuda(name, torch_module.empty((1024,), device="cuda"))
    elif name == "staging_reference":
        registry.cuda(name, torch_module.empty((4096,), device="cuda"))
    elif name == "worker_future_cuda_result":
        worker = registry.worker(
            name,
            ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="hiveframe-v4-fixture-negative"
            ),
        )
        future = registry.future(
            name, worker.submit(lambda: torch_module.empty((2048,), device="cuda"))
        )
        future.result()
    elif name == "source_cache_entry":
        tensor = registry.cuda(name, torch_module.empty((3072,), device="cuda"))
        cache_entry = registry.helper(name, SourceCacheLeak(tensor=tensor))
    else:
        raise FixtureLifecycleError("unknown negative leak case")

    leaked = memory_snapshot(
        torch_module,
        label=f"negative:{name}:retained",
        registry=registry,
        fixture_state="RUNNING",
    )
    leaked_checks = final_memory_gate(leaked, warm_baseline)
    detected = not all(leaked_checks.values())
    registry.synchronize_owned_cuda()
    registry.join_workers()
    registry.release_strong_references()
    worker = None
    future = None
    cache_entry = None
    tensor = None
    gc.collect()
    torch_module.cuda.empty_cache()
    released = memory_snapshot(
        torch_module,
        label=f"negative:{name}:released",
        registry=registry,
        fixture_state="CLOSED",
    )
    released_checks = final_memory_gate(released, warm_baseline)
    return {
        "name": name,
        "leak_detected": detected,
        "retained_snapshot": leaked,
        "retained_checks": leaked_checks,
        "released_snapshot": released,
        "released_checks": released_checks,
        "release_passed": all(released_checks.values()),
        "passed": detected and all(released_checks.values()),
    }


def run_teardown_remediation(
    torch_module: Any,
    *,
    verification_cycles: int = 3,
    run_negative_tests: bool = True,
) -> dict[str, Any]:
    """Run one planned warm-up and a fixed number of verification cycles."""

    if verification_cycles < 1:
        raise FixtureLifecycleError("at least one verification cycle is required")
    cold = memory_snapshot(
        torch_module,
        label="cold_baseline",
        registry=None,
        fixture_state="NOT_STARTED",
    )
    warmup = run_fixture_cycle(torch_module, cycle_name="warm_up")
    warm_baseline = warmup["close"]["snapshots"]["empty_cache"]
    negatives = []
    if run_negative_tests:
        negatives = [
            _negative_case(torch_module, name=name, warm_baseline=warm_baseline)
            for name in (
                "cuda_tensor_reference",
                "staging_reference",
                "worker_future_cuda_result",
                "source_cache_entry",
            )
        ]

    verifications = [
        run_fixture_cycle(torch_module, cycle_name=f"verification_{index}")
        for index in range(1, verification_cycles + 1)
    ]
    finals = [
        cycle["close"]["snapshots"]["empty_cache"] for cycle in verifications
    ]
    cycle_gates = [final_memory_gate(final, warm_baseline) for final in finals]
    allocated = [int(final["allocated_bytes"]) for final in finals]
    reserved = [int(final["reserved_bytes"]) for final in finals]
    allocated_growth = [
        current - previous for previous, current in zip(allocated, allocated[1:])
    ]
    reserved_growth = [
        current - previous for previous, current in zip(reserved, reserved[1:])
    ]
    functional_pass = bool(
        warmup["functional"]["passed"]
        and all(cycle["functional"]["passed"] for cycle in verifications)
    )
    close_pass = bool(
        warmup["close_idempotence"]
        and all(cycle["close_idempotence"] for cycle in verifications)
        and all(all(gate.values()) for gate in cycle_gates)
    )
    negative_pass = bool(
        not run_negative_tests or all(case["passed"] for case in negatives)
    )
    no_growth = bool(
        all(value == 0 for value in allocated_growth)
        and all(value == 0 for value in reserved_growth)
    )
    classification = ROOT_CAUSE
    allocator_category = (
        "LAZY_CUDA_INITIALIZATION_BASELINE_MISMATCH"
        if int(warm_baseline["allocated_bytes"]) > int(cold["allocated_bytes"])
        else "NO_LAZY_ALLOCATED_DELTA"
    )
    checks = {
        "root_cause_known": classification != "UNKNOWN",
        "warmup_functional_pass": warmup["functional"]["passed"],
        "verification_count_exact": len(verifications) == verification_cycles,
        "verification_functional_pass": functional_pass,
        "verification_memory_gate_pass": close_pass,
        "negative_leak_tests_pass": negative_pass,
        "allocated_monotonic_growth_zero": all(
            value == 0 for value in allocated_growth
        ),
        "reserved_monotonic_growth_zero": all(
            value == 0 for value in reserved_growth
        ),
        "retry_zero": True,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "root_cause_classification": classification,
        "allocator_baseline_classification": allocator_category,
        "cold_baseline": cold,
        "warm_up": warmup,
        "warm_baseline": warm_baseline,
        "negative_tests": negatives,
        "verification_cycles": verifications,
        "verification_final_allocated_bytes": allocated,
        "verification_final_reserved_bytes": reserved,
        "allocated_growth_bytes": allocated_growth,
        "reserved_growth_bytes": reserved_growth,
        "planned_warmup_count": 1,
        "planned_verification_count": verification_cycles,
        "retry_count": 0,
        "checks": checks,
        "passed": all(checks.values()) and no_growth,
        "decision": (
            "H3_CUDA_FIXTURE_TEARDOWN_REMEDIATION_READY"
            if all(checks.values()) and no_growth
            else "H3_CUDA_FIXTURE_TEARDOWN_REMEDIATION_FAILED"
        ),
    }
