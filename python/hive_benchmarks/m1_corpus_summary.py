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
    rights_by_clip = {item.get("clip_id"): item for item in rights.get("receipts", [])}
    oracle_by_clip = {item.get("clip_id"): item for item in oracle.get("annotations", [])}
    for clip in manifest.get("clips", []):
        if clip.get("admission_status") != "eligible":
            continue
        clip_id = clip["clip_id"]
        receipt = rights_by_clip.get(clip_id)
        annotation = oracle_by_clip.get(clip_id)
        if receipt is None:
            errors.append(f"eligible clip {clip_id} has no rights receipt")
        elif receipt.get("review_status") != "admitted" or receipt.get("original_sha256") != clip.get("original_sha256"):
            errors.append(f"eligible clip {clip_id} rights receipt is not admitted or digest-matched")
        if annotation is None:
            errors.append(f"eligible clip {clip_id} has no oracle annotation")
        elif annotation.get("review_status") != "verified" or annotation.get("artifact_digest") != clip.get("oracle_sha256"):
            errors.append(f"eligible clip {clip_id} oracle is not verified or digest-matched")
    return errors


def decide(
    manifest_summary: dict[str, Any],
    rights_summary: dict[str, Any],
    oracle_summary: dict[str, Any],
    protocol_errors: list[str],
    cross_errors: list[str],
) -> str:
    if protocol_errors or not manifest_summary["valid"] or not oracle_summary["valid"] or cross_errors:
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
    decision_markdown = "\n".join(
        [
            "# M1-A Real-video Corpus and Oracle Admission Decision",
            "",
            f"Decision: **{decision}**",
            "",
            f"Eligible actual clips: {manifest_summary['counts']['eligible']} / {manifest_summary['minimum_eligible_clips']}.",
            f"Missing required scene classes: {len(manifest_summary['missing_scene_classes'])}.",
            "",
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
