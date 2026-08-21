from __future__ import annotations

import inspect
import unittest

from hive_product.h3_hybrid_cache_staging import (
    CANDIDATE_AGGREGATE_BYTES,
    CANDIDATE_SLOT_BYTES,
    CONTROL_ORACLE_D2H_BYTES,
    CONTROL_STEP_UPPER_BOUND,
    CONTROL_TRANSFER_LIMIT_BYTES,
    HOST_OS_COMFY_RESERVE_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PINNED_HOST_TOTAL_BYTES,
    PINNED_RING_DEPTH,
    HybridPreflightError,
    HybridControlOracleRing,
    _PinnedSlot,
    _transition_preflight_slot,
    build_runtime_admission,
    build_ring_capacity_admission,
    calibration_gate,
)
from hive_product.h3_hybrid_cache_staging_probe import completion_gates
from test_h3_gpu_local_evidence_v2 import calibration_receipt


PHYSICAL_RAM_BYTES = 66_145_665_024
AVAILABLE_RAM_BYTES = 47_136_583_680
PHYSICAL_VRAM_BYTES = 12_884_377_600


class H3HybridCacheStagingTests(unittest.TestCase):
    def test_preflight_slot_lifecycle_is_strict_and_complete(self):
        slot = _PinnedSlot(payload=object(), event=object())
        observed = [slot.state]
        for state in (
            "D2H_IN_FLIGHT",
            "CPU_READY",
            "PROCESSING",
            "FINALIZED",
            "FREE",
        ):
            _transition_preflight_slot(slot, state)
            observed.append(slot.state)
        self.assertEqual(
            observed,
            [
                "FREE",
                "D2H_IN_FLIGHT",
                "CPU_READY",
                "PROCESSING",
                "FINALIZED",
                "FREE",
            ],
        )

    def test_preflight_slot_rejects_legacy_unknown_and_skipped_states(self):
        for current, target in (
            ("PENDING", "CPU_READY"),
            ("UNKNOWN", "FREE"),
            ("FREE", "PROCESSING"),
            ("D2H_IN_FLIGHT", "FINALIZED"),
            ("CPU_READY", "FREE"),
        ):
            slot = _PinnedSlot(payload=object(), event=object(), state=current)
            with self.assertRaises(HybridPreflightError):
                _transition_preflight_slot(slot, target)

    def test_balanced_profile_has_no_gpu_source_or_control_h2d(self):
        result = build_runtime_admission(
            physical_ram_bytes=PHYSICAL_RAM_BYTES,
            current_available_ram_bytes=AVAILABLE_RAM_BYTES,
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        balanced = result["balanced_12gb"]
        receipt = balanced["receipt"]
        self.assertEqual(balanced["persistent_full_source_cuda_bytes"], 0)
        self.assertEqual(receipt["GPU_SOURCE_CACHE_BYTES"]["status"], "STRUCTURAL_ZERO")
        self.assertEqual(receipt["CONTROL_ORACLE_H2D_BYTES"]["value"], 0)
        self.assertEqual(receipt["HOT_PATH_FORCED_SYNC_COUNT"]["value"], 0)
        self.assertFalse(balanced["BALANCED12GB_2GIB_RESERVE_SATISFIED"])

    def test_transfer_and_ring_bounds_are_exact(self):
        self.assertEqual(CANDIDATE_AGGREGATE_BYTES, 1_448_079_360)
        self.assertEqual(CONTROL_STEP_UPPER_BOUND, 20)
        self.assertEqual(CONTROL_ORACLE_D2H_BYTES, 28_961_587_200)
        self.assertLessEqual(CONTROL_ORACLE_D2H_BYTES, CONTROL_TRANSFER_LIMIT_BYTES)
        self.assertEqual(PINNED_RING_DEPTH, 4)
        self.assertEqual(PINNED_HOST_TOTAL_BYTES, CANDIDATE_SLOT_BYTES * 4)

    def test_ring_capacity_is_trace_derived_and_ram_admitted(self):
        admitted = build_ring_capacity_admission(
            current_available_ram_bytes=AVAILABLE_RAM_BYTES
        )
        blocked = build_ring_capacity_admission(
            current_available_ram_bytes=(
                HOST_OS_COMFY_RESERVE_BYTES
                + HOST_SOURCE_CACHE_BYTES
                + CANDIDATE_SLOT_BYTES * 3
            )
        )
        self.assertEqual(admitted["measured_maximum_in_flight"], 3)
        self.assertEqual(admitted["safety_slot_count"], 1)
        self.assertEqual(admitted["required_slots"], 4)
        self.assertTrue(admitted["admitted"])
        self.assertEqual(blocked["maximum_slots"], 3)
        self.assertFalse(blocked["admitted"])

    def test_vram_and_host_ram_admission_include_reserves(self):
        result = build_runtime_admission(
            physical_ram_bytes=PHYSICAL_RAM_BYTES,
            current_available_ram_bytes=AVAILABLE_RAM_BYTES,
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        balanced = result["balanced_12gb"]
        host = balanced["host_ram"]
        self.assertLess(balanced["projected_peak_vram_bytes"], PHYSICAL_VRAM_BYTES)
        self.assertEqual(host["source_cache_bytes"], HOST_SOURCE_CACHE_BYTES)
        self.assertEqual(host["pinned_ring_bytes"], PINNED_HOST_TOTAL_BYTES)
        self.assertGreaterEqual(host["projected_headroom_bytes"], HOST_OS_COMFY_RESERVE_BYTES)
        self.assertEqual(host["admission"], "PASS")
        self.assertEqual(balanced["runtime_admission"], "PASS")

    def test_host_ram_or_vram_shortfall_blocks_control(self):
        host_blocked = build_runtime_admission(
            physical_ram_bytes=64_000_000_000,
            current_available_ram_bytes=2_000_000_000,
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        vram_blocked = build_runtime_admission(
            physical_ram_bytes=PHYSICAL_RAM_BYTES,
            current_available_ram_bytes=AVAILABLE_RAM_BYTES,
            physical_vram_bytes=12_500_000_000,
        )
        self.assertFalse(host_blocked["control_submission_allowed"])
        self.assertFalse(vram_blocked["control_submission_allowed"])

    def test_calibration_remains_false_safe_zero_and_holdout_unknown(self):
        result = calibration_gate(calibration_receipt())
        self.assertEqual(result["record_count"], 279)
        self.assertEqual(result["selected_false_safe_count"], 0)
        self.assertEqual(result["holdout_status"], "UNKNOWN")
        self.assertGreaterEqual(result["planned_q_ratio"], 0.03)
        self.assertEqual(result["status"], "CALIBRATION_GEOMETRY_ONLY")

    def test_hot_path_has_no_forced_cpu_read_or_sync(self):
        source = inspect.getsource(HybridControlOracleRing.enqueue)
        for forbidden in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize("):
            self.assertNotIn(forbidden, source)
        self.assertIn("non_blocking=True", source)
        self.assertIn("wait_event", source)

    def test_quality_profile_is_simulated_and_uses_same_contract(self):
        result = build_runtime_admission(
            physical_ram_bytes=PHYSICAL_RAM_BYTES,
            current_available_ram_bytes=AVAILABLE_RAM_BYTES,
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        balanced = result["balanced_12gb"]
        quality = result["quality_24gb_plus"]
        self.assertEqual(quality["execution_status"], "SIMULATED_NOT_EXECUTED")
        self.assertFalse(quality["physical_24gb_device_present"])
        self.assertEqual(
            balanced["receipt"]["RUST_TENSOR_BYTES"],
            quality["receipt"]["RUST_TENSOR_BYTES"],
        )
        self.assertEqual(quality["projected_peak_vram_bytes"], 15_355_989_428)

    def test_completion_gate_requires_synthetic_proofs(self):
        calibration = calibration_gate(calibration_receipt())
        admission = build_runtime_admission(
            physical_ram_bytes=PHYSICAL_RAM_BYTES,
            current_available_ram_bytes=AVAILABLE_RAM_BYTES,
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        synthetic = {
            "hot_path_forced_sync_zero": True,
            "backpressure_prevents_overwrite": True,
            "ring": {"RING_OVERFLOW_COUNT": {"value": 0}},
            "bf16_bit_preserved": True,
            "cpu_gpu_metric_max_abs_error": 0.0,
            "classification_identical": True,
            "h3_model_load_count": 0,
            "comfy_generation_count": 0,
            "control_submission_count": 0,
            "selective_execution_count": 0,
            "partial_q_execution_count": 0,
            "actual_attention_omission_count": 0,
        }
        self.assertTrue(all(completion_gates(calibration, admission, synthetic).values()))


if __name__ == "__main__":
    unittest.main()
