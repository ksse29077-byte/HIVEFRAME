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
    resources_from_instrumentation,
    sample_process_tree_rss,
    settings_for_profile,
    stable_hash,
    timing_from_instrumentation,
    validate_receipt_contract,
)
from hive_hooks.wan21_m0_instrumented import (
    allocator_environment,
    execute_with_kernel_profiler,
    reset_allocator_peak,
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
        self.assertIn("--kernel-profiler", command)
        self.assertIn("disabled", command)
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

    def test_one_step_memory_admission_spec_is_valid(self) -> None:
        spec = Wan21RunSpec(
            prompt="Memory admission.",
            negative_prompt="No blur.",
            seed=101,
            output_prefix=Path("out"),
            metrics_path=Path("metrics.json"),
            frame_num=49,
            sample_steps=1,
            repeat=1,
        )
        spec.validate()
        command = build_generate_command(
            python_executable=Path("python"),
            driver_path=Path("python/hive_hooks/wan21_m0_instrumented.py"),
            code_dir=Path("vendor/Wan2.1"),
            checkpoint_dir=Path("models/Wan2.1-T2V-1.3B"),
            spec=spec,
        )
        steps_index = command.index("--sample-steps")
        self.assertEqual(command[steps_index + 1], "1")
        self.assertEqual(command[command.index("--repeat") + 1], "1")


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

    def test_memory_admission_profile_is_exact_and_non_benchmark(self) -> None:
        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        plan = build_run_plan(
            self.config,
            prompt,
            "baseline-memory-admission",
        )
        settings = plan["effective_settings"]
        self.assertFalse(plan["execution_started"])
        self.assertEqual(
            plan["expected_run_kind"],
            "baseline memory admission probe",
        )
        self.assertEqual(plan["prompt_id"], "static-speaking-person")
        self.assertEqual(plan["sample"]["seed"], 101)
        self.assertEqual(
            settings["negative_prompt"],
            self.config["generation"]["negative_prompt"],
        )
        self.assertEqual(settings["size"], "832*480")
        self.assertEqual(settings["frame_num"], 49)
        self.assertEqual(settings["fps"], 16)
        self.assertEqual(settings["sample_steps"], 1)
        self.assertEqual(settings["repeat"], 1)
        self.assertEqual(settings["sample_guide_scale"], 6.0)
        self.assertEqual(settings["sample_solver"], "unipc")
        self.assertEqual(settings["dtype"], "bfloat16")
        self.assertEqual(settings["device"], "cuda:0")
        self.assertTrue(settings["offload_model"])
        self.assertTrue(settings["t5_cpu"])
        self.assertEqual(settings["kernel_profiler"], "disabled")
        self.assertEqual(
            settings["wall_clock_mode"], "official_unprofiled"
        )
        self.assertEqual(
            plan["backend"]["model_revision"],
            "37ec512624d61f7aa208f7ea8140a131f93afc9a",
        )
        self.assertEqual(
            plan["backend"]["code_revision"],
            "9737cba9c1c3c4d04b33fcad41c111989865d315",
        )
        self.assertEqual(
            plan["settings_hash"],
            "0a100b5ee62af0e85cdf859383b1b9dd54badc1655f9a8a48b357d922a6c90ee",
        )
        eligibility = plan["benchmark_eligibility"]
        self.assertEqual(eligibility["benchmark_status"], "safety_test")
        self.assertFalse(eligibility["quality_eligible"])
        self.assertFalse(eligibility["speedup_comparison_eligible"])
        self.assertFalse(eligibility["official_baseline_eligible"])
        self.assertTrue(eligibility["memory_admission_eligible"])

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
        admission = settings_for_profile(
            self.config, "baseline-memory-admission", repeat=1
        )
        admission_hash = stable_hash(
            {"sample": prompt, "settings": admission}
        )
        self.assertNotEqual(smoke_hash, baseline_hash)
        self.assertNotEqual(admission_hash, smoke_hash)
        self.assertNotEqual(admission_hash, baseline_hash)
        self.assertEqual(
            smoke_hash,
            "76f0a1ab1196788431a1de4af3319ef5427c3353c1bdb7c6df9641881a2a4588",
        )
        self.assertEqual(
            baseline_hash,
            "5a4da7ba8926901ce705c6724b7953afae91bc6e53c0d222145807a741417598",
        )
        self.assertEqual(
            admission_hash,
            "0a100b5ee62af0e85cdf859383b1b9dd54badc1655f9a8a48b357d922a6c90ee",
        )

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

    def test_admission_plan_starts_no_preflight_child_or_gpu_path(self) -> None:
        args = argparse.Namespace(
            profile="baseline-memory-admission",
            prompt_id="static-speaking-person",
            output_dir=None,
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
            return_code = command_run(args, self.config)
        self.assertEqual(return_code, 0)
        preflight.assert_not_called()
        run_sample.assert_not_called()
        popen.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["effective_settings"]["sample_steps"], 1)
        self.assertEqual(len(payload["output"]["expected_artifacts"]), 5)

    def test_admission_missing_or_mismatched_hash_blocks_before_model(self) -> None:
        for approval_hash in (None, "0" * 64):
            with self.subTest(approval_hash=approval_hash):
                args = argparse.Namespace(
                    profile="baseline-memory-admission",
                    prompt_id="static-speaking-person",
                    output_dir=None,
                    plan=False,
                    expect_settings_hash=approval_hash,
                )
                output = io.StringIO()
                with (
                    patch(
                        "hive_benchmarks.m0_runner.read_gate_state"
                    ) as gate_state,
                    patch(
                        "hive_benchmarks.m0_runner.run_sample"
                    ) as run_sample,
                    contextlib.redirect_stdout(output),
                ):
                    return_code = command_run(args, self.config)
                self.assertEqual(return_code, 2)
                gate_state.assert_not_called()
                run_sample.assert_not_called()
                self.assertEqual(
                    json.loads(output.getvalue())["stage"],
                    "settings-approval",
                )

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
        for profile in (
            "smoke-cold-warm",
            "baseline-memory-admission",
            "baseline-reproducibility",
        ):
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
        self.assertIn(
            "baseline-memory-admission",
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
        self.assertEqual(receipt["schema_version"], "0.2.0")
        validate_receipt_contract(receipt)

    def test_memory_admission_receipt_v02_requires_safe_classification(self) -> None:
        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        settings = settings_for_profile(
            self.config, "baseline-memory-admission", repeat=1
        )
        preflight = {
            "environment": {
                "project_git": {
                    "revision": "test-revision",
                    "dirty": False,
                }
            },
            "blockers": [
                {
                    "code": "gate_refresh_required",
                    "message": "Regression smoke must run on the new commit.",
                }
            ],
            "warnings": [],
        }
        receipt = blocked_receipt(
            self.config,
            prompt,
            preflight,
            settings,
            "baseline-memory-admission",
            ["python", "instrumented.py"],
        )
        validate_receipt_contract(receipt)
        self.assertEqual(receipt["schema_version"], "0.2.0")
        self.assertEqual(
            receipt["run_kind"], "baseline memory admission probe"
        )
        eligibility = receipt["benchmark_eligibility"]
        self.assertEqual(eligibility["benchmark_status"], "safety_test")
        self.assertFalse(eligibility["quality_eligible"])
        self.assertFalse(eligibility["speedup_comparison_eligible"])
        self.assertFalse(eligibility["official_baseline_eligible"])
        self.assertTrue(eligibility["memory_admission_eligible"])

    def test_cuda_event_span_is_not_reported_as_kernel_time(self) -> None:
        instrumentation = self._instrumentation_fixture()
        timing, unsupported = timing_from_instrumentation(
            instrumentation,
            11.0,
            cli_observed_seconds=12.0,
        )
        cold = timing["runs"][0]
        self.assertEqual(
            cold["generation"]["cuda_event_span"]["value"],
            4.5,
        )
        self.assertEqual(
            cold["generation"]["gpu_kernel"]["support_status"],
            "not_collected",
        )
        self.assertIsNone(cold["generation"]["gpu_kernel"]["value"])
        self.assertNotIn("cuda_gpu_seconds", json.dumps(timing))
        self.assertNotIn("cuda_gpu_time", unsupported)
        self.assertNotIn("host_ram_descendants", unsupported)

    def test_disabled_kernel_profiler_runs_once_and_records_null_reason(self) -> None:
        calls = []

        def operation() -> str:
            calls.append("called")
            return "result"

        result, record = execute_with_kernel_profiler(
            object(), "disabled", operation
        )
        self.assertEqual(result, "result")
        self.assertEqual(calls, ["called"])
        self.assertIsNone(record["value"])
        self.assertEqual(record["support_status"], "not_collected")
        self.assertIn("official wall-clock", record["unsupported_reason"])

    def test_torch_kernel_profiler_sums_profiler_kernel_durations(self) -> None:
        class Event:
            def __init__(self, duration: float):
                self.self_cuda_time_total = duration

        class Capture:
            def __enter__(self) -> "Capture":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            @staticmethod
            def key_averages() -> list[Event]:
                return [Event(1000.0), Event(2500.0)]

        class ProfilerActivity:
            CUDA = "cuda"

        class Profiler:
            @staticmethod
            def profile(*, activities: list[str]) -> Capture:
                self.assertEqual(activities, ["cuda"])
                return Capture()

        Profiler.ProfilerActivity = ProfilerActivity

        class FakeTorch:
            profiler = Profiler()

        result, record = execute_with_kernel_profiler(
            FakeTorch(), "torch", lambda: "profiled"
        )
        self.assertEqual(result, "profiled")
        self.assertEqual(record["support_status"], "supported")
        self.assertAlmostEqual(record["value"], 0.0035)

    def test_profiler_extraction_failure_does_not_repeat_operation(self) -> None:
        calls = []

        class Capture:
            def __enter__(self) -> "Capture":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            @staticmethod
            def key_averages() -> list[object]:
                raise RuntimeError("CUPTI results unavailable")

        class ProfilerActivity:
            CUDA = "cuda"

        class Profiler:
            @staticmethod
            def profile(*, activities: list[str]) -> Capture:
                return Capture()

        Profiler.ProfilerActivity = ProfilerActivity

        class FakeTorch:
            profiler = Profiler()

        def operation() -> str:
            calls.append("called")
            return "profiled"

        result, record = execute_with_kernel_profiler(
            FakeTorch(), "torch", operation
        )
        self.assertEqual(result, "profiled")
        self.assertEqual(calls, ["called"])
        self.assertEqual(record["support_status"], "unsupported")
        self.assertIsNone(record["value"])

    def test_generation_peak_reset_calls_allocator_api(self) -> None:
        class FakeCuda:
            calls: list[int] = []

            @classmethod
            def reset_peak_memory_stats(cls, index: int) -> None:
                cls.calls.append(index)

        class FakeTorch:
            cuda = FakeCuda()

        reset_allocator_peak(FakeTorch(), 0)
        reset_allocator_peak(FakeTorch(), 0)
        self.assertEqual(FakeCuda.calls, [0, 0])

    def test_run_and_process_allocator_peaks_are_separate(self) -> None:
        instrumentation = self._instrumentation_fixture()
        resources = resources_from_instrumentation(
            instrumentation,
            peak_main_rss=100,
            peak_child_rss=40,
            peak_tree_rss=140,
            process_tree_support_status="supported",
            process_tree_unsupported_reason=None,
            peak_gpu_memory_mib=12000,
            gpu_utilization_samples=[10, 20],
        )
        self.assertEqual(
            resources["process"]["peak_vram_allocated"]["value"],
            900,
        )
        self.assertEqual(
            resources["runs"][0]["generation_peak_vram_allocated"]["value"],
            700,
        )
        self.assertEqual(
            resources["runs"][0][
                "generation_end_current_vram_reserved"
            ]["value"],
            650,
        )
        self.assertNotEqual(
            resources["process"]["peak_vram_reserved"]["scope"],
            resources["runs"][0]["generation_peak_vram_reserved"]["scope"],
        )

    def test_allocator_environment_is_recorded_with_pool_statistics(self) -> None:
        class FakeProperties:
            total_memory = 12_000

        class FakeCuda:
            @staticmethod
            def get_allocator_backend() -> str:
                return "native"

            @staticmethod
            def get_device_properties(_: int) -> FakeProperties:
                return FakeProperties()

            @staticmethod
            def memory_stats(_: int) -> dict[str, int]:
                return {
                    "allocated_bytes.all.current": 10,
                    "reserved_bytes.large_pool.peak": 20,
                    "unrelated": 30,
                }

        class FakeTorch:
            cuda = FakeCuda()

        with patch.dict(
            os.environ,
            {
                "PYTORCH_ALLOC_CONF": "backend:native",
                "PYTORCH_CUDA_ALLOC_CONF": "backend:native",
            },
            clear=False,
        ):
            result = allocator_environment(FakeTorch(), 0)
        self.assertEqual(result["allocator_backend"], "native")
        self.assertEqual(result["device_total_memory_bytes"], 12_000)
        self.assertEqual(
            result["pool_statistics"]["reserved_bytes.large_pool.peak"],
            20,
        )
        self.assertNotIn("unrelated", result["pool_statistics"])

    def test_wall_hierarchy_and_unattributed_remainder_are_nonnegative(self) -> None:
        instrumentation = self._instrumentation_fixture()
        instrumentation["runs"][0]["generation_wall_seconds"] = 1.0
        timing, _ = timing_from_instrumentation(instrumentation, 11.0)
        cold = timing["runs"][0]
        self.assertEqual(cold["generation"]["unattributed_wall"]["value"], 0.0)
        self.assertEqual(
            cold["generation"]["wall"]["parent_span"],
            "run:cold",
        )
        self.assertIn(
            {
                "parent": "generation:cold",
                "child": "denoising:cold",
            },
            timing["span_relationships"],
        )
        self.assertGreaterEqual(timing["unattributed_wall"]["value"], 0.0)

    def test_incomplete_parent_spans_are_not_reported_as_partial_totals(self) -> None:
        instrumentation = self._instrumentation_fixture()
        instrumentation["runs"][0].pop(
            "video_encode_cuda_event_span_seconds"
        )
        instrumentation["runs"][0].pop("video_encode_wall_seconds")
        timing, unsupported = timing_from_instrumentation(
            instrumentation, 11.0
        )
        self.assertIsNone(timing["process_cuda_event_span"]["value"])
        self.assertEqual(
            timing["process_cuda_event_span"]["support_status"],
            "not_collected",
        )
        self.assertIn(
            "partial sum",
            timing["process_cuda_event_span"]["unsupported_reason"],
        )
        self.assertIsNone(timing["runs"][0]["unattributed_wall"]["value"])
        self.assertIn("cuda_event_span", unsupported)

    def test_process_tree_rss_aggregates_descendants(self) -> None:
        values = {10: 100, 11: 40, 12: 60}
        with (
            patch(
                "hive_benchmarks.m0_runner.process_tree_pids",
                return_value=({10, 11, 12}, None),
            ),
            patch(
                "hive_benchmarks.m0_runner.process_rss_bytes",
                side_effect=lambda pid: values[pid],
            ),
        ):
            sample = sample_process_tree_rss(10)
        self.assertEqual(sample["main_process_rss_bytes"], 100)
        self.assertEqual(sample["child_process_rss_bytes"], 100)
        self.assertEqual(sample["process_tree_rss_bytes"], 200)
        self.assertEqual(sample["support_status"], "supported")

    def test_missing_runner_and_process_tree_samples_are_not_zero(self) -> None:
        timing, _ = timing_from_instrumentation(
            self._instrumentation_fixture(), None
        )
        self.assertIsNone(timing["runner_child_process_wall"]["value"])
        self.assertEqual(
            timing["runner_child_process_wall"]["support_status"],
            "not_collected",
        )
        resources = resources_from_instrumentation(
            self._instrumentation_fixture(),
            peak_main_rss=None,
            peak_child_rss=None,
            peak_tree_rss=None,
            process_tree_support_status="supported",
            process_tree_unsupported_reason=None,
            peak_gpu_memory_mib=None,
            gpu_utilization_samples=[],
        )
        self.assertIsNone(
            resources["host_ram"]["child_process_peak_rss"]["value"]
        )
        self.assertEqual(
            resources["host_ram"]["child_process_peak_rss"][
                "support_status"
            ],
            "not_collected",
        )
        self.assertIsNone(
            resources["process"]["nvidia_system_sampled_peak"]["value"]
        )

    def test_run_collision_blocks_before_gate_or_model_execution(self) -> None:
        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            plan = build_run_plan(
                self.config,
                prompt,
                "smoke-cold-warm",
                output_dir,
            )
            collision = output_dir / f"{plan['run_id']}.receipt.json"
            collision.write_text("existing", encoding="utf-8")
            args = argparse.Namespace(
                profile="smoke-cold-warm",
                prompt_id="static-speaking-person",
                output_dir=temporary,
                plan=False,
                expect_settings_hash=plan["settings_hash"],
            )
            output = io.StringIO()
            with (
                patch("hive_benchmarks.m0_runner.read_gate_state") as gate,
                patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
                contextlib.redirect_stdout(output),
            ):
                return_code = command_run(args, self.config)
        self.assertEqual(return_code, 2)
        gate.assert_not_called()
        run_sample.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["stage"],
            "run-id-collision",
        )

    def test_admission_collision_blocks_before_gate_or_model_execution(self) -> None:
        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            plan = build_run_plan(
                self.config,
                prompt,
                "baseline-memory-admission",
                output_dir,
            )
            collision = output_dir / f"{plan['run_id']}.cold.mp4"
            collision.write_bytes(b"existing")
            args = argparse.Namespace(
                profile="baseline-memory-admission",
                prompt_id="static-speaking-person",
                output_dir=temporary,
                plan=False,
                expect_settings_hash=plan["settings_hash"],
            )
            output = io.StringIO()
            with (
                patch("hive_benchmarks.m0_runner.read_gate_state") as gate,
                patch("hive_benchmarks.m0_runner.run_sample") as run_sample,
                contextlib.redirect_stdout(output),
            ):
                return_code = command_run(args, self.config)
        self.assertEqual(return_code, 2)
        gate.assert_not_called()
        run_sample.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["stage"],
            "run-id-collision",
        )

    def test_admission_gate_never_changes_official_gates(self) -> None:
        from hive_benchmarks.m0_runner import gate_fingerprint

        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        plan = build_run_plan(
            self.config, prompt, "baseline-memory-admission"
        )
        for return_code, expected_status in ((0, "passed"), (1, "failed")):
            with self.subTest(return_code=return_code):
                original_reproducibility = {
                    "status": "passed",
                    "receipt": "preserve-existing-receipt",
                }
                state = {
                    "schema_version": "0.1.0",
                    "smoke": {
                        "status": "succeeded",
                        **gate_fingerprint(self.config),
                    },
                    "reproducibility": dict(original_reproducibility),
                }
                receipt = {
                    "run_id": plan["run_id"],
                    "profile": "baseline-memory-admission",
                    "reproducibility": {"status": "not_evaluated"},
                }
                args = argparse.Namespace(
                    profile="baseline-memory-admission",
                    prompt_id="static-speaking-person",
                    output_dir=None,
                    plan=False,
                    expect_settings_hash=plan["settings_hash"],
                )
                output = io.StringIO()
                with (
                    patch(
                        "hive_benchmarks.m0_runner.read_gate_state",
                        return_value=state,
                    ),
                    patch(
                        "hive_benchmarks.m0_runner.run_sample",
                        return_value=(return_code, receipt),
                    ) as run_sample,
                    patch(
                        "hive_benchmarks.m0_runner.write_gate_state"
                    ) as write_gate,
                    contextlib.redirect_stdout(output),
                ):
                    actual = command_run(args, self.config)
                self.assertEqual(actual, return_code)
                written = write_gate.call_args.args[1]
                self.assertEqual(
                    written["reproducibility"],
                    original_reproducibility,
                )
                self.assertEqual(
                    written["memory_admission"]["status"],
                    expected_status,
                )
                self.assertEqual(run_sample.call_args.kwargs["repeat"], 1)

    def test_plan_lists_output_directory_and_expected_artifacts(self) -> None:
        prompt = next(
            item
            for item in load_suite(self.config)
            if item["id"] == "static-speaking-person"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            plan = build_run_plan(
                self.config,
                prompt,
                "smoke-cold-warm",
                output_dir,
            )
        self.assertEqual(plan["output"]["directory"], str(output_dir))
        self.assertFalse(plan["output"]["overwrite_allowed"])
        paths = [
            item["path"] for item in plan["output"]["expected_artifacts"]
        ]
        self.assertTrue(any(path.endswith(".cold.mp4") for path in paths))
        self.assertTrue(any(path.endswith(".warm.mp4") for path in paths))
        self.assertTrue(any(path.endswith(".receipt.json") for path in paths))

    def test_receipt_schema_declares_v01_compatibility_and_v02_metrics(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "run_receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["enum"],
            ["0.1.0", "0.2.0"],
        )
        metric_required = set(schema["$defs"]["measurement"]["required"])
        self.assertTrue(
            {
                "value",
                "unit",
                "scope",
                "measurement_method",
                "aggregation",
                "support_status",
                "unsupported_reason",
                "parent_span",
                "run_label",
                "repeat_index",
            }.issubset(metric_required)
        )
        timing_run = schema["$defs"]["timingV2"]["properties"]["runs"][
            "items"
        ]["properties"]
        self.assertEqual(
            timing_run["generation"]["properties"]["gpu_kernel"]["$ref"],
            "#/$defs/measurement",
        )
        resource_run = schema["$defs"]["resourcesV2"]["properties"]["runs"][
            "items"
        ]["properties"]
        self.assertEqual(
            resource_run["generation_peak_vram_allocated"]["$ref"],
            "#/$defs/measurement",
        )

    def test_legacy_v01_receipt_remains_accepted_by_runtime_policy(self) -> None:
        legacy = {
            "schema_version": "0.1.0",
            "kind": "hiveframe.m0.run_receipt",
            "run_id": "legacy",
            "status": "succeeded",
            "partial": False,
            "profile": "smoke",
            "timing": {"cuda_gpu_seconds": 1.0},
            "resources": {},
            "unsupported_metrics": {},
            "error": None,
        }
        validate_receipt_contract(legacy)

    def test_gate_fingerprint_contract_is_unchanged_by_receipt_v2(self) -> None:
        from hive_benchmarks.m0_runner import gate_fingerprint, gate_matches

        fingerprint = gate_fingerprint(self.config)
        gate = {"status": "passed", **fingerprint}
        self.assertTrue(gate_matches(gate, self.config, "passed"))

    @staticmethod
    def _instrumentation_fixture() -> dict[str, object]:
        not_collected = {
            "value": None,
            "unit": "seconds",
            "support_status": "not_collected",
            "unsupported_reason": "disabled for official wall-clock",
            "measurement_method": "torch.profiler/CUPTI (disabled)",
        }
        return {
            "schema_version": "0.2.0",
            "total_wall_seconds": 10.0,
            "model_load": {
                "model_load_wall_seconds": 2.0,
                "model_load_cuda_event_span_seconds": 1.5,
                "gpu_kernel_seconds": dict(not_collected),
            },
            "runs": [
                {
                    "label": "cold",
                    "repeat_index": 0,
                    "run_wall_seconds": 6.0,
                    "prompt_encode_calls": [
                        {
                            "label": "positive",
                            "encode_wall_seconds": 1.0,
                            "encode_cuda_event_span_seconds": 0.8,
                        }
                    ],
                    "denoising_steps": [
                        {
                            "index": 0,
                            "model_forward_calls": 2,
                            "step_wall_seconds": 2.0,
                            "step_cuda_event_span_seconds": 1.8,
                        }
                    ],
                    "vae_decode_wall_seconds": 1.0,
                    "vae_decode_cuda_event_span_seconds": 0.9,
                    "generation_wall_seconds": 5.0,
                    "generation_cuda_event_span_seconds": 4.5,
                    "video_encode_wall_seconds": 1.0,
                    "video_encode_cuda_event_span_seconds": 0.5,
                    "gpu_kernel_seconds": dict(not_collected),
                    "video_encode_gpu_kernel_seconds": dict(not_collected),
                    "memory": {
                        "peak_allocated_bytes": 700,
                        "peak_reserved_bytes": 800,
                        "current_allocated_bytes": 600,
                        "current_reserved_bytes": 650,
                    },
                }
            ],
            "process_memory": {
                "process_peak_allocated_bytes": 900,
                "process_peak_reserved_bytes": 1000,
                "final_current_allocated_bytes": 500,
                "final_current_reserved_bytes": 550,
            },
            "allocator_environment": {
                "allocator_backend": "native",
                "pytorch_alloc_conf": None,
                "pytorch_cuda_alloc_conf_alias": None,
                "device_total_memory_bytes": 12_000,
                "pool_statistics": {
                    "reserved_bytes.all.peak": 1000,
                },
                "scope": "selected device",
                "measurement_method": "PyTorch allocator APIs",
                "unsupported": {},
            },
            "kernel_profiler": {
                "mode": "disabled",
                "official_wall_clock_eligible": True,
                "overhead_disclosure": "disabled in official wall-clock",
            },
        }


if __name__ == "__main__":
    unittest.main()
