from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_benchmarks.topology_pruning.candidates import (
    CANDIDATES,
    analytical_precheck,
    topology_geometry,
)
from hive_benchmarks.topology_pruning.cost_model import (
    amdahl_bound,
    break_even_seconds,
    build_cost_record,
    prediction_error,
)
from hive_benchmarks.topology_pruning.metrics import (
    measured,
    unavailable,
    validate_metric,
)
from hive_benchmarks.topology_pruning.report import decide_gate
from hive_benchmarks.topology_pruning.runner import (
    _accuracy,
    _attach_measured_break_even,
)
from hive_benchmarks.topology_pruning.synthetic_cases import (
    ChangeBox,
    SyntheticCase,
    case_receipt,
    exact_dirty_mask,
    generate_case,
)
from hive_probes.rust_io_reference import run_pipeline


def tiny_case() -> SyntheticCase:
    return SyntheticCase(
        case_id="test-local",
        label="Test Local",
        width=16,
        height=16,
        frames=4,
        calibration_profile="low",
        expected="test",
        changes=(ChangeBox(9, 4, 2, 4),),
    )


def thresholds() -> dict:
    return {
        "prune_full_canvas_generate_candidate": True,
        "max_observation_multiplier_without_backend_savings": 1.5,
        "minimum_potential_generation_savings_to_keep": 0.01,
        "small_input_max_pixels": 16 * 16 * 4,
        "global_motion_dirty_ratio": 0.5,
        "false_stable_max": 0.005,
        "prediction_relative_error_refine": 0.35,
    }


class TopologyPruningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rust_report = json.loads(
            (
                ROOT
                / "reports"
                / "rust_io_admission"
                / "benchmark-summary.json"
            ).read_text(encoding="utf-8")
        )

    def test_mono_cost_calculation(self) -> None:
        geometry = topology_geometry(tiny_case(), CANDIDATES[0])
        self.assertEqual(geometry["eye_count"], 1)
        self.assertEqual(
            geometry["total_observation_pixels"],
            geometry["input_pixels"],
        )
        self.assertEqual(geometry["observation_multiplier_vs_mono"], 1.0)

    def test_overlap_byte_calculation(self) -> None:
        geometry = topology_geometry(tiny_case(), CANDIDATES[1])
        self.assertEqual(
            geometry["overlap_duplicate_bytes"],
            geometry["input_bytes"],
        )
        self.assertEqual(geometry["observation_multiplier_vs_mono"], 2.0)

    def test_fixed_eye_cost_and_break_even(self) -> None:
        geometry = topology_geometry(tiny_case(), CANDIDATES[1])
        cost = build_cost_record(
            self.rust_report,
            "low",
            "uniform_2x2",
            "mono_1x1",
            geometry,
        )
        self.assertGreater(cost["fixed_eye_cost_proxy"]["value"], 0)
        self.assertGreater(cost["S_required"]["value"], 0)
        self.assertEqual(break_even_seconds(2.5, 1.0), 1.5)

    def test_unavailable_metric_semantics(self) -> None:
        metric = unavailable("seconds", "not isolated")
        validate_metric(metric)
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["status"], "unavailable")

    def test_amdahl_bound_is_partial_without_m0_fraction(self) -> None:
        bound = amdahl_bound(self.rust_report)
        self.assertEqual(bound["status"], "partially_available")
        self.assertEqual(bound["s_control"]["status"], "available")
        self.assertIsNone(bound["f_input"]["value"])
        self.assertIsNone(bound["end_to_end_upper_bound"]["value"])

    def test_analytical_candidate_pruning(self) -> None:
        geometry = topology_geometry(tiny_case(), CANDIDATES[1])
        result = analytical_precheck(
            tiny_case(),
            CANDIDATES[1],
            geometry,
            thresholds(),
        )
        self.assertEqual(result["status"], "analytically_pruned")
        rules = {
            item["rule"] for item in result["evidence"]["triggered_rules"]
        }
        self.assertIn("small_input_management_cost", rules)

    def test_reference_emits_bounded_generate_for_local_multi_eye(self) -> None:
        profile, sequence = generate_case(tiny_case(), seed=101)
        full = {"x": 0, "y": 0, "width": 16, "height": 16}
        for topology in ("uniform_2x2", "motion_focused"):
            units = run_pipeline(
                profile,
                topology,
                sequence,
            )["semantic_result"]["compute_plan"]["units"]
            generated = [
                unit["scope"]
                for unit in units
                if unit["action"] == "generate"
            ]
            self.assertTrue(generated, topology)
            self.assertNotIn(full, generated, topology)

    def test_high_local_multi_eye_survives_precheck(self) -> None:
        case = SyntheticCase(
            case_id="high-local",
            label="High Local",
            width=1920,
            height=1080,
            frames=8,
            calibration_profile="high",
            expected="test",
            changes=(ChangeBox(968, 238, 72, 84),),
        )
        for candidate in CANDIDATES[1:]:
            geometry = topology_geometry(case, candidate)
            result = analytical_precheck(
                case,
                candidate,
                geometry,
                thresholds(),
            )
            self.assertEqual(result["status"], "retained_for_probe")

    def test_pruned_receipt_preserves_reason_and_evidence(self) -> None:
        geometry = topology_geometry(tiny_case(), CANDIDATES[2])
        result = analytical_precheck(
            tiny_case(),
            CANDIDATES[2],
            geometry,
            thresholds(),
        )
        self.assertTrue(result["reason"])
        self.assertTrue(result["evidence"]["triggered_rules"])

    def test_deterministic_synthetic_case(self) -> None:
        first = case_receipt(tiny_case(), seed=101)
        second = case_receipt(tiny_case(), seed=101)
        self.assertEqual(first["input_sha256"], second["input_sha256"])
        self.assertEqual(first, second)

    def test_exact_dirty_mask(self) -> None:
        _, sequence = generate_case(tiny_case(), seed=101)
        dirty = exact_dirty_mask(sequence)
        self.assertEqual(int(dirty.sum()), 8)
        self.assertTrue(dirty[4:8, 9:11].all())

    def test_false_stable_calculation(self) -> None:
        profile, sequence = generate_case(tiny_case(), seed=101)
        semantic = run_pipeline(
            profile,
            "mono_1x1",
            sequence,
        )["semantic_result"]
        accuracy = _accuracy(sequence, semantic)
        self.assertEqual(accuracy["dirty_recall"], 1.0)
        self.assertEqual(accuracy["false_stable_rate"], 0.0)

    def test_predicted_vs_measured_comparison(self) -> None:
        error = prediction_error(0.010, 0.012)
        self.assertAlmostEqual(error["absolute_error_seconds"], 0.002)
        self.assertAlmostEqual(error["relative_error"], 1 / 6)

    def test_measured_break_even_uses_case_mono(self) -> None:
        measured_cases = [
            {
                "case_id": "case",
                "candidate_id": "T0",
                "metrics": {
                    "p50_latency_seconds": measured(
                        0.010,
                        "seconds",
                        "test",
                    )
                },
                "comparison": {},
            },
            {
                "case_id": "case",
                "candidate_id": "T2",
                "metrics": {
                    "p50_latency_seconds": measured(
                        0.014,
                        "seconds",
                        "test",
                    )
                },
                "comparison": {},
            },
        ]
        _attach_measured_break_even(measured_cases)
        self.assertEqual(
            measured_cases[0]["comparison"]["measured_S_required_seconds"],
            0.0,
        )
        self.assertAlmostEqual(
            measured_cases[1]["comparison"]["measured_S_required_seconds"],
            0.004,
        )

    def test_decision_gate_mono_first(self) -> None:
        pruning = [
            {
                "candidate_id": candidate,
                "precheck": {
                    "status": (
                        "retained_for_probe"
                        if candidate == "T0"
                        else "analytically_pruned"
                    )
                },
            }
            for candidate in ("T0", "T1", "T2")
        ]
        measured_cases = [
            {
                "candidate_id": "T0",
                "accuracy": {"false_stable_rate": 0.0},
                "comparison": {"relative_error": 0.0},
            }
        ]
        decision = decide_gate(pruning, measured_cases, thresholds())
        self.assertEqual(decision["decision"], "MONO_FIRST")

    def test_negative_cost_rejection(self) -> None:
        with self.assertRaises(ValueError):
            measured(-0.001, "seconds", "test")
        with self.assertRaises(ValueError):
            break_even_seconds(-1.0, 1.0)
        with self.assertRaises(ValueError):
            prediction_error(1.0, -1.0)

    def test_unsupported_metric_cannot_masquerade_as_zero(self) -> None:
        with self.assertRaises(ValueError):
            validate_metric(
                {
                    "value": 0,
                    "status": "unavailable",
                    "reason": "not measured",
                    "method": "not measured",
                    "unit": "seconds",
                }
            )

    def test_declared_candidate_scope_is_bounded(self) -> None:
        self.assertEqual([item.candidate_id for item in CANDIDATES], ["T0", "T1", "T2"])
        self.assertEqual(
            [item.runtime_topology for item in CANDIDATES],
            ["mono_1x1", "uniform_2x2", "motion_focused"],
        )


if __name__ == "__main__":
    unittest.main()
