from __future__ import annotations

import json
from pathlib import Path
import unittest

from hive_benchmarks.m1_a2_prepare import (
    FILTER_CHAIN,
    build_manifest_clip,
    build_oracle,
    build_rights_receipt,
    derivative_command,
    frame_timestamps_from_payload,
    plan,
)
from hive_benchmarks.m1_corpus_summary import build_reports
from hive_benchmarks.m1_corpus_validator import validate_manifest
from hive_benchmarks.m1_oracle_validator import validate_oracle_document
from hive_benchmarks.m1_protocol import public_sanitation_errors
from hive_benchmarks.m1_rights_validator import validate_rights_document


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "configs" / "m1-a2-assets.json").read_text(encoding="utf-8"))


class M1A2PrepareTests(unittest.TestCase):
    def test_config_fixes_twelve_distinct_originals_and_scene_classes(self) -> None:
        clips = CONFIG["clips"]
        self.assertEqual([item["clip_id"] for item in clips], [f"c{index:02d}" for index in range(1, 13)])
        self.assertEqual(len({item["original_sha256"] for item in clips}), 12)
        required = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))[
            "required_scene_classes"
        ]
        self.assertEqual([item["scene_class"] for item in clips], required)

    def test_derivative_contract_preserves_declared_orientation_policy(self) -> None:
        contract = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))[
            "derivative_contract"
        ]
        self.assertEqual(
            contract["orientation_policy"],
            "apply_declared_container_rotation_then_clear_rotation_metadata",
        )

    def test_frame_timestamp_parser_ignores_rotation_side_data(self) -> None:
        payload = {
            "frames": [
                {
                    "best_effort_timestamp_time": "0.000000",
                    "side_data_list": [{"rotation": -90, "displaymatrix": "00000000: 0 65536"}],
                },
                {"best_effort_timestamp_time": "0.033333"},
            ]
        }
        self.assertEqual(frame_timestamps_from_payload(payload), [0.0, 0.033333])

    def test_derivative_command_is_pinned_and_never_overwrites(self) -> None:
        command = derivative_command(Path("ffmpeg"), Path("source.mp4"), Path("output.mkv"))
        joined = " ".join(str(item) for item in command)
        self.assertIn("-n", command)
        self.assertNotIn("-y", command)
        self.assertIn("-an", command)
        self.assertIn("ffv1", command)
        self.assertIn("-threads 1", joined)
        self.assertIn("-fps_mode passthrough", joined)
        self.assertGreater(command.index("-fflags"), command.index("-i"))
        self.assertIn("832:480", FILTER_CHAIN)
        self.assertIn("fps=16:round=down:start_time=0", FILTER_CHAIN)

    def test_oracle_scaffold_is_pending_and_full_canvas_uncertain(self) -> None:
        clip = CONFIG["clips"][0]
        annotation = build_oracle(clip, "a" * 64, 4)
        document = {
            "schema_version": "0.1.0",
            "annotation_version": "m1-a2-pending-v0",
            "annotations": [annotation],
        }
        self.assertEqual(annotation["review_status"], "pending")
        self.assertEqual(annotation["confidence"], 0.0)
        self.assertEqual(len(annotation["transitions"]), 3)
        for transition in annotation["transitions"]:
            self.assertFalse(transition["scene_cut"])
            self.assertEqual(transition["camera_motion"], "uncertain")
            self.assertEqual(transition["regions"][0]["state"], "uncertain")
            self.assertEqual(transition["regions"][0]["geometry"]["xywh"], [0, 0, 832, 480])
        self.assertEqual(validate_oracle_document(document), [])

    def test_pending_documents_validate_and_cannot_produce_ready_gate(self) -> None:
        clip = CONFIG["clips"][0]
        source = {
            "bytes": 100,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "frame_count": 4,
            "duration_seconds": 0.1,
            "codec": "h264",
            "container": "mov,mp4,m4a,3gp,3g2,mj2",
            "audio_present": True,
        }
        oracle = build_oracle(clip, "b" * 64, 4)
        manifest_base = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))
        manifest = {
            **manifest_base,
            "corpus_version": "m1-a2-pending-review-v0",
            "clips": [build_manifest_clip(CONFIG, clip, source, "b" * 64, oracle["artifact_digest"])],
        }
        rights = {"schema_version": "0.1.0", "receipts": [build_rights_receipt(CONFIG, clip)]}
        oracles = {
            "schema_version": "0.1.0",
            "annotation_version": "m1-a2-pending-v0",
            "annotations": [oracle],
        }
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(validate_rights_document(rights), [])
        self.assertEqual(validate_oracle_document(oracles), [])
        reports = build_reports(
            manifest,
            rights,
            oracles,
            json.loads((ROOT / "configs" / "m1-topology-candidates.json").read_text(encoding="utf-8")),
            json.loads((ROOT / "configs" / "m1-measurement-contract.json").read_text(encoding="utf-8")),
            [],
        )
        admission = json.loads(reports["admission-report.json"])
        self.assertEqual(admission["decision"], "RIGHTS_REVIEW_BLOCKED")
        self.assertFalse(admission["results_eligible_for_topology_performance"])

    def test_public_metadata_has_no_local_absolute_path(self) -> None:
        clip = CONFIG["clips"][0]
        rights = build_rights_receipt(CONFIG, clip)
        oracle = build_oracle(clip, "c" * 64, 3)
        self.assertEqual(public_sanitation_errors(CONFIG), [])
        self.assertEqual(public_sanitation_errors(rights), [])
        self.assertEqual(public_sanitation_errors(oracle), [])

    def test_plan_is_nonexecuting_and_declares_review_boundary(self) -> None:
        payload = plan(CONFIG)
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["original_count"], 12)
        self.assertEqual(payload["target_resolution"], [832, 480])
        self.assertEqual(payload["target_fps"], 16)
        self.assertEqual(payload["decoder_version"], "7.1.1")
        self.assertEqual(payload["oracle_workflow_status"], "pending_review")
        self.assertEqual(payload["model_loads"], 0)
        self.assertEqual(payload["cuda_runs"], 0)
        self.assertEqual(payload["topology_performance_runs"], 0)


if __name__ == "__main__":
    unittest.main()
