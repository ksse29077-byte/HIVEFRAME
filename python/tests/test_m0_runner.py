from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_backends.wan21 import Wan21RunSpec, build_generate_command
from hive_benchmarks.m0_runner import (
    blocked_receipt,
    download_plan,
    load_config,
    load_suite,
    settings_for_profile,
    stable_hash,
)


class Wan21CommandTests(unittest.TestCase):
    def test_command_is_deterministic_and_official(self) -> None:
        spec = Wan21RunSpec(
            prompt="A deterministic prompt.",
            negative_prompt="No blur.",
            seed=101,
            output_prefix=Path("out"),
            metrics_path=Path("metrics.json"),
        )
        command = build_generate_command(
            python_executable=Path("python"),
            driver_path=Path("python/hive_hooks/wan21_m0_instrumented.py"),
            code_dir=Path("vendor/Wan2.1"),
            checkpoint_dir=Path("models/Wan2.1-T2V-1.3B"),
            spec=spec,
        )
        self.assertIn("models/Wan2.1-T2V-1.3B", " ".join(command).replace("\\", "/"))
        self.assertIn("832*480", command)
        self.assertIn("49", command)
        self.assertIn("101", command)
        self.assertIn("--negative-prompt", command)
        self.assertIn("--dtype", command)
        self.assertIn("bfloat16", command)
        self.assertIn("--device", command)
        self.assertIn("cuda:0", command)
        self.assertIn("--t5-cpu", command)
        self.assertNotIn("--use_prompt_extend", command)

    def test_invalid_frame_count_is_rejected(self) -> None:
        spec = Wan21RunSpec(
            prompt="Invalid frames.",
            negative_prompt="",
            seed=1,
            output_prefix=Path("out"),
            metrics_path=Path("metrics.json"),
            frame_num=50,
        )
        with self.assertRaises(ValueError):
            spec.validate()


class M0ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(ROOT / "configs" / "m0.wan21.toml")

    def test_model_is_pinned_to_exact_revision_and_size(self) -> None:
        self.assertEqual(
            self.config["model"]["revision"],
            "37ec512624d61f7aa208f7ea8140a131f93afc9a",
        )
        self.assertEqual(
            self.config["model"]["expected_repository_bytes"], 17573837064
        )

    def test_suite_has_ten_unique_deterministic_samples(self) -> None:
        suite = load_suite(self.config)
        self.assertEqual(len(suite), 10)
        self.assertEqual(len({item["id"] for item in suite}), 10)
        self.assertTrue(all(isinstance(item["seed"], int) for item in suite))

    def test_download_plan_does_not_download(self) -> None:
        plan = download_plan(self.config)
        self.assertFalse(plan["download_performed"])
        self.assertEqual(plan["expected_bytes"], 17573837064)
        self.assertIn("models", plan["destination"])
        self.assertEqual(plan["expected_installed_bytes"], 18000000000)
        self.assertGreater(
            plan["recommended_free_before_download_bytes"],
            plan["expected_installed_bytes"],
        )

    def test_smoke_and_baseline_profiles_are_separate(self) -> None:
        smoke = settings_for_profile(self.config, "smoke", repeat=1)
        baseline = settings_for_profile(
            self.config, "reproducibility", repeat=2
        )
        self.assertEqual(smoke["frame_num"], 17)
        self.assertEqual(smoke["sample_steps"], 4)
        self.assertEqual(smoke["repeat"], 1)
        self.assertEqual(baseline["frame_num"], 49)
        self.assertEqual(baseline["sample_steps"], 50)
        self.assertEqual(baseline["repeat"], 2)
        self.assertEqual(baseline["dtype"], "bfloat16")
        self.assertEqual(baseline["device"], "cuda:0")
        self.assertTrue(baseline["negative_prompt"])

    def test_settings_hash_is_order_independent(self) -> None:
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

    def test_receipt_schema_is_valid_json(self) -> None:
        path = ROOT / "schemas" / "run_receipt.schema.json"
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["properties"]["status"]["enum"][0], "blocked")

    def test_blocked_receipt_contains_required_provenance(self) -> None:
        prompt = load_suite(self.config)[0]
        settings = settings_for_profile(self.config, "smoke", repeat=1)
        preflight = {
            "environment": {
                "project_git": {
                    "revision": "test-revision",
                    "dirty": False,
                }
            },
            "blockers": [
                {
                    "code": "model_missing",
                    "message": "Checkpoint is not installed.",
                }
            ],
            "warnings": [],
        }
        receipt = blocked_receipt(
            self.config,
            prompt,
            preflight,
            settings,
            "smoke",
            ["python", "instrumented.py"],
        )
        schema = json.loads(
            (ROOT / "schemas" / "run_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        for field in schema["required"]:
            self.assertIn(field, receipt)
        self.assertEqual(receipt["status"], "blocked")
        self.assertTrue(receipt["partial"])
        self.assertEqual(len(receipt["settings_hash"]), 64)
        self.assertEqual(len(receipt["configuration_hash"]), 64)
        self.assertEqual(receipt["environment"]["project_git"]["revision"], "test-revision")


if __name__ == "__main__":
    unittest.main()
