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


class ControlV2EvidenceError(RuntimeError):
    """Fail the one-shot CONTROL instead of dropping or truncating evidence."""


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
    event: Any | None = None
    transfer_start: Any | None = None
    state: str = "FREE"
    metadata: dict[str, Any] | None = None


class PreallocatedPinnedRing:
    """Pinned memory allocated by the node module before workflow submission."""

    def __init__(self, torch_module: Any) -> None:
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
            for _ in range(PINNED_RING_DEPTH)
        ]
        self.allocated_bytes = sum(
            int(slot.payload.numel()) * int(slot.payload.element_size()) for slot in self.slots
        )
        if self.allocated_bytes != PINNED_HOST_TOTAL_BYTES:
            raise ControlV2EvidenceError("pinned ring allocation size changed")


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

    def __init__(self, torch_module: Any, resources: PreallocatedPinnedRing, *, lineage_base: str) -> None:
        self.torch = torch_module
        self.resources = resources
        self.lineage_base = lineage_base
        self.transfer_stream: Any | None = None
        self._queue: Queue[int | None] = Queue(maxsize=PINNED_RING_DEPTH)
        self._lock = Lock()
        self._worker = Thread(target=self._run, name="hiveframe-h3-control-v2-oracle", daemon=True)
        self._write_index = 0
        self._source_cache: dict[int, Any] = {}
        self._source_steps: dict[int, int] = {}
        self._failure: BaseException | None = None
        self.records: list[dict[str, Any]] = []
        self.source_identities: set[str] = set()
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
        self.d2h_transfer_time_ms = 0.0
        self._worker.start()

    def _raise_worker_failure(self) -> None:
        if self._failure is not None:
            raise ControlV2EvidenceError("background CPU oracle failed") from self._failure

    def enqueue(self, *, payload: Any, metadata: Mapping[str, Any], producer_event: Any) -> Any:
        """Schedule D2H without a host read or wait; return the transfer completion event."""

        self._raise_worker_failure()
        identity = str(metadata["source_identity"])
        if identity in self.source_identities:
            self.duplicate_d2h_count += 1
            raise ControlV2EvidenceError("duplicate source identity would repeat D2H")
        if payload.device.type != "cuda" or payload.dtype != self.torch.bfloat16:
            raise ControlV2EvidenceError("CONTROL V2 accepts CUDA BF16 payloads only")
        if tuple(int(value) for value in payload.shape) != SLOT_SHAPE:
            raise ControlV2EvidenceError("CONTROL V2 payload shape changed")
        if self.transfer_stream is None:
            self.transfer_stream = self.torch.cuda.Stream(device=payload.device)
            for slot in self.resources.slots:
                slot.event = self.torch.cuda.Event(blocking=False)
                slot.transfer_start = self.torch.cuda.Event(enable_timing=True, blocking=False)
        with self._lock:
            slot_index = self._write_index
            slot = self.resources.slots[slot_index]
            if slot.state != "FREE":
                self.ring_backpressure_count += 1
                self.ring_overflow_count += 1
                raise ControlV2EvidenceError("CPU oracle lag would overwrite the pinned ring")
            slot.state = "PENDING"
            slot.metadata = dict(metadata)
            self._write_index = (self._write_index + 1) % len(self.resources.slots)
        with self.torch.cuda.stream(self.transfer_stream):
            self.transfer_stream.wait_event(producer_event)
            slot.transfer_start.record(self.transfer_stream)
            slot.payload.copy_(payload, non_blocking=True)
            slot.event.record(self.transfer_stream)
        try:
            self._queue.put_nowait(slot_index)
        except Full as error:
            self.ring_backpressure_count += 1
            self.ring_overflow_count += 1
            raise ControlV2EvidenceError("CPU oracle queue overflow") from error
        self.source_identities.add(identity)
        self.enqueue_count += 1
        self.d2h_bytes += CANDIDATE_SLOT_BYTES
        if self.d2h_bytes > CONTROL_TRANSFER_LIMIT_BYTES:
            raise ControlV2EvidenceError("CONTROL V2 D2H budget exceeded")
        return slot.event

    def _run(self) -> None:
        try:
            while True:
                slot_index = self._queue.get()
                if slot_index is None:
                    self._queue.task_done()
                    return
                try:
                    self._consume(slot_index)
                finally:
                    self._queue.task_done()
        except BaseException as error:
            self._failure = error

    def _consume(self, slot_index: int) -> None:
        slot = self.resources.slots[slot_index]
        if slot.state != "PENDING" or slot.metadata is None:
            raise ControlV2EvidenceError("worker received an invalid pinned slot")
        self.background_event_wait_count += 1
        slot.event.synchronize()
        self.d2h_transfer_time_ms += float(slot.transfer_start.elapsed_time(slot.event))
        metadata = slot.metadata
        block = int(metadata["block"])
        step = int(metadata["step"])
        source = self._source_cache.get(block)
        if source is not None:
            source_step = self._source_steps[block]
            if source_step + 1 != step or metadata["lineage_base"] != self.lineage_base:
                self.lineage_mismatch_count += 1
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
        retained = self._source_cache.get(block)
        if retained is None:
            retained = self.torch.empty_like(slot.payload, pin_memory=False)
            self._source_cache[block] = retained
        retained.copy_(slot.payload)
        self._source_steps[block] = step
        with self._lock:
            slot.metadata = None
            slot.state = "FREE"

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

    def receipt(self) -> dict[str, Any]:
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
            "d2h_transfer_time_ms": self.d2h_transfer_time_ms,
            "cpu_oracle_time_ms": self.cpu_oracle_time_ms,
            "persistent_gpu_source_bytes": 0,
            "rust_tensor_bytes": 0,
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
    ) -> None:
        super().__init__(
            mode=CONTROL_MODE,
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch_module,
            candidate_blocks=CANDIDATE_BLOCKS,
        )
        self.oracle = HybridControlOracleWorker(
            torch_module, resources, lineage_base=lineage_base
        )
        self.lineage_base = lineage_base
        self._pending_metadata: dict[tuple[int, int], dict[str, Any]] = {}
        self._staging_release_event: Any | None = None

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
        self.oracle.finish()
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
        return base

    def close(self) -> None:
        self._pending_metadata.clear()
        self._region_staging = None


if CANDIDATE_AGGREGATE_BYTES != CANDIDATE_SLOT_BYTES * len(CANDIDATE_BLOCKS):
    raise RuntimeError("CONTROL V2 aggregate source-cache design changed")
if EXPECTED_RECORD_COUNT > MAX_EVIDENCE_RECORDS:
    raise RuntimeError("CONTROL V2 evidence design exceeds the fixed record limit")
if FULL_Q_ROWS != 15_424_000:
    raise RuntimeError("CONTROL V2 theoretical Full Q baseline changed")
