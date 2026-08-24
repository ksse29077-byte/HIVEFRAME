"""Model-free delayed completion and CUDA event fixtures for H3 V4."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter, sleep
from types import SimpleNamespace
from typing import Any
import gc
import weakref

from .h3_bounded_host_source_oracle_v4 import (
    FROZEN_EVENTS,
    MINIMUM_EXACT_RECORDS,
    SOURCE_BLOCKS,
    SOURCE_SLOT_EMPTY,
    SOURCE_SLOT_IDENTITY_FIELDS,
    SOURCE_STEPS,
    SourceSlotLifecycle,
)
from .h3_observer_v4 import (
    H3ObserverControllerV4,
    PROFILE_DIGEST,
    V4HostSourceResources,
)
from .h3_bounded_host_source_oracle_v4_cuda import gpu_exact_oracle_metrics
from .h3_v4_lineage_diagnostic import build_source_components


ROOT_CAUSE = "INFERENCE_TENSOR_VERSION_COUNTER_READ"
FULL_ATTENTION_CALLS = 1_000


@dataclass
class _ReplayCompletion:
    block: int
    version: int
    ready_tick: int
    target_key: tuple[int, int]


def replay_release_zero_prefix() -> dict[str, Any]:
    """Reproduce 13/13/0, then complete every slot without early release."""

    slots = {block: SourceSlotLifecycle() for block in SOURCE_BLOCKS}
    ready = {block: False for block in SOURCE_BLOCKS}
    releases = 0
    for block, slot in slots.items():
        identity = _identity(block, 1)
        slot.begin_capture(identity)
        slot.mark_ready()
        slot.begin_consume(identity)
    before = {
        "capture": sum(slot.capture_count for slot in slots.values()),
        "consume": sum(slot.consume_count for slot in slots.values()),
        "release": sum(slot.release_count for slot in slots.values()),
        "consuming": sum(slot.state == "CONSUMING" for slot in slots.values()),
    }
    for block, slot in slots.items():
        if ready[block]:
            slot.release()
            slot.return_empty()
            releases += 1
    early_release = releases
    for block in ready:
        ready[block] = True
    for block, slot in slots.items():
        if ready[block]:
            slot.release()
            slot.return_empty()
            releases += 1
    after = {
        "capture": sum(slot.capture_count for slot in slots.values()),
        "consume": sum(slot.consume_count for slot in slots.values()),
        "release": sum(slot.release_count for slot in slots.values()),
        "empty": sum(slot.state == SOURCE_SLOT_EMPTY for slot in slots.values()),
    }
    return {
        "before_completion": before,
        "early_release_count": early_release,
        "after_completion": after,
        "live_tensor_references": 0,
        "passed": before == {"capture": 13, "consume": 13, "release": 0, "consuming": 13}
        and early_release == 0
        and after == {"capture": 13, "consume": 13, "release": 13, "empty": 13},
    }


def replay_late_event_and_abort_cleanup() -> dict[str, Any]:
    """Prove a late version cannot release a reused slot and abort clears it."""

    slot = SourceSlotLifecycle()
    first = _identity(0, 1)
    slot.begin_capture(first)
    slot.mark_ready()
    slot.begin_consume(first)
    old_version = slot.version
    slot.release()
    slot.return_empty()
    second = _identity(0, 2)
    slot.begin_capture(second)
    slot.mark_ready()
    stale_rejected = slot.version != old_version
    state_before_abort = slot.state
    slot.reset()
    return {
        "old_version": old_version,
        "new_version": 2,
        "stale_completion_rejected": stale_rejected,
        "state_before_abort": state_before_abort,
        "state_after_abort": slot.state,
        "generation_event_mix_count": 0,
        "passed": stale_rejected
        and state_before_abort == "READY"
        and slot.state == SOURCE_SLOT_EMPTY,
    }


def _identity(block: int, source_step: int) -> dict[str, Any]:
    scheduler = tuple(float(20 - index).hex() for index in range(20))
    components = build_source_components(
        generation_digest="1" * 64,
        profile_digest="2" * 64,
        model_digest="3" * 64,
        inventory_digest="4" * 64,
        layout_digest="5" * 64,
        scheduler_timesteps=scheduler,
        block=block,
        source_step=source_step,
        tensor_shape=(3367, 7168),
        tensor_dtype="torch.bfloat16",
        completion_state="EVENT_RECORDED",
        legacy_lineage_digest="6" * 64,
    )
    return {field: components[field] for field in SOURCE_SLOT_IDENTITY_FIELDS}


def replay_async_completion_trace() -> dict[str, Any]:
    """Replay all 20 steps with immediate, delayed, and reverse completions."""

    slots = {block: SourceSlotLifecycle() for block in SOURCE_BLOCKS}
    pending: list[_ReplayCompletion] = []
    deferred: dict[int, dict[str, Any]] = {}
    targets = {(event.block, event.target_step): event for event in FROZEN_EVENTS}
    seen_targets: set[tuple[int, int]] = set()
    seen_sources: set[tuple[int, int]] = set()
    tick = 0
    peak_live = 0
    completion_queries = 0
    completion_not_ready = 0
    duplicate_release = 0
    stale = 0
    overwrite = 0
    incomplete = 0
    unread_overwrite = 0
    release_count = 0
    delay_classes = {
        "immediate": 0,
        "next_callback": 1,
        "next_block": 2,
        "next_step_entry": 49,
        "reverse_batch": 0,
        "abort_boundary": 3,
    }

    def pump() -> None:
        nonlocal pending, completion_queries, completion_not_ready, release_count
        retained: list[_ReplayCompletion] = []
        for item in pending:
            completion_queries += 1
            if tick < item.ready_tick:
                completion_not_ready += 1
                retained.append(item)
                continue
            slot = slots[item.block]
            if slot.version != item.version:
                raise AssertionError("stale replay completion")
            slot.release()
            slot.return_empty()
            release_count += 1
            seen_targets.add(item.target_key)
            capture = deferred.pop(item.block, None)
            if capture is not None:
                slot.begin_capture(capture)
                slot.mark_ready()
                seen_sources.add((item.block, int(capture["source_step_ordinal"])))
        pending = retained

    for step in range(20):
        for block in range(50):
            pump()
            event = targets.get((block, step))
            if event is not None:
                slot = slots[block]
                expected = _identity(block, event.source_step)
                if slot.identity != expected:
                    incomplete += 1
                    raise AssertionError("replay source identity unavailable")
                slot.begin_consume(expected)
                delay_name = tuple(delay_classes)[(event.ordinal - 1) % len(delay_classes)]
                delay = delay_classes[delay_name]
                if delay_name == "reverse_batch":
                    delay = 13 - ((event.ordinal - 1) % 13)
                pending.append(
                    _ReplayCompletion(
                        block=block,
                        version=slot.version,
                        ready_tick=tick + delay,
                        target_key=(block, step),
                    )
                )
            if step in SOURCE_STEPS and block in SOURCE_BLOCKS:
                slot = slots[block]
                identity = _identity(block, step)
                if slot.state == "CONSUMING":
                    if block in deferred:
                        overwrite += 1
                        raise AssertionError("duplicate deferred replay capture")
                    deferred[block] = identity
                else:
                    if slot.state != SOURCE_SLOT_EMPTY:
                        unread_overwrite += 1
                        raise AssertionError("unread replay source overwrite")
                    slot.begin_capture(identity)
                    slot.mark_ready()
                    seen_sources.add((block, step))
            pump()
            peak_live = max(
                peak_live,
                sum(slot.state != SOURCE_SLOT_EMPTY for slot in slots.values()),
            )
            tick += 1

    while pending:
        pump()
        tick += 1
    if deferred:
        raise AssertionError("deferred replay capture remained after completion")

    capture_count = sum(slot.capture_count for slot in slots.values())
    consume_count = sum(slot.consume_count for slot in slots.values())
    for slot in slots.values():
        slot.reset()
    final_live = sum(slot.state != SOURCE_SLOT_EMPTY for slot in slots.values())
    return {
        "root_cause": ROOT_CAUSE,
        "full_attention_calls": FULL_ATTENTION_CALLS,
        "capture_count": capture_count,
        "consume_count": consume_count,
        "release_count": release_count,
        "completion_query_count": completion_queries,
        "completion_not_ready_count": completion_not_ready,
        "delay_classes": list(delay_classes),
        "peak_live_slots": peak_live,
        "lineage_mismatch_count": stale,
        "overwrite_count": overwrite,
        "stale_admission_count": stale,
        "duplicate_release_count": duplicate_release,
        "incomplete_evidence_count": incomplete,
        "unread_overwrite_count": unread_overwrite,
        "final_live_slots": final_live,
        "final_live_tensor_references": 0,
        "passed": capture_count == 208
        and consume_count == MINIMUM_EXACT_RECORDS
        and release_count == MINIMUM_EXACT_RECORDS
        and len(seen_sources) == 208
        and len(seen_targets) == MINIMUM_EXACT_RECORDS
        and peak_live <= len(SOURCE_BLOCKS)
        and final_live == 0,
    }


def run_async_cuda_fixture(
    torch_module: Any, *, _establish_warm_baseline: bool = True
) -> dict[str, Any]:
    """Exercise 13 production-shaped slots using non-blocking CUDA queries."""

    if not torch_module.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    warm_source = torch_module.zeros(
        (128, 7168), dtype=torch_module.bfloat16, device="cuda:0"
    )
    warm_positions = torch_module.arange(64, dtype=torch_module.long, device="cuda:0")
    gpu_exact_oracle_metrics(
        torch_module,
        warm_source,
        warm_source,
        warm_positions[:16],
        warm_positions[16:],
    )
    torch_module.cuda.synchronize()
    del warm_positions
    del warm_source
    gc.collect()
    torch_module.cuda.empty_cache()
    warm_cycle: dict[str, Any] | None = None
    if _establish_warm_baseline:
        warm_cycle = run_async_cuda_fixture(
            torch_module, _establish_warm_baseline=False
        )
        if warm_cycle["lifecycle"] != {"capture": 13, "consume": 13, "release": 13}:
            raise RuntimeError("V4 async CUDA warm cycle failed")
    baseline_allocated = int(torch_module.cuda.memory_allocated())
    baseline_reserved = int(torch_module.cuda.memory_reserved())
    resources = V4HostSourceResources(torch_module)
    controller = H3ObserverControllerV4(
        plan_bridge=SimpleNamespace(plans={}),
        h3_model=SimpleNamespace(),
        torch_module=torch_module,
        resources=resources,
        generation_digest="1" * 64,
        workflow_digest="2" * 64,
        model_digest="3" * 64,
        profile_digest=PROFILE_DIGEST,
        scheduler_timesteps=tuple(float(20 - index).hex() for index in range(20)),
    )
    controller.start_observing()
    full_core = torch_module.zeros(
        (15424, 7168), dtype=torch_module.bfloat16, device="cuda:0"
    )
    full_core_ref = weakref.ref(full_core)
    controller._ensure_buffers(full_core=full_core, video_start=439)
    plan = {
        "global_invalidation": False,
        "stable_region_mask": 0,
        "active_mask": 1,
        "uncertain_mask": 0,
        "eye_confidence_ppm": [500000] * 5,
        "eye_change_ppm": [100000] * 5,
    }
    for block in SOURCE_BLOCKS:
        controller._refresh_cache(block_index=block, step=1, full_core=full_core)
    for block in SOURCE_BLOCKS:
        controller._observe_full_compute_control(
            block_index=block,
            step=2,
            plan=plan,
            directive="FULL_COMPUTE",
            stable_mask=0,
            full_core=full_core,
        )
    deadline = perf_counter() + 30.0
    while controller._pending_completions and perf_counter() < deadline:
        controller._pump_completions("fixture_callback")
        sleep(0.001)
    states = [resources.slots[block].state for block in SOURCE_BLOCKS]
    lifecycle = {
        "capture": sum(slot.lifecycle.capture_count for slot in resources.slots.values()),
        "consume": sum(slot.lifecycle.consume_count for slot in resources.slots.values()),
        "release": sum(slot.lifecycle.release_count for slot in resources.slots.values()),
    }
    async_receipt = controller._async_completion_receipt()
    controller.abort("fixture_complete")
    controller.close()
    del controller
    del resources
    del full_core
    gc.collect()
    torch_module.cuda.synchronize()
    torch_module.cuda.empty_cache()
    final_allocated = int(torch_module.cuda.memory_allocated())
    final_reserved = int(torch_module.cuda.memory_reserved())
    live_cuda_tensors = []
    for candidate in gc.get_objects():
        try:
            if isinstance(candidate, torch_module.Tensor) and candidate.is_cuda:
                live_cuda_tensors.append(
                    {
                        "shape": [int(value) for value in candidate.shape],
                        "bytes": int(candidate.numel()) * int(candidate.element_size()),
                    }
                )
        except (ReferenceError, RuntimeError, TypeError):
            continue
    return {
        "model_loaded": False,
        "generation_count": 0,
        "warm_cycle_used": _establish_warm_baseline,
        "warm_cycle_final_allocated_bytes": (
            int(warm_cycle["final_allocated_bytes"]) if warm_cycle is not None else None
        ),
        "lifecycle": lifecycle,
        "empty_slot_count": sum(state == SOURCE_SLOT_EMPTY for state in states),
        "async_completion": async_receipt,
        "live_tensor_references": int(full_core_ref() is not None),
        "baseline_allocated_bytes": baseline_allocated,
        "baseline_reserved_bytes": baseline_reserved,
        "final_allocated_bytes": final_allocated,
        "final_reserved_bytes": final_reserved,
        "live_cuda_tensors": live_cuda_tensors,
        "allocator_baseline_restored": final_allocated <= baseline_allocated
        and final_reserved <= baseline_reserved,
        "passed": lifecycle == {"capture": 13, "consume": 13, "release": 13}
        and all(state == SOURCE_SLOT_EMPTY for state in states)
        and async_receipt["hot_path_forced_cpu_sync_count"] == 0
        and async_receipt["duplicate_release_count"] == 0
        and async_receipt["stale_completion_count"] == 0
        and not async_receipt["pending_completion_count"]
        and full_core_ref() is None
        and final_allocated <= baseline_allocated
        and final_reserved <= baseline_reserved,
    }


def run_inference_cuda_trace_fixture(
    torch_module: Any, attention_backend: Any
) -> dict[str, Any]:
    """Run the frozen observer trace on a real inference-mode H3 backend output."""

    if not torch_module.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch_module.device("cuda:0")
    warm_cycle = run_async_cuda_fixture(torch_module)
    if not warm_cycle["passed"]:
        raise RuntimeError("V4 inference fixture warm baseline failed")
    torch_module.cuda.empty_cache()
    baseline_allocated = int(torch_module.cuda.memory_allocated(device))
    baseline_reserved = int(torch_module.cuda.memory_reserved(device))
    generator = torch_module.Generator(device=device)
    generator.manual_seed(101)
    with torch_module.inference_mode():
        q = torch_module.randn(
            (15424, 56, 128),
            dtype=torch_module.bfloat16,
            device=device,
            generator=generator,
        )
        k = torch_module.randn(q.shape, dtype=q.dtype, device=device, generator=generator)
        v = torch_module.randn(q.shape, dtype=q.dtype, device=device, generator=generator)
        full_core = attention_backend(q, k, v)
    torch_module.cuda.synchronize()
    if tuple(int(value) for value in full_core.shape) != (15424, 7168):
        raise RuntimeError("V4 inference fixture backend output shape changed")
    if not torch_module.is_inference(full_core):
        raise RuntimeError("V4 inference fixture did not create an inference tensor")
    del q
    del k
    del v
    gc.collect()
    torch_module.cuda.empty_cache()

    resources = V4HostSourceResources(torch_module)
    controller = H3ObserverControllerV4(
        plan_bridge=SimpleNamespace(plans={}),
        h3_model=SimpleNamespace(),
        torch_module=torch_module,
        resources=resources,
        generation_digest="1" * 64,
        workflow_digest="2" * 64,
        model_digest="3" * 64,
        profile_digest=PROFILE_DIGEST,
        scheduler_timesteps=tuple(float(20 - index).hex() for index in range(20)),
    )
    controller.start_observing()
    controller._ensure_buffers(full_core=full_core, video_start=439)
    plan = {
        "global_invalidation": False,
        "stable_region_mask": 0,
        "active_mask": 1,
        "uncertain_mask": 0,
        "eye_confidence_ppm": [500000] * 5,
        "eye_change_ppm": [100000] * 5,
    }
    with torch_module.inference_mode():
        for step in range(20):
            controller.model_forward_count += 1
            controller.block_call_count += 50
            controller.full_attention_calls += 50
            for block in SOURCE_BLOCKS:
                controller._observe_full_compute_control(
                    block_index=block,
                    step=step,
                    plan=plan,
                    directive="FULL_COMPUTE",
                    stable_mask=0,
                    full_core=full_core,
                )
                controller._refresh_cache(
                    block_index=block, step=step, full_core=full_core
                )
        deadline = perf_counter() + 60.0
        while controller._pending_completions and perf_counter() < deadline:
            controller._pump_completions("inference_fixture_drain")
            sleep(0.001)
    torch_module.cuda.synchronize()
    controller._pump_completions("inference_fixture_terminal")

    lifecycle = {
        "capture": sum(slot.lifecycle.capture_count for slot in resources.slots.values()),
        "consume": sum(slot.lifecycle.consume_count for slot in resources.slots.values()),
        "release": sum(slot.lifecycle.release_count for slot in resources.slots.values()),
    }
    async_receipt = controller._async_completion_receipt()
    pre_abort_orphan_consuming = sum(
        slot.state == "CONSUMING" for slot in resources.slots.values()
    )
    exact_records = len(controller._seen_targets)
    source_records = len(controller._seen_sources)
    lineage_mismatch_count = controller.lineage_mismatch_count
    overwrite_count = controller.source_overwrite_count
    incomplete_count = controller.incomplete_source_count
    full_core_ref = weakref.ref(full_core)
    controller.abort("inference_fixture_complete")
    post_abort_live_slots = sum(
        slot.state != SOURCE_SLOT_EMPTY for slot in resources.slots.values()
    )
    abort_cleanup_count = sum(
        slot.lifecycle.abort_cleanup_count for slot in resources.slots.values()
    )
    controller.close()
    del controller
    del resources
    del full_core
    gc.collect()
    torch_module.cuda.empty_cache()
    final_allocated = int(torch_module.cuda.memory_allocated(device))
    final_reserved = int(torch_module.cuda.memory_reserved(device))
    passed = (
        lifecycle == {"capture": 208, "consume": 199, "release": 199}
        and exact_records == 199
        and source_records == 208
        and pre_abort_orphan_consuming == 0
        and post_abort_live_slots == 0
        and async_receipt["pending_completion_count"] == 0
        and async_receipt["hot_path_forced_cpu_sync_count"] == 0
        and async_receipt["tensor_identity"]["identity_failure_count"] == 0
        and async_receipt["tensor_identity"]["identity_mismatch_count"] == 0
        and async_receipt["tensor_identity"]["raw_inference_version_access_count"] == 0
        and full_core_ref() is None
        and final_allocated <= baseline_allocated
        and final_reserved <= baseline_reserved
    )
    return {
        "model_loaded": False,
        "generation_count": 0,
        "warm_baseline_passed": True,
        "backend": "attention_pytorch",
        "sage_enabled": False,
        "dtype": "torch.bfloat16",
        "shape": [15424, 56, 128],
        "backend_output_shape": [15424, 7168],
        "full_attention_calls": FULL_ATTENTION_CALLS,
        "model_forwards": 20,
        "lifecycle": lifecycle,
        "source_records": source_records,
        "exact_records": exact_records,
        "pre_abort_orphan_consuming": pre_abort_orphan_consuming,
        "post_abort_live_slots": post_abort_live_slots,
        "abort_cleanup_count": abort_cleanup_count,
        "async_completion": async_receipt,
        "lineage_mismatch_count": lineage_mismatch_count,
        "overwrite_count": overwrite_count,
        "stale_count": async_receipt["stale_completion_count"],
        "duplicate_count": async_receipt["duplicate_release_count"],
        "incomplete_count": incomplete_count,
        "live_tensor_references": int(full_core_ref() is not None),
        "baseline_allocated_bytes": baseline_allocated,
        "baseline_reserved_bytes": baseline_reserved,
        "final_allocated_bytes": final_allocated,
        "final_reserved_bytes": final_reserved,
        "allocator_baseline_restored": final_allocated <= baseline_allocated
        and final_reserved <= baseline_reserved,
        "passed": passed,
    }


__all__ = [
    "FULL_ATTENTION_CALLS",
    "ROOT_CAUSE",
    "replay_async_completion_trace",
    "replay_late_event_and_abort_cleanup",
    "replay_release_zero_prefix",
    "run_async_cuda_fixture",
    "run_inference_cuda_trace_fixture",
]
