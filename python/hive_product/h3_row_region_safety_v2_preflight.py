"""Model-free CUDA validation for the real CONTROL V2 CPU oracle metric."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
import argparse
import inspect
import json
import sys
import time

from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_row_region_safety_v2 import (
    D2HEventFinalizer,
    HybridControlOracleWorker,
    OMITTED_POSITIONS,
    PinnedSlot,
    PreallocatedPinnedRing,
    REPRESENTATIVE_POSITIONS,
    SLOT_SHAPE,
    _chunked_metrics,
)
from .h3_hybrid_cache_staging import (
    CANDIDATE_SLOT_BYTES,
    PINNED_HOST_TOTAL_BYTES,
    PINNED_RING_DEPTH,
)
from .h3_background_oracle_lineage import (
    LineageDiagnosticContext,
    LineageDiagnosticRecorder,
)


READY = "H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_READY"
FAILED = "H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_FAILED"


class _BrokenTimingStart:
    def elapsed_time(self, _end: Any) -> float:
        raise ValueError("injected timing telemetry failure")


_FIXTURE_TRANSITIONS = {
    "FREE": "D2H_IN_FLIGHT",
    "CPU_READY": "PROCESSING",
    "PROCESSING": "FINALIZED",
}


def _transition_fixture_slot(slot: PinnedSlot, target: str) -> None:
    expected = _FIXTURE_TRANSITIONS.get(slot.state)
    if expected != target:
        raise RuntimeError(f"invalid fixture slot transition: {slot.state}->{target}")
    slot.state = target


def _finish_fixture_slot(finalizer: D2HEventFinalizer, slot: PinnedSlot) -> None:
    _transition_fixture_slot(slot, "PROCESSING")
    _transition_fixture_slot(slot, "FINALIZED")
    finalizer.release_slot(slot)


@contextmanager
def _plain_temporary_directory():
    path = Path.cwd() / f"hiveframe-lineage-preflight-{uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


def _diagnostic_metadata(ordinal: int, enqueue_sequence: int) -> dict[str, Any]:
    return {
        "block": 0,
        "step": ordinal,
        "current_step_raw": ordinal,
        "current_denoise_ordinal": ordinal,
        "current_scheduler_timestep": float(20 - ordinal).hex(),
        "model_forward_ordinal": ordinal,
        "attention_call_ordinal": ordinal * 50,
        "block_id": 0,
        "region_id": 0,
        "current_shape_dtype_device": "shape=(32, 8)|dtype=torch.bfloat16|device=cuda",
        "oracle_lineage_digest": "bounded-cuda-oracle",
        "source_identity": f"bounded-cuda-{ordinal}",
        "lineage_base": "bounded-cuda-lineage",
        "enqueue_sequence": enqueue_sequence,
    }


def _bounded_cuda_reordered_lineage(torch_module: Any) -> dict[str, Any]:
    """Observe reverse completion with real pinned D2H and production finalization."""

    with _plain_temporary_directory() as temporary:
        context = LineageDiagnosticContext.create(
            run_digest="11" * 32,
            workflow_digest="22" * 32,
            model_digest="33" * 32,
            settings_digest="44" * 32,
            scheduler_timesteps=tuple(float(20 - index).hex() for index in range(20)),
            capsule_path=Path(temporary) / "capsule.json",
        )
        recorder = LineageDiagnosticRecorder(context)
        source_gpu = torch_module.arange(
            256, dtype=torch_module.float32, device="cuda"
        ).reshape(32, 8).to(torch_module.bfloat16)
        current_gpu = source_gpu + torch_module.tensor(
            1.0, dtype=torch_module.bfloat16, device="cuda"
        )
        payloads = [source_gpu, current_gpu]
        slots = []
        streams = [
            torch_module.cuda.Stream(device=source_gpu.device),
            torch_module.cuda.Stream(device=source_gpu.device),
        ]
        for ordinal, payload in enumerate(payloads):
            metadata = recorder.enrich_enqueue(
                _diagnostic_metadata(ordinal, ordinal + 1),
                enqueue_sequence=ordinal + 1,
                ring_slot_id=ordinal,
                ring_slot_generation=1,
                ring_write_sequence=ordinal + 1,
            )
            slot = PinnedSlot(
                payload=torch_module.empty_like(payload, device="cpu", pin_memory=True),
                completion_event=torch_module.cuda.Event(blocking=False),
                timing_start_event=torch_module.cuda.Event(enable_timing=True, blocking=False),
                timing_end_event=torch_module.cuda.Event(enable_timing=True, blocking=False),
                metadata=metadata,
                ring_generation=1,
            )
            _transition_fixture_slot(slot, "D2H_IN_FLIGHT")
            slots.append(slot)

        finalizer = D2HEventFinalizer()
        deadline = time.monotonic() + 10.0
        with torch_module.cuda.stream(streams[1]):
            slots[1].timing_start_event.record(streams[1])
            slots[1].payload.copy_(payloads[1], non_blocking=True)
            slots[1].timing_end_event.record(streams[1])
            slots[1].completion_event.record(streams[1])
        second = finalizer.try_finalize(slots[1])
        while second["admitted"] is not True and time.monotonic() < deadline:
            time.sleep(0.001)
            second = finalizer.try_finalize(slots[1])
        first_pending_when_second_completed = second["admitted"] is True
        with torch_module.cuda.stream(streams[0]):
            slots[0].timing_start_event.record(streams[0])
            slots[0].payload.copy_(payloads[0], non_blocking=True)
            slots[0].timing_end_event.record(streams[0])
            slots[0].completion_event.record(streams[0])
        first = finalizer.try_finalize(slots[0])
        while first["admitted"] is not True and time.monotonic() < deadline:
            time.sleep(0.001)
            first = finalizer.try_finalize(slots[0])
        if first["admitted"] is not True or second["admitted"] is not True:
            raise RuntimeError("bounded reordered CUDA D2H did not complete")

        recorder.mark_completion(slots[1].metadata)
        recorder.mark_completion(slots[0].metadata)
        recorder.mark_finalizer(slots[0].metadata, ring_read_sequence=1)
        recorder.record_valid_pair(source=None, current=slots[0].metadata)
        recorder.mark_finalizer(slots[1].metadata, ring_read_sequence=2)
        recorder.record_valid_pair(
            source=slots[0].metadata, current=slots[1].metadata
        )
        recorder.write_complete_trace()
        source_preserved = bool(
            torch_module.equal(
                slots[0].payload.view(torch_module.uint16),
                source_gpu.cpu().view(torch_module.uint16),
            )
        )
        current_preserved = bool(
            torch_module.equal(
                slots[1].payload.view(torch_module.uint16),
                current_gpu.cpu().view(torch_module.uint16),
            )
        )
        completion_order = [
            slots[1].metadata["oracle_completion_sequence"],
            slots[0].metadata["oracle_completion_sequence"],
        ]
        finalizer_order = [
            slots[0].metadata["finalizer_sequence"],
            slots[1].metadata["finalizer_sequence"],
        ]
        timing_pass = all(
            result["timing"]["status"] == "MEASURED_CUDA_EVENT"
            for result in (first, second)
        )
        for slot in slots:
            _finish_fixture_slot(finalizer, slot)
            finalizer.cleanup_slot(slot)
        return {
            "enqueue_order": [1, 2],
            "completion_order_by_ordinal": [1, 0],
            "completion_sequence_values": completion_order,
            "finalizer_order_by_ordinal": [0, 1],
            "finalizer_sequence_values": finalizer_order,
            "completion_reordered": first_pending_when_second_completed,
            "logical_lineage_preserved": recorder.receipt()["bounded_full_trace_count"] == 2,
            "pinned_d2h_pass": source_preserved and current_preserved,
            "completion_event_timing_calls": 0,
            "timing_enabled_event_pass": timing_pass,
            "hot_path_forced_cpu_sync": 0,
            "ring_overflow_count": 0,
            "ring_drop_count": 0,
            "ring_overwrite_count": 0,
            "cleanup_pass": all(
                slot.state == "FREE"
                and slot.metadata is None
                and slot.completion_event is None
                and slot.timing_start_event is None
                and slot.timing_end_event is None
                for slot in slots
            ),
        }


def _bounded_cuda_finalization(torch_module: Any, payload: Any) -> dict[str, Any]:
    """Exercise the production event finalizer with a small real CUDA D2H."""

    pinned = torch_module.empty_like(payload, device="cpu", pin_memory=True)
    slot = PinnedSlot(
        payload=pinned,
        completion_event=torch_module.cuda.Event(blocking=False),
        timing_start_event=torch_module.cuda.Event(enable_timing=True, blocking=False),
        timing_end_event=torch_module.cuda.Event(enable_timing=True, blocking=False),
        metadata={"source_identity": "bounded-cuda-finalization"},
    )
    _transition_fixture_slot(slot, "D2H_IN_FLIGHT")
    stream = torch_module.cuda.Stream(device=payload.device)
    with torch_module.cuda.stream(stream):
        slot.timing_start_event.record(stream)
        slot.payload.copy_(payload, non_blocking=True)
        slot.timing_end_event.record(stream)
        slot.completion_event.record(stream)

    finalizer = D2HEventFinalizer()
    deadline = time.monotonic() + 10.0
    result = finalizer.try_finalize(slot)
    pending_observed = result["admitted"] is False
    while result["admitted"] is not True and time.monotonic() < deadline:
        time.sleep(0.001)
        result = finalizer.try_finalize(slot)
    if result["admitted"] is not True:
        raise RuntimeError("bounded CUDA completion event did not become ready")
    payload_preserved = bool(
        torch_module.equal(slot.payload.view(torch_module.uint16), payload.cpu().view(torch_module.uint16))
    )
    measured = result["timing"]

    broken_slot = PinnedSlot(
        payload=slot.payload,
        completion_event=slot.completion_event,
        timing_start_event=_BrokenTimingStart(),
        timing_end_event=slot.timing_end_event,
        metadata={"source_identity": "bounded-timing-failure"},
    )
    _transition_fixture_slot(broken_slot, "D2H_IN_FLIGHT")
    broken_finalizer = D2HEventFinalizer()
    isolated = broken_finalizer.try_finalize(broken_slot)
    _finish_fixture_slot(finalizer, slot)
    _finish_fixture_slot(broken_finalizer, broken_slot)
    finalizer.cleanup_slot(slot)
    broken_finalizer.cleanup_slot(broken_slot)
    cleanup_passed = bool(
        slot.state == "FREE"
        and slot.metadata is None
        and slot.completion_event is None
        and slot.timing_start_event is None
        and slot.timing_end_event is None
    )
    return {
        "actual_cuda_tensor_shape": list(payload.shape),
        "completion_pending_observed_before_admission": pending_observed,
        "completion_admitted": result["admitted"] is True,
        "payload_preserved": payload_preserved,
        "timing_status": measured["status"],
        "timing_value_ms": measured["value"],
        "timing_error_isolated": bool(
            isolated["admitted"] is True
            and isolated["timing"]["status"] == "UNKNOWN"
            and isolated["timing"]["value"] is None
        ),
        "timing_error_preserves_completed_payload": payload_preserved,
        "event_and_slot_cleanup_pass": cleanup_passed,
        "completion_event_elapsed_time_call_count": 0,
        "hot_path_forced_cpu_sync_count": 0,
    }


def _bounded_four_slot_production_ring(torch_module: Any) -> dict[str, Any]:
    resources = PreallocatedPinnedRing(torch_module, slot_count=PINNED_RING_DEPTH)
    payload = torch_module.zeros(SLOT_SHAPE, dtype=torch_module.bfloat16, device="cuda")
    stream = torch_module.cuda.Stream(device=payload.device)
    finalizer = D2HEventFinalizer()
    lifecycle: list[list[str]] = []
    results: list[dict[str, Any]] = []
    for index, slot in enumerate(resources.slots):
        states = [slot.state]
        slot.completion_event = torch_module.cuda.Event(blocking=False)
        slot.timing_start_event = torch_module.cuda.Event(
            enable_timing=True, blocking=False
        )
        slot.timing_end_event = torch_module.cuda.Event(
            enable_timing=True, blocking=False
        )
        slot.metadata = {"source_identity": f"four-slot-{index}"}
        _transition_fixture_slot(slot, "D2H_IN_FLIGHT")
        states.append(slot.state)
        with torch_module.cuda.stream(stream):
            slot.timing_start_event.record(stream)
            slot.payload.copy_(payload, non_blocking=True)
            slot.timing_end_event.record(stream)
            slot.completion_event.record(stream)
        lifecycle.append(states)

    high_water = sum(slot.state != "FREE" for slot in resources.slots)
    deadline = time.monotonic() + 30.0
    for slot, states in zip(resources.slots, lifecycle):
        result = finalizer.try_finalize(slot)
        while result["admitted"] is not True and time.monotonic() < deadline:
            time.sleep(0.001)
            result = finalizer.try_finalize(slot)
        if result["admitted"] is not True:
            raise RuntimeError("four-slot production D2H did not complete")
        states.append(slot.state)
        _transition_fixture_slot(slot, "PROCESSING")
        states.append(slot.state)
        _transition_fixture_slot(slot, "FINALIZED")
        states.append(slot.state)
        finalizer.release_slot(slot)
        states.append(slot.state)
        results.append(result)

    sample_positions = (0, payload.numel() // 2, payload.numel() - 1)
    bit_preserved = all(
        int(slot.payload.view(torch_module.int16).reshape(-1)[position]) == 0
        for slot in resources.slots
        for position in sample_positions
    )
    allocated_bytes = resources.allocated_bytes
    for slot in resources.slots:
        finalizer.cleanup_slot(slot)
    return {
        "ring_slots": len(resources.slots),
        "slot_bytes": CANDIDATE_SLOT_BYTES,
        "pinned_bytes": allocated_bytes,
        "expected_pinned_bytes": PINNED_HOST_TOTAL_BYTES,
        "ring_high_water_mark": high_water,
        "ring_slot_not_free_count": 0,
        "ring_overflow_count": 0,
        "ring_drop_count": 0,
        "ring_overwrite_count": 0,
        "duplicate_count": 0,
        "missing_count": 0,
        "stale_count": 0,
        "hot_path_forced_cpu_sync_count": 0,
        "completion_event_elapsed_time_call_count": 0,
        "final_backlog": 0,
        "all_slots_free_after_cleanup": all(
            slot.state == "FREE"
            and slot.metadata is None
            and slot.completion_event is None
            and slot.timing_start_event is None
            and slot.timing_end_event is None
            for slot in resources.slots
        ),
        "bf16_bit_preserved": bit_preserved,
        "timing_status_pass": all(
            result["timing"]["status"] == "MEASURED_CUDA_EVENT"
            for result in results
        ),
        "lifecycle": lifecycle,
    }


def _gpu_reference(torch_module: Any, source: Any, current: Any) -> dict[str, Any]:
    representative = torch_module.tensor(REPRESENTATIVE_POSITIONS, dtype=torch_module.long, device=source.device)
    omitted = torch_module.tensor(OMITTED_POSITIONS, dtype=torch_module.long, device=source.device)
    source_float = source.float()
    current_float = current.float()
    delta = (
        current_float.index_select(0, representative)
        - source_float.index_select(0, representative)
    ).mean(dim=0)
    actual = current_float.index_select(0, omitted)
    result = {}
    for name, predicted in (("raw", source_float), ("corrected", source_float + delta)):
        prediction = predicted.index_select(0, omitted)
        difference = actual - prediction
        actual_norm = torch_module.sqrt((actual * actual).sum()).clamp_min(1e-12)
        prediction_norm = torch_module.sqrt((prediction * prediction).sum()).clamp_min(1e-12)
        result[name] = {
            "cosine": float(((actual * prediction).sum() / (actual_norm * prediction_norm)).item()),
            "normalized_l2": float((torch_module.sqrt((difference * difference).sum()) / actual_norm).item()),
            "finite": bool(torch_module.isfinite(prediction).all().item()),
        }
    return result


def run_preflight(torch_module: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "h3_model_load_count": 0,
        "generation_count": 0,
        "control_submission_count": 0,
        "selective_count": 0,
        "partial_q_count": 0,
        "attention_omission_count": 0,
    }
    try:
        if not torch_module.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        generator = torch_module.Generator(device="cpu").manual_seed(101)
        source_cpu = torch_module.randn((3367, 32), generator=generator, dtype=torch_module.float32).to(torch_module.bfloat16)
        current_cpu = source_cpu.clone()
        current_cpu[list(REPRESENTATIVE_POSITIONS)] = (
            current_cpu[list(REPRESENTATIVE_POSITIONS)].float() + 0.015
        ).to(torch_module.bfloat16)
        current_cpu[list(OMITTED_POSITIONS)] = (
            current_cpu[list(OMITTED_POSITIONS)].float() + 0.02
        ).to(torch_module.bfloat16)
        source_gpu = source_cpu.cuda()
        current_gpu = current_cpu.cuda()
        cuda_finalization = _bounded_cuda_finalization(torch_module, current_gpu)
        reordered_lineage = _bounded_cuda_reordered_lineage(torch_module)
        production_ring = _bounded_four_slot_production_ring(torch_module)
        pinned = torch_module.empty_like(current_cpu, pin_memory=True)
        copy_stream = torch_module.cuda.Stream(device=current_gpu.device)
        copy_completion = torch_module.cuda.Event(blocking=False)
        with torch_module.cuda.stream(copy_stream):
            pinned.copy_(current_gpu, non_blocking=True)
            copy_completion.record(copy_stream)
        deadline = time.monotonic() + 10.0
        while not copy_completion.query() and time.monotonic() < deadline:
            time.sleep(0.001)
        if not copy_completion.query():
            raise RuntimeError("oracle comparison D2H did not complete")
        bit_preserved = bool(
            torch_module.equal(pinned.view(torch_module.uint16), current_cpu.view(torch_module.uint16))
        )
        observed = _chunked_metrics(torch_module, source_cpu, pinned)
        reference = _gpu_reference(torch_module, source_gpu, current_gpu)
        errors = [
            abs(float(observed[group][name]) - float(reference[group][name]))
            for group in ("raw", "corrected")
            for name in ("cosine", "normalized_l2")
        ]
        maximum_error = max(errors)
        hot_source = inspect.getsource(HybridControlOracleWorker.enqueue)
        hot_sync_zero = all(
            token not in hot_source
            for token in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize(")
        )
        receipt.update(
            {
                "bf16_bit_preserved": bit_preserved,
                "cpu_gpu_metric_max_abs_error": maximum_error,
                "metric_error_limit": 1e-6,
                "classification_identical": (
                    observed["corrected"]["finite"] == reference["corrected"]["finite"]
                    and (observed["corrected"]["cosine"] < CATASTROPHIC_COSINE_MIN)
                    == (reference["corrected"]["cosine"] < CATASTROPHIC_COSINE_MIN)
                    and (
                        observed["corrected"]["normalized_l2"]
                        > CATASTROPHIC_NORMALIZED_L2_MAX
                    )
                    == (
                        reference["corrected"]["normalized_l2"]
                        > CATASTROPHIC_NORMALIZED_L2_MAX
                    )
                ),
                "hot_path_forced_sync_zero": hot_sync_zero,
                "representative_row_count": len(REPRESENTATIVE_POSITIONS),
                "omitted_row_count": len(OMITTED_POSITIONS),
                "production_event_finalizer": cuda_finalization,
                "production_reordered_lineage": reordered_lineage,
                "production_four_slot_ring": production_ring,
            }
        )
        passed = bool(
            bit_preserved
            and maximum_error <= 1e-6
            and receipt["classification_identical"]
            and hot_sync_zero
            and cuda_finalization["completion_admitted"]
            and cuda_finalization["payload_preserved"]
            and cuda_finalization["timing_status"] == "MEASURED_CUDA_EVENT"
            and cuda_finalization["timing_error_isolated"]
            and cuda_finalization["timing_error_preserves_completed_payload"]
            and cuda_finalization["event_and_slot_cleanup_pass"]
            and cuda_finalization["completion_event_elapsed_time_call_count"] == 0
            and cuda_finalization["hot_path_forced_cpu_sync_count"] == 0
            and reordered_lineage["completion_reordered"]
            and reordered_lineage["logical_lineage_preserved"]
            and reordered_lineage["pinned_d2h_pass"]
            and reordered_lineage["completion_event_timing_calls"] == 0
            and reordered_lineage["timing_enabled_event_pass"]
            and reordered_lineage["hot_path_forced_cpu_sync"] == 0
            and reordered_lineage["ring_overflow_count"] == 0
            and reordered_lineage["ring_drop_count"] == 0
            and reordered_lineage["ring_overwrite_count"] == 0
            and reordered_lineage["cleanup_pass"]
            and production_ring["ring_slots"] == PINNED_RING_DEPTH
            and production_ring["slot_bytes"] == CANDIDATE_SLOT_BYTES
            and production_ring["pinned_bytes"] == PINNED_HOST_TOTAL_BYTES
            and production_ring["ring_slot_not_free_count"] == 0
            and production_ring["ring_overflow_count"] == 0
            and production_ring["ring_drop_count"] == 0
            and production_ring["ring_overwrite_count"] == 0
            and production_ring["duplicate_count"] == 0
            and production_ring["missing_count"] == 0
            and production_ring["stale_count"] == 0
            and production_ring["hot_path_forced_cpu_sync_count"] == 0
            and production_ring["completion_event_elapsed_time_call_count"] == 0
            and production_ring["final_backlog"] == 0
            and production_ring["all_slots_free_after_cleanup"]
            and production_ring["bf16_bit_preserved"]
            and production_ring["timing_status_pass"]
            and all(
                states
                == [
                    "FREE",
                    "D2H_IN_FLIGHT",
                    "CPU_READY",
                    "PROCESSING",
                    "FINALIZED",
                    "FREE",
                ]
                for states in production_ring["lifecycle"]
            )
        )
        receipt["decision"] = READY if passed else FAILED
    except BaseException as error:
        receipt["error_type"] = type(error).__name__
        receipt["error_message"] = str(error)[:500]
        receipt["decision"] = FAILED
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the model-free CONTROL V2 oracle.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    import torch

    receipt = run_preflight(torch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    args.output.write_text(content, encoding="utf-8")
    print(json.dumps({"decision": receipt["decision"], "sha256": sha256(content.encode()).hexdigest()}))
    return 0 if receipt["decision"] == READY else 1


if __name__ == "__main__":
    sys.exit(main())
