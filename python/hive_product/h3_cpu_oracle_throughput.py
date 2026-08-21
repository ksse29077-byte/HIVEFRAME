"""Model-free throughput and capacity contract for the H3 CPU oracle ring."""

from __future__ import annotations

from hashlib import sha256
import heapq
import json
from typing import Any, Mapping, Sequence

from .h3_hybrid_cache_staging import (
    CANDIDATE_COUNT,
    CONTROL_STEP_UPPER_BOUND,
    PINNED_RING_DEPTH,
    TRACE_MEASURED_MAX_IN_FLIGHT,
)


SCHEMA_VERSION = "h3.cpu-oracle-ring-throughput.1"
SELECTED_WORKER_COUNT = 1
TRACE_BURST_LENGTH = 3
TRACE_PROGRESS_INTERVAL_SECONDS = 66.20238609996159
SUSTAINED_RATE_MARGIN = 1.10


def analyze_backpressure_trace(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Recover only facts explicitly present in the bounded 30/31/32/33 trace."""

    pending = list(trace.get("pending_records_before_mismatch", []))
    mismatch = dict(trace.get("mismatch", {}))
    pending_sequences = [int(item["oracle_enqueue_sequence"]) for item in pending]
    rejected_sequence = int(mismatch["oracle_enqueue_sequence"])
    if pending_sequences != [31, 32] or rejected_sequence != 33:
        raise ValueError("the bounded actual-H3 backpressure trace changed")
    measured_in_flight = len(pending_sequences) + 1
    if measured_in_flight != TRACE_MEASURED_MAX_IN_FLIGHT:
        raise ValueError("trace-derived maximum in-flight contract changed")
    return {
        "fully_consumed_sequence": int(
            trace["last_fully_consumed_sequence_before_mismatch"]
        ),
        "pending_sequences": pending_sequences,
        "first_rejected_sequence": rejected_sequence,
        "measured_maximum_in_flight": measured_in_flight,
        "payload_arrival_timestamps": "UNAVAILABLE_IN_SOURCE_TRACE",
        "cpu_service_timestamps": "UNAVAILABLE_IN_SOURCE_TRACE",
    }


def simulate_ring(
    arrivals: Sequence[tuple[int, float]],
    *,
    service_seconds: Sequence[float],
    ring_slots: int,
    worker_count: int,
) -> dict[str, Any]:
    """Deterministically replay slot occupancy without sleeping or GPU work."""

    if ring_slots < 1 or worker_count < 1 or not service_seconds:
        raise ValueError("ring replay requires slots, workers, and service samples")
    workers = [(0.0, worker) for worker in range(worker_count)]
    heapq.heapify(workers)
    in_flight: list[tuple[float, int]] = []
    accepted: list[int] = []
    rejected: list[int] = []
    completions: list[tuple[float, int]] = []
    high_water = 0
    backlog_growth = 0
    previous_occupancy = 0
    for index, (ordinal, arrival) in enumerate(arrivals):
        while in_flight and in_flight[0][0] <= float(arrival):
            heapq.heappop(in_flight)
        occupancy = len(in_flight)
        if occupancy >= ring_slots:
            rejected.append(int(ordinal))
            continue
        worker_ready, worker = heapq.heappop(workers)
        started = max(float(arrival), worker_ready)
        completed = started + float(service_seconds[index % len(service_seconds)])
        heapq.heappush(workers, (completed, worker))
        heapq.heappush(in_flight, (completed, int(ordinal)))
        completions.append((completed, int(ordinal)))
        accepted.append(int(ordinal))
        occupancy = len(in_flight)
        high_water = max(high_water, occupancy)
        backlog_growth = max(backlog_growth, occupancy - previous_occupancy)
        previous_occupancy = occupancy
    completion_order = [ordinal for _, ordinal in sorted(completions)]
    digest_payload = {
        "accepted": accepted,
        "rejected": rejected,
        "completion_order": completion_order,
    }
    return {
        "ring_slots": int(ring_slots),
        "worker_count": int(worker_count),
        "arrival_count": len(arrivals),
        "accepted_count": len(accepted),
        "rejected_sequences": rejected,
        "ring_high_water_mark": high_water,
        "maximum_backlog_growth": backlog_growth,
        "completion_order": completion_order,
        "final_backlog": 0 if not rejected else len(rejected),
        "deterministic_digest": sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def production_arrivals(
    *,
    step_interval_seconds: float = TRACE_PROGRESS_INTERVAL_SECONDS,
) -> list[tuple[int, float]]:
    """Build the 20-step, 30-candidate order with trace-backed bursts of three."""

    if step_interval_seconds <= 0:
        raise ValueError("step interval must be positive")
    arrivals: list[tuple[int, float]] = []
    ordinal = 0
    burst_count = CANDIDATE_COUNT // TRACE_BURST_LENGTH
    burst_interval = float(step_interval_seconds) / burst_count
    for step in range(CONTROL_STEP_UPPER_BOUND):
        step_start = step * float(step_interval_seconds)
        for burst in range(burst_count):
            arrival = step_start + burst * burst_interval
            for _ in range(TRACE_BURST_LENGTH):
                ordinal += 1
                arrivals.append((ordinal, arrival))
    return arrivals


def throughput_gate(
    *,
    worker_measurements: Mapping[str, Mapping[str, Any]],
    ring_admission: Mapping[str, Any],
    actual_trace_replay: Mapping[str, Any],
    production_replay: Mapping[str, Any],
) -> dict[str, bool]:
    selected = worker_measurements[str(SELECTED_WORKER_COUNT)]
    producer_rate = CANDIDATE_COUNT / TRACE_PROGRESS_INTERVAL_SECONDS
    return {
        "selected_worker_is_minimum": SELECTED_WORKER_COUNT == 1,
        "consumer_rate_margin_pass": float(selected["records_per_second"])
        >= producer_rate * SUSTAINED_RATE_MARGIN,
        "deterministic_metric_digest_pass": len(selected["result_digests"]) == 1,
        "ring_ram_admission_pass": ring_admission.get("admitted") is True,
        "ring_capacity_has_safety_slot": int(ring_admission["required_slots"])
        >= TRACE_MEASURED_MAX_IN_FLIGHT + 1,
        "actual_trace_replay_no_drop": not actual_trace_replay["rejected_sequences"],
        "production_replay_no_drop": not production_replay["rejected_sequences"],
        "production_replay_all_records": production_replay["accepted_count"]
        == CANDIDATE_COUNT * CONTROL_STEP_UPPER_BOUND,
        "production_final_backlog_zero": production_replay["final_backlog"] == 0,
        "selected_worker_preserves_completion_order": production_replay[
            "completion_order"
        ]
        == list(range(1, CANDIDATE_COUNT * CONTROL_STEP_UPPER_BOUND + 1)),
        "ring_high_water_within_capacity": production_replay[
            "ring_high_water_mark"
        ]
        <= PINNED_RING_DEPTH,
    }

