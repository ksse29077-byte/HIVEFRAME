from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import unittest

from hive_product.ltx_admission import (
    REQUIRED_NODES,
    build_workflow,
    decide,
    integrity_passed,
    load_config,
    public_projection,
    queue_counts,
    sha256_bytes,
    validate_config,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "ltx_video_2b_fp8_admission.json"


class LTXAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(CONFIG_PATH)

    def workflow(self) -> dict:
        config = deepcopy(self.config)
        config["profile"]["prompt_sha256"] = sha256_bytes("test prompt")
        config["profile"]["negative_prompt_sha256"] = sha256_bytes("test negative")
        return build_workflow(
            config,
            input_name="private.png",
            output_prefix="hiveframe/ltx-test",
            prompt="test prompt",
            negative_prompt="test negative",
        )

    def test_fixed_profile_and_budget(self) -> None:
        profile = self.config["profile"]
        budget = self.config["execution_budget"]
        self.assertEqual((profile["width"], profile["height"], profile["frames"]), (768, 512, 33))
        self.assertEqual((profile["fps"], profile["steps"], profile["guidance"]), (24.0, 8, 1.0))
        self.assertFalse(profile["stg"])
        self.assertEqual(budget["maximum_backend_submissions"], 1)
        self.assertEqual((budget["retry_count"], budget["fallback_count"], budget["wan_downloads_or_runs"]), (0, 0, 0))

    def test_budget_or_profile_drift_is_rejected(self) -> None:
        changed = deepcopy(self.config)
        changed["profile"]["steps"] = 1
        with self.assertRaisesRegex(ValueError, "profile changed"):
            validate_config(changed)
        changed = deepcopy(self.config)
        changed["execution_budget"]["maximum_generations"] = 2
        with self.assertRaisesRegex(ValueError, "unbounded"):
            validate_config(changed)

    def test_workflow_is_local_core_i2v_only(self) -> None:
        workflow = self.workflow()
        classes = {node["class_type"] for node in workflow.values()}
        self.assertEqual(classes, REQUIRED_NODES)
        self.assertFalse(any("Api" in name for name in classes))
        self.assertFalse(any("Wan" in name for name in classes))
        self.assertEqual(workflow["1"]["inputs"]["ckpt_name"], self.config["model"]["filename"])
        self.assertEqual(workflow["2"]["inputs"]["clip_name"], self.config["text_encoder"]["filename"])
        self.assertEqual(workflow["6"]["inputs"]["length"], 33)
        self.assertEqual(workflow["8"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["10"]["inputs"]["noise_seed"], 101)
        self.assertEqual(workflow["10"]["inputs"]["cfg"], 1.0)

    def test_pinned_file_contract(self) -> None:
        self.assertEqual(self.config["model"]["bytes"], 4461695684)
        self.assertEqual(
            self.config["model"]["sha256"], "d6d8fa8ed3a98346787c2503ac80fb5d7cebcf80e356b79a2ba361fbadf97e15"
        )
        self.assertEqual(self.config["text_encoder"]["bytes"], 5157348688)
        self.assertEqual(
            self.config["text_encoder"]["sha256"],
            "a498f0485dc9536735258018417c3fd7758dc3bccc0a645feaa472b34955557a",
        )

    def test_queue_counting(self) -> None:
        self.assertEqual(queue_counts({"queue_running": [], "queue_pending": []}), (0, 0))
        self.assertEqual(queue_counts({"queue_running": [[1]], "queue_pending": [[2], [3]]}), (1, 2))

    def test_integrity_gate(self) -> None:
        metrics = {
            "container": "mp4",
            "codec": "h264",
            "width": 768,
            "height": 512,
            "decoded_frame_count": 33,
            "fps": 24.0,
            "black_frame_count": 0,
            "corrupt_frame_count": 0,
            "file_bytes": 100,
        }
        self.assertTrue(integrity_passed(metrics, self.config["integrity_gate"], 200))
        metrics["decoded_frame_count"] = 32
        self.assertFalse(integrity_passed(metrics, self.config["integrity_gate"], 200))

    def test_decision_requires_all_admission_evidence(self) -> None:
        receipt = {
            "blocked_before_submit": False,
            "terminal_status": "succeeded",
            "output_integrity_passed": True,
            "admission_stop_seconds": 900,
            "timings": {"submit_to_terminal_seconds": 100.0},
            "counters": {
                "backend_submission_count": 1,
                "gpu_execution_started_count": 1,
                "completed_count": 1,
                "retry_count": 0,
                "fallback_count": 0,
                "external_api_call_count": 0,
                "external_job_termination_count": 0,
                "oom_count": 0,
            },
        }
        self.assertEqual(decide(receipt), "LTX_ADMISSION_READY_FOR_FORMAL_H3_COMPARISON")
        receipt["timings"]["submit_to_terminal_seconds"] = 901.0
        self.assertEqual(decide(receipt), "LTX_ADMISSION_FAILED")
        receipt["timings"]["submit_to_terminal_seconds"] = 100.0
        receipt["counters"]["oom_count"] = 1
        self.assertEqual(decide(receipt), "LTX_ADMISSION_FAILED")
        receipt["blocked_before_submit"] = True
        self.assertEqual(decide(receipt), "LTX_ADMISSION_BLOCKED")

    def test_public_projection_removes_private_fields(self) -> None:
        projected = public_projection(
            {
                "private_run_root": "C:/private",
                "input_path": "C:/private/dog.png",
                "profile": {"prompt": "private prompt", "seed": 101},
                "workflow": {"4": {"inputs": {"text": "private prompt"}}},
                "runtime_inspection": {"system_stats": {"system": {"argv": ["C:/private/runtime"]}}},
                "prompt_id": "private-id",
                "result": {"private_path": "C:/private/out.mp4", "sha256": "a" * 64},
            }
        )
        dump = json.dumps(projected)
        self.assertNotIn("C:/private", dump)
        self.assertNotIn("private prompt", dump)
        self.assertEqual(projected["result"]["sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
