from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from hive_benchmarks.topology_pruning.r2_attribution import (
    STAGE_TAXONOMY,
    calibrate_instrumentation,
    run_attributed,
)
from hive_benchmarks.topology_pruning.r2_runner import (
    _expected_hashes,
    _assert_output_available,
    build_parser,
    decide,
    plan,
    normalize_python_semantic_evidence,
    sanitize_rust_public_evidence,
    validate_config,
    validate_immutable_git_blobs,
)
from hive_benchmarks.topology_pruning.r2_evidence import (
    canonical_digest,
    canonical_python_evidence,
    canonical_rust_evidence,
    evidence_bundle_digests,
)
from hive_benchmarks.topology_pruning.r2_audit import audit as audit_r2_evidence
from hive_benchmarks.topology_pruning.synthetic_cases import CASES, generate_case
from hive_probes.rust_io_reference import generate_sequence, input_profile, run_pipeline


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "m1-p0-r2.rust-compound-runtime.json"


def gate_inputs() -> tuple[dict, dict]:
    python_result = {
        "uninstrumented_summaries": {
            candidate: {"p50_seconds": 0.020 + index * 0.010, "semantic_hashes": [candidate]}
            for index, candidate in enumerate(("T0", "T1", "T2"))
        },
        "paired_attribution": {
            "T1": {"attributed_percentage": 0.9, "unattributed_percentage": 0.1},
            "T2": {"attributed_percentage": 0.9, "unattributed_percentage": 0.1},
        },
    }
    rust_result = {
        "summaries": {
            candidate: {
                "core_p50_seconds": 0.010 + index * 0.005,
                "benchmark_amortized_boundary_inclusive_p50_seconds": 0.012 + index * 0.005,
                "semantic_hashes": [candidate],
            }
            for index, candidate in enumerate(("T0", "T1", "T2"))
        },
        "boundary": {"ffi_call_seconds": {"status": "collected"}},
        "copy_accounting": {"copied_input_multiples": 2.0},
    }
    return python_result, rust_result


class TopologyPruningR2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def test_fixed_scope_and_taxonomy(self) -> None:
        validate_config(self.config)
        self.assertEqual(self.config["topologies"], ["T0", "T1", "T2"])
        self.assertEqual(self.config["warmups"], 5)
        self.assertEqual(self.config["repetitions"], 20)
        self.assertEqual(tuple(self.config["stage_taxonomy"]), STAGE_TAXONOMY)
        self.assertNotIn("MONO_FIRST", self.config["decision_rules"])
        self.assertEqual(
            self.config["profile"], "case-b-high-resolution-local-change"
        )

    def test_v1_and_r1_git_blobs_are_immutable(self) -> None:
        validate_immutable_git_blobs(self.config)
        self.assertEqual(len(self.config["immutable_git_blob_sha256"]), 16)

    def test_attributed_pipeline_preserves_semantics_and_stage_scopes(self) -> None:
        profile = input_profile("low", 101)
        sequence = generate_sequence(profile)
        for topology in ("mono_1x1", "uniform_2x2", "motion_focused"):
            plain = run_pipeline(profile, topology, sequence)
            attributed = run_attributed(profile, topology, sequence)
            self.assertEqual(plain["semantic_hash"], attributed["semantic_hash"])
            self.assertEqual(set(attributed["stages"]), set(STAGE_TAXONOMY))
            self.assertGreaterEqual(attributed["unattributed_ns"], 0)
            self.assertEqual(
                attributed["total_ns"],
                attributed["attributed_exclusive_ns"] + attributed["unattributed_ns"],
            )
            self.assertEqual(attributed["counters"]["bytes_copied"], 0)

    def test_instrumentation_overhead_is_separate(self) -> None:
        calibration = calibrate_instrumentation(5)
        self.assertGreater(calibration["p50_ns"], 0)
        self.assertFalse(calibration["subtracted_from_results"])

    def test_exact_case_b_hashes_match_r1(self) -> None:
        case_b = next(
            case for case in CASES if case.case_id == "case-b-high-resolution-local-change"
        )
        profile, sequence = generate_case(case_b, 101)
        expected = _expected_hashes()
        for candidate, topology in {
            "T0": "mono_1x1",
            "T1": "uniform_2x2",
            "T2": "motion_focused",
        }.items():
            plain = run_pipeline(profile, topology, sequence)
            attributed = run_attributed(profile, topology, sequence)
            self.assertEqual(plain["semantic_hash"], expected[candidate])
            self.assertEqual(attributed["semantic_hash"], expected[candidate])

    def test_gate_viable_requires_collected_ffi(self) -> None:
        python_result, rust_result = gate_inputs()
        decision = decide(self.config, python_result, rust_result)
        self.assertEqual(decision["decision"], "RUST_RUNTIME_VIABLE")
        rust_result["boundary"]["ffi_call_seconds"]["status"] = "not_collected"
        decision = decide(self.config, python_result, rust_result)
        self.assertEqual(decision["decision"], "REFINE_RUST_BOUNDARY")

    def test_gate_optimizes_when_attributed_rust_core_is_not_better(self) -> None:
        python_result, rust_result = gate_inputs()
        rust_result["summaries"]["T1"]["core_p50_seconds"] = 1.0
        rust_result["summaries"]["T2"]["core_p50_seconds"] = 1.0
        decision = decide(self.config, python_result, rust_result)
        self.assertEqual(decision["decision"], "OPTIMIZE_COMPOUND_RUNTIME")

    def test_gate_enforces_unattributed_threshold(self) -> None:
        python_result, rust_result = gate_inputs()
        rust_result["summaries"]["T1"]["core_p50_seconds"] = 1.0
        rust_result["summaries"]["T2"]["core_p50_seconds"] = 1.0
        python_result["paired_attribution"]["T2"]["unattributed_percentage"] = 0.3
        decision = decide(self.config, python_result, rust_result)
        self.assertEqual(decision["decision"], "PAUSE_CURRENT_IMPLEMENTATION")

    def test_gate_pauses_on_semantic_failure(self) -> None:
        python_result, rust_result = gate_inputs()
        rust_result["summaries"]["T2"]["semantic_hashes"] = ["different"]
        decision = decide(self.config, python_result, rust_result)
        self.assertEqual(decision["decision"], "PAUSE_CURRENT_IMPLEMENTATION")

    def test_plan_does_not_execute_measurement_or_create_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "r2"
            args = build_parser().parse_args(["--output-dir", str(output), "--plan"])
            with patch(
                "hive_benchmarks.topology_pruning.r2_runner._python_measurement",
                side_effect=AssertionError("measurement must not run"),
            ):
                result = plan(args)
            self.assertFalse(result["execution_started"])
            self.assertFalse(output.exists())
            self.assertEqual(len(result["expected_artifacts"]), 5)

    def test_existing_output_blocks_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "decision-report.md").write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                _assert_output_available(output)

    def test_semantic_payloads_are_normalized_without_measurement_changes(self) -> None:
        legacy = {
            "samples": [
                {
                    "block_index": block,
                    "candidate_id": candidate,
                    "semantic_hash": f"hash-{candidate}",
                    "attributed": {
                        "semantic_hash": f"hash-{candidate}",
                        "semantic_result": {"candidate": candidate, "stable": True},
                        "total_ns": block + 1,
                    },
                }
                for block in range(2)
                for candidate in ("T0", "T1", "T2")
            ]
        }
        normalized = canonical_python_evidence(legacy)
        self.assertEqual(len(normalized["semantic_evidence"]), 3)
        self.assertEqual(len(normalized["samples"]), 6)
        for sample in normalized["samples"]:
            self.assertNotIn("semantic_result", sample["attributed"])
            self.assertNotIn("semantic_hash", sample["attributed"])
            record = normalized["semantic_evidence"][sample["semantic_ref"]]
            self.assertEqual(record["semantic_hash"], sample["semantic_hash"])
        self.assertEqual(
            canonical_digest(normalized),
            canonical_digest(normalize_python_semantic_evidence(normalized)),
        )

    def test_rust_command_is_a_sanitized_template(self) -> None:
        private_root = "".join(("C", ":", "/private"))
        private = {
            "command": [
                f"{private_root}/bin/runtime.exe",
                "r2-batch",
                "--input",
                f"{private_root}/temp/input.bin",
                "--output",
                f"{private_root}/temp/output.json",
            ],
            "stdout": f"read {private_root}/temp/input.bin",
            "stderr": "",
            "measured": 7,
        }
        sanitized = canonical_rust_evidence(private)
        rendered = json.dumps(sanitized, sort_keys=True)
        self.assertNotIn(private_root, rendered)
        self.assertEqual(sanitized["command_template"][0], "<rust-binary>")
        self.assertIn("<temporary-input>", sanitized["command_template"])
        self.assertIn("<temporary-output>", sanitized["command_template"])
        self.assertEqual(sanitized["measured"], 7)

    def test_attempt_002_public_evidence_is_normalized_and_path_safe(self) -> None:
        evidence = ROOT / "reports" / "topology_pruning" / "r2-failures" / "attempt-002"
        python_result = json.loads(
            (evidence / "python-stage-attribution.json").read_text(encoding="utf-8")
        )
        rust_result = json.loads(
            (evidence / "rust-boundary-results.json").read_text(encoding="utf-8")
        )
        failure = json.loads((evidence / "failure.json").read_text(encoding="utf-8"))
        self.assertEqual(len(python_result["samples"]), 60)
        self.assertEqual(len(python_result["semantic_evidence"]), 3)
        counts = {candidate: 0 for candidate in ("T0", "T1", "T2")}
        for sample in python_result["samples"]:
            counts[sample["candidate_id"]] += 1
            self.assertNotIn("semantic_result", sample["attributed"])
            self.assertNotIn("semantic_hash", sample["attributed"])
            record = python_result["semantic_evidence"][sample["semantic_ref"]]
            self.assertEqual(record["semantic_hash"], sample["semantic_hash"])
            self.assertEqual(record["candidate_id"], sample["candidate_id"])
        self.assertEqual(counts, {"T0": 20, "T1": 20, "T2": 20})
        self.assertFalse(failure["results_eligible"])
        public_text = json.dumps({"python": python_result, "rust": rust_result})
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", public_text))
        self.assertIsNone(re.search(r"/(?:home|Users)/[^/]+/", public_text))
        self.assertIsNone(re.search(r"(?i)(?:AppData|OneDrive)[\\/]", public_text))
        self.assertEqual(rust_result["command_template"][0], "<rust-binary>")

    def test_final_evidence_has_complete_paired_accounting(self) -> None:
        evidence = ROOT / "reports" / "topology_pruning" / "r2"
        python_result = json.loads(
            (evidence / "python-stage-attribution.json").read_text(encoding="utf-8")
        )
        rust_result = json.loads(
            (evidence / "rust-boundary-results.json").read_text(encoding="utf-8")
        )
        parity = json.loads(
            (evidence / "parity-report.json").read_text(encoding="utf-8")
        )
        decision_report = (evidence / "decision-report.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(len(python_result["samples"]), 60)
        self.assertEqual(len(rust_result["samples"]), 60)
        self.assertEqual(len(python_result["semantic_evidence"]), 3)
        for sample in python_result["samples"]:
            self.assertNotIn("semantic_result", sample["attributed"])
            self.assertNotIn("semantic_hash", sample["attributed"])
            record = python_result["semantic_evidence"][sample["semantic_ref"]]
            self.assertEqual(record["semantic_hash"], sample["semantic_hash"])
            self.assertEqual(record["candidate_id"], sample["candidate_id"])
        for candidate in ("T1", "T2"):
            paired = python_result["paired_attribution"][candidate]
            self.assertEqual(paired["pairs"], 20)
            self.assertEqual(len(paired["records"]), 20)
            self.assertTrue(all(record["equation_holds"] for record in paired["records"]))
        self.assertTrue(parity["semantic_parity"])
        self.assertTrue(parity["deterministic_hashes"])
        self.assertIsNone(rust_result["boundary"]["ffi_call_seconds"]["value"])
        self.assertEqual(
            rust_result["boundary"]["ffi_call_seconds"]["status"],
            "not_collected",
        )
        self.assertEqual(rust_result["command_template"][0], "<rust-binary>")
        public_text = json.dumps({"python": python_result, "rust": rust_result})
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", public_text))
        self.assertIsNone(re.search(r"/(?:home|Users)/[^/]+/", public_text))
        self.assertIn("Decision: **REFINE_RUST_BOUNDARY**", decision_report)

    def test_equivalence_manifest_matches_current_public_evidence(self) -> None:
        manifest = json.loads(
            (
                ROOT
                / "reports"
                / "topology_pruning"
                / "r2"
                / "evidence-equivalence.json"
            ).read_text(encoding="utf-8")
        )
        current = evidence_bundle_digests(ROOT)
        self.assertTrue(manifest["logical_equivalence"]["equivalent"])
        self.assertEqual(
            manifest["logical_equivalence"]["logical_evidence_digest_before"],
            manifest["logical_equivalence"]["logical_evidence_digest_after"],
        )
        self.assertEqual(
            current["logical_evidence_digest"],
            manifest["logical_equivalence"]["logical_evidence_digest_after"],
        )
        self.assertEqual(
            current["artifact_digests"],
            manifest["logical_equivalence"]["artifact_digests"],
        )
        self.assertEqual(manifest["execution_counts"]["measurement_reruns"], 0)
        self.assertEqual(manifest["preserved_result"]["final_gate"], "REFINE_RUST_BOUNDARY")

    def test_r2_public_tree_has_no_private_execution_paths(self) -> None:
        roots = [
            ROOT / "reports" / "topology_pruning" / "r2",
            ROOT / "reports" / "topology_pruning" / "r2-failures",
        ]
        unc_prefix = re.escape(chr(92) * 2)
        forbidden = re.compile(
            r"(?i)(?:[A-Z]:[\\/]|"
            + unc_prefix
            + r"[^\\\s]+[\\/]|/(?:home|Users)/[^/\s]+/|AppData[\\/]|OneDrive[\\/])"
        )
        violations: list[str] = []
        for evidence_root in roots:
            for path in evidence_root.rglob("*"):
                if not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                if forbidden.search(text):
                    violations.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(violations, [])

    def test_success_and_failed_evidence_remain_separate(self) -> None:
        final_report = (
            ROOT / "reports" / "topology_pruning" / "r2" / "decision-report.md"
        ).read_text(encoding="utf-8")
        attempt_001 = json.loads(
            (
                ROOT
                / "reports"
                / "topology_pruning"
                / "r2-failures"
                / "attempt-001"
                / "failure.json"
            ).read_text(encoding="utf-8")
        )
        attempt_002 = json.loads(
            (
                ROOT
                / "reports"
                / "topology_pruning"
                / "r2-failures"
                / "attempt-002"
                / "failure.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("Decision: **REFINE_RUST_BOUNDARY**", final_report)
        self.assertFalse(attempt_001["results_eligible"])
        self.assertFalse(attempt_002["results_eligible"])

    def test_r2_arithmetic_audit_retains_350_assertions(self) -> None:
        result = audit_r2_evidence(ROOT)
        self.assertEqual(result["assertions"], 350)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["decision"], "REFINE_RUST_BOUNDARY")


if __name__ == "__main__":
    unittest.main()
