"""Apply M1-A2 phase-one human review without promoting Oracle evidence.

The input checklist remains in the approved local asset bundle.  Git receives
only a sanitized receipt and schema-valid metadata.  This module deliberately
keeps corpus admission and every Oracle review field pending.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .m1_corpus_summary import build_reports, tracked_paths
from .m1_corpus_validator import validate_manifest
from .m1_oracle_validator import validate_oracle_document
from .m1_protocol import public_sanitation_errors
from .m1_rights_validator import validate_rights_document


CHECKLIST_COLUMNS = (
    "clip_id",
    "expected_scene_class",
    "rights_review",
    "scene_content_review",
    "privacy_review",
    "oracle_initial_pass",
    "blind_re_review",
    "adjudication",
    "final_status",
)
PHASE_ONE_FIELDS = ("rights_review", "scene_content_review", "privacy_review")
ORACLE_FIELDS = ("oracle_initial_pass", "blind_re_review", "adjudication", "final_status")
RECORDED_DATE = "2026-08-03"


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_checklist(path: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CHECKLIST_COLUMNS:
            raise ValueError(
                f"checklist columns must be exactly {list(CHECKLIST_COLUMNS)}; got {reader.fieldnames}"
            )
        rows = [
            {key: (value or "").strip().lower() for key, value in row.items()}
            for row in reader
        ]

    expected = {
        clip["clip_id"]: clip["scene_class"] for clip in config.get("clips", [])
    }
    ids = [row["clip_id"] for row in rows]
    if ids != list(expected):
        raise ValueError(f"checklist clip order or membership mismatch: {ids}")
    if len(ids) != len(set(ids)):
        raise ValueError("checklist contains duplicate clip IDs")

    for row in rows:
        clip_id = row["clip_id"]
        if row["expected_scene_class"] != expected[clip_id]:
            raise ValueError(f"scene class mismatch for {clip_id}")
        for field in PHASE_ONE_FIELDS:
            if row[field] != "yes":
                raise ValueError(f"{clip_id} {field} must be yes")
        for field in ORACLE_FIELDS:
            if row[field] != "pending_review":
                raise ValueError(f"{clip_id} {field} must remain pending_review")
    return rows


def progress(row: dict[str, str], checklist_sha256: str) -> dict[str, Any]:
    return {
        "phase": "phase_1_rights_scene_privacy",
        "phase_one_status": "completed",
        "recorded_date": RECORDED_DATE,
        "checklist_sha256": checklist_sha256,
        **{field: row[field] for field in PHASE_ONE_FIELDS + ORACLE_FIELDS},
    }


def apply_progress(
    manifest: dict[str, Any],
    rights: dict[str, Any],
    rows: list[dict[str, str]],
    checklist_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated_manifest = copy.deepcopy(manifest)
    updated_rights = copy.deepcopy(rights)
    rows_by_id = {row["clip_id"]: row for row in rows}
    clips_by_id = {clip["clip_id"]: clip for clip in updated_manifest["clips"]}
    receipts_by_id = {
        receipt["clip_id"]: receipt for receipt in updated_rights["receipts"]
    }
    if set(rows_by_id) != set(clips_by_id) or set(rows_by_id) != set(receipts_by_id):
        raise ValueError("checklist, corpus, and rights clip IDs do not match")

    for clip_id, row in rows_by_id.items():
        phase = progress(row, checklist_sha256)
        receipt = receipts_by_id[clip_id]
        clip = clips_by_id[clip_id]

        receipt["human_review_progress"] = copy.deepcopy(phase)
        receipt["rights_basis"] = (
            "Self-recorded rights declaration and capture log; human phase-one "
            "rights, scene, and privacy review completed; final Oracle admission pending."
        )
        receipt["consent_basis"] = (
            "Designated C01 consent and the human phase-one visual review were confirmed; "
            "Oracle review and final corpus admission remain pending."
            if clip_id == "c01"
            else "The capture declaration reports no third-party identifiable person, and human "
            "phase-one privacy review is complete; final corpus admission remains pending."
        )
        receipt["reviewed_at"] = {
            "value": None,
            "status": "pending",
            "reason": (
                "Human phase-one rights, scene, and privacy review completed on the recorded date; "
                "Oracle initial pass, blind re-review, adjudication, and final status remain pending."
            ),
            "method": "M1-A2 human review checklist",
        }
        receipt["review_method"] = (
            "Direct human original/derivative review for rights, expected scene content, and privacy; "
            "aggregate receipt remains pending until the Oracle workflow completes."
        )

        clip["human_review_progress"] = copy.deepcopy(phase)
        clip["rejection_reason"] = {
            "value": None,
            "status": "pending",
            "reason": (
                "Human phase-one rights, scene, and privacy review completed; Oracle initial pass, "
                "blind re-review, adjudication, and final status remain pending."
            ),
            "method": "M1-A2 human review checklist",
        }
        clip["reviewed_at"] = {
            "value": None,
            "status": "pending",
            "reason": "Phase-one human review is complete but final corpus review is not complete.",
            "method": "M1-A2 human review checklist",
        }
        clip["review_method"] = (
            "Direct human original/derivative rights, scene-content, and privacy review completed; "
            "Oracle stages remain pending."
        )
        clip["evidence_notes"] = [
            note
            for note in clip["evidence_notes"]
            if note != "Scene class is a recording intent until human review confirms coverage."
        ]
        clip["evidence_notes"].extend(
            [
                "Human phase-one review confirmed the expected scene content, rights, and privacy checklist items.",
                "Admission remains pending because Oracle initial review and later review stages are incomplete.",
            ]
        )

        if receipt["review_status"] != "pending" or clip["admission_status"] != "pending":
            raise ValueError(f"phase-one update must not promote {clip_id}")
        if clip["sensitive_content_status"] != "pending":
            raise ValueError(f"phase-one update must not infer sensitive-content disposition for {clip_id}")

    return updated_manifest, updated_rights


def build_receipt(
    rows: list[dict[str, str]], checklist_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "review_phase": "phase_1_rights_scene_privacy",
        "recorded_date": RECORDED_DATE,
        "checklist_sha256": checklist_sha256,
        "checklist_storage_reference": "approved-asset:m1-a2/review-package/review-checklist.csv",
        "reviewed_clips": len(rows),
        "phase_one_complete": len(rows),
        "oracle_initial_pass_complete": 0,
        "blind_re_review_complete": 0,
        "adjudication_complete": 0,
        "final_status_complete": 0,
        "eligible_clips": 0,
        "verified_oracles": 0,
        "gate": "RIGHTS_REVIEW_BLOCKED",
        "results_eligible_for_topology_performance": False,
        "records": [
            {
                "clip_id": row["clip_id"],
                "expected_scene_class": row["expected_scene_class"],
                **{field: row[field] for field in PHASE_ONE_FIELDS + ORACLE_FIELDS},
            }
            for row in rows
        ],
        "execution_counts": {
            "model_downloads": 0,
            "model_loads": 0,
            "cuda_runs": 0,
            "paid_external_service_calls": 0,
            "external_customer_or_personal_data_transfers": 0,
            "backend_integration_runs": 0,
            "topology_performance_runs": 0,
        },
    }


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-m1-a2")
    if temporary.exists():
        raise FileExistsError(f"temporary output already exists: {temporary}")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def plan(checklist: Path, config: dict[str, Any]) -> dict[str, Any]:
    rows = validate_checklist(checklist, config)
    return {
        "execution_started": False,
        "checklist_sha256": sha256_file(checklist),
        "clips": len(rows),
        "phase_one_complete": len(rows),
        "oracle_initial_pass_complete": 0,
        "blind_re_review_complete": 0,
        "adjudication_complete": 0,
        "final_status_complete": 0,
        "eligible_clips": 0,
        "verified_oracles": 0,
        "expected_gate": "RIGHTS_REVIEW_BLOCKED",
        "topology_performance_runs": 0,
    }


def apply(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    rows = validate_checklist(args.checklist, config)
    checklist_sha256 = sha256_file(args.checklist)
    manifest = load_json(args.public_data_dir / "corpus-manifest.pending.json")
    rights = load_json(args.public_data_dir / "rights-receipts.pending.json")
    oracle = load_json(args.asset_root / "metadata" / "oracle-annotations.pending.json")
    updated_manifest, updated_rights = apply_progress(
        manifest, rights, rows, checklist_sha256
    )

    manifest_errors = validate_manifest(updated_manifest)
    rights_errors = validate_rights_document(updated_rights)
    oracle_errors = validate_oracle_document(oracle)
    if manifest_errors or rights_errors or oracle_errors:
        raise ValueError(
            f"updated document validation failed: manifest={manifest_errors}, "
            f"rights={rights_errors}, oracle={oracle_errors}"
        )

    reports = build_reports(
        updated_manifest,
        updated_rights,
        oracle,
        load_json(args.repo_root / "configs" / "m1-topology-candidates.json"),
        load_json(args.repo_root / "configs" / "m1-measurement-contract.json"),
        tracked_paths(args.repo_root),
    )
    admission = json.loads(reports["admission-report.json"])
    expected = {
        "decision": "RIGHTS_REVIEW_BLOCKED",
        "counts": {"eligible": 0, "investigated": 12, "pending": 12, "rejected": 0},
        "oracle_counts": {"pending": 12, "rejected": 0, "total": 12, "verified": 0},
        "rights_counts": {"admitted": 0, "pending": 12, "rejected": 0},
    }
    for key, value in expected.items():
        if admission.get(key) != value:
            raise ValueError(f"phase-one review changed protected admission field {key}")
    if admission.get("results_eligible_for_topology_performance") is not False:
        raise ValueError("phase-one review must not enable topology results")
    phase_summary = admission.get("human_review_phase_one", {})
    if (
        phase_summary.get("phase_one_complete") != 12
        or phase_summary.get("oracle_initial_pass_complete") != 0
        or not phase_summary.get("all_cross_document_matches")
    ):
        raise ValueError("phase-one admission summary mismatch")

    receipt = build_receipt(rows, checklist_sha256)
    for value in (updated_manifest, updated_rights, receipt, admission):
        errors = public_sanitation_errors(value)
        if errors:
            raise ValueError(f"public sanitation failed: {errors}")

    atomic_write(
        args.public_data_dir / "corpus-manifest.pending.json",
        canonical_json(updated_manifest),
    )
    atomic_write(
        args.public_data_dir / "rights-receipts.pending.json",
        canonical_json(updated_rights),
    )
    atomic_write(
        args.public_data_dir / "human-review-phase-1.json", canonical_json(receipt)
    )
    atomic_write(
        args.asset_root / "metadata" / "corpus-manifest.pending.json",
        canonical_json(updated_manifest),
    )
    atomic_write(
        args.asset_root / "metadata" / "rights-receipts.pending.json",
        canonical_json(updated_rights),
    )
    atomic_write(
        args.asset_root / "review-package" / "human-review-phase-1.json",
        canonical_json(receipt),
    )
    for name, content in reports.items():
        atomic_write(args.report_dir / name, content)
    atomic_write(
        args.asset_root / "review-package" / "gate-report.json",
        reports["admission-report.json"],
    )
    return {
        "checklist_sha256": checklist_sha256,
        "phase_one_complete": len(rows),
        "oracle_initial_pass_complete": 0,
        "blind_re_review_complete": 0,
        "adjudication_complete": 0,
        "final_status_complete": 0,
        "eligible_clips": 0,
        "verified_oracles": 0,
        "gate": admission["decision"],
        "topology_performance_runs": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--public-data-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    config = load_json(args.config)
    result = plan(args.checklist, config) if args.plan else apply(args, config)
    print(canonical_json(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
