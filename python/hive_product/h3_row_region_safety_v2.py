"""Balanced12GB holdout oracle for one Full Compute H3 CONTROL V2."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from queue import Empty, Full, Queue
from threading import Lock, Thread
from time import perf_counter, sleep
from typing import Any, Mapping, Sequence
import json

from .a3_g1_conditional_reuse import CONTROL_MODE, ELIGIBLE_CACHE_SOURCE_STEPS, H3A3G1Controller
from .attention_output_reuse import CATASTROPHIC_COSINE_MIN, CATASTROPHIC_NORMALIZED_L2_MAX
from .h3_hybrid_cache_staging import (
    CANDIDATE_AGGREGATE_BYTES,
    CANDIDATE_SLOT_BYTES,
    CONTROL_ORACLE_D2H_BYTES,
    CONTROL_TRANSFER_LIMIT_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PINNED_HOST_TOTAL_BYTES,
    PINNED_RING_DEPTH,
)
from .h3_background_oracle_lineage import (
    LineageDiagnosticAbort,
    LineageDiagnosticRecorder,
)
from .h3_row_region_safety import (
    CACHE_HARD_CAP_BYTES,
    FULL_Q_ROWS,
    MAX_EVIDENCE_RECORDS,
    SHAPE_WIDTH,
    SafetyEvidencePlanBridge,
)
from .regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


SCHEMA_VERSION = "h3.row-region-safety-evidence-control-v2.1"
HOLDOUT_LABEL = "HOLDOUT_CONTROL_V2"
CANDIDATE_BLOCKS = tuple(range(30))
VETO_BLOCKS = frozenset({30, 31, 48, 49})
REGION = 0
EXPECTED_ENQUEUE_COUNT = len(CANDIDATE_BLOCKS) * 20
EXPECTED_RECORD_COUNT = len(CANDIDATE_BLOCKS) * len(ELIGIBLE_CACHE_SOURCE_STEPS)
METRIC_CHUNK_ROWS = 256


class ControlV2EvidenceError(Exception):
    """Fail closed without entering the native Full Compute fallback."""


def _region_rows() -> tuple[int, ...]:
    rows = CPU_PROTOTYPE_PLANS[1].region_rows[REGION]
    return tuple(sorted((*rows["representative"], *rows["omitted"])))


def _region_positions() -> tuple[tuple[int, ...], tuple[int, ...]]:
    rows = CPU_PROTOTYPE_PLANS[1].region_rows[REGION]
    positions = {row: index for index, row in enumerate(_region_rows())}
    return (
        tuple(positions[row] for row in rows["representative"]),
        tuple(positions[row] for row in rows["omitted"]),
    )


REGION_ROWS = _region_rows()
REPRESENTATIVE_POSITIONS, OMITTED_POSITIONS = _region_positions()
PLANNED_Q_ROWS = len(OMITTED_POSITIONS)
SLOT_SHAPE = (len(REGION_ROWS), SHAPE_WIDTH)


def settings_digest() -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": CONTROL_MODE,
        "candidate_blocks": CANDIDATE_BLOCKS,
        "veto_blocks": sorted(VETO_BLOCKS),
        "region": REGION,
        "eligible_source_steps": ELIGIBLE_CACHE_SOURCE_STEPS,
        "maximum_records": MAX_EVIDENCE_RECORDS,
        "oracle": "ASYNC_D2H_PINNED_RING_CPU_EXACT_BF16",
        "full_compute_only": True,
        "h2d_bytes": 0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def evidence_design_receipt() -> dict[str, Any]:
    return {
        "label": HOLDOUT_LABEL,
        "candidate_blocks": list(CANDIDATE_BLOCKS),
        "veto_blocks": sorted(VETO_BLOCKS),
        "region": REGION,
        "representative_rows": len(REPRESENTATIVE_POSITIONS),
        "omitted_rows": len(OMITTED_POSITIONS),
        "slot_shape": list(SLOT_SHAPE),
        "slot_bytes": CANDIDATE_SLOT_BYTES,
        "source_cache_bytes": HOST_SOURCE_CACHE_BYTES,
        "pinned_ring_bytes": PINNED_HOST_TOTAL_BYTES,
        "expected_enqueue_count": EXPECTED_ENQUEUE_COUNT,
        "expected_record_count": EXPECTED_RECORD_COUNT,
        "record_limit": MAX_EVIDENCE_RECORDS,
        "expected_d2h_bytes": CONTROL_ORACLE_D2H_BYTES,
        "d2h_limit_bytes": CONTROL_TRANSFER_LIMIT_BYTES,
        "h2d_bytes": 0,
    }


@dataclass
class PinnedSlot:
    payload: Any
    completion_event: Any | None = None
    timing_start_event: Any | None = None
    timing_end_event: Any | None = None
    state: str = "FREE"
    metadata: dict[str, Any] | None = None
    ring_generation: int = 0
    occupied_started_at: float | None = None


class PreallocatedPinnedRing:
    """Pinned memory allocated by the node module before workflow submission."""

    def __init__(self, torch_module: Any, *, slot_count: int = PINNED_RING_DEPTH) -> None:
        if slot_count < 2:
            raise ControlV2EvidenceError("pinned ring requires at least two slots")
        self.torch = torch_module
        self.slots = [
            PinnedSlot(
                payload=torch_module.empty(
                    SLOT_SHAPE,
                    dtype=torch_module.bfloat16,
                    device="cpu",
                    pin_memory=True,
                )
            )
            for _ in range(int(slot_count))
        ]
        self.allocated_bytes = sum(
            int(slot.payload.numel()) * int(slot.payload.element_size()) for slot in self.slots
        )
        if self.allocated_bytes != CANDIDATE_SLOT_BYTES * int(slot_count):
            raise ControlV2EvidenceError("pinned ring allocation size changed")


class D2HEventFinalizer:
    """Admit completed D2H slots while isolating optional CUDA timing."""

    def __init__(self) -> None:
        self.completion_query_count = 0
        self.completion_not_ready_count = 0
        self.timing_sample_count = 0
        self.timing_unknown_count = 0
        self.timing_total_ms = 0.0
        self.timing_failure_reasons: list[str] = []
        self.cleaned_event_count = 0

    def try_finalize(self, slot: PinnedSlot) -> dict[str, Any]:
        """Return pending until D2H completion; timing can fail independently."""

        if slot.state != "D2H_IN_FLIGHT" or slot.metadata is None:
            raise ControlV2EvidenceError("event finalizer received an invalid D2H slot")
        if slot.completion_event is None:
            raise ControlV2EvidenceError("D2H completion event is missing")
        self.completion_query_count += 1
        try:
            completed = bool(slot.completion_event.query())
        except BaseException as error:
            raise ControlV2EvidenceError("D2H completion query failed") from error
        if not completed:
            self.completion_not_ready_count += 1
            return {"admitted": False, "completion": "PENDING", "timing": None}
        slot.state = "CPU_READY"

        timing: dict[str, Any]
        if slot.timing_start_event is None or slot.timing_end_event is None:
            timing = self._unknown_timing("TIMING_EVENT_MISSING")
        else:
            try:
                elapsed_ms = float(
                    slot.timing_start_event.elapsed_time(slot.timing_end_event)
                )
                self.timing_sample_count += 1
                self.timing_total_ms += elapsed_ms
                timing = {
                    "status": "MEASURED_CUDA_EVENT",
                    "value": elapsed_ms,
                    "unit": "ms",
                    "measurement_method": "timing-enabled CUDA start.elapsed_time(end)",
                    "fallback_reason": None,
                }
            except BaseException as error:
                timing = self._unknown_timing(
                    f"TIMING_ELAPSED_TIME_FAILED:{type(error).__name__}"
                )
        return {"admitted": True, "completion": "COMPLETE", "timing": timing}

    def _unknown_timing(self, reason: str) -> dict[str, Any]:
        self.timing_unknown_count += 1
        if reason not in self.timing_failure_reasons:
            self.timing_failure_reasons.append(reason)
        return {
            "status": "UNKNOWN",
            "value": None,
            "unit": "ms",
            "measurement_method": "CUDA event timing unavailable",
            "fallback_reason": reason,
        }

    def cleanup_slot(self, slot: PinnedSlot) -> None:
        for name in (
            "completion_event",
            "timing_start_event",
            "timing_end_event",
        ):
            if getattr(slot, name) is not None:
                self.cleaned_event_count += 1
            setattr(slot, name, None)
        slot.metadata = None
        slot.occupied_started_at = None
        slot.state = "FREE"

    @staticmethod
    def release_slot(slot: PinnedSlot) -> None:
        """Release a finalized slot while retaining its reusable CUDA events."""

        if slot.state != "FINALIZED":
            raise ControlV2EvidenceError("only a finalized slot may be released")
        slot.metadata = None
        slot.occupied_started_at = None
        slot.state = "FREE"

    def receipt(self) -> dict[str, Any]:
        status = "UNKNOWN" if self.timing_unknown_count else "MEASURED_CUDA_EVENT"
        if self.timing_sample_count == 0 and self.timing_unknown_count == 0:
            status = "NOT_COLLECTED"
        return {
            "completion_method": "nonblocking CUDA Event query",
            "completion_query_count": self.completion_query_count,
            "completion_not_ready_count": self.completion_not_ready_count,
            "completion_event_elapsed_time_count": 0,
            "forced_cpu_synchronization_count": 0,
            "timing_status": status,
            "timing_sample_count": self.timing_sample_count,
            "timing_unknown_count": self.timing_unknown_count,
            "timing_total_ms": (
                None if self.timing_unknown_count else self.timing_total_ms
            ),
            "timing_failure_reasons": list(self.timing_failure_reasons),
            "host_wall_time_substituted_for_cuda_time": False,
            "cleaned_event_count": self.cleaned_event_count,
        }


def _evidence_integrity_checks(
    receipt: Mapping[str, Any],
    *,
    expected_enqueue_count: int,
    expected_record_count: int,
    expected_d2h_bytes: int,
) -> dict[str, bool]:
    writes = receipt.get("ring_write_sequence", [])
    reads = receipt.get("ring_read_sequence", [])
    return {
        "enqueue_count_exact": receipt.get("enqueue_count") == expected_enqueue_count,
        "record_count_exact": receipt.get("record_count") == expected_record_count,
        "incomplete_zero": receipt.get("incomplete_record_count") == 0,
        "ring_backpressure_zero": receipt.get("ring_backpressure_count") == 0,
        "ring_overflow_zero": receipt.get("ring_overflow_count") == 0,
        "ring_overwrite_zero": receipt.get("ring_overwrite_count") == 0,
        "evidence_drop_zero": receipt.get("evidence_drop_count") == 0,
        "duplicate_d2h_zero": receipt.get("duplicate_d2h_count") == 0,
        "lineage_mismatch_zero": receipt.get("lineage_mismatch_count") == 0,
        "d2h_bytes_exact": receipt.get("d2h_bytes") == expected_d2h_bytes,
        "h2d_bytes_zero": receipt.get("h2d_bytes") == 0,
        "ring_sequence_cardinality_exact": len(writes)
        == len(reads)
        == expected_enqueue_count,
        "ring_sequence_identity_exact": writes == reads,
        "event_and_slot_cleanup_pass": receipt.get("event_and_slot_cleanup_pass")
        is True,
        "hot_path_forced_sync_zero": receipt.get("hot_path_forced_sync_count")
        == 0,
    }


def _timing_summary(samples: Sequence[float]) -> dict[str, Any]:
    if not samples:
        return {
            "count": 0,
            "total": 0.0,
            "min": None,
            "median": None,
            "p95": None,
            "max": None,
        }
    ordered = sorted(float(value) for value in samples)
    middle = len(ordered) // 2
    median_value = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    p95_index = min(len(ordered) - 1, max(0, (95 * len(ordered) + 99) // 100 - 1))
    return {
        "count": len(ordered),
        "total": sum(ordered),
        "min": ordered[0],
        "median": median_value,
        "p95": ordered[p95_index],
        "max": ordered[-1],
    }


def _chunked_metrics(torch_module: Any, source: Any, current: Any) -> dict[str, Any]:
    """Compute the established correction and quality metrics on bounded CPU chunks."""

    representative = torch_module.tensor(REPRESENTATIVE_POSITIONS, dtype=torch_module.long)
    omitted = torch_module.tensor(OMITTED_POSITIONS, dtype=torch_module.long)
    if tuple(source.shape) != tuple(current.shape) or int(source.ndim) != 2:
        raise ControlV2EvidenceError("CPU oracle source/current shape mismatch")
    width = int(source.shape[1])
    delta = torch_module.zeros((width,), dtype=torch_module.float32)
    for start in range(0, int(representative.numel()), METRIC_CHUNK_ROWS):
        positions = representative[start : start + METRIC_CHUNK_ROWS]
        delta.add_(
            (
                current.index_select(0, positions).float()
                - source.index_select(0, positions).float()
            ).sum(dim=0)
        )
    delta.div_(int(representative.numel()))

    accumulators = {
        "raw": {"dot": 0.0, "prediction_sq": 0.0, "difference_sq": 0.0},
        "corrected": {"dot": 0.0, "prediction_sq": 0.0, "difference_sq": 0.0},
    }
    actual_sq = 0.0
    finite = True
    for start in range(0, int(omitted.numel()), METRIC_CHUNK_ROWS):
        positions = omitted[start : start + METRIC_CHUNK_ROWS]
        actual = current.index_select(0, positions).float()
        raw_prediction = source.index_select(0, positions).float()
        corrected_prediction = raw_prediction + delta
        actual_sq += float((actual * actual).sum().item())
        for name, prediction in (("raw", raw_prediction), ("corrected", corrected_prediction)):
            difference = actual - prediction
            values = accumulators[name]
            values["dot"] += float((actual * prediction).sum().item())
            values["prediction_sq"] += float((prediction * prediction).sum().item())
            values["difference_sq"] += float((difference * difference).sum().item())
            finite = finite and bool(torch_module.isfinite(prediction).all().item())
        finite = finite and bool(torch_module.isfinite(actual).all().item())
    actual_norm = max(actual_sq, 1e-24) ** 0.5
    result: dict[str, Any] = {}
    for name, values in accumulators.items():
        prediction_norm = max(values["prediction_sq"], 1e-24) ** 0.5
        result[name] = {
            "cosine": values["dot"] / (actual_norm * prediction_norm),
            "normalized_l2": max(values["difference_sq"], 0.0) ** 0.5 / actual_norm,
            "finite": finite,
        }
    return result


class HybridControlOracleWorker:
    """One-way D2H producer with all host waits and metrics on one worker."""

    def __init__(
        self,
        torch_module: Any,
        resources: PreallocatedPinnedRing,
        *,
        lineage_base: str,
        diagnostic: LineageDiagnosticRecorder | None = None,
    ) -> None:
        self.torch = torch_module
        self.resources = resources
        self.lineage_base = lineage_base
        self.diagnostic = diagnostic
        self.transfer_stream: Any | None = None
        self._queue: Queue[int | None] = Queue(maxsize=len(resources.slots))
        self._lock = Lock()
        self._worker = Thread(target=self._run, name="hiveframe-h3-control-v2-oracle", daemon=True)
        self._write_index = 0
        self._source_cache: dict[int, Any] = {}
        self._source_steps: dict[int, int] = {}
        self._source_metadata: dict[int, dict[str, Any]] = {}
        self._failure: BaseException | None = None
        self.event_finalizer = D2HEventFinalizer()
        self.records: list[dict[str, Any]] = []
        self.source_identities: set[str] = set()
        self.ring_write_sequence: list[dict[str, Any]] = []
        self.ring_read_sequence: list[dict[str, Any]] = []
        self.integrity_checks: dict[str, bool] | None = None
        self.event_and_slot_cleanup_pass = False
        self.enqueue_count = 0
        self.d2h_bytes = 0
        self.h2d_bytes = 0
        self.background_event_wait_count = 0
        self.hot_path_forced_sync_count = 0
        self.ring_backpressure_count = 0
        self.ring_overflow_count = 0
        self.ring_overwrite_count = 0
        self.evidence_drop_count = 0
        self.duplicate_d2h_count = 0
        self.lineage_mismatch_count = 0
        self.nonfinite_count = 0
        self.cpu_oracle_time_ms = 0.0
        self.cpu_service_seconds: list[float] = []
        self.slot_occupancy_seconds: list[float] = []
        self.enqueue_host_times: list[float] = []
        self.ring_high_water_mark = 0
        self._worker.start()

    def _raise_worker_failure(self) -> None:
        if self.diagnostic is not None and self.diagnostic.failed:
            raise LineageDiagnosticAbort(
                "background oracle lineage diagnostic failed"
            ) from self._failure
        if self._failure is not None:
            raise ControlV2EvidenceError("background CPU oracle failed") from self._failure

    def enqueue(self, *, payload: Any, metadata: Mapping[str, Any], producer_event: Any) -> Any:
        """Schedule D2H without a host read or wait; return the transfer completion event."""

        enqueue_host_time = perf_counter()
        self._raise_worker_failure()
        identity = str(metadata["source_identity"])
        if identity in self.source_identities:
            self.duplicate_d2h_count += 1
            self._capture_enqueue_failure(
                "DUPLICATE_OR_MISSING_RECORD:DUPLICATE_SOURCE_IDENTITY", metadata
            )
            raise ControlV2EvidenceError("duplicate source identity would repeat D2H")
        if payload.device.type != "cuda" or payload.dtype != self.torch.bfloat16:
            raise ControlV2EvidenceError("CONTROL V2 accepts CUDA BF16 payloads only")
        if tuple(int(value) for value in payload.shape) != SLOT_SHAPE:
            raise ControlV2EvidenceError("CONTROL V2 payload shape changed")
        if self.transfer_stream is None:
            self.transfer_stream = self.torch.cuda.Stream(device=payload.device)
            for slot in self.resources.slots:
                slot.completion_event = self.torch.cuda.Event(blocking=False)
                slot.timing_start_event = self.torch.cuda.Event(
                    enable_timing=True, blocking=False
                )
                slot.timing_end_event = self.torch.cuda.Event(
                    enable_timing=True, blocking=False
                )
        with self._lock:
            slot_index = next(
                (
                    (self._write_index + offset) % len(self.resources.slots)
                    for offset in range(len(self.resources.slots))
                    if self.resources.slots[
                        (self._write_index + offset) % len(self.resources.slots)
                    ].state
                    == "FREE"
                ),
                None,
            )
            if slot_index is None:
                self.ring_backpressure_count += 1
                self.ring_overflow_count += 1
                self._capture_enqueue_failure(
                    "DUPLICATE_OR_MISSING_RECORD:RING_SLOT_NOT_FREE", metadata
                )
                if self.diagnostic is not None:
                    raise LineageDiagnosticAbort(
                        "lineage diagnostic captured ring backpressure"
                    )
                raise ControlV2EvidenceError("CPU oracle lag would overwrite the pinned ring")
            slot = self.resources.slots[slot_index]
            next_enqueue = self.enqueue_count + 1
            slot.ring_generation += 1
            prepared = dict(metadata)
            if self.diagnostic is not None:
                prepared = self.diagnostic.enrich_enqueue(
                    prepared,
                    enqueue_sequence=next_enqueue,
                    ring_slot_id=slot_index,
                    ring_slot_generation=slot.ring_generation,
                    ring_write_sequence=next_enqueue,
                )
            slot.state = "D2H_IN_FLIGHT"
            slot.metadata = prepared
            slot.occupied_started_at = enqueue_host_time
            self._write_index = (self._write_index + 1) % len(self.resources.slots)
            self.ring_high_water_mark = max(
                self.ring_high_water_mark,
                sum(candidate.state != "FREE" for candidate in self.resources.slots),
            )
        with self.torch.cuda.stream(self.transfer_stream):
            self.transfer_stream.wait_event(producer_event)
            slot.timing_start_event.record(self.transfer_stream)
            slot.payload.copy_(payload, non_blocking=True)
            slot.timing_end_event.record(self.transfer_stream)
            slot.completion_event.record(self.transfer_stream)
        try:
            self._queue.put_nowait(slot_index)
        except Full as error:
            self.ring_backpressure_count += 1
            self.ring_overflow_count += 1
            self._capture_enqueue_failure(
                "DUPLICATE_OR_MISSING_RECORD:QUEUE_OVERFLOW", slot.metadata or metadata
            )
            if self.diagnostic is not None:
                raise LineageDiagnosticAbort(
                    "lineage diagnostic captured oracle queue overflow"
                ) from error
            raise ControlV2EvidenceError("CPU oracle queue overflow") from error
        self.source_identities.add(identity)
        self.enqueue_host_times.append(enqueue_host_time)
        self.enqueue_count += 1
        self.d2h_bytes += CANDIDATE_SLOT_BYTES
        self.ring_write_sequence.append(
            self._sequence_entry(slot_index, slot.metadata, self.enqueue_count)
        )
        if self.d2h_bytes > CONTROL_TRANSFER_LIMIT_BYTES:
            raise ControlV2EvidenceError("CONTROL V2 D2H budget exceeded")
        return slot.completion_event

    def _capture_enqueue_failure(
        self, rejection_reason: str, metadata: Mapping[str, Any]
    ) -> None:
        if self.diagnostic is None or self.diagnostic.failed:
            return
        current = dict(metadata)
        current.setdefault("oracle_enqueue_sequence", self.enqueue_count + 1)
        current.setdefault("oracle_completion_sequence", None)
        current.setdefault("finalizer_sequence", None)
        current.setdefault("ring_slot_id", self._write_index)
        current.setdefault("ring_slot_generation", 0)
        current.setdefault("ring_write_sequence", self.enqueue_count + 1)
        current.setdefault("ring_read_sequence", None)
        current.setdefault("current_lineage_digest", current.get("oracle_lineage_digest"))
        source = self._source_metadata.get(int(current["block_id"]))
        self.diagnostic.capture_failure(
            rejection_reason=rejection_reason,
            source=source,
            current=current,
        )

    @staticmethod
    def _sequence_entry(
        slot_index: int, metadata: Mapping[str, Any], ordinal: int
    ) -> dict[str, Any]:
        return {
            "ordinal": ordinal,
            "slot": slot_index,
            "block": int(metadata["block"]),
            "step": int(metadata["step"]),
            "source_identity_digest": sha256(
                str(metadata["source_identity"]).encode()
            ).hexdigest(),
        }

    def _run(self) -> None:
        try:
            while True:
                slot_index = self._queue.get()
                if slot_index is None:
                    self._queue.task_done()
                    return
                try:
                    while not self._consume(slot_index):
                        sleep(0.001)
                finally:
                    self._queue.task_done()
        except BaseException as error:
            self._failure = error

    def _consume(self, slot_index: int) -> bool:
        slot = self.resources.slots[slot_index]
        if slot.state != "D2H_IN_FLIGHT" or slot.metadata is None:
            raise ControlV2EvidenceError("worker received an invalid pinned slot")
        finalized = self.event_finalizer.try_finalize(slot)
        if finalized["admitted"] is not True:
            return False
        if slot.state != "CPU_READY":
            raise ControlV2EvidenceError("completed D2H slot did not become CPU ready")
        slot.state = "PROCESSING"
        service_started = perf_counter()
        self.background_event_wait_count += 1
        metadata = slot.metadata
        if self.diagnostic is not None:
            self.diagnostic.mark_completion(metadata)
            self.diagnostic.mark_finalizer(
                metadata, ring_read_sequence=len(self.ring_read_sequence) + 1
            )
        block = int(metadata["block"])
        step = int(metadata["step"])
        source = self._source_cache.get(block)
        source_metadata = self._source_metadata.get(block)
        if source is not None:
            source_step = self._source_steps[block]
            if source_step + 1 != step or metadata["lineage_base"] != self.lineage_base:
                self.lineage_mismatch_count += 1
                if self.diagnostic is not None:
                    completed_after = self._completed_after_mismatch(slot_index)
                    self.diagnostic.capture_failure(
                        rejection_reason=(
                            "SOURCE_DENOISE_ORDINAL_NOT_AGE_ONE"
                            if source_step + 1 != step
                            else "CURRENT_LINEAGE_DIGEST_MISMATCH"
                        ),
                        source=source_metadata,
                        current=metadata,
                        completed_after_mismatch=completed_after,
                    )
                raise ControlV2EvidenceError("source lineage or step ordering changed")
            if source_step in ELIGIBLE_CACHE_SOURCE_STEPS:
                if len(self.records) >= MAX_EVIDENCE_RECORDS:
                    raise ControlV2EvidenceError("complete evidence batch would overflow")
                started = perf_counter()
                metrics = _chunked_metrics(self.torch, source, slot.payload)
                self.cpu_oracle_time_ms += (perf_counter() - started) * 1000.0
                corrected = metrics["corrected"]
                finite = bool(corrected["finite"])
                unsafe = (
                    not finite
                    or float(corrected["cosine"]) < CATASTROPHIC_COSINE_MIN
                    or float(corrected["normalized_l2"]) > CATASTROPHIC_NORMALIZED_L2_MAX
                )
                state = str(metadata["predicted_state"])
                if not finite:
                    self.nonfinite_count += 1
                self.records.append(
                    {
                        "evidence_label": HOLDOUT_LABEL,
                        "step": step,
                        "source_step": source_step,
                        "block": block,
                        "region": REGION,
                        "packed_row_start": min(REGION_ROWS),
                        "packed_row_count": len(REGION_ROWS),
                        "predicted_state": state,
                        "uncertainty_ppm": int(metadata["uncertainty_ppm"]),
                        "motion_ppm": int(metadata["motion_ppm"]),
                        "payload_bytes": CANDIDATE_SLOT_BYTES,
                        "planned_q_rows": PLANNED_Q_ROWS,
                        "raw": metrics["raw"],
                        "corrected": corrected,
                        "actual_safety": "UNSAFE" if unsafe else "SAFE",
                        "false_safe": state == "STABLE" and unsafe,
                        "false_unsafe": state != "STABLE" and not unsafe,
                        "oracle_lineage_digest": str(metadata["oracle_lineage_digest"]),
                    }
                )
        if self.diagnostic is not None:
            self.diagnostic.record_valid_pair(
                source=source_metadata,
                current=metadata,
            )
        retained = self._source_cache.get(block)
        if retained is None:
            retained = self.torch.empty_like(slot.payload, pin_memory=False)
            self._source_cache[block] = retained
        retained.copy_(slot.payload)
        self._source_steps[block] = step
        self._source_metadata[block] = dict(metadata)
        self.ring_read_sequence.append(
            self._sequence_entry(
                slot_index, metadata, len(self.ring_read_sequence) + 1
            )
        )
        with self._lock:
            occupied_started_at = slot.occupied_started_at
            slot.state = "FINALIZED"
            self.event_finalizer.release_slot(slot)
        service_finished = perf_counter()
        self.cpu_service_seconds.append(service_finished - service_started)
        if occupied_started_at is not None:
            self.slot_occupancy_seconds.append(service_finished - occupied_started_at)
        return True

    def _completed_after_mismatch(self, current_slot_index: int) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        if self.diagnostic is None:
            return completed
        for index, candidate in enumerate(self.resources.slots):
            if index == current_slot_index or candidate.state != "D2H_IN_FLIGHT":
                continue
            if candidate.metadata is None or candidate.completion_event is None:
                continue
            try:
                ready = bool(candidate.completion_event.query())
            except BaseException:
                ready = False
            if ready:
                self.diagnostic.mark_completion(candidate.metadata)
                completed.append(dict(candidate.metadata))
            if len(completed) == 4:
                break
        return completed

    def finish(self, timeout_seconds: float = 900.0) -> None:
        deadline = perf_counter() + timeout_seconds
        while self._queue.unfinished_tasks and perf_counter() < deadline:
            self._raise_worker_failure()
            sleep(0.05)
        self._raise_worker_failure()
        if self._queue.unfinished_tasks:
            raise ControlV2EvidenceError("CPU oracle did not drain before its bounded timeout")
        self._queue.put_nowait(None)
        self._worker.join(timeout=5.0)
        self._raise_worker_failure()
        if self._worker.is_alive():
            raise ControlV2EvidenceError("CPU oracle worker did not terminate")
        for slot in self.resources.slots:
            self.event_finalizer.cleanup_slot(slot)
        self.transfer_stream = None
        self.event_and_slot_cleanup_pass = all(
            slot.state == "FREE"
            and slot.metadata is None
            and slot.completion_event is None
            and slot.timing_start_event is None
            and slot.timing_end_event is None
            for slot in self.resources.slots
        )

    def abort_and_cleanup(self, timeout_seconds: float = 30.0) -> None:
        """Drain already-enqueued D2H work without a forced CUDA synchronization."""

        deadline = perf_counter() + timeout_seconds
        while (
            self._worker.is_alive()
            and self._failure is None
            and self._queue.unfinished_tasks
            and perf_counter() < deadline
        ):
            sleep(0.001)
        if self._worker.is_alive() and self._failure is None:
            self._queue.put_nowait(None)
            self._worker.join(timeout=max(0.0, deadline - perf_counter()))
        if self._worker.is_alive():
            raise ControlV2EvidenceError(
                "diagnostic CPU oracle did not stop before cleanup"
            )
        while perf_counter() < deadline:
            pending = [
                slot
                for slot in self.resources.slots
                if slot.state == "D2H_IN_FLIGHT" and slot.completion_event is not None
            ]
            if not pending:
                break
            if all(bool(slot.completion_event.query()) for slot in pending):
                break
            sleep(0.001)
        for slot in self.resources.slots:
            if slot.state == "D2H_IN_FLIGHT" and slot.completion_event is not None:
                if not bool(slot.completion_event.query()):
                    raise ControlV2EvidenceError(
                        "diagnostic D2H cleanup did not complete before timeout"
                    )
            self.event_finalizer.cleanup_slot(slot)
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except Empty:
                break
        self.transfer_stream = None
        self.event_and_slot_cleanup_pass = all(
            slot.state == "FREE" and slot.metadata is None
            for slot in self.resources.slots
        )

    def validate_integrity(self) -> dict[str, bool]:
        receipt = self.receipt()
        checks = _evidence_integrity_checks(
            receipt,
            expected_enqueue_count=EXPECTED_ENQUEUE_COUNT,
            expected_record_count=EXPECTED_RECORD_COUNT,
            expected_d2h_bytes=CONTROL_ORACLE_D2H_BYTES,
        )
        self.integrity_checks = checks
        if not all(checks.values()):
            failed = sorted(name for name, passed in checks.items() if not passed)
            raise ControlV2EvidenceError(
                "CONTROL V2 evidence integrity failed: " + ",".join(failed)
            )
        return checks

    def receipt(self) -> dict[str, Any]:
        timing = self.event_finalizer.receipt()
        producer_span = (
            self.enqueue_host_times[-1] - self.enqueue_host_times[0]
            if len(self.enqueue_host_times) > 1
            else 0.0
        )
        service_total = sum(self.cpu_service_seconds)
        return {
            "scope": "REAL_H3_FULL_COMPUTE_CONTROL_V2",
            "enqueue_count": self.enqueue_count,
            "record_count": len(self.records),
            "complete_record_count": len(self.records),
            "incomplete_record_count": 0,
            "source_cache_bytes": sum(
                int(value.numel()) * int(value.element_size()) for value in self._source_cache.values()
            ),
            "pinned_ring_bytes": self.resources.allocated_bytes,
            "d2h_bytes": self.d2h_bytes,
            "h2d_bytes": self.h2d_bytes,
            "duplicate_d2h_count": self.duplicate_d2h_count,
            "background_event_wait_count": self.background_event_wait_count,
            "hot_path_forced_sync_count": self.hot_path_forced_sync_count,
            "ring_backpressure_count": self.ring_backpressure_count,
            "ring_overflow_count": self.ring_overflow_count,
            "ring_overwrite_count": self.ring_overwrite_count,
            "evidence_drop_count": self.evidence_drop_count,
            "lineage_mismatch_count": self.lineage_mismatch_count,
            "nonfinite_count": self.nonfinite_count,
            "d2h_transfer_time_ms": timing["timing_total_ms"],
            "d2h_timing_telemetry": timing,
            "cpu_oracle_time_ms": self.cpu_oracle_time_ms,
            "cpu_service_seconds": _timing_summary(self.cpu_service_seconds),
            "slot_occupancy_seconds": _timing_summary(self.slot_occupancy_seconds),
            "enqueue_interval_seconds": _timing_summary(
                [
                    current - previous
                    for previous, current in zip(
                        self.enqueue_host_times, self.enqueue_host_times[1:]
                    )
                ]
            ),
            "producer_arrival_rate_records_per_second": (
                (len(self.enqueue_host_times) - 1) / producer_span
                if producer_span > 0.0
                else None
            ),
            "worker_service_rate_records_per_second": (
                len(self.cpu_service_seconds) / service_total
                if service_total > 0.0
                else None
            ),
            "ring_high_water_mark": self.ring_high_water_mark,
            "ring_slot_count": len(self.resources.slots),
            "final_slot_states": [slot.state for slot in self.resources.slots],
            "final_backlog": self._queue.unfinished_tasks,
            "persistent_gpu_source_bytes": 0,
            "rust_tensor_bytes": 0,
            "ring_write_sequence": list(self.ring_write_sequence),
            "ring_read_sequence": list(self.ring_read_sequence),
            "event_and_slot_cleanup_pass": self.event_and_slot_cleanup_pass,
            "integrity_checks": dict(self.integrity_checks or {}),
            "lineage_diagnostic": (
                None if self.diagnostic is None else self.diagnostic.receipt()
            ),
        }


class H3RowRegionSafetyControllerV2(H3A3G1Controller):
    """Observe every candidate output while all H3 Attention remains exact Full Compute."""

    def __init__(
        self,
        *,
        plan_bridge: SafetyEvidencePlanBridge,
        h3_model: Any,
        torch_module: Any,
        resources: PreallocatedPinnedRing,
        lineage_base: str,
        diagnostic: LineageDiagnosticRecorder | None = None,
    ) -> None:
        super().__init__(
            mode=CONTROL_MODE,
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch_module,
            candidate_blocks=CANDIDATE_BLOCKS,
        )
        self.oracle = HybridControlOracleWorker(
            torch_module,
            resources,
            lineage_base=lineage_base,
            diagnostic=diagnostic,
        )
        self.lineage_base = lineage_base
        self.diagnostic = diagnostic
        self._pending_metadata: dict[tuple[int, int], dict[str, Any]] = {}
        self._staging_release_event: Any | None = None

    def instrumented_forward(
        self,
        block: Any,
        x: Any,
        t_emb: Any,
        mod_segments: Sequence[Sequence[int]],
        rope_freqs: Any,
        transformer_options: Mapping[str, Any] | None = None,
    ) -> Any:
        if self.diagnostic is not None:
            self.oracle._raise_worker_failure()
        result = super().instrumented_forward(
            block,
            x,
            t_emb,
            mod_segments,
            rope_freqs,
            transformer_options,
        )
        if self.diagnostic is not None:
            self.oracle._raise_worker_failure()
        return result

    def _cache_ready(self, block_index: int, step: int) -> bool:
        return int(block_index) in CANDIDATE_BLOCKS and 1 <= int(step) <= 17

    def _observe_full_compute_control(
        self,
        *,
        block_index: int,
        step: int,
        plan: Mapping[str, Any] | None,
        directive: str,
        stable_mask: int,
        full_core: Any,
    ) -> None:
        del directive, stable_mask, full_core
        confidence = plan.get("eye_confidence_ppm", [0] * 5) if isinstance(plan, Mapping) else [0] * 5
        motion = plan.get("eye_change_ppm", [1_000_000] * 5) if isinstance(plan, Mapping) else [1_000_000] * 5
        state = self._predicted_state(plan)
        oracle_lineage = sha256(
            f"{self.lineage_base}:{block_index}:{REGION}".encode()
        ).hexdigest()
        self._pending_metadata[(block_index, step)] = {
            "block": block_index,
            "step": step,
            "source_step_raw": None,
            "current_step_raw": step,
            "source_denoise_ordinal": None,
            "current_denoise_ordinal": step,
            "source_scheduler_timestep": None,
            "current_scheduler_timestep": (
                None
                if self.diagnostic is None
                else self.diagnostic.context.scheduler_timestep(step)
            ),
            "model_forward_ordinal": step,
            "attention_call_ordinal": self.block_call_count,
            "block_id": block_index,
            "region_id": REGION,
            "predicted_state": state,
            "uncertainty_ppm": max(0, 1_000_000 - int(confidence[REGION + 1])),
            "motion_ppm": int(motion[REGION + 1]),
            "lineage_base": self.lineage_base,
            "oracle_lineage_digest": oracle_lineage,
            "source_identity": f"{oracle_lineage}:{step}",
        }

    @staticmethod
    def _predicted_state(plan: Mapping[str, Any] | None) -> str:
        if not isinstance(plan, Mapping) or bool(plan.get("global_invalidation", True)):
            return "UNCERTAIN"
        stable = plan.get("stable_region_mask", 0)
        active = plan.get("active_mask", 0)
        uncertain = plan.get("uncertain_mask", 0)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (stable, active, uncertain)):
            return "UNCERTAIN"
        if stable & 1 and not ((active | uncertain) & 1):
            return "STABLE"
        if active & 1 and not (uncertain & 1):
            return "ACTIVE"
        return "UNCERTAIN"

    def _refresh_cache(self, *, block_index: int, step: int, full_core: Any) -> None:
        metadata = self._pending_metadata.pop((block_index, step), None)
        if metadata is None:
            raise ControlV2EvidenceError("candidate metadata was not captured before D2H")
        current_stream = self.torch.cuda.current_stream(device=full_core.device)
        if self._staging_release_event is not None:
            current_stream.wait_event(self._staging_release_event)
        indices = self._region_cache_indices[REGION]
        staging = self._region_staging[: int(indices.numel())]
        metadata["current_shape_dtype_device"] = (
            f"shape={tuple(int(value) for value in staging.shape)}|"
            f"dtype={staging.dtype}|device={staging.device.type}"
        )
        self.torch.index_select(full_core, 0, indices, out=staging)
        producer_event = self.torch.cuda.Event(blocking=False)
        producer_event.record(current_stream)
        self._staging_release_event = self.oracle.enqueue(
            payload=staging,
            metadata=metadata,
            producer_event=producer_event,
        )
        self.full_refreshes += 1
        self.eligible_source_steps_seen.add(step)

    def finalize(self) -> dict[str, Any]:
        finalization_started = perf_counter()
        drain_started = perf_counter()
        self.oracle.finish()
        drain_seconds = perf_counter() - drain_started
        self._staging_release_event = None
        integrity = self.oracle.validate_integrity()
        base = super().finalize()
        evidence = list(self.oracle.records)
        confusion = {
            "true_safe": sum(item["predicted_state"] == "STABLE" and item["actual_safety"] == "SAFE" for item in evidence),
            "false_safe": sum(bool(item["false_safe"]) for item in evidence),
            "true_unsafe": sum(item["predicted_state"] != "STABLE" and item["actual_safety"] == "UNSAFE" for item in evidence),
            "false_unsafe": sum(bool(item["false_unsafe"]) for item in evidence),
        }
        oracle = self.oracle.receipt()
        base["schema_version"] = SCHEMA_VERSION
        base["candidate_blocks"] = list(CANDIDATE_BLOCKS)
        base["veto_blocks"] = sorted(VETO_BLOCKS)
        base["safety_evidence"] = {
            "label": HOLDOUT_LABEL,
            "records": evidence,
            "record_count": len(evidence),
            "record_limit": MAX_EVIDENCE_RECORDS,
            "overflow": False,
            "confusion_matrix": confusion,
            "false_unsafe_status": "COLLECTED" if confusion["false_unsafe"] else "NOT_COLLECTED",
            "rust_tensor_transfer_bytes": 0,
        }
        base["hybrid_oracle"] = oracle
        base["hybrid_oracle"]["integrity_checks"] = integrity
        base["cache"].update(
            {
                "host_cache_bytes": oracle["source_cache_bytes"],
                "h2d_bytes": 0,
                "d2h_bytes": oracle["d2h_bytes"],
                "transfer_total_bytes": oracle["d2h_bytes"],
                "cache_hard_cap_bytes": CACHE_HARD_CAP_BYTES,
            }
        )
        base["partial_attention_calls"] = 0
        base["control_timings"] = {
            "cpu_oracle_drain_seconds": drain_seconds,
            "evidence_finalization_seconds": perf_counter() - finalization_started,
        }
        return base

    def finalize_diagnostic(self) -> dict[str, Any]:
        if self.diagnostic is None:
            raise ControlV2EvidenceError("lineage diagnostic is not configured")
        self.oracle.finish()
        self._staging_release_event = None
        self.diagnostic.write_complete_trace()
        base = super().finalize()
        base["formal_control_result"] = False
        base["safety_evidence_admitted"] = False
        base["rust_cache_plan_calls"] = 0
        base["lineage_diagnostic"] = self.diagnostic.receipt()
        base["partial_attention_calls"] = 0
        return base

    def diagnostic_failure_receipt(self) -> dict[str, Any]:
        if self.diagnostic is None:
            return {"lineage_diagnostic": None}
        self.oracle.abort_and_cleanup()
        return {
            "formal_control_result": False,
            "safety_evidence_admitted": False,
            "rust_cache_plan_calls": 0,
            "full_compute_only": True,
            "model_forward_count_observed": self.model_forward_count,
            "block_call_count_observed": self.block_call_count,
            "lineage_diagnostic": self.diagnostic.receipt(),
            "hybrid_oracle": self.oracle.receipt(),
        }

    def close(self) -> None:
        if self.diagnostic is not None and not self.oracle.event_and_slot_cleanup_pass:
            self.oracle.abort_and_cleanup()
        self._pending_metadata.clear()
        self._staging_release_event = None
        self._region_staging = None


if CANDIDATE_AGGREGATE_BYTES != CANDIDATE_SLOT_BYTES * len(CANDIDATE_BLOCKS):
    raise RuntimeError("CONTROL V2 aggregate source-cache design changed")
if EXPECTED_RECORD_COUNT > MAX_EVIDENCE_RECORDS:
    raise RuntimeError("CONTROL V2 evidence design exceeds the fixed record limit")
if FULL_Q_ROWS != 15_424_000:
    raise RuntimeError("CONTROL V2 theoretical Full Q baseline changed")
