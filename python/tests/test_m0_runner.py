from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_backends.wan21 import Wan21RunSpec, build_generate_command
from hive_benchmarks.m0_runner import download_plan, load_config, load_suite


class Wan21CommandTests(unittest.TestCase):
    def test_command_is_deterministic_and_official(self) -> None:
        spec = Wan21RunSpec(
            prompt="A deterministic prompt.",
            seed=101,
            output_path=Path("out.mp4"),
        )
        command = build_generate_command(
            python_executable=Path("python"),
            code_dir=Path("vendor/Wan2.1"),
            checkpoint_dir=Path("models/Wan2.1-T2V-1.3B"),
            spec=spec,
        )
        self.assertIn("t2v-1.3B", command)
        self.assertIn("832*480", command)
        self.assertIn("49", command)
        self.assertIn("101", command)
        self.assertIn("--t5_cpu", command)
        self.assertNotIn("--use_prompt_extend", command)

    def test_invalid_frame_count_is_rejected(self) -> None:
        spec = Wan21RunSpec(
            prompt="Invalid frames.",
            seed=1,
            output_path=Path("out.mp4"),
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

    def test_receipt_schema_is_valid_json(self) -> None:
        path = ROOT / "schemas" / "run_receipt.schema.json"
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["properties"]["status"]["enum"][0], "blocked")


if __name__ == "__main__":
    unittest.main()
