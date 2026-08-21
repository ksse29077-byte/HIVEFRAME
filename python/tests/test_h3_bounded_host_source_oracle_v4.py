from __future__ import annotations

import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import (
    CANDIDATE_H2D_ADMISSION_BYTES,
    FROZEN_EVENTS,
    GPU_STAGING_BUDGET_BYTES,
    HOST_SOURCE_BUDGET_BYTES,
    HOST_SOURCE_RESIDENT_BYTES,
    MINIMUM_CANDIDATE_H2D_BYTES,
    MINIMUM_PLANNED_Q_RATIO,
    PERSISTENT_EXACT_GPU_SOURCE_BYTES,
    SOURCE_BLOCKS,
    SOURCE_CAPTURE_D2H_BYTES,
    SOURCE_PAYLOAD_BYTES,
    SharedStagingState,
    V4ContractError,
    build_memory_admission,
    build_transfer_ledger,
    frozen_inventory_digest,
    model_free_preflight_receipt,
    replay_frozen_inventory,
)


class H3BoundedHostSourceOracleV4Tests(unittest.TestCase):
    def test_frozen_inventory_is_minimum_deterministic_three_percent_plan(self):
        self.assertEqual(SOURCE_BLOCKS, tuple(range(13)))
        self.assertEqual(len(FROZEN_EVENTS), 199)
        self.assertGreaterEqual(MINIMUM_PLANNED_Q_RATIO, 0.03)
        self.assertLess(12 * 16 * 2331 / 15_424_000, 0.03)
        self.assertEqual(FROZEN_EVENTS[-1].block, 3)
        self.assertEqual(FROZEN_EVENTS[-1].source_step, 16)
        self.assertEqual(len(frozen_inventory_digest()), 64)

    def test_exact_host_and_shared_gpu_allocations_match_v4_bounds(self):
        self.assertEqual(SOURCE_PAYLOAD_BYTES, 48_269_312)
        self.assertEqual(HOST_SOURCE_RESIDENT_BYTES, 627_501_056)
        self.assertLessEqual(HOST_SOURCE_RESIDENT_BYTES, HOST_SOURCE_BUDGET_BYTES)
        self.assertEqual(PERSISTENT_EXACT_GPU_SOURCE_BYTES, 0)
        self.assertEqual(GPU_STAGING_BUDGET_BYTES, SOURCE_PAYLOAD_BYTES)

    def test_candidate_only_transfer_ledger_has_no_current_or_cpu_oracle_payload(self):
        ledger = build_transfer_ledger()
        self.assertTrue(ledger["passed"])
        self.assertEqual(ledger["current_payload_d2h_bytes"], 0)
        self.assertEqual(ledger["cpu_oracle_payload_d2h_bytes"], 0)
        self.assertEqual(ledger["source_capture_d2h_bytes"], SOURCE_CAPTURE_D2H_BYTES)
        self.assertEqual(ledger["candidate_source_h2d_bytes"], MINIMUM_CANDIDATE_H2D_BYTES)
        self.assertLessEqual(MINIMUM_CANDIDATE_H2D_BYTES, CANDIDATE_H2D_ADMISSION_BYTES)

    def test_shared_staging_rejects_overwrite_and_skipped_transition(self):
        staging = SharedStagingState()
        staging.transition("H2D_IN_FLIGHT", owner_ordinal=1)
        with self.assertRaises(V4ContractError):
            staging.transition("ORACLE_PROCESSING", owner_ordinal=1)

        staging = SharedStagingState()
        staging.transition("H2D_IN_FLIGHT", owner_ordinal=1)
        with self.assertRaises(V4ContractError):
            staging.transition("GPU_READY", owner_ordinal=2)
        self.assertEqual(staging.overwritten_staging_count, 1)

    def test_exact_and_stress_replays_end_empty_without_loss(self):
        for replay in (
            replay_frozen_inventory(),
            replay_frozen_inventory(burst=True),
            replay_frozen_inventory(latency_scale=1.5),
            replay_frozen_inventory(latency_scale=1.5, burst=True),
        ):
            self.assertTrue(replay["passed"])
            self.assertEqual(replay["record_count"], 199)
            self.assertEqual(replay["final_backlog"], 0)
            self.assertEqual(replay["overwritten_staging"], 0)

    def test_memory_admission_includes_vram_and_ram_reserves(self):
        admitted = build_memory_admission(
            physical_vram_bytes=12_884_377_600,
            projected_baseline_peak_bytes=12_515_000_000,
            available_ram_bytes=8 * 1024**3,
        )
        blocked = build_memory_admission(
            physical_vram_bytes=12_884_377_600,
            projected_baseline_peak_bytes=12_700_000_000,
            available_ram_bytes=2 * 1024**3,
        )
        self.assertTrue(admitted["passed"])
        self.assertFalse(blocked["passed"])

    def test_model_free_receipt_covers_all_required_replays(self):
        receipt = model_free_preflight_receipt()
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["exact_record_count"], 199)
        self.assertEqual(set(receipt["replays"]), {
            "exact",
            "same_step_burst",
            "h2d_latency_1_5x",
            "oracle_latency_1_5x",
            "combined_1_5x",
        })


if __name__ == "__main__":
    unittest.main()
