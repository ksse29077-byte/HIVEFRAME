from __future__ import annotations

import unittest
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_benchmarks.rust_io_admission import compare_suites, decide_admission
from hive_probes.rust_io_reference import (
    TOPOLOGIES,
    benchmark_case,
    benchmark_suite,
    generate_sequence,
    run_pipeline,
    semantic_hash,
    validate_profile,
    validate_sequence,
)


def small_profile() -> dict:
    return {
        "profile_id": "test-small",
        "width": 16,
        "height": 16,
        "frames": 4,
        "seed": 101,
        "change_regions": [
            {"x": 9, "y": 4, "width": 2, "height": 4},
        ],
    }


class RustIoReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = small_profile()
        self.sequence = generate_sequence(self.profile)

    def run_topology(self, topology: str) -> dict:
        return run_pipeline(self.profile, topology, self.sequence)

    def test_mono_eye_parity_projection(self) -> None:
        result = self.run_topology("mono_1x1")["semantic_result"]
        self.assertEqual(len(result["eyes"]), 1)
        # The exact canvas assertion remains explicit rather than relying on hash.
        self.assertEqual(
            result["eyes"][0]["write_scope"],
            {"x": 0, "y": 0, "width": 16, "height": 16},
        )

    def test_uniform_2x2_and_4x4_eye_counts(self) -> None:
        self.assertEqual(
            len(self.run_topology("uniform_2x2")["semantic_result"]["eyes"]),
            5,
        )
        self.assertEqual(
            len(self.run_topology("uniform_4x4")["semantic_result"]["eyes"]),
            17,
        )

    def test_overlap_coordinate_parity_contract(self) -> None:
        result = self.run_topology("overlap_2x2")["semantic_result"]
        for eye in result["eyes"]:
            receptive = eye["receptive_field"]
            self.assertEqual(
                eye["local_to_global"],
                [receptive["x"], receptive["y"]],
            )
            if eye["write_scope"] is not None:
                scope = eye["write_scope"]
                self.assertLessEqual(receptive["x"], scope["x"])
                self.assertLessEqual(receptive["y"], scope["y"])
                self.assertGreaterEqual(
                    receptive["x"] + receptive["width"],
                    scope["x"] + scope["width"],
                )
                self.assertGreaterEqual(
                    receptive["y"] + receptive["height"],
                    scope["y"] + scope["height"],
                )

    def test_motion_detection_parity_contract(self) -> None:
        result = self.run_topology("motion_focused")["semantic_result"]
        focus = next(
            observation
            for observation in result["observations"]
            if observation["eye_id"] == "motion-focus-00"
        )
        self.assertGreater(focus["changed_pixels"], 0)
        self.assertEqual(
            focus["motion_bbox"],
            {"x": 9, "y": 4, "width": 2, "height": 4},
        )

    def test_fusion_provenance_is_preserved(self) -> None:
        result = self.run_topology("uniform_2x2")["semantic_result"]
        observation_ids = set(
            result["shared_visual_state"]["observation_ids"]
        )
        for region in result["shared_visual_state"]["regions"]:
            self.assertTrue(region["sources"])
            self.assertTrue(set(region["sources"]).issubset(observation_ids))

    def test_uncertain_conflict_is_not_hidden(self) -> None:
        result = self.run_topology("overlap_2x2")["semantic_result"]
        states = {
            region["state"]
            for region in result["shared_visual_state"]["regions"]
        }
        self.assertIn("uncertain", states)
        actions = {
            unit["action"] for unit in result["compute_plan"]["units"]
        }
        self.assertIn("reconcile", actions)

    def test_invalid_input_rejection(self) -> None:
        invalid = small_profile()
        invalid["frames"] = 1
        with self.assertRaises(ValueError):
            validate_profile(invalid)
        with self.assertRaises(ValueError):
            validate_sequence(
                self.profile,
                np.zeros((1, 16, 16), dtype=np.uint8),
            )

    def test_repeated_run_is_deterministic(self) -> None:
        for topology in TOPOLOGIES:
            first = self.run_topology(topology)["semantic_result"]
            second = self.run_topology(topology)["semantic_result"]
            self.assertEqual(first, second)
            self.assertEqual(semantic_hash(first), semantic_hash(second))

    def test_unsupported_metrics_use_null_and_reason(self) -> None:
        result = self.run_topology("mono_1x1")["semantic_result"]
        for claim in result["compute_plan"]["claims"]:
            self.assertIsNone(claim["value"])
            self.assertIn(claim["status"], {"unsupported", "uncollected"})
            self.assertTrue(claim["reason"])
            self.assertTrue(claim["method"])

    def test_suite_parity_and_admission_helpers(self) -> None:
        suite = benchmark_suite(
            [],
            [],
            seed=101,
            warmups=0,
            repetitions=1,
        )
        parity = compare_suites(suite, suite)
        self.assertEqual(parity["status"], "passed")
        decision = decide_admission(parity, [])
        self.assertEqual(decision["decision"], "DEFER")

    def test_single_case_records_required_metrics(self) -> None:
        case = benchmark_case(
            self.profile,
            "mono_1x1",
            warmups=0,
            repetitions=1,
        )
        self.assertEqual(case["semantic_hash"], semantic_hash(case["semantic_result"]))
        for name in (
            "p50_latency_seconds",
            "p95_latency_seconds",
            "routing_seconds_mean",
            "coordinate_transform_seconds_mean",
            "observation_seconds_mean",
            "fusion_seconds_mean",
            "compute_plan_seconds_mean",
            "logical_bytes_read",
            "bytes_copied",
            "temporary_buffer_bytes",
        ):
            self.assertIn(name, case["metrics"])


if __name__ == "__main__":
    unittest.main()
