"""Build public-safe M1-A admission reports from metadata-only inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any

from .m1_corpus_validator import summarize_manifest
from .m1_oracle_validator import summarize_oracles
from .m1_protocol import load_json, public_sanitation_errors
from .m1_rights_validator import summarize_rights


ARTIFACTS = (
    "admission-report.json",
    "rights-summary.json",
    "coverage-summary.json",
    "oracle-validation.json",
    "decision-report.md",
)
ALLOWED_DECISIONS = (
    "M1_CORPUS_AND_ORACLE_READY",
    "CORPUS_ACQUISITION_REQUIRED",
    "RIGHTS_REVIEW_BLOCKED",
    "ORACLE_PROTOCOL_REVISE",
)


def tracked_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def validate_topologies(config: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["topology config must be an object"]
    candidates = config.get("candidates", [])
    ids = [item.get("topology_id") for item in candidates if isinstance(item, dict)]
    if ids != [f"T{index}" for index in range(8)]:
        errors.append("topology candidates must be exactly ordered T0 through T7")
    required = {
        "topology_id", "eye_policy", "roles", "receptive_field_policy", "write_policy",
        "overlap_policy", "temporal_window", "temporal_stride", "activation_policy",
        "global_safety_eye", "uncertainty_promotion", "scene_cut_policy", "fallback_policy",
        "unsupported_policy",
    }
    for index, candidate in enumerate(candidates):
        missing = sorted(required - set(candidate))
        if missing:
            errors.append(f"candidate {index} missing {missing}")
        if candidate.get("global_safety_eye") is not True:
            errors.append(f"candidate {index} lacks the global safety eye")
    if config.get("global_rules", {}).get("mono_role") != "comparator_and_safety_fallback_only":
        errors.append("Mono must remain comparator and safety fallback only")
    return errors + public_sanitation_errors(config)


def validate_measurement_contract(config: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["measurement contract must be an object"]
    if config.get("results_present") is not False:
        errors.append("M1-A measurement contract must contain no results")
    decisions = config.get("m1_a_gate_decisions")
    if decisions != list(ALLOWED_DECISIONS):
        errors.append("M1-A Gate decisions changed")
    gate = config.get("provisional_safety_gate", {})
    if gate.get("dirty_recall_min") != 0.995 or gate.get("false_stable_rate_max") != 0.005:
        errors.append("predeclared dirty-recall or false-stable threshold changed")
    if gate.get("scene_cut_miss_count_max") != 0 or gate.get("preserve_violation_count_max") != 0:
        errors.append("cut and preserve violation allowances must remain zero")
    if gate.get("complete_cost_required") is not True:
        errors.append("complete cost inclusion is required")
    return errors + public_sanitation_errors(config)


def cross_document_errors(manifest: dict[str, Any], rights: dict[str, Any], oracle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    manifest_clips = [item for item in manifest.get("clips", []) if isinstance(item, dict)]
    receipts = [item for item in rights.get("receipts", []) if isinstance(item, dict)]
    annotations = [item for item in oracle.get("annotations", []) if isinstance(item, dict)]
    manifest_ids = {item.get("clip_id") for item in manifest_clips}

    rights_groups: dict[Any, list[dict[str, Any]]] = {}
    for receipt in receipts:
        rights_groups.setdefault(receipt.get("clip_id"), []).append(receipt)
    oracle_groups: dict[Any, list[dict[str, Any]]] = {}
    for annotation in annotations:
        oracle_groups.setdefault(annotation.get("clip_id"), []).append(annotation)

    for clip_id, grouped in rights_groups.items():
        if len(grouped) > 1:
            errors.append(f"duplicate rights receipts for clip {clip_id}")
        if clip_id not in manifest_ids:
            errors.append(f"orphan rights receipt for clip {clip_id}")
    for clip_id, grouped in oracle_groups.items():
        if len(grouped) > 1:
            errors.append(f"duplicate oracle annotations for clip {clip_id}")
        if clip_id not in manifest_ids:
            errors.append(f"orphan oracle annotation for clip {clip_id}")

    for clip in manifest_clips:
        clip_id = clip.get("clip_id")
        receipt_group = rights_groups.get(clip_id, [])
        annotation_group = oracle_groups.get(clip_id, [])
        receipt = receipt_group[0] if len(receipt_group) == 1 else None
        annotation = annotation_group[0] if len(annotation_group) == 1 else None
        admission_status = clip.get("admission_status")

        clip_progress = clip.get("human_review_progress")
        receipt_progress = receipt.get("human_review_progress") if receipt is not None else None
        if clip_progress != receipt_progress:
            errors.append(f"clip {clip_id} human review progress does not match rights receipt")

        if admission_status != "eligible":
            if annotation is not None and annotation.get("review_status") == "verified":
                errors.append(f"non-eligible clip {clip_id} has a verified oracle annotation")
            if receipt is not None:
                expected_review = {"pending": "pending", "rejected": "rejected"}.get(admission_status)
                if expected_review is not None and receipt.get("review_status") != expected_review:
                    errors.append(
                        f"non-eligible clip {clip_id} rights review status does not match {admission_status} admission"
                    )
            continue

        if receipt is None:
            errors.append(f"eligible clip {clip_id} has no rights receipt")
        else:
            if receipt.get("review_status") != "admitted":
                errors.append(f"eligible clip {clip_id} rights review_status is not admitted")
            if receipt.get("original_sha256") != clip.get("original_sha256"):
                errors.append(f"eligible clip {clip_id} rights original_sha256 does not match manifest")
            if receipt.get("source_class") != clip.get("source_class"):
                errors.append(f"eligible clip {clip_id} rights source_class does not match manifest")
            if receipt.get("license_identifier") != clip.get("license_identifier"):
                errors.append(f"eligible clip {clip_id} rights license_identifier does not match manifest")
            if receipt.get("terms_digest") != clip.get("license_terms_digest"):
                errors.append(f"eligible clip {clip_id} rights terms_digest does not match manifest")
            if receipt.get("permissions") != clip.get("permissions"):
                errors.append(f"eligible clip {clip_id} rights permissions do not match manifest")
            attribution = receipt.get("attribution_obligation", {})
            if attribution.get("required") != clip.get("attribution_required"):
                errors.append(f"eligible clip {clip_id} rights attribution requirement does not match manifest")
            if attribution.get("text") != clip.get("attribution_text"):
                errors.append(f"eligible clip {clip_id} rights attribution text does not match manifest")
            if receipt.get("consent_status") != clip.get("consent_status"):
                errors.append(f"eligible clip {clip_id} rights consent_status does not match manifest")
            if receipt.get("identifiable_people") != clip.get("identifiable_people"):
                errors.append(f"eligible clip {clip_id} rights identifiable_people does not match manifest")

        if annotation is None:
            errors.append(f"eligible clip {clip_id} has no oracle annotation")
        else:
            if annotation.get("review_status") != "verified":
                errors.append(f"eligible clip {clip_id} oracle review_status is not verified")
            if annotation.get("source_sha256") != clip.get("original_sha256"):
                errors.append(f"eligible clip {clip_id} oracle source_sha256 does not match manifest")
            if annotation.get("derivative_sha256") != clip.get("derivative_sha256"):
                errors.append(f"eligible clip {clip_id} oracle derivative_sha256 does not match manifest")
            if annotation.get("artifact_digest") != clip.get("oracle_sha256"):
                errors.append(f"eligible clip {clip_id} oracle artifact_digest does not match manifest")
            if not isinstance(annotation.get("semantic_payloads"), dict) or not annotation.get("transitions"):
                errors.append(f"eligible clip {clip_id} oracle artifact/reference payload is missing")
            if "hard_cut" in clip.get("scene_classes", []) and not any(
                transition.get("scene_cut") is True
                for transition in annotation.get("transitions", [])
                if isinstance(transition, dict)
            ):
                errors.append(f"eligible hard_cut clip {clip_id} has no scene_cut oracle transition")
    return errors


def summarize_human_review_phase_one(
    manifest: dict[str, Any], rights: dict[str, Any]
) -> dict[str, Any] | None:
    clips = [item for item in manifest.get("clips", []) if isinstance(item, dict)]
    receipts = [item for item in rights.get("receipts", []) if isinstance(item, dict)]
    progress_by_clip = {
        item.get("clip_id"): item.get("human_review_progress") for item in receipts
    }
    rows: list[dict[str, Any]] = []
    for clip in clips:
        progress = clip.get("human_review_progress")
        if progress is None:
            continue
        clip_id = clip.get("clip_id")
        rows.append(
            {
                "clip_id": clip_id,
                "phase_one_complete": all(
                    progress.get(field) == "yes"
                    for field in ("rights_review", "scene_content_review", "privacy_review")
                ),
                "oracle_initial_pass": progress.get("oracle_initial_pass"),
                "blind_re_review": progress.get("blind_re_review"),
                "adjudication": progress.get("adjudication"),
                "final_status": progress.get("final_status"),
                "cross_document_match": progress == progress_by_clip.get(clip_id),
            }
        )
    if not rows:
        return None
    hashes = {
        clip["human_review_progress"]["checklist_sha256"]
        for clip in clips
        if isinstance(clip.get("human_review_progress"), dict)
    }
    return {
        "phase": "phase_1_rights_scene_privacy",
        "checklist_sha256": next(iter(hashes)) if len(hashes) == 1 else None,
        "reviewed_clips": len(rows),
        "phase_one_complete": sum(item["phase_one_complete"] for item in rows),
        "oracle_initial_pass_complete": sum(
            item["oracle_initial_pass"] != "pending_review" for item in rows
        ),
        "blind_re_review_complete": sum(
            item["blind_re_review"] != "pending_review" for item in rows
        ),
        "adjudication_complete": sum(
            item["adjudication"] != "pending_review" for item in rows
        ),
        "final_status_complete": sum(
            item["final_status"] != "pending_review" for item in rows
        ),
        "all_cross_document_matches": all(item["cross_document_match"] for item in rows),
    }


def decide(
    manifest_summary: dict[str, Any],
    rights_summary: dict[str, Any],
    oracle_summary: dict[str, Any],
    protocol_errors: list[str],
    cross_errors: list[str],
) -> str:
    if (
        protocol_errors
        or not manifest_summary["valid"]
        or not rights_summary["valid"]
        or not oracle_summary["valid"]
        or cross_errors
    ):
        return "ORACLE_PROTOCOL_REVISE"
    if rights_summary["counts"]["pending"] or rights_summary["counts"]["rejected"]:
        return "RIGHTS_REVIEW_BLOCKED"
    if (
        manifest_summary["counts"]["eligible"] < manifest_summary["minimum_eligible_clips"]
        or manifest_summary["missing_scene_classes"]
    ):
        return "CORPUS_ACQUISITION_REQUIRED"
    eligible = manifest_summary["counts"]["eligible"]
    if rights_summary["counts"]["admitted"] != eligible or oracle_summary["counts"]["verified"] != eligible:
        return "ORACLE_PROTOCOL_REVISE"
    return "M1_CORPUS_AND_ORACLE_READY"


def build_reports(
    manifest: dict[str, Any],
    rights: dict[str, Any],
    oracle: dict[str, Any],
    topologies: dict[str, Any],
    measurement: dict[str, Any],
    tracked: list[str],
) -> dict[str, str]:
    manifest_summary = summarize_manifest(manifest, tracked)
    rights_summary = summarize_rights(rights)
    oracle_summary = summarize_oracles(oracle)
    protocol_errors = validate_topologies(topologies) + validate_measurement_contract(measurement)
    cross_errors = cross_document_errors(manifest, rights, oracle)
    decision = decide(manifest_summary, rights_summary, oracle_summary, protocol_errors, cross_errors)
    human_review_phase_one = summarize_human_review_phase_one(manifest, rights)
    coverage = {
        "schema_version": "0.1.0",
        "minimum_eligible_clips": manifest_summary["minimum_eligible_clips"],
        "eligible_clips": manifest_summary["counts"]["eligible"],
        "covered_scene_classes": manifest_summary["covered_scene_classes"],
        "missing_scene_classes": manifest_summary["missing_scene_classes"],
        "coverage_complete": not manifest_summary["missing_scene_classes"] and manifest_summary["counts"]["eligible"] >= manifest_summary["minimum_eligible_clips"],
    }
    admission = {
        "schema_version": "0.1.0",
        "run_kind": "m1_a_corpus_oracle_admission",
        "decision": decision,
        "results_eligible_for_topology_performance": False,
        "m1_complete": False,
        "counts": manifest_summary["counts"],
        "rights_counts": rights_summary["counts"],
        "oracle_counts": oracle_summary["counts"],
        "protocol_errors": protocol_errors,
        "cross_document_errors": cross_errors,
        "manifest_errors": manifest_summary["errors"],
        "rights_errors": rights_summary["errors"],
        "oracle_errors": oracle_summary["errors"],
        "binary_media_tracked": manifest_summary["binary_media_tracked"],
        "execution_counts": {
            "model_downloads": 0, "model_loads": 0, "cuda_runs": 0,
            "paid_external_service_calls": 0, "external_customer_or_personal_data_transfers": 0,
            "backend_integration_runs": 0,
        },
        "claim_boundary": "Admission metadata only; no topology, generation, quality, cost, GPU, or product conclusion.",
    }
    if human_review_phase_one is not None:
        admission["human_review_phase_one"] = human_review_phase_one
    decision_markdown = "\n".join(
        [
            "# M1-A Real-video Corpus and Oracle Admission Decision",
            "",
            f"Decision: **{decision}**",
            "",
            f"Eligible actual clips: {manifest_summary['counts']['eligible']} / {manifest_summary['minimum_eligible_clips']}.",
            f"Missing required scene classes: {len(manifest_summary['missing_scene_classes'])}.",
            "",
            *(
                [
                    f"Human phase-one rights/scene/privacy review: {human_review_phase_one['phase_one_complete']} / {human_review_phase_one['reviewed_clips']} complete.",
                    "Oracle initial pass, blind re-review, adjudication, and final status remain pending.",
                    "",
                ]
                if human_review_phase_one is not None
                else []
            ),
            "This is a metadata/protocol Gate only. It is not topology performance, generation quality, speedup, GPU savings, product evidence, or M1 completion.",
            "",
            "No model was downloaded or loaded; CUDA, paid services, backend integration, and external personal-data transfer were not used.",
            "",
        ]
    )
    return {
        "admission-report.json": json.dumps(admission, indent=2, sort_keys=True) + "\n",
        "rights-summary.json": json.dumps(rights_summary, indent=2, sort_keys=True) + "\n",
        "coverage-summary.json": json.dumps(coverage, indent=2, sort_keys=True) + "\n",
        "oracle-validation.json": json.dumps(oracle_summary, indent=2, sort_keys=True) + "\n",
        "decision-report.md": decision_markdown,
    }


def write_reports(output_dir: Path, reports: dict[str, str]) -> None:
    conflicts = [str(output_dir / name) for name in ARTIFACTS if (output_dir / name).exists()]
    if conflicts:
        raise FileExistsError(f"refusing to overwrite existing artifacts: {conflicts}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in reports.items():
        (output_dir / name).write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rights", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--topologies", type=Path, required=True)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.plan:
        print(json.dumps({"execution_started": False, "expected_artifacts": list(ARTIFACTS), "output_dir": "<repository-root>/reports/m1/corpus"}, indent=2))
        return 0
    reports = build_reports(
        load_json(args.manifest), load_json(args.rights), load_json(args.oracle),
        load_json(args.topologies), load_json(args.measurement), tracked_paths(root),
    )
    write_reports(args.output_dir, reports)
    print(reports["admission-report.json"], end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
