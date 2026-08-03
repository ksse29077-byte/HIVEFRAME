from __future__ import annotations

import json
from pathlib import Path
import unittest

import numpy as np

from hive_benchmarks.m1_a2_guided_oracle_review import (
    HEIGHT,
    LOW_HEIGHT,
    LOW_WIDTH,
    WIDTH,
    build_proposals,
    derive_partition,
    method_receipt,
    plan,
    render_html,
    transition_features,
    validate_temporal_coverage,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "configs" / "m1-a2-assets.json").read_text(encoding="utf-8"))


def synthetic_frames(*, cut: bool = False) -> np.ndarray:
    frames = np.zeros((12, LOW_HEIGHT, LOW_WIDTH), dtype=np.uint8)
    frames[:, 10:90, 10:190] = 40
    for index in range(2, 8):
        left = 15 + (index - 2) * 10
        frames[index:, 40:70, left : left + 24] = 210
    if cut:
        frames[7:] = 225
    return frames


class M1A2GuidedOracleReviewTests(unittest.TestCase):
    def test_adjacent_difference_is_deterministic_and_detects_change(self) -> None:
        first = transition_features(synthetic_frames())
        second = transition_features(synthetic_frames())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 11)
        self.assertTrue(any(item["boxes"] for item in first))
        self.assertTrue(
            all(
                box["source"] == "automatic_adjacent_frame_difference_proposal"
                for item in first
                for box in item["boxes"]
            )
        )

    def test_grouped_proposals_cover_every_transition_without_gaps(self) -> None:
        proposal = build_proposals(
            transition_features(synthetic_frames()), "c01", "static_background_speaking_person"
        )
        validate_temporal_coverage(proposal["proposals"], proposal["frame_count"])
        self.assertEqual(proposal["proposals"][0]["start_frame"], 0)
        self.assertEqual(proposal["proposals"][-1]["end_frame"], 11)
        self.assertTrue(
            all(item["review_status"] == "pending_review" for item in proposal["proposals"])
        )

    def test_stable_complement_is_complete_and_nonoverlapping(self) -> None:
        boxes = [
            {"x": 10, "y": 20, "width": 100, "height": 80, "state": "dirty"},
            {"x": 200, "y": 100, "width": 50, "height": 60, "state": "uncertain"},
        ]
        partition = derive_partition(boxes)
        self.assertEqual(sum(item["width"] * item["height"] for item in partition), WIDTH * HEIGHT)
        self.assertIn("stable", {item["state"] for item in partition})
        self.assertIn("dirty", {item["state"] for item in partition})
        self.assertIn("uncertain", {item["state"] for item in partition})

    def test_overlapping_boxes_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            derive_partition(
                [
                    {"x": 0, "y": 0, "width": 100, "height": 100, "state": "dirty"},
                    {"x": 50, "y": 50, "width": 100, "height": 100, "state": "uncertain"},
                ]
            )

    def test_declared_semantic_classes_receive_review_candidates(self) -> None:
        features = transition_features(synthetic_frames())
        camera = build_proposals(features, "c04", "slow_pan")
        occlusion = build_proposals(features, "c08", "multiple_objects_occlusion")
        lighting = build_proposals(features, "c11", "lighting_change")
        self.assertTrue(any(p["flags"]["camera_motion"] == "candidate" for p in camera["proposals"]))
        self.assertTrue(any(p["flags"]["occlusion"] == "candidate" for p in occlusion["proposals"]))
        self.assertTrue(any(p["flags"]["lighting_change"] == "candidate" for p in lighting["proposals"]))

    def test_c07_ranks_hard_cut_candidates_but_selects_none(self) -> None:
        proposal = build_proposals(transition_features(synthetic_frames(cut=True)), "c07", "hard_cut")
        self.assertEqual(len(proposal["cut_candidates"]), 8)
        self.assertEqual(proposal["cut_candidates"][0]["transition_frame"], 6)
        self.assertIsNone(proposal["hard_cut_selected"])
        self.assertEqual(proposal["oracle_initial_pass"], "pending_review")

    def test_guided_html_is_offline_korean_and_human_controlled(self) -> None:
        clip = build_proposals(transition_features(synthetic_frames()), "c01", "demo")
        clip["proxy"] = "../oracle-initial-review/proxies/c01-review.mp4"
        html = render_html([clip])
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", html)
        for label in (
            "제안이 맞음",
            "수정 필요",
            "판단 어려움",
            "후보 구간 재생",
            "클립 1차 검수 완료",
            "dirty 박스 추가",
            "uncertain 박스 추가",
            "pending_review",
        ):
            self.assertIn(label, html)
        self.assertIn("drag", html.lower())
        self.assertIn("derived_stable_complement", html)
        self.assertIn("hard_cut_override={start_frame:frame", html)
        self.assertIn("source:'human_selected_hard_cut'", html)
        self.assertIn("verified_oracles:0", html)
        self.assertNotIn("verified_oracles:1", html)

    def test_receipt_forbids_truth_eligibility_and_execution(self) -> None:
        receipt = method_receipt(
            [
                {
                    "clip_id": "c01",
                    "proposal_intervals": 1,
                    "dirty_boxes": 1,
                    "uncertain_boxes": 0,
                    "cut_candidates": 0,
                }
            ]
        )
        self.assertFalse(receipt["automatic_proposals_are_truth"])
        self.assertEqual(receipt["review_status"], "pending_review")
        self.assertEqual(receipt["eligible_clips"], 0)
        self.assertEqual(receipt["verified_oracles"], 0)
        self.assertEqual(receipt["gate"], "RIGHTS_REVIEW_BLOCKED")
        self.assertTrue(all(value == 0 for value in receipt["execution_counts"].values()))

    def test_plan_is_nonexecuting_and_preserves_gate(self) -> None:
        result = plan(CONFIG, Path("guided-review"))
        self.assertFalse(result["execution_started"])
        self.assertEqual(result["clips"], 12)
        self.assertFalse(result["automatic_proposals_are_truth"])
        self.assertEqual(result["oracle_initial_pass"], "pending_review")
        self.assertEqual(result["eligible_clips"], 0)
        self.assertEqual(result["verified_oracles"], 0)
        self.assertEqual(result["gate"], "RIGHTS_REVIEW_BLOCKED")
        self.assertEqual(result["model_loads"], 0)
        self.assertEqual(result["cuda_runs"], 0)
        self.assertEqual(result["backend_integration_runs"], 0)
        self.assertEqual(result["topology_performance_runs"], 0)


if __name__ == "__main__":
    unittest.main()
