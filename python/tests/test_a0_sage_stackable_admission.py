from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
from hashlib import sha256
import json
import unittest

from hive_product.a0_sage_stackable_admission import (
    _frame_ssim,
    _selected_review_indices,
    automatic_screen,
    decide,
    public_projection,
    validate_f0_artifacts,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "configs" / "a0_sage_stackable_attention.json").read_text(encoding="utf-8"))


class A0SageStackableAdmissionTests(unittest.TestCase):
    def passing_metrics(self) -> dict:
        return {
            "output_integrity_passed": True,
            "normalized_mae": 0.03,
            "motion_energy_ratio": 1.0,
            "spatial_gradient_energy_ratio": 1.0,
            "temporal_difference_energy_ratio": 1.0,
        }

    def test_contract_preserves_historical_decision(self) -> None:
        historical = CONFIG["historical_f0"]
        self.assertEqual(historical["decision"], "F0_SAGE_NO_GAIN")
        self.assertTrue(historical["decision_is_immutable"])

    def test_a0_does_not_reuse_standalone_thresholds(self) -> None:
        historical = CONFIG["historical_f0"]
        self.assertFalse(historical["standalone_candidate_threshold_used_by_a0"])
        self.assertFalse(historical["standalone_two_x_gate_used_by_a0"])

    def test_fixed_catastrophic_gate_values(self) -> None:
        gate = CONFIG["automatic_catastrophic_regression_gate"]
        self.assertEqual(gate["normalized_mae_max"], 0.06)
        for prefix in ("motion_energy_ratio", "spatial_gradient_energy_ratio", "temporal_difference_energy_ratio"):
            self.assertEqual(gate[f"{prefix}_min"], 0.8)
            self.assertEqual(gate[f"{prefix}_max"], 1.25)

    def test_automatic_screen_pass_is_not_quality_proof(self) -> None:
        screen = automatic_screen(self.passing_metrics(), CONFIG["automatic_catastrophic_regression_gate"])
        self.assertTrue(screen["passed"])
        self.assertEqual(screen["status"], "AUTOMATIC_REGRESSION_SCREEN_PASSED")
        self.assertFalse(screen["quality_at_least_standard_proven"])
        self.assertEqual(screen["visual_equivalence"], "not_proven")

    def test_each_catastrophic_metric_can_fail(self) -> None:
        gate = CONFIG["automatic_catastrophic_regression_gate"]
        for field, value in (
            ("normalized_mae", 0.061),
            ("motion_energy_ratio", 1.251),
            ("spatial_gradient_energy_ratio", 0.799),
            ("temporal_difference_energy_ratio", 1.251),
        ):
            metrics = self.passing_metrics()
            metrics[field] = value
            self.assertFalse(automatic_screen(metrics, gate)["passed"], field)

    def test_success_decision_is_optional_and_pending_human_review(self) -> None:
        result = decide(artifacts_valid=True, runtime_positive=True, screen_passed=True, config=CONFIG)
        self.assertEqual(result["decision"], "A0_SAGE_STACKABLE_COMPONENT_READY_FOR_VISUAL_REVIEW")
        self.assertEqual(result["disposition"], "KEEP_AS_OPTIONAL")
        self.assertEqual(result["component_status"], "AVAILABLE_OPTIONAL")
        self.assertFalse(result["product_default"])
        self.assertEqual(result["human_visual_review"], "PENDING_HUMAN_REVIEW")

    def test_quality_failure_preserves_optional_evidence_only(self) -> None:
        result = decide(artifacts_valid=True, runtime_positive=True, screen_passed=False, config=CONFIG)
        self.assertEqual(result["decision"], "A0_SAGE_AUTOMATIC_QUALITY_REGRESSION")
        self.assertEqual(result["disposition"], "KEEP_AS_OPTIONAL_EVIDENCE")
        self.assertEqual(result["product_promotion"], 0)

    def test_no_gain_and_runtime_failure_fail_open(self) -> None:
        no_gain = decide(artifacts_valid=True, runtime_positive=False, screen_passed=True, config=CONFIG)
        rejected = decide(artifacts_valid=False, runtime_positive=True, screen_passed=True, config=CONFIG)
        self.assertEqual(no_gain["decision"], "A0_SAGE_CURRENT_ENVIRONMENT_NO_GAIN")
        self.assertEqual(rejected["decision"], "A0_SAGE_RUNTIME_REJECTED")
        self.assertEqual(no_gain["standard_full_compute_fallback"], "preserved")
        self.assertEqual(rejected["standard_full_compute_fallback"], "preserved")

    def test_review_indices_are_deduplicated(self) -> None:
        selected = _selected_review_indices([0, 31, 62, 93, 123], [(100.0, 31), (90.0, 20), (80.0, 40), (70.0, 60)], 3)
        self.assertEqual(selected, [0, 20, 31, 40, 60, 62, 93, 123])

    def test_public_projection_removes_paths_and_prompt(self) -> None:
        projected = public_projection({
            "private_path": "C:/private/video.mp4",
            "nested": {"path": "/private/file", "prompt": "secret prompt", "sha256": "a" * 64},
        })
        dump = json.dumps(projected)
        self.assertNotIn("private", dump)
        self.assertNotIn("secret prompt", dump)
        self.assertEqual(projected["nested"]["sha256"], "a" * 64)

    def test_identical_frame_ssim_is_one(self) -> None:
        import numpy as np

        frame = np.arange(64, dtype=np.float64).reshape(8, 8)
        self.assertAlmostEqual(_frame_ssim(frame, frame, np), 1.0)

    def test_generation_budget_is_bounded(self) -> None:
        budget = CONFIG["execution_budget"]
        self.assertTrue(budget["artifact_reuse_first"])
        self.assertEqual(budget["maximum_fresh_generations_if_reuse_invalid"], 2)
        self.assertEqual(budget["retry_count"], 0)
        self.assertEqual(budget["maximum_third_generation"], 0)

    def test_private_artifact_provenance_and_hashes_are_enforced(self) -> None:
        # The desktop sandbox can redirect the process-wide temp directory to
        # an ACL-restricted location, so keep this model-free fixture under the
        # checked-out workspace and let TemporaryDirectory remove it.
        with TemporaryDirectory(prefix="hiveframe-a0-", dir=ROOT) as temporary:
            root = Path(temporary)
            files = {}
            for name, payload in {
                "standard.mp4": b"standard",
                "sage.mp4": b"sage",
                "contact.png": b"contact",
                "side.mp4": b"side",
            }.items():
                path = root / name
                path.write_bytes(payload)
                files[name] = path
            config = deepcopy(CONFIG)
            historical = config["historical_f0"]
            historical.update(
                {
                    "standard_output_sha256": sha256(b"standard").hexdigest(),
                    "sage_output_sha256": sha256(b"sage").hexdigest(),
                    "contact_sheet_sha256": sha256(b"contact").hexdigest(),
                    "side_by_side_sha256": sha256(b"side").hexdigest(),
                }
            )

            def summary(mode: str, run_id: str, video: Path, digest: str, total: float, runner: float) -> dict:
                return {
                    "mode": mode,
                    "run_id": run_id,
                    "terminal_status": "succeeded",
                    "retry_count": 0,
                    "result": {"private_path": str(video), "sha256": digest},
                    "receipt": {
                        "output_sha256": digest,
                        "workflow_sha256": historical["workflow_sha256"],
                        "metrics": {"total_wall_seconds": {"value": total}},
                    },
                    "phase_metrics": {"runner_total_seconds": {"value": runner}},
                    "integrity": {
                        "codec": "h264",
                        "width": 864,
                        "height": 480,
                        "decoded_frame_count": 124,
                        "fps": 24.0,
                        "audio_stream_count": 1,
                        "black_frame_count": 0,
                        "corrupted_frame_count": 0,
                    },
                }

            standard = summary(
                "standard",
                historical["standard_run_id"],
                files["standard.mp4"],
                historical["standard_output_sha256"],
                historical["standard_submit_to_terminal_seconds"],
                historical["standard_runner_total_seconds"],
            )
            sage = summary(
                "sage-auto",
                historical["sage_run_id"],
                files["sage.mp4"],
                historical["sage_output_sha256"],
                historical["sage_submit_to_terminal_seconds"],
                historical["sage_runner_total_seconds"],
            )
            pair = {
                "schema_version": "f0.sage.comparison.private.1",
                "standard_run_id": historical["standard_run_id"],
                "sage_run_id": historical["sage_run_id"],
                "fixed_profile_match": True,
                "prompt_hash_match": True,
                "contact_sheet": {"path": str(files["contact.png"])},
                "side_by_side_preview": {"path": str(files["side.mp4"])},
            }
            standard_path = root / "standard.json"
            sage_path = root / "sage.json"
            pair_path = root / "pair.json"
            standard_path.write_text(json.dumps(standard), encoding="utf-8")
            sage_path.write_text(json.dumps(sage), encoding="utf-8")
            pair_path.write_text(json.dumps(pair), encoding="utf-8")
            artifacts = validate_f0_artifacts(
                config=config,
                standard_summary_path=standard_path,
                sage_summary_path=sage_path,
                pair_manifest_path=pair_path,
            )
            self.assertEqual(artifacts.provenance["status"], "F0_ARTIFACTS_REUSED")
            files["sage.mp4"].write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Sage video SHA-256 mismatch"):
                validate_f0_artifacts(
                    config=config,
                    standard_summary_path=standard_path,
                    sage_summary_path=sage_path,
                    pair_manifest_path=pair_path,
                )


if __name__ == "__main__":
    unittest.main()
