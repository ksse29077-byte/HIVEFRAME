from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_benchmarks.topology_pruning.paired_normalization import (
    CASE_B,
    PRUNED_COMBINATIONS,
    RETAINED_COMBINATIONS,
    assert_unavailable_values_are_null,
    decide_r1_gate,
    deterministic_case_b_order,
    observed_cost_terms,
    paired_delta_records,
    percentile,
    relative_error,
    summarize_paired_deltas,
    validate_config,
    validate_v1_hashes,
)
from hive_benchmarks.topology_pruning.r1_runner import (
    _assert_output_available,
    build_parser,
    plan,
)


CONFIG_PATH = ROOT / "configs" / "m1-p0-r1.same-run-mono-normalization.json"


def sample(block: int, candidate: str, seconds: float) -> dict:
    return {
        "phase": "measured",
        "case_id": CASE_B,
        "block_index": block,
        "order_index": {"T0": 0, "T1": 1, "T2": 2}[candidate],
        "candidate_id": candidate,
        "total_seconds": seconds,
    }


def complete_blocks(values: list[tuple[float, float, float]]) -> list[dict]:
    samples = []
    for block, (mono, t1, t2) in enumerate(values):
        samples.extend(
            [
                sample(block, "T0", mono),
                sample(block, "T1", t1),
                sample(block, "T2", t2),
            ]
        )
    return samples


def thresholds() -> dict:
    return {
        "prediction_relative_error_max": 0.35,
        "dirty_recall_required": 1.0,
        "false_stable_required": 0.0,
    }


class TopologyPruningR1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_predeclared_config_retains_exact_v1_scope(self) -> None:
        validate_config(self.config)
        self.assertEqual(tuple(self.config["retained_combinations"]), RETAINED_COMBINATIONS)
        self.assertEqual(
            tuple(self.config["analytically_pruned_combinations"]),
            PRUNED_COMBINATIONS,
        )
        self.assertEqual(self.config["warmups"], 5)
        self.assertEqual(self.config["repetitions"], 20)
        self.assertEqual(self.config["thresholds"]["prediction_relative_error_max"], 0.35)

    def test_paired_mono_delta_uses_same_block(self) -> None:
        samples = complete_blocks([(1.0, 1.4, 1.6), (2.0, 2.5, 2.7)])
        records = paired_delta_records(samples, "T1")
        self.assertEqual(len(records), 2)
        self.assertAlmostEqual(records[0]["delta_seconds"], 0.4)
        self.assertAlmostEqual(records[1]["delta_seconds"], 0.5)

    def test_different_case_pair_is_rejected(self) -> None:
        samples = complete_blocks([(1.0, 1.4, 1.6)])
        samples[1]["case_id"] = "wrong-case"
        with self.assertRaises(ValueError):
            paired_delta_records(samples, "T1")

    def test_different_or_missing_repeat_block_is_rejected(self) -> None:
        samples = complete_blocks([(1.0, 1.4, 1.6)])
        samples[1]["block_index"] = 1
        with self.assertRaises(ValueError):
            paired_delta_records(samples, "T1")

    def test_unpaired_sample_is_rejected(self) -> None:
        samples = [sample(0, "T0", 1.0), sample(0, "T1", 1.4)]
        with self.assertRaises(ValueError):
            paired_delta_records(samples, "T1")

    def test_fixed_and_variable_cost_terms_remain_separate(self) -> None:
        terms = observed_cost_terms(
            session_fixed=1.0,
            case_shared=2.0,
            topology_variable=3.0,
            measurement_noise=-0.25,
        )
        self.assertEqual(terms["C_session_fixed"], 1.0)
        self.assertEqual(terms["C_topology_variable"], 3.0)
        self.assertEqual(terms["C_observed"], 5.75)

    def test_paired_delta_differs_from_independent_median_subtraction(self) -> None:
        samples = complete_blocks(
            [
                (1.0, 3.0, 4.0),
                (2.0, 99.0, 5.0),
                (100.0, 102.0, 103.0),
                (101.0, 103.0, 104.0),
            ]
        )
        paired = paired_delta_records(samples, "T1")
        paired_p50 = percentile([item["delta_seconds"] for item in paired], 0.50)
        mono_p50 = percentile([1.0, 2.0, 100.0, 101.0], 0.50)
        candidate_p50 = percentile([3.0, 99.0, 102.0, 103.0], 0.50)
        self.assertEqual(paired_p50, 2.0)
        self.assertEqual(candidate_p50 - mono_p50, 97.0)
        self.assertNotEqual(paired_p50, candidate_p50 - mono_p50)

    def test_p50_p95_and_relative_error(self) -> None:
        samples = complete_blocks(
            [(1.0, 1.1, 1.2), (1.0, 1.2, 1.3), (1.0, 1.3, 1.4)]
        )
        summary = summarize_paired_deltas(
            paired_delta_records(samples, "T1"),
            predicted_delta_seconds=0.25,
        )
        self.assertAlmostEqual(summary["measured_delta_p50_seconds"], 0.2)
        self.assertAlmostEqual(summary["measured_delta_p95_seconds"], 0.3)
        self.assertAlmostEqual(summary["absolute_error_seconds"], 0.05)
        self.assertAlmostEqual(summary["relative_error"], 0.25)

    def test_zero_relative_error_denominator_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            relative_error(0.1, 0.0)

    def test_unavailable_metric_cannot_use_zero(self) -> None:
        with self.assertRaises(ValueError):
            assert_unavailable_values_are_null(
                {
                    "value": 0,
                    "status": "unavailable",
                    "reason": "not measured",
                    "method": "not measured",
                }
            )

    def test_deterministic_interleaving(self) -> None:
        first = [deterministic_case_b_order(101, "measured", index) for index in range(20)]
        second = [deterministic_case_b_order(101, "measured", index) for index in range(20)]
        self.assertEqual(first, second)
        self.assertTrue(all(set(order) == {"T0", "T1", "T2"} for order in first))
        self.assertGreater(len(set(first)), 1)

    def test_v1_reports_match_predeclared_hashes(self) -> None:
        validate_v1_hashes(ROOT, self.config["v1_immutable_sha256"])

    def test_gate_proceed_requires_both_errors_and_ranking(self) -> None:
        paired = {"T1": {"relative_error": 0.10}, "T2": {"relative_error": 0.20}}
        decision = decide_r1_gate(
            paired,
            ranking_match=True,
            dirty_recall=1.0,
            false_stable=0.0,
            deterministic_hashes=True,
            unavailable_semantics_valid=True,
            thresholds=thresholds(),
        )
        self.assertEqual(decision["decision"], "PROCEED_TO_COST_SURFACE")

    def test_gate_refines_on_prediction_error(self) -> None:
        paired = {"T1": {"relative_error": 0.10}, "T2": {"relative_error": 0.36}}
        decision = decide_r1_gate(
            paired,
            ranking_match=True,
            dirty_recall=1.0,
            false_stable=0.0,
            deterministic_hashes=True,
            unavailable_semantics_valid=True,
            thresholds=thresholds(),
        )
        self.assertEqual(decision["decision"], "REFINE_COST_MODEL")

    def test_gate_pauses_on_false_stable(self) -> None:
        paired = {"T1": {"relative_error": 0.10}, "T2": {"relative_error": 0.20}}
        decision = decide_r1_gate(
            paired,
            ranking_match=True,
            dirty_recall=0.99,
            false_stable=0.01,
            deterministic_hashes=True,
            unavailable_semantics_valid=True,
            thresholds=thresholds(),
        )
        self.assertEqual(decision["decision"], "PAUSE_COMPOUND_INPUT")

    def test_gate_mono_first_requires_admitted_structural_evidence(self) -> None:
        paired = {"T1": {"relative_error": 0.10}, "T2": {"relative_error": 0.20}}
        decision = decide_r1_gate(
            paired,
            ranking_match=True,
            dirty_recall=1.0,
            false_stable=0.0,
            deterministic_hashes=True,
            unavailable_semantics_valid=True,
            thresholds=thresholds(),
            all_compound_pruned=True,
        )
        self.assertEqual(decision["decision"], "MONO_FIRST")

    def test_plan_does_not_execute_pipeline_or_create_output(self) -> None:
        args = build_parser().parse_args(["--plan"])
        with patch(
            "hive_benchmarks.topology_pruning.r1_runner.run_pipeline",
            side_effect=AssertionError("pipeline must not run"),
        ):
            result = plan(args)
        self.assertFalse(result["execution_started"])
        self.assertEqual(result["warmups"], 5)
        self.assertEqual(result["repetitions"], 20)

    def test_existing_r1_artifact_blocks_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "decision-report.md").write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                _assert_output_available(output)


if __name__ == "__main__":
    unittest.main()
