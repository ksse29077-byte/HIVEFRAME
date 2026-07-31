from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_backends.wan21 import Wan21RunSpec, build_generate_command
from hive_benchmarks.m0_runner import (
    blocked_receipt,
    build_parser,
    build_run_plan,
    build_smoke_plan,
    command_run,
    command_smoke,
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

    def test_external_paths_can_be_short_and_outside_repository(self) -> None:
        root = ROOT / "reports"
        variables = {
            "HIVEFRAME_WAN_CODE_DIR": str(root / "wan"),
            "HIVEFRAME_MODEL_DIR": str(root / "short" / "m"),
            "HIVEFRAME_HF_CACHE_DIR": str(root / "c"),
            "HIVEFRAME_M0_REPORT_DIR": str(root / "r"),
        }
        with patch.dict(os.environ, variables, clear=False):
            config = load_config(ROOT / "configs" / "m0.wan21.toml")
        self.assertEqual(config["backend"]["code_dir"], str((root / "wan").resolve()))
        self.assertEqual(
            config["model"]["local_dir"], str((root / "short" / "m").resolve())
        )
        self.assertEqual(config["model"]["cache_dir"], str((root / "c").resolve()))
        self.assertEqual(
            config["paths"]["run_dir"], str((root / "r" / "runs").resolve())
        )
        plan = download_plan(config)
        self.assertEqual(
            plan["destination"], str((root / "short" / "m").resolve())
        )
        self.assertEqual(plan["storage_volume_checked_at"], str(root.resolve()))
        self.assertEqual(
            plan["cache_destination"], str((root / "c").resolve())
        )

    def test_smoke_and_baseline_profiles_are_separate(self) -> None:
        smoke = settings_for_profile(self.config, "smoke", repeat=1)
        baseline = settings_for_profile(
            self.config, "baseline-reproducibility", repeat=2
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

    def test_smoke_cold_warm_profile_uses_smoke_cost_with_two_runs(self) -> None:
        settings = settings_for_profile(
            self.config, "smoke-cold-warm", repeat=2
        )
        self.assertEqual(settings["size"], "832*480")
        self.assertEqual(settings["frame_num"], 17)
        self.assertEqual(settings["fps"], 16)
        self.assertEqual(settings["sample_steps"], 4)
        self.assertEqual(settings["repeat"], 2)
        self.assertEqual(settings["sample_guide_scale"], 6.0)
        self.assertEqual(settings["sample_solver"], "unipc")
        self.assertEqual(settings["dtype"], "bfloat16")
        self.assertEqual(settings["device"], "cuda:0")
        self.assertTrue(settings["offload_model"])
        self.assertTrue(settings["t5_cpu"])

    def test_explicit_profile_settings_hashes_differ(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        smoke = settings_for_profile(
            self.config, "smoke-cold-warm", repeat=2
        )
        baseline = settings_for_profile(
            self.config, "baseline-reproducibility", repeat=2
        )
        smoke_hash = stable_hash({"sample": prompt, "settings": smoke})
        baseline_hash = stable_hash({"sample": prompt, "settings": baseline})
        self.assertNotEqual(smoke_hash, baseline_hash)

    def test_run_plan_exposes_final_settings_without_execution(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        plan = build_run_plan(self.config, prompt, "smoke-cold-warm")
        self.assertFalse(plan["execution_started"])
        self.assertEqual(plan["selected_profile"], "smoke-cold-warm")
        self.assertEqual(plan["prompt_id"], "static-speaking-person")
        self.assertEqual(plan["effective_settings"]["frame_num"], 17)
        self.assertEqual(plan["effective_settings"]["sample_steps"], 4)
        self.assertEqual(plan["effective_settings"]["repeat"], 2)
        self.assertEqual(
            plan["backend"]["model_revision"],
            self.config["model"]["revision"],
        )
        self.assertEqual(
            plan["backend"]["code_revision"],
            self.config["upstream"]["code_revision"],
        )
        self.assertEqual(len(plan["settings_hash"]), 64)

    def test_smoke_plan_uses_one_low_cost_run(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        plan = build_smoke_plan(
            self.config,
            prompt,
            "smoke-regression-test-001",
        )
        settings = plan["effective_settings"]
        self.assertFalse(plan["execution_started"])
        self.assertEqual(plan["selected_profile"], "smoke")
        self.assertEqual(plan["expected_run_kind"], "single regression smoke")
        self.assertEqual(plan["run_id"], "smoke-regression-test-001")
        self.assertEqual(settings["size"], "832*480")
        self.assertEqual(settings["frame_num"], 17)
        self.assertEqual(settings["fps"], 16)
        self.assertEqual(settings["sample_steps"], 4)
        self.assertEqual(settings["repeat"], 1)
        self.assertEqual(plan["sample"]["seed"], 101)

    def test_smoke_cli_plan_does_not_start_preflight_or_execution(self) -> None:
        args = argparse.Namespace(
            output_dir=None,
            run_id="smoke-regression-test-002",
            plan=True,
            expect_settings_hash=None,
        )
        output = io.StringIO()
        with (
            patch("hive_benchmarks.m0_runner.evaluate_preflight") as preflight,
            patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
            patch("hive_benchmarks.m0_runner.subprocess.Popen") as popen,
            contextlib.redirect_stdout(output),
        ):
            return_code = command_smoke(args, self.config)
        self.assertEqual(return_code, 0)
        preflight.assert_not_called()
        run_sample.assert_not_called()
        popen.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["effective_settings"]["repeat"], 1)

    def test_smoke_missing_approval_hash_blocks_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                output_dir=temporary,
                run_id="smoke-regression-test-003",
                plan=False,
                expect_settings_hash=None,
            )
            output = io.StringIO()
            with (
                patch(
                    "hive_benchmarks.m0_runner.evaluate_preflight"
                ) as preflight,
                patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
                contextlib.redirect_stdout(output),
            ):
                return_code = command_smoke(args, self.config)
        self.assertEqual(return_code, 2)
        preflight.assert_not_called()
        run_sample.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["stage"],
            "settings-approval",
        )

    def test_smoke_mismatched_approval_hash_blocks_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                output_dir=temporary,
                run_id="smoke-regression-test-004",
                plan=False,
                expect_settings_hash="0" * 64,
            )
            output = io.StringIO()
            with (
                patch(
                    "hive_benchmarks.m0_runner.evaluate_preflight"
                ) as preflight,
                patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
                contextlib.redirect_stdout(output),
            ):
                return_code = command_smoke(args, self.config)
        self.assertEqual(return_code, 2)
        preflight.assert_not_called()
        run_sample.assert_not_called()
        self.assertIn("does not match", output.getvalue())

    def test_smoke_approved_hash_and_run_id_reach_receipt_execution(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        run_id = "smoke-regression-test-005"
        plan = build_smoke_plan(self.config, prompt, run_id)
        receipt = {
            "run_id": run_id,
            "profile": "smoke",
            "settings_hash": plan["settings_hash"],
        }
        with tempfile.TemporaryDirectory() as temporary:
            args = argparse.Namespace(
                output_dir=temporary,
                run_id=run_id,
                plan=False,
                expect_settings_hash=plan["settings_hash"],
            )
            output = io.StringIO()
            with (
                patch(
                    "hive_benchmarks.m0_runner.run_sample",
                    return_value=(0, receipt),
                ) as run_sample,
                patch(
                    "hive_benchmarks.m0_runner.read_gate_state",
                    return_value={
                        "schema_version": "0.1.0",
                        "smoke": None,
                        "reproducibility": None,
                    },
                ),
                patch("hive_benchmarks.m0_runner.write_gate_state"),
                contextlib.redirect_stdout(output),
            ):
                return_code = command_smoke(args, self.config)
        self.assertEqual(return_code, 0)
        self.assertEqual(run_sample.call_args.kwargs["profile"], "smoke")
        self.assertEqual(run_sample.call_args.kwargs["repeat"], 1)
        self.assertEqual(run_sample.call_args.kwargs["run_id"], run_id)
        self.assertEqual(json.loads(output.getvalue())["run_id"], run_id)

    def test_smoke_existing_run_id_blocks_before_overwrite(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        run_id = "smoke-regression-test-006"
        plan = build_smoke_plan(self.config, prompt, run_id)
        with tempfile.TemporaryDirectory() as temporary:
            collision = Path(temporary) / f"{run_id}.receipt.json"
            collision.write_text("existing", encoding="utf-8")
            args = argparse.Namespace(
                output_dir=temporary,
                run_id=run_id,
                plan=False,
                expect_settings_hash=plan["settings_hash"],
            )
            output = io.StringIO()
            with (
                patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
                contextlib.redirect_stdout(output),
            ):
                return_code = command_smoke(args, self.config)
        self.assertEqual(return_code, 2)
        run_sample.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["stage"], "run-id-collision")
        self.assertIn(str(collision), payload["message"])

    def test_smoke_invalid_run_id_has_understandable_cli_error(self) -> None:
        error = io.StringIO()
        with (
            contextlib.redirect_stderr(error),
            self.assertRaises(SystemExit),
        ):
            build_parser().parse_args(
                [
                    "smoke",
                    "--run-id",
                    "../unsafe",
                    "--plan",
                ]
            )
        self.assertIn("Run ID must be", error.getvalue())

    def test_cli_plan_does_not_start_preflight_or_model_execution(self) -> None:
        args = argparse.Namespace(
            profile="smoke-cold-warm",
            prompt_id="static-speaking-person",
            output_dir=None,
            plan=True,
            expect_settings_hash=None,
        )
        output = io.StringIO()
        with (
            patch("hive_benchmarks.m0_runner.evaluate_preflight") as preflight,
            patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
            contextlib.redirect_stdout(output),
        ):
            return_code = command_run(args, self.config)
        self.assertEqual(return_code, 0)
        preflight.assert_not_called()
        run_sample.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["execution_started"])

    def test_settings_hash_mismatch_blocks_before_model_execution(self) -> None:
        args = argparse.Namespace(
            profile="smoke-cold-warm",
            prompt_id="static-speaking-person",
            output_dir=None,
            plan=False,
            expect_settings_hash="0" * 64,
        )
        output = io.StringIO()
        with (
            patch("hive_benchmarks.m0_runner.read_gate_state") as gate_state,
            patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
            contextlib.redirect_stdout(output),
        ):
            return_code = command_run(args, self.config)
        self.assertEqual(return_code, 2)
        gate_state.assert_not_called()
        run_sample.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["stage"], "settings-approval")
        self.assertIn("does not match", payload["message"])

    def test_approved_profile_is_forwarded_to_receipt_execution(self) -> None:
        prompt = next(
            item for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        plan = build_run_plan(self.config, prompt, "smoke-cold-warm")
        args = argparse.Namespace(
            profile="smoke-cold-warm",
            prompt_id="static-speaking-person",
            output_dir=None,
            plan=False,
            expect_settings_hash=plan["settings_hash"],
        )
        receipt = {
            "run_id": "smoke-cold-warm-static-speaking-person-101",
            "profile": "smoke-cold-warm",
            "reproducibility": {"status": "hash_match"},
        }
        output = io.StringIO()
        with (
            patch(
                "hive_benchmarks.m0_runner.read_gate_state",
                return_value={"schema_version": "0.1.0", "smoke": {}},
            ),
            patch(
                "hive_benchmarks.m0_runner.gate_matches",
                return_value=True,
            ),
            patch(
                "hive_benchmarks.m0_runner.run_sample",
                return_value=(0, receipt),
            ) as run_sample,
            patch("hive_benchmarks.m0_runner.write_gate_state"),
            contextlib.redirect_stdout(output),
        ):
            return_code = command_run(args, self.config)
        self.assertEqual(return_code, 0)
        self.assertEqual(
            run_sample.call_args.kwargs["profile"],
            "smoke-cold-warm",
        )
        self.assertEqual(run_sample.call_args.kwargs["repeat"], 2)
        self.assertEqual(json.loads(output.getvalue())["profile"], args.profile)

    def test_invalid_run_profile_has_understandable_cli_error(self) -> None:
        error = io.StringIO()
        with (
            contextlib.redirect_stderr(error),
            self.assertRaises(SystemExit),
        ):
            build_parser().parse_args(
                [
                    "run",
                    "--profile",
                    "unknown-profile",
                    "--prompt-id",
                    "static-speaking-person",
                    "--plan",
                ]
            )
        self.assertIn("invalid choice", error.getvalue())
        self.assertIn("smoke-cold-warm", error.getvalue())

    def test_documented_plan_commands_match_the_parser(self) -> None:
        document = (ROOT / "docs" / "M0_BASELINE.md").read_text(
            encoding="utf-8"
        )
        parser = build_parser()
        smoke_args = parser.parse_args(
            [
                "smoke",
                "--run-id",
                "smoke-regression-documented",
                "--plan",
            ]
        )
        self.assertTrue(smoke_args.plan)
        self.assertEqual(
            smoke_args.run_id,
            "smoke-regression-documented",
        )
        self.assertIn("smoke --run-id", document)
        for profile in ("smoke-cold-warm", "baseline-reproducibility"):
            command = [
                "run",
                "--profile",
                profile,
                "--prompt-id",
                "static-speaking-person",
                "--plan",
            ]
            args = parser.parse_args(command)
            self.assertEqual(args.profile, profile)
            self.assertTrue(args.plan)
            self.assertIn(f"--profile {profile}", document)

    def test_settings_hash_is_order_independent(self) -> None:
        self.assertEqual(stable_hash({"a": 1, "b": 2}), stable_hash({"b": 2, "a": 1}))

    def test_receipt_schema_is_valid_json(self) -> None:
        path = ROOT / "schemas" / "run_receipt.schema.json"
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["properties"]["status"]["enum"][0], "blocked")
        self.assertIn("smoke", payload["properties"]["profile"]["enum"])
        self.assertEqual(payload["properties"]["run_id"]["minLength"], 1)
        self.assertIn(
            "smoke-cold-warm",
            payload["properties"]["profile"]["enum"],
        )
        self.assertIn(
            "baseline-reproducibility",
            payload["properties"]["profile"]["enum"],
        )

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
