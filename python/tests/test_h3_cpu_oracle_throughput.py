from __future__ import annotations

import json
from pathlib import Path
import unittest

from hive_product.h3_cpu_oracle_throughput import (
    analyze_backpressure_trace,
    production_arrivals,
    simulate_ring,
)
from hive_product.h3_hybrid_cache_staging import PINNED_RING_DEPTH


class H3CpuOracleThroughputTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "h3_oracle_ring_backpressure_trace.json"
        self.trace = json.loads(fixture.read_text(encoding="utf-8"))

    def test_actual_30_31_32_33_trace_requires_three_in_flight(self):
        analysis = analyze_backpressure_trace(self.trace)
        self.assertEqual(analysis["fully_consumed_sequence"], 30)
        self.assertEqual(analysis["pending_sequences"], [31, 32])
        self.assertEqual(analysis["first_rejected_sequence"], 33)
        self.assertEqual(analysis["measured_maximum_in_flight"], 3)
        self.assertEqual(
            analysis["payload_arrival_timestamps"], "UNAVAILABLE_IN_SOURCE_TRACE"
        )

    def test_two_slots_reproduce_failure_and_four_slots_absorb_burst(self):
        arrivals = [(31, 0.0), (32, 0.0), (33, 0.0)]
        failed = simulate_ring(
            arrivals, service_seconds=[0.18], ring_slots=2, worker_count=1
        )
        remediated = simulate_ring(
            arrivals,
            service_seconds=[0.18],
            ring_slots=PINNED_RING_DEPTH,
            worker_count=1,
        )
        self.assertEqual(failed["rejected_sequences"], [33])
        self.assertEqual(remediated["rejected_sequences"], [])
        self.assertEqual(remediated["ring_high_water_mark"], 3)
        self.assertEqual(remediated["completion_order"], [31, 32, 33])

    def test_full_twenty_step_schedule_is_bounded_and_ordered(self):
        arrivals = production_arrivals()
        replay = simulate_ring(
            arrivals,
            service_seconds=[0.18],
            ring_slots=PINNED_RING_DEPTH,
            worker_count=1,
        )
        self.assertEqual(len(arrivals), 600)
        self.assertEqual(replay["accepted_count"], 600)
        self.assertEqual(replay["rejected_sequences"], [])
        self.assertEqual(replay["ring_high_water_mark"], 3)
        self.assertEqual(replay["final_backlog"], 0)
        self.assertEqual(replay["completion_order"], list(range(1, 601)))


if __name__ == "__main__":
    unittest.main()
