from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from hive_benchmarks.m1_a2_human_review import (
    CHECKLIST_COLUMNS,
    apply_progress,
    build_receipt,
    plan,
    validate_checklist,
)
from hive_benchmarks.m1_corpus_summary import build_reports, cross_document_errors
from hive_benchmarks.m1_corpus_validator import validate_manifest
from hive_benchmarks.m1_oracle_validator import validate_oracle_document
from hive_benchmarks.m1_rights_validator import validate_rights_document


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "configs" / "m1-a2-assets.json").read_text(encoding="utf-8"))
MANIFEST = json.loads(
    (ROOT / "data_ledger" / "m1-a2" / "corpus-manifest.pending.json").read_text(
        encoding="utf-8"
    )
)
RIGHTS = json.loads(
    (ROOT / "data_ledger" / "m1-a2" / "rights-receipts.pending.json").read_text(
        encoding="utf-8"
    )
)


def rows() -> list[dict[str, str]]:
    return [
        {
            "clip_id": clip["clip_id"],
            "expected_scene_class": clip["scene_class"],
            "rights_review": "yes",
            "scene_content_review": "yes",
            "privacy_review": "yes",
            "oracle_initial_pass": "pending_review",
            "blind_re_review": "pending_review",
            "adjudication": "pending_review",
            "final_status": "pending_review",
        }
        for clip in CONFIG["clips"]
    ]


def write_checklist(path: Path, values: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CHECKLIST_COLUMNS)
        writer.writeheader()
        writer.writerows(values)


class M1A2HumanReviewTests(unittest.TestCase):
    def test_exact_phase_one_checklist_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            write_checklist(path, rows())
            parsed = validate_checklist(path, CONFIG)
            self.assertEqual(len(parsed), 12)
            self.assertTrue(
                all(
                    item[field] == "yes"
                    for item in parsed
                    for field in ("rights_review", "scene_content_review", "privacy_review")
                )
            )
            self.assertTrue(
                all(
                    item[field] == "pending_review"
                    for item in parsed
                    for field in (
                        "oracle_initial_pass",
                        "blind_re_review",
                        "adjudication",
                        "final_status",
                    )
                )
            )

    def test_non_yes_or_oracle_promotion_is_rejected(self) -> None:
        for field, value in (
            ("privacy_review", "no"),
            ("oracle_initial_pass", "yes"),
        ):
            values = rows()
            values[0][field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "review.csv"
                write_checklist(path, values)
                with self.assertRaises(ValueError):
                    validate_checklist(path, CONFIG)

    def test_progress_is_schema_valid_and_preserves_pending_admission(self) -> None:
        updated_manifest, updated_rights = apply_progress(
            MANIFEST, RIGHTS, rows(), "a" * 64
        )
        self.assertEqual(validate_manifest(updated_manifest), [])
        self.assertEqual(validate_rights_document(updated_rights), [])
        self.assertTrue(
            all(item["admission_status"] == "pending" for item in updated_manifest["clips"])
        )
        self.assertTrue(
            all(item["review_status"] == "pending" for item in updated_rights["receipts"])
        )
        self.assertTrue(
            all(
                item["human_review_progress"]["oracle_initial_pass"] == "pending_review"
                for item in updated_manifest["clips"]
            )
        )

    def test_cross_document_progress_must_match(self) -> None:
        manifest, rights = apply_progress(MANIFEST, RIGHTS, rows(), "b" * 64)
        self.assertEqual(cross_document_errors(manifest, rights, {"annotations": []}), [])
        rights["receipts"][0]["human_review_progress"]["checklist_sha256"] = "c" * 64
        errors = cross_document_errors(manifest, rights, {"annotations": []})
        self.assertTrue(any("human review progress" in error for error in errors))

    def test_report_surfaces_phase_one_without_ready_or_verification(self) -> None:
        manifest, rights = apply_progress(MANIFEST, RIGHTS, rows(), "d" * 64)
        oracle = {
            "schema_version": "0.1.0",
            "annotation_version": "m1-a2-pending-v0",
            "annotations": [],
        }
        self.assertEqual(validate_oracle_document(oracle), [])
        reports = build_reports(
            manifest,
            rights,
            oracle,
            json.loads((ROOT / "configs" / "m1-topology-candidates.json").read_text()),
            json.loads((ROOT / "configs" / "m1-measurement-contract.json").read_text()),
            [],
        )
        admission = json.loads(reports["admission-report.json"])
        self.assertEqual(admission["decision"], "RIGHTS_REVIEW_BLOCKED")
        self.assertEqual(admission["human_review_phase_one"]["phase_one_complete"], 12)
        self.assertEqual(
            admission["human_review_phase_one"]["oracle_initial_pass_complete"], 0
        )
        self.assertEqual(admission["counts"]["eligible"], 0)
        self.assertEqual(admission["oracle_counts"]["verified"], 0)
        self.assertFalse(admission["results_eligible_for_topology_performance"])

    def test_receipt_cannot_claim_later_review_stages(self) -> None:
        receipt = build_receipt(rows(), "e" * 64)
        self.assertEqual(receipt["phase_one_complete"], 12)
        self.assertEqual(receipt["oracle_initial_pass_complete"], 0)
        self.assertEqual(receipt["blind_re_review_complete"], 0)
        self.assertEqual(receipt["eligible_clips"], 0)
        self.assertEqual(receipt["verified_oracles"], 0)

    def test_plan_is_nonexecuting_and_gate_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            write_checklist(path, rows())
            payload = plan(path, CONFIG)
        self.assertFalse(payload["execution_started"])
        self.assertEqual(payload["phase_one_complete"], 12)
        self.assertEqual(payload["expected_gate"], "RIGHTS_REVIEW_BLOCKED")
        self.assertEqual(payload["eligible_clips"], 0)
        self.assertEqual(payload["verified_oracles"], 0)
        self.assertEqual(payload["topology_performance_runs"], 0)


if __name__ == "__main__":
    unittest.main()
