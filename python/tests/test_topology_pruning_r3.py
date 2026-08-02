from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hive_benchmarks.topology_pruning.r3_runner import (
    ARTIFACT_NAMES,
    CONFIG_PATH,
    _implementation_order,
    build_parser,
    decide,
    execute,
    plan,
    validate_config,
    validate_immutable_r2,
)


ROOT = Path(__file__).resolve().parents[2]


def gate_inputs() -> tuple[dict, dict, dict]:
    summaries = {
        candidate: {
            "python_p50_seconds": 1.0,
            "python_p95_seconds": 1.2,
            "rust_boundary_p50_seconds": 0.7 if candidate != "T0" else 1.04,
            "rust_boundary_p95_seconds": 1.0 if candidate != "T0" else 1.2,
            "p50_reduction_vs_python": 0.3 if candidate != "T0" else -0.04,
            "p95_regression_vs_python": -0.1 if candidate != "T0" else 0.0,
            "ffi_buffer_marshal_fraction_p50": 0.05,
            "buffer_acquisition_p50_seconds": 0.001,
            "ffi_enter_exit_residual_p50_seconds": 0.001,
            "output_marshal_p50_seconds": 0.001,
        }
        for candidate in ("T0", "T1", "T2")
    }
    parity = {"semantic_parity_rate": 1.0, "deterministic_hashes": True}
    copies = {
        "input_copy_bytes": 0,
        "subprocess_count": 0,
        "temporary_file_count": 0,
        "unavailable_values_are_null": True,
    }
    return summaries, parity, copies


class TopologyPruningR3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_predeclared_scope_and_thresholds(self) -> None:
        validate_config(self.config)
        self.assertEqual(self.config["topologies"], ["T0", "T1", "T2"])
        self.assertEqual(self.config["shape"], [8, 1080, 1920])
        self.assertEqual(self.config["warmups"], 5)
        self.assertEqual(self.config["repetitions"], 30)
        self.assertEqual(self.config["thresholds"]["t1_t2_p50_reduction_min"], 0.2)
        self.assertNotIn("MONO_FIRST", self.config["decision_rules"])

    def test_r2_evidence_is_immutable(self) -> None:
        validate_immutable_r2(self.config)
        self.assertEqual(len(self.config["immutable_r2_git_blobs"]), 21)

    def test_boundary_is_one_call_and_zero_copy(self) -> None:
        ffi = self.config["ffi"]
        self.assertEqual(ffi["calls_per_candidate"], 1)
        self.assertEqual(ffi["per_eye_calls"], 0)
        self.assertEqual(ffi["input_copy_bytes_required"], 0)
        self.assertEqual(ffi["temporary_files_required"], 0)
        self.assertEqual(ffi["subprocesses_required"], 0)
        self.assertTrue(ffi["buffer_readonly_required"])
        self.assertTrue(ffi["input_json_forbidden"])

    def test_pyo3_version_license_and_python_abi_are_pinned(self) -> None:
        ffi = self.config["ffi"]
        self.assertEqual((ffi["technology"], ffi["version"]), ("PyO3", "0.29.0"))
        self.assertEqual(ffi["python_abi"], "abi3-py312")
        licenses = {item["name"]: item for item in self.config["dependency_licenses"]}
        self.assertEqual(licenses["pyo3"]["license"], "MIT OR Apache-2.0")
        self.assertIn("Unicode-3.0", licenses["unicode-ident"]["license"])

    def test_plan_is_model_free_and_does_not_import_extension(self) -> None:
        args = build_parser().parse_args(
            [
                "--output-dir",
                str(ROOT / "reports" / "topology_pruning" / "r3"),
                "--plan",
            ]
        )
        with patch(
            "hive_benchmarks.topology_pruning.r3_runner._extension",
            side_effect=AssertionError("extension must not import during plan"),
        ):
            payload = plan(args)
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["expected_artifacts"], list(ARTIFACT_NAMES))
        self.assertEqual(payload["model_loads"], 0)
        self.assertEqual(payload["cuda_runs"], 0)

    def test_execution_requires_exact_contract_hash_before_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / ARTIFACT_NAMES[0]).write_text("{}", encoding="utf-8")
            args = build_parser().parse_args(["--output-dir", str(output)])
            with patch(
                "hive_benchmarks.topology_pruning.r3_runner.measure",
                side_effect=AssertionError("measurement must remain blocked"),
            ):
                with self.assertRaisesRegex(ValueError, "exact plan contract hash"):
                    execute(args)

    def test_candidate_and_implementation_order_are_deterministic_and_rotating(self) -> None:
        first = [_implementation_order(101, "measured", block, "T1") for block in range(30)]
        second = [_implementation_order(101, "measured", block, "T1") for block in range(30)]
        self.assertEqual(first, second)
        self.assertEqual(set(first), {("python", "rust_inprocess"), ("rust_inprocess", "python")})

    def test_admitted_gate_uses_fixed_thresholds(self) -> None:
        summaries, parity, copies = gate_inputs()
        result = decide(self.config, summaries, parity, copies)
        self.assertEqual(result["decision"], "RUST_CONTROL_PLANE_ADMITTED")
        summaries["T2"]["p50_reduction_vs_python"] = 0.199
        result = decide(self.config, summaries, parity, copies)
        self.assertEqual(result["decision"], "REFINE_SHARED_BUFFER_BOUNDARY")

    def test_safety_failure_pauses_adapter_not_compound_perception(self) -> None:
        summaries, parity, copies = gate_inputs()
        copies["input_copy_bytes"] = 1
        result = decide(self.config, summaries, parity, copies)
        self.assertEqual(result["decision"], "PAUSE_CURRENT_INPROCESS_ADAPTER")
        self.assertTrue(self.config["evidence_boundaries"]["compound_perception_first"])
        self.assertTrue(self.config["evidence_boundaries"]["mono_is_comparator_and_safety_fallback"])

    def test_unavailable_allocation_count_is_null_with_reason(self) -> None:
        metric = self.config["instrumentation"]["allocation_count"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["status"], "not_collected")
        self.assertTrue(metric["reason"])

    def test_predeclared_artifact_matches_config_hash(self) -> None:
        artifact = json.loads(
            (ROOT / "reports" / "topology_pruning" / "r3" / ARTIFACT_NAMES[0]).read_text(
                encoding="utf-8"
            )
        )
        import hashlib

        digest = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
        self.assertEqual(artifact["source_config_sha256"], digest)
        self.assertFalse(artifact["results_eligible"])

    def test_public_contract_has_no_local_paths_or_addresses(self) -> None:
        rendered = json.dumps(self.config, sort_keys=True)
        self.assertNotRegex(rendered, r"[A-Za-z]:[\\/]")
        self.assertNotRegex(rendered, r"/(?:home|Users)/[^/]+/")
        self.assertNotIn("pointer_address", rendered)
        self.assertFalse(self.config["copy_accounting"]["addresses_public"])

    def test_extension_source_forbids_subprocess_file_and_json_handoff(self) -> None:
        source = (ROOT / "crates" / "hive-retina-python" / "src" / "lib.rs").read_text(
            encoding="utf-8"
        )
        self.assertIn("PyBuffer::<u8>::get", source)
        self.assertNotIn("Command::new", source)
        self.assertNotIn("File::", source)
        self.assertNotIn("serde_json", source)


if __name__ == "__main__":
    unittest.main()
