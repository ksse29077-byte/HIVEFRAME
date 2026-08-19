from __future__ import annotations

import inspect
import unittest

from hive_product.h3_gpu_local_evidence_v2 import (
    CACHE_HARD_CAP_BYTES,
    CALIBRATION_STATUS,
    CALIBRATION_VETO_BLOCKS,
    EXPECTED_TRANSFER_BYTES,
    FULL_Q_ROWS,
    GpuLocalEvidenceCollector,
    MAX_EVIDENCE_RECORDS,
    TRANSFER_HEADROOM_MIN_BYTES,
    TRANSFER_PREFLIGHT_LIMIT_BYTES,
    analyze_partial_control_receipt,
    evidence_admitted,
)


def record(
    *,
    block: int,
    source_step: int,
    region: int = 0,
    stable: bool = True,
    false_safe: bool = False,
):
    return {
        "step": source_step + 1,
        "source_step": source_step,
        "block": block,
        "region": region,
        "predicted_state": "STABLE" if stable else "UNCERTAIN",
        "uncertainty_ppm": 10_000,
        "motion_ppm": 20_000,
        "payload_bytes": (48_269_312, 44_556_288, 41_373_696, 38_191_104)[region],
        "raw": {
            "cosine": 0.98,
            "normalized_l2": 0.2,
            "normalized_mae": 0.2,
            "energy_ratio": 1.0,
            "finite": True,
        },
        "corrected": {
            "cosine": 0.95 if false_safe else 0.99,
            "normalized_l2": 0.3 if false_safe else 0.1,
            "normalized_mae": 0.2,
            "energy_ratio": 1.0,
            "finite": True,
        },
        "actual_safety": "UNSAFE" if false_safe else "SAFE",
        "false_safe": false_safe,
        "false_unsafe": not stable and not false_safe,
    }


def calibration_receipt():
    records = [
        record(block=block, source_step=source_step)
        for source_step in (1, 3, 5, 7, 9)
        for block in range(30)
    ]
    risk_pattern = (30, 31, 48, 49, 30, 31, 48, 49, 30, 31, 48, 49, 30, 31, 48, 49, 30, 31, 48)
    records.extend(
        record(block=block, source_step=1 + index % 15, false_safe=True)
        for index, block in enumerate(risk_pattern)
    )
    records.extend(
        record(block=48 + index % 2, source_step=1 + index % 15, region=index % 4, stable=False)
        for index in range(110)
    )
    assert len(records) == 279
    return {
        "run_digest": "11" * 32,
        "model_revision_digest": "22" * 32,
        "workflow_revision_digest": "33" * 32,
        "settings_digest": "44" * 32,
        "attention_execution": {
            "cache": {
                "d2h_bytes": 30_057_990_144,
                "h2d_bytes": 12_856_610_816,
                "transfer_total_bytes": EXPECTED_TRANSFER_BYTES,
                "transfer_budget_bytes": 40 * 1024**3,
            },
            "safety_evidence": {"records": records, "overflow": False},
        },
    }


class H3GpuLocalEvidenceV2Tests(unittest.TestCase):
    def test_partial_calibration_is_attributed_but_never_admitted(self):
        result = analyze_partial_control_receipt(calibration_receipt())
        self.assertEqual(result["decision_input_status"], CALIBRATION_STATUS)
        self.assertEqual(result["record_count"], 279)
        self.assertEqual(result["false_safe_count"], 19)
        self.assertEqual(len(result["false_safe_attributions"]), 19)
        self.assertEqual(
            result["false_safe_clusters"]["concentrated_blocks"],
            list(CALIBRATION_VETO_BLOCKS),
        )
        self.assertFalse(result["admission_eligible"])
        self.assertEqual(result["rust_calls"], 0)
        self.assertEqual(result["rust_tensor_bytes"], 0)
        required = {
            "step",
            "source_step",
            "block",
            "region",
            "predicted_state",
            "motion_ppm",
            "uncertainty_ppm",
            "corrected_cosine",
            "corrected_normalized_l2",
            "packed_row_start",
            "packed_row_end",
            "packed_row_count",
            "cache_age",
            "source_identity_digest",
            "payload_bytes",
        }
        self.assertTrue(all(set(item) == required for item in result["false_safe_attributions"]))

    def test_conservative_veto_preserves_three_percent_geometry_potential(self):
        result = analyze_partial_control_receipt(calibration_receipt())
        veto = result["conservative_pre_attention_veto"]
        potential = result["safe_geometry_potential"]
        self.assertEqual(veto["selected_calibration_false_safe"], 0)
        self.assertFalse(veto["uses_post_attention_metric_online"])
        self.assertLess(veto["selected_calibration_planned_q_ratio"], 0.03)
        self.assertEqual(potential["minimum_age_one_events_for_three_percent"], 7)
        self.assertGreaterEqual(potential["planned_q_rows"] / FULL_Q_ROWS, 0.03)
        self.assertEqual(potential["status"], "GEOMETRY_POTENTIAL_NOT_HOLDOUT_RESULT")

    def test_transfer_ledger_and_projected_v2_budget_are_exact(self):
        result = analyze_partial_control_receipt(calibration_receipt())
        self.assertEqual(result["failed_control_transfer_ledger"]["total_bytes"], 42_914_600_960)
        performance = result["performance_receipt"]
        self.assertEqual(performance["CACHE_PAYLOAD_D2H_BYTES"]["status"], "STRUCTURAL_ZERO")
        self.assertEqual(performance["CACHE_PAYLOAD_H2D_BYTES"]["status"], "STRUCTURAL_ZERO")
        self.assertLessEqual(
            performance["PROJECTED_CONTROL_TOTAL_TRANSFER_BYTES"]["value"],
            TRANSFER_PREFLIGHT_LIMIT_BYTES,
        )
        self.assertGreaterEqual(
            performance["PROJECTED_CONTROL_TRANSFER_HEADROOM_BYTES"]["value"],
            TRANSFER_HEADROOM_MIN_BYTES,
        )
        self.assertLessEqual(result["gpu_local_cache"]["payload_bytes"], CACHE_HARD_CAP_BYTES)

    def test_balanced_and_quality_profiles_use_one_algorithm(self):
        profiles = analyze_partial_control_receipt(calibration_receipt())["profiles"]
        self.assertEqual(
            profiles["Balanced12GB"]["algorithm_id"],
            profiles["Quality24GBPlus"]["algorithm_id"],
        )
        self.assertEqual(profiles["Quality24GBPlus"]["execution_status"], "SIMULATED_NOT_EXECUTED")

    def test_incomplete_invalid_and_overflow_batches_are_not_admitted(self):
        self.assertFalse(evidence_admitted(completed=False, overflow=False, invalid=False))
        self.assertFalse(evidence_admitted(completed=True, overflow=True, invalid=False))
        self.assertFalse(evidence_admitted(completed=True, overflow=False, invalid=True))
        self.assertTrue(evidence_admitted(completed=True, overflow=False, invalid=False))
        self.assertEqual(MAX_EVIDENCE_RECORDS, 640)

    def test_hot_path_has_no_forced_host_metric_read_or_sync(self):
        source = "\n".join(
            inspect.getsource(method)
            for method in (
                GpuLocalEvidenceCollector.capture_source,
                GpuLocalEvidenceCollector._bounded_metrics,
                GpuLocalEvidenceCollector.observe,
            )
        )
        for forbidden in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize("):
            self.assertNotIn(forbidden, source)
        self.assertIn("index_select", source)
        self.assertIn("metric_buffer", source)


if __name__ == "__main__":
    unittest.main()
