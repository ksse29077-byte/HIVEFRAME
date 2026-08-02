"""Model-free validation for the M1-A real-video corpus manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .m1_protocol import (
    ALLOWED_STORAGE_CLASSES,
    ELIGIBLE_SOURCE_CLASSES,
    is_sha256,
    is_unavailable,
    load_json,
    public_sanitation_errors,
    require_keys,
    tracked_binary_errors,
)
from .m1_schema_contract import validate_m1_schema


REQUIRED_CLIP_KEYS = (
    "clip_id", "neutral_description", "scene_classes", "stress_labels", "source_class",
    "source_provenance", "rights_status", "rights_holder", "source_authority", "license_identifier",
    "license_terms_digest", "attribution_required", "attribution_text", "permissions",
    "identifiable_people", "consent_required", "consent_status", "sensitive_content_status",
    "original_sha256", "original_bytes", "width", "height", "fps", "frame_count", "duration_seconds",
    "codec", "container", "audio_present", "derivative_sha256", "oracle_sha256", "storage_class",
    "storage_reference", "admission_status", "rejection_reason", "reviewed_at", "review_method",
    "evidence_notes",
)


def validate_derivative_contract(contract: Any, path: str = "$.derivative_contract") -> list[str]:
    required = (
        "original_immutable", "decoder", "decoder_version", "orientation_policy", "colorspace",
        "bit_depth", "alpha_policy", "aspect_policy", "crop_policy", "letterbox_policy",
        "resize_policy", "target_resolution", "target_fps", "sampling_policy", "vfr_policy",
        "audio_policy", "output_representation", "command_template", "tool_version",
        "frame_mapping_policy", "result_tuning_forbidden",
    )
    errors = require_keys(contract, required, path)
    if errors or not isinstance(contract, dict):
        return errors
    if contract["original_immutable"] is not True or contract["result_tuning_forbidden"] is not True:
        errors.append(f"{path}: originals must remain immutable and result-driven tuning is forbidden")
    command = contract.get("command_template", "")
    for placeholder in ("<decoder>", "<original-input>", "<analysis-output>"):
        if placeholder not in command:
            errors.append(f"{path}.command_template: missing {placeholder}")
    errors.extend(public_sanitation_errors(contract))
    return errors


def validate_clip(clip: Any, path: str = "$.clips[]") -> list[str]:
    errors = require_keys(clip, REQUIRED_CLIP_KEYS, path)
    if errors or not isinstance(clip, dict):
        return errors
    for field in ("original_sha256",):
        if not is_sha256(clip[field]):
            errors.append(f"{path}.{field}: expected SHA-256")
    for field in ("derivative_sha256", "oracle_sha256", "license_terms_digest"):
        if not (is_sha256(clip[field]) or is_unavailable(clip[field])):
            errors.append(f"{path}.{field}: expected SHA-256 or explicit unavailable/pending metadata")
    if clip["storage_class"] not in ALLOWED_STORAGE_CLASSES:
        errors.append(f"{path}.storage_class: invalid storage class")
    if clip["admission_status"] not in {"eligible", "pending", "rejected"}:
        errors.append(f"{path}.admission_status: invalid status")
    if clip["rights_status"] not in {"admitted", "pending", "rejected"}:
        errors.append(f"{path}.rights_status: invalid status")
    if not isinstance(clip.get("scene_classes"), list) or not clip["scene_classes"]:
        errors.append(f"{path}.scene_classes: at least one scene class is required")
    for field in ("original_bytes", "width", "height", "frame_count"):
        if not isinstance(clip.get(field), int) or clip[field] <= 0:
            errors.append(f"{path}.{field}: expected positive integer")
    if isinstance(clip.get("frame_count"), int) and clip["frame_count"] < 2:
        errors.append(f"{path}.frame_count: real video requires at least two frames")
    for field in ("fps", "duration_seconds", "codec", "container", "audio_present"):
        if clip.get(field) is None or clip.get(field) == "":
            errors.append(f"{path}.{field}: unavailable values require explicit metadata")
    if clip["admission_status"] == "eligible":
        if clip["source_class"] not in ELIGIBLE_SOURCE_CLASSES:
            errors.append(f"{path}: eligible clip requires an eligible source class")
        if clip["rights_status"] != "admitted":
            errors.append(f"{path}: eligible clip requires admitted rights")
        if clip["consent_status"] not in {"verified", "not_required"}:
            errors.append(f"{path}: eligible clip requires resolved consent")
        if clip["sensitive_content_status"] not in {"none_observed", "reviewed_allowed"}:
            errors.append(f"{path}: eligible clip requires resolved sensitive-content review")
        if not is_sha256(clip["derivative_sha256"]) or not is_sha256(clip["oracle_sha256"]):
            errors.append(f"{path}: eligible clip requires derivative and oracle digests")
    errors.extend(public_sanitation_errors(clip))
    return errors


def validate_manifest(manifest: Any) -> list[str]:
    errors = validate_m1_schema(manifest, "m1-real-video-corpus-manifest.schema.json")
    errors.extend(require_keys(
        manifest,
        ("schema_version", "corpus_version", "minimum_eligible_clips", "required_scene_classes", "derivative_contract", "clips"),
        "$",
    ))
    if errors or not isinstance(manifest, dict):
        return errors
    if manifest["schema_version"] != "0.1.0":
        errors.append("$.schema_version: expected 0.1.0")
    if manifest["minimum_eligible_clips"] != 12:
        errors.append("$.minimum_eligible_clips: M1-A requires exactly 12 as the minimum")
    required_classes = manifest.get("required_scene_classes")
    if not isinstance(required_classes, list) or len(set(required_classes)) != 12:
        errors.append("$.required_scene_classes: exactly 12 unique required classes are expected")
    errors.extend(validate_derivative_contract(manifest.get("derivative_contract")))
    clips = manifest.get("clips")
    if not isinstance(clips, list):
        return errors + ["$.clips: expected array"]
    seen: set[str] = set()
    seen_original_digests: set[str] = set()
    for index, clip in enumerate(clips):
        errors.extend(validate_clip(clip, f"$.clips[{index}]"))
        if isinstance(clip, dict):
            clip_id = clip.get("clip_id")
            if clip_id in seen:
                errors.append(f"$.clips[{index}].clip_id: duplicate {clip_id}")
            seen.add(clip_id)
            digest = clip.get("original_sha256")
            if clip.get("admission_status") == "eligible" and digest in seen_original_digests:
                errors.append(f"$.clips[{index}].original_sha256: eligible clips must be distinct actual videos")
            if clip.get("admission_status") == "eligible":
                seen_original_digests.add(digest)
    errors.extend(public_sanitation_errors(manifest))
    return errors


def summarize_manifest(manifest: dict[str, Any], tracked_paths: Iterable[str] = ()) -> dict[str, Any]:
    errors = validate_manifest(manifest) + tracked_binary_errors(tracked_paths)
    clips = manifest.get("clips", [])
    eligible = [clip for clip in clips if clip.get("admission_status") == "eligible"]
    pending = [clip for clip in clips if clip.get("admission_status") == "pending"]
    rejected = [clip for clip in clips if clip.get("admission_status") == "rejected"]
    covered = sorted({scene for clip in eligible for scene in clip.get("scene_classes", [])})
    required = manifest.get("required_scene_classes", [])
    missing = [scene for scene in required if scene not in covered]
    return {
        "schema_version": "0.1.0",
        "valid": not errors,
        "errors": errors,
        "counts": {"investigated": len(clips), "eligible": len(eligible), "pending": len(pending), "rejected": len(rejected)},
        "minimum_eligible_clips": manifest.get("minimum_eligible_clips"),
        "covered_scene_classes": covered,
        "missing_scene_classes": missing,
        "binary_media_tracked": False if not tracked_binary_errors(tracked_paths) else True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--tracked-path", action="append", default=[])
    args = parser.parse_args()
    summary = summarize_manifest(load_json(args.manifest), args.tracked_path)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
