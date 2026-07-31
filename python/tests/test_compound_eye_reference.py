from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_eyes.reference import build_reference_eyes
from hive_probes.compound_eye_v0 import (
    make_synthetic_sequence,
    run_reference_simulation,
)
from hive_visual_state.contracts import (
    PixelBox,
    hash_json,
    validate_compute_plan,
    validate_eye_contract,
    validate_eye_observation,
    validate_shared_visual_state,
)


class CompoundEyeReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sequence = make_synthetic_sequence(seed=101)
        self.result = run_reference_simulation(self.sequence, seed=101)

    def test_identical_input_and_seed_are_deterministic(self) -> None:
        repeated = run_reference_simulation(self.sequence.copy(), seed=101)
        self.assertEqual(hash_json(self.result), hash_json(repeated))
        self.assertEqual(
            self.result["observation_receipt"],
            repeated["observation_receipt"],
        )

    def test_reference_eye_set_and_receptive_fields_match_contracts(self) -> None:
        eyes = build_reference_eyes(self.sequence)
        self.assertEqual(len(eyes), 7)
        observations = self.result["eye_observations"]
        for eye, contract, observation in zip(
            eyes, self.result["eye_contracts"], observations
        ):
            validate_eye_contract(
                contract,
                canvas_width=16,
                canvas_height=16,
                frames=4,
            )
            validate_eye_observation(
                observation,
                contract,
                canvas_width=16,
                canvas_height=16,
                frames=4,
            )
            self.assertEqual(
                contract["receptive_field"],
                observation["receptive_field"],
                eye.eye_id,
            )

    def test_global_eye_provides_whole_scene_context(self) -> None:
        observation = next(
            item
            for item in self.result["eye_observations"]
            if item["eye_type"] == "global_low_resolution"
        )
        self.assertEqual(
            observation["receptive_field"]["windows"][0]["pixel_xywh"],
            [0, 0, 16, 16],
        )
        self.assertTrue(observation["features"]["scene_context_available"])
        self.assertEqual(
            self.result["shared_visual_state"]["global_context"][
                "source_observation_id"
            ],
            observation["observation_id"],
        )

    def test_regional_eyes_never_report_outside_write_scope(self) -> None:
        observations = [
            item
            for item in self.result["eye_observations"]
            if item["eye_type"] == "regional"
        ]
        self.assertEqual(len(observations), 4)
        for observation in observations:
            self.assertEqual(observation["write_scope"]["mode"], "bounded")
            scope = PixelBox(
                *observation["write_scope"]["windows"][0]["pixel_xywh"]
            )
            for region in observation["regions"]:
                self.assertTrue(scope.contains(PixelBox(*region["pixel_xywh"])))

    def test_boundary_eye_coordinate_transforms_are_consistent(self) -> None:
        observation = next(
            item
            for item in self.result["eye_observations"]
            if item["eye_type"] == "overlap_boundary"
        )
        self.assertEqual(len(observation["receptive_field"]["windows"]), 2)
        for window in observation["receptive_field"]["windows"]:
            x, y, width, height = window["pixel_xywh"]
            self.assertEqual(
                window["local_to_global"]["offset_xy"],
                [x, y],
            )
            self.assertEqual(
                window["normalized_xywh"],
                [
                    round(x / 16, 8),
                    round(y / 16, 8),
                    round(width / 16, 8),
                    round(height / 16, 8),
                ],
            )

    def test_motion_eye_detects_the_synthetic_change_box(self) -> None:
        observation = next(
            item
            for item in self.result["eye_observations"]
            if item["eye_type"] == "frame_difference_motion"
        )
        self.assertGreater(observation["features"]["changed_pixel_count"], 0)
        self.assertEqual(observation["regions"][0]["pixel_xywh"], [6, 4, 4, 4])
        self.assertEqual(observation["regions"][0]["state"], "dirty")

    def test_fusion_preserves_sources_confidence_and_all_region_states(self) -> None:
        state = self.result["shared_visual_state"]
        validate_shared_visual_state(state)
        observed_states = {region["state"] for region in state["regions"]}
        self.assertEqual(observed_states, {"dirty", "stable", "uncertain"})
        for region in state["regions"]:
            self.assertTrue(region["sources"])
            self.assertGreaterEqual(region["confidence"], 0)
            self.assertLessEqual(region["confidence"], 1)
            for source in region["sources"]:
                self.assertIn(source["observation_id"], state["observation_ids"])

    def test_compute_plan_is_selective_but_makes_no_speedup_claim(self) -> None:
        plan = self.result["compute_plan"]
        validate_compute_plan(plan)
        decisions = {unit["decision"] for unit in plan["execution_units"]}
        self.assertEqual(decisions, {"generate", "reuse_cache", "reconcile"})
        self.assertIsNone(plan["claims"]["actual_sparse_speedup"]["value"])
        self.assertEqual(
            plan["claims"]["actual_sparse_speedup"]["support_status"],
            "not_collected",
        )
        self.assertIsNone(plan["claims"]["gpu_kernel_seconds"]["value"])
        self.assertEqual(
            plan["claims"]["gpu_kernel_seconds"]["support_status"],
            "unsupported",
        )

    def test_unsupported_observation_metrics_are_never_numeric(self) -> None:
        for observation in self.result["eye_observations"]:
            for metric in observation["unsupported_metrics"]:
                self.assertIsNone(metric["value"])
                self.assertIn(
                    metric["support_status"],
                    {"unsupported", "not_collected"},
                )
                self.assertTrue(metric["reason"])
                self.assertTrue(metric["measurement_method"])

    def test_schema_drafts_are_valid_json_and_cover_reference_artifacts(self) -> None:
        instances = {
            "eye_contract.schema.json": self.result["eye_contracts"][0],
            "eye_observation.schema.json": self.result["eye_observations"][0],
            "shared_visual_state.schema.json": self.result[
                "shared_visual_state"
            ],
            "compute_plan.schema.json": self.result["compute_plan"],
        }
        for name, instance in instances.items():
            schema = json.loads(
                (ROOT / "schemas" / name).read_text(encoding="utf-8")
            )
            self.assertEqual(
                schema["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertTrue(set(schema["required"]).issubset(instance))

    def test_custom_input_can_be_simulated_without_model_or_cuda(self) -> None:
        sequence = np.zeros((3, 8, 8, 1), dtype=np.float32)
        sequence[-1, 1:3, 3:5, 0] = 1.0
        result = run_reference_simulation(
            sequence,
            seed=7,
            sequence_id="custom",
        )
        self.assertEqual(result["observation_receipt"]["seed"], 7)
        self.assertTrue(result["observation_receipt"]["deterministic"])
        self.assertNotIn("backend", result["observation_receipt"])


if __name__ == "__main__":
    unittest.main()
