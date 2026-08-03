"""Prepare the local M1-A2 derivative and pending human-review package.

This module is deliberately model-free.  It never labels a transition as
verified, never invokes a backend, and never writes original video files.
Binary derivatives and review previews remain below the explicitly supplied
asset root; only sanitized metadata is exported to the repository.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .m1_corpus_summary import build_reports, tracked_paths, write_reports
from .m1_protocol import public_sanitation_errors, sha256_json


TARGET_WIDTH = 832
TARGET_HEIGHT = 480
TARGET_FPS = 16
FILTER_CHAIN = (
    "setpts=PTS-STARTPTS,"
    "scale=832:480:force_original_aspect_ratio=decrease:flags=lanczos:"
    "in_color_matrix=bt709:out_color_matrix=bt709,"
    "pad=832:480:(ow-iw)/2:(oh-ih)/2:color=black,"
    "setsar=1,fps=fps=16:round=down:start_time=0,format=yuv420p"
)
PUBLIC_COMMAND_TEMPLATE = (
    "<decoder> -i <original-input> -map 0:v:0 -an -vf <declared-filter-chain> "
    "-c:v ffv1 <analysis-output>"
)
LOCAL_DIRS = (
    "derivatives",
    "frame-maps",
    "inventory",
    "logs",
    "metadata",
    "receipts",
    "review-package",
    "verification",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"path escapes approved root: {path}")
    return resolved


def write_text_new(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json_new(path: Path, value: Any) -> None:
    write_text_new(path, canonical_json(value))


def run_checked(command: list[str], *, log_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if log_path is not None:
        write_text_new(log_path, completed.stderr)
    if completed.returncode:
        raise RuntimeError(
            f"command failed with exit {completed.returncode}: {Path(command[0]).name}\n{completed.stderr}"
        )
    return completed


def ffprobe_json(ffprobe: Path, media: Path, *, count_packets: bool = False) -> dict[str, Any]:
    command = [
        str(ffprobe), "-v", "error",
    ]
    if count_packets:
        command.append("-count_packets")
    command += [
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,codec_tag_string,width,height,pix_fmt,"
            "color_space,color_transfer,color_primaries,color_range,r_frame_rate,"
            "avg_frame_rate,nb_frames,nb_read_packets,start_time,duration:"
            "stream_side_data=rotation:format=format_name,start_time,duration,size"
        ),
        "-of", "json", str(media),
    ]
    return json.loads(run_checked(command).stdout)


def parse_fps(value: str) -> float:
    return float(Fraction(value))


def source_metadata(ffprobe: Path, source: Path) -> dict[str, Any]:
    payload = ffprobe_json(ffprobe, source)
    video = next(item for item in payload["streams"] if item.get("codec_type") == "video")
    audio_present = any(item.get("codec_type") == "audio" for item in payload["streams"])
    rotation = 0
    for item in video.get("side_data_list", []):
        if "rotation" in item:
            rotation = int(item["rotation"])
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": parse_fps(video["avg_frame_rate"]),
        "nominal_fps": video["r_frame_rate"],
        "frame_count": int(video["nb_frames"]),
        "duration_seconds": float(video.get("duration") or payload["format"]["duration"]),
        "codec": video["codec_name"],
        "codec_tag": video.get("codec_tag_string"),
        "container": payload["format"]["format_name"],
        "pixel_format": video.get("pix_fmt"),
        "color_space": video.get("color_space"),
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
        "color_range": video.get("color_range"),
        "rotation": rotation,
        "audio_present": audio_present,
        "bytes": int(payload["format"]["size"]),
    }


def derivative_metadata(ffprobe: Path, derivative: Path) -> dict[str, Any]:
    payload = ffprobe_json(ffprobe, derivative, count_packets=True)
    video = next(item for item in payload["streams"] if item.get("codec_type") == "video")
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": parse_fps(video["avg_frame_rate"]),
        "frame_count": int(video["nb_read_packets"]),
        "duration_seconds": float(payload["format"]["duration"]),
        "codec": video["codec_name"],
        "container": payload["format"]["format_name"],
        "pixel_format": video.get("pix_fmt"),
        "color_space": video.get("color_space"),
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
        "color_range": video.get("color_range"),
        "audio_present": any(item.get("codec_type") == "audio" for item in payload["streams"]),
        "bytes": int(payload["format"]["size"]),
    }


def derivative_command(ffmpeg: Path, source: Path, output: Path) -> list[str]:
    return [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-i", str(source), "-map", "0:v:0", "-an",
        "-vf", FILTER_CHAIN, "-c:v", "ffv1", "-level", "3", "-coder", "1",
        "-context", "1", "-g", "1", "-slices", "4", "-slicecrc", "1",
        "-threads", "1", "-flags:v", "+bitexact", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-fps_mode", "passthrough", "-fflags", "+bitexact",
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-metadata:s:v:0", "rotate=0", "-f", "matroska", str(output),
    ]


def source_timestamps(ffprobe: Path, source: Path) -> list[float]:
    command = [
        str(ffprobe), "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(source),
    ]
    payload = json.loads(run_checked(command).stdout)
    timestamps = frame_timestamps_from_payload(payload)
    if not timestamps or timestamps != sorted(timestamps):
        raise ValueError(f"source frame timestamps are missing or non-monotonic: {source.name}")
    return timestamps


def frame_timestamps_from_payload(payload: dict[str, Any]) -> list[float]:
    return [
        float(frame["best_effort_timestamp_time"])
        for frame in payload.get("frames", [])
        if isinstance(frame, dict) and "best_effort_timestamp_time" in frame
    ]


def frame_mapping(clip_id: str, timestamps: list[float], output_frames: int) -> dict[str, Any]:
    mappings = []
    for output_index in range(output_frames):
        output_time = output_index / TARGET_FPS
        source_index = max(0, bisect.bisect_right(timestamps, output_time + 1e-12) - 1)
        mappings.append(
            {
                "derivative_frame_index": output_index,
                "derivative_timestamp_seconds": output_time,
                "source_frame_index": source_index,
                "source_timestamp_seconds": timestamps[source_index],
            }
        )
    return {
        "schema_version": "0.1.0",
        "clip_id": clip_id,
        "sampling_policy": "constant 16 FPS using the nearest prior source timestamp",
        "source_frame_count": len(timestamps),
        "derivative_frame_count": output_frames,
        "mappings": mappings,
    }


def pending(value_reason: str, method: str) -> dict[str, Any]:
    return {"value": None, "status": "pending", "reason": value_reason, "method": method}


def build_oracle(clip: dict[str, Any], derivative_hash: str, frame_count: int) -> dict[str, Any]:
    semantic_payload = {
        "workflow_status": "pending_review",
        "label": "full_canvas_uncertain_scaffold",
        "reason": "No automated signal is promoted to a human-verified oracle label.",
    }
    semantic_ref = "pending-full-canvas-uncertain"
    semantic_hash = sha256_json(semantic_payload)
    transitions = []
    for frame in range(frame_count - 1):
        transitions.append(
            {
                "transition_id": f"{clip['clip_id']}-t{frame:04d}",
                "frame_interval": [frame, frame + 1],
                "scene_cut": False,
                "camera_motion": "uncertain",
                "full_reobserve": False,
                "invalidated_object_ids": [],
                "regions": [
                    {
                        "region_id": f"{clip['clip_id']}-t{frame:04d}-uncertain",
                        "state": "uncertain",
                        "geometry": {"type": "bbox", "xywh": [0, 0, TARGET_WIDTH, TARGET_HEIGHT]},
                        "object_ids": [],
                        "change_causes": [],
                        "confidence": 0.0,
                        "semantic_ref": semantic_ref,
                        "semantic_hash": semantic_hash,
                    }
                ],
            }
        )
    annotation = {
        "clip_id": clip["clip_id"],
        "source_sha256": clip["original_sha256"],
        "derivative_sha256": derivative_hash,
        "canvas": [TARGET_WIDTH, TARGET_HEIGHT],
        "frame_count": frame_count,
        "object_catalog": [],
        "semantic_payloads": {semantic_ref: semantic_payload},
        "transitions": transitions,
        "annotation_provenance": "Deterministic uncertainty scaffold prepared without a model or promoted automatic labels.",
        "annotation_method": "Every adjacent-frame transition starts as full-canvas uncertain pending human review.",
        "review_protocol": "time_separated_blind_self_review",
        "review_status": "pending",
        "confidence": 0.0,
        "disagreement": [],
    }
    annotation["artifact_digest"] = sha256_json(annotation)
    return annotation


def evidence_digest(config: dict[str, Any], clip_id: str) -> str:
    evidence = {
        "capture_log_sha256": config["rights_evidence"]["capture_log_sha256"],
        "rights_declaration_sha256": config["rights_evidence"]["rights_declaration_sha256"],
    }
    if clip_id == "c01":
        evidence["c01_consent_sha256"] = config["rights_evidence"]["c01_consent_sha256"]
    return sha256_json(evidence)


def build_rights_receipt(config: dict[str, Any], clip: dict[str, Any]) -> dict[str, Any]:
    consent_status = "verified" if clip["consent_required_declared"] else "not_required"
    consent_basis = (
        "Explicit C01 self-consent evidence is present; final visual review remains pending."
        if clip["clip_id"] == "c01"
        else "Capture declaration reports no third-party identifiable person; final visual review remains pending."
    )
    return {
        "clip_id": clip["clip_id"],
        "original_sha256": clip["original_sha256"],
        "source_class": "pending_rights_review",
        "rights_basis": "Self-recorded rights declaration and capture log pending final human visual review.",
        "rights_holder": "declared self-recording rights holder",
        "license_identifier": "hiveframe-m1-a2-self-recorded-declaration-2026-08-03",
        "official_source_reference": f"approved-asset:m1-a2/{clip['clip_id']}",
        "terms_digest": config["rights_evidence"]["rights_declaration_sha256"],
        "attribution_obligation": {"required": False, "text": "No attribution required by the recorded declaration."},
        "permissions": {"research": True, "commercial": True, "copy": True, "derivative": True, "redistribution": True},
        "identifiable_people": clip["identifiable_people_declared"],
        "consent_basis": consent_basis,
        "consent_status": consent_status,
        "restrictions": [
            "No external analysis-service transfer.",
            "Public distribution of original video requires separate approval.",
        ],
        "review_status": "pending",
        "reviewed_at": pending("Human visual rights review has not completed.", "M1-A2 review package"),
        "review_method": "Evidence structure check plus pending human visual and oracle review.",
        "evidence_digest": evidence_digest(config, clip["clip_id"]),
    }


def build_manifest_clip(
    config: dict[str, Any],
    clip: dict[str, Any],
    source: dict[str, Any],
    derivative_hash: str,
    oracle_digest: str,
) -> dict[str, Any]:
    return {
        "clip_id": clip["clip_id"],
        "neutral_description": clip["neutral_description"],
        "scene_classes": [clip["scene_class"]],
        "stress_labels": clip["stress_labels"],
        "source_class": "pending_rights_review",
        "source_provenance": "Direct self-recording declared in the approved M1-A2 evidence bundle.",
        "rights_status": "pending",
        "rights_holder": "declared self-recording rights holder",
        "source_authority": "declared self-recording owner",
        "license_identifier": "hiveframe-m1-a2-self-recorded-declaration-2026-08-03",
        "license_terms_digest": config["rights_evidence"]["rights_declaration_sha256"],
        "attribution_required": False,
        "attribution_text": "No attribution required by the recorded declaration.",
        "permissions": {"research": True, "commercial": True, "copy": True, "derivative": True, "redistribution": True},
        "identifiable_people": clip["identifiable_people_declared"],
        "consent_required": clip["consent_required_declared"],
        "consent_status": "verified" if clip["consent_required_declared"] else "not_required",
        "sensitive_content_status": "pending",
        "original_sha256": clip["original_sha256"],
        "original_bytes": source["bytes"],
        "width": source["width"],
        "height": source["height"],
        "fps": source["fps"],
        "frame_count": source["frame_count"],
        "duration_seconds": source["duration_seconds"],
        "codec": source["codec"],
        "container": source["container"],
        "audio_present": source["audio_present"],
        "derivative_sha256": derivative_hash,
        "oracle_sha256": oracle_digest,
        "storage_class": "local_approved_artifact_store",
        "storage_reference": f"approved-asset:m1-a2/originals/{clip['clip_id']}",
        "admission_status": "pending",
        "rejection_reason": pending(
            "Human visual rights and oracle review has not completed.",
            "M1-A2 review package",
        ),
        "reviewed_at": pending("Human review has not completed.", "M1-A2 review package"),
        "review_method": "Deterministic derivative prepared; human rights, scene, privacy, and oracle review pending.",
        "evidence_notes": [
            "Original and derivative binaries remain outside Git.",
            "Scene class is a recording intent until human review confirms coverage.",
            "Automatic oracle promotion was not used.",
        ],
    }


def verify_tool(config: dict[str, Any], ffmpeg: Path, ffprobe: Path, asset_root: Path) -> dict[str, Any]:
    ensure_within(ffmpeg, asset_root)
    ensure_within(ffprobe, asset_root)
    if sha256_file(ffmpeg) != config["tooling"]["ffmpeg_sha256"]:
        raise ValueError("ffmpeg executable digest mismatch")
    if sha256_file(ffprobe) != config["tooling"]["ffprobe_sha256"]:
        raise ValueError("ffprobe executable digest mismatch")
    ffmpeg_line = run_checked([str(ffmpeg), "-version"]).stdout.splitlines()[0]
    ffprobe_line = run_checked([str(ffprobe), "-version"]).stdout.splitlines()[0]
    if not ffmpeg_line.startswith("ffmpeg version 7.1.1"):
        raise ValueError(f"unexpected ffmpeg version: {ffmpeg_line}")
    if not ffprobe_line.startswith("ffprobe version 7.1.1"):
        raise ValueError(f"unexpected ffprobe version: {ffprobe_line}")
    return {"ffmpeg_version": ffmpeg_line, "ffprobe_version": ffprobe_line}


def verify_evidence(config: dict[str, Any], asset_root: Path) -> None:
    evidence_paths = {
        "capture_log_sha256": asset_root / "notes" / "capture-log.txt",
        "rights_declaration_sha256": asset_root / "notes" / "rights-declaration.txt",
        "c01_consent_sha256": asset_root / "consent" / "C01_self_consent.txt",
    }
    for key, path in evidence_paths.items():
        ensure_within(path, asset_root)
        if not path.is_file() or sha256_file(path) != config["rights_evidence"][key]:
            raise ValueError(f"rights evidence missing or changed: {key}")


def make_contact_sheet(ffmpeg: Path, derivative: Path, frame_count: int, output: Path) -> None:
    indices = sorted({round(index * (frame_count - 1) / 15) for index in range(16)})
    select_expr = "+".join(f"eq(n\\,{index})" for index in indices)
    filter_chain = (
        f"select='{select_expr}',"
        "scale=208:120:force_original_aspect_ratio=decrease:flags=lanczos,"
        "pad=208:120:(ow-iw)/2:(oh-ih)/2:black,tile=4x4"
    )
    run_checked(
        [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-i", str(derivative), "-vf", filter_chain, "-frames:v", "1",
            "-compression_level", "9", str(output),
        ]
    )


def review_instructions() -> str:
    return """# M1-A2 Human Review Package

Status: **pending_review**

No oracle label in this package is verified. Every adjacent-frame transition is
initialized as full-canvas `uncertain`. Automated frame difference, optical
flow, model inference, and topology measurement were not used.

For each clip:

1. Confirm that the intended scene class is actually present.
2. Check for third-party faces, voices, screens, documents, addresses, vehicle
   identifiers, logos, artwork, music, and other rights or privacy concerns.
3. Confirm source-to-derivative orientation, complete duration, 832x480 canvas,
   16 FPS frame mapping, letterbox, and absence of unintended crop.
4. Review every adjacent-frame transition and replace the uncertainty scaffold
   with a complete non-overlapping `dirty`/`stable`/`uncertain` partition.
5. Add `preserve` only as an orthogonal policy label; it may overlap stable but
   never dirty or uncertain.
6. For C07, identify the exact hard-cut transition, mark the full canvas dirty,
   set `scene_cut=true` and `full_reobserve=true`, and invalidate prior objects.
7. Record object identities and change causes only when visually supported.
8. Perform a time-separated blind second review, record disagreements, and
   adjudicate before changing `review_status` from `pending` to `verified`.

Do not mark `M1_CORPUS_AND_ORACLE_READY` until all twelve clips, rights records,
privacy checks, scene coverage, annotations, and validator results pass after
human review.
"""


def collision_paths(asset_root: Path, public_dir: Path, report_dir: Path) -> list[str]:
    collisions = []
    for name in LOCAL_DIRS:
        path = asset_root / name
        if path.exists():
            collisions.append(str(path))
    if public_dir.exists():
        collisions.append(str(public_dir))
    if report_dir.exists():
        collisions.append(str(report_dir))
    return collisions


def plan(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_started": False,
        "run_id": config["run_id"],
        "original_count": len(config["clips"]),
        "target_resolution": [TARGET_WIDTH, TARGET_HEIGHT],
        "target_fps": TARGET_FPS,
        "decoder_version": config["tooling"]["version"],
        "output_representation": "lossless_ffv1_mkv_analysis_derivative",
        "determinism_check": "two independent encodes must have identical SHA-256",
        "oracle_workflow_status": "pending_review",
        "model_loads": 0,
        "cuda_runs": 0,
        "topology_performance_runs": 0,
    }


def prepare(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    asset_root = Path(args.asset_root).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    public_dir = Path(args.public_output_dir).resolve()
    report_dir = Path(args.report_output_dir).resolve()
    ffmpeg = Path(args.ffmpeg).resolve()
    ffprobe = Path(args.ffprobe).resolve()
    ensure_within(asset_root, asset_root)
    if collisions := collision_paths(asset_root, public_dir, report_dir):
        raise FileExistsError(f"refusing to overwrite existing M1-A2 outputs: {collisions}")
    verify_evidence(config, asset_root)
    versions = verify_tool(config, ffmpeg, ffprobe, asset_root)
    for name in LOCAL_DIRS:
        (asset_root / name).mkdir(parents=True, exist_ok=False)

    license_path = asset_root / "tools" / "ffmpeg-7.1.1" / "LICENSE"
    install_receipt = {
        "schema_version": "0.1.0",
        "source_url": config["tooling"]["source_url"],
        "archive_path": str(asset_root / "tools" / "downloads" / "ffmpeg-7.1.1-essentials_build.zip"),
        "archive_sha256": config["tooling"]["archive_sha256"],
        "ffmpeg_path": str(ffmpeg),
        "ffmpeg_sha256": sha256_file(ffmpeg),
        "ffprobe_path": str(ffprobe),
        "ffprobe_sha256": sha256_file(ffprobe),
        "license_path": str(license_path),
        "license_sha256": sha256_file(license_path),
        "license": config["tooling"]["license"],
        "versions": versions,
        "system_path_modified": False,
        "administrator_privileges_used": False,
    }
    write_json_new(asset_root / "receipts" / "ffmpeg-install-receipt.json", install_receipt)

    inventory: list[dict[str, Any]] = []
    derivative_receipts: list[dict[str, Any]] = []
    frame_map_index: list[dict[str, Any]] = []
    oracle_annotations: list[dict[str, Any]] = []
    manifest_clips: list[dict[str, Any]] = []
    rights_receipts: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for clip in config["clips"]:
        clip_id = clip["clip_id"]
        source_path = ensure_within(asset_root / "originals" / clip["file_name"], asset_root)
        if not source_path.is_file() or sha256_file(source_path) != clip["original_sha256"]:
            raise ValueError(f"original missing or changed: {clip_id}")
        source = source_metadata(ffprobe, source_path)
        if (
            source["width"] != 1920
            or source["height"] != 1080
            or source["codec"] != "h264"
            or source["pixel_format"] != "yuv420p"
            or source["color_space"] != "bt709"
            or source["rotation"] not in {0, 90, -90, 180, -180}
        ):
            raise ValueError(f"source metadata contract mismatch: {clip_id}: {source}")

        derivative_path = asset_root / "derivatives" / f"{clip_id}-analysis-832x480-16fps-ffv1.mkv"
        verification_path = asset_root / "verification" / f"{clip_id}-repeat.mkv"
        log_path = asset_root / "logs" / f"{clip_id}-ffmpeg.log"
        run_checked(derivative_command(ffmpeg, source_path, derivative_path), log_path=log_path)
        run_checked(derivative_command(ffmpeg, source_path, verification_path))
        derivative_hash = sha256_file(derivative_path)
        verification_hash = sha256_file(verification_path)
        if derivative_hash != verification_hash:
            raise ValueError(f"deterministic repeat mismatch: {clip_id}")
        verification_path.unlink()

        derivative = derivative_metadata(ffprobe, derivative_path)
        if (
            derivative["width"] != TARGET_WIDTH
            or derivative["height"] != TARGET_HEIGHT
            or abs(derivative["fps"] - TARGET_FPS) > 1e-9
            or derivative["codec"] != "ffv1"
            or derivative["pixel_format"] != "yuv420p"
            or derivative["color_space"] != "bt709"
            or derivative["audio_present"]
        ):
            raise ValueError(f"derivative metadata contract mismatch: {clip_id}: {derivative}")
        run_checked(
            [
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin",
                "-i", str(derivative_path), "-map", "0:v:0", "-f", "null", os.devnull,
            ]
        )

        timestamps = source_timestamps(ffprobe, source_path)
        if len(timestamps) != source["frame_count"]:
            raise ValueError(f"source timestamp count mismatch: {clip_id}")
        mapping = frame_mapping(clip_id, timestamps, derivative["frame_count"])
        frame_map_path = asset_root / "frame-maps" / f"{clip_id}-frame-map.json"
        write_json_new(frame_map_path, mapping)
        mapping_hash = sha256_file(frame_map_path)

        oracle = build_oracle(clip, derivative_hash, derivative["frame_count"])
        oracle_annotations.append(oracle)
        oracle_path = asset_root / "metadata" / f"{clip_id}-oracle-pending.json"
        write_json_new(
            oracle_path,
            {"schema_version": "0.1.0", "annotation_version": "m1-a2-pending-v0", "annotations": [oracle]},
        )

        preview_path = asset_root / "review-package" / "contact-sheets" / f"{clip_id}-contact-sheet.png"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        make_contact_sheet(ffmpeg, derivative_path, derivative["frame_count"], preview_path)

        inventory.append(
            {
                "clip_id": clip_id,
                "file_name": clip["file_name"],
                "original_sha256": clip["original_sha256"],
                "scene_class_expected": clip["scene_class"],
                "scene_coverage_status": "pending_review",
                "metadata": source,
            }
        )
        receipt = {
            "clip_id": clip_id,
            "source_sha256": clip["original_sha256"],
            "derivative_sha256": derivative_hash,
            "derivative_bytes": derivative["bytes"],
            "derivative_metadata": derivative,
            "frame_mapping_sha256": mapping_hash,
            "contact_sheet_sha256": sha256_file(preview_path),
            "command_template": PUBLIC_COMMAND_TEMPLATE,
            "declared_filter_chain": FILTER_CHAIN,
            "deterministic_repeat_sha256": verification_hash,
            "deterministic_repeat_match": True,
            "decode_validation": "passed",
            "verification_temporary_removed": True,
        }
        derivative_receipts.append(receipt)
        frame_map_index.append(
            {
                "clip_id": clip_id,
                "frame_mapping_sha256": mapping_hash,
                "source_frame_count": len(timestamps),
                "derivative_frame_count": derivative["frame_count"],
            }
        )
        rights_receipt = build_rights_receipt(config, clip)
        rights_receipts.append(rights_receipt)
        manifest_clips.append(
            build_manifest_clip(config, clip, source, derivative_hash, oracle["artifact_digest"])
        )
        review_rows.append(
            {
                "clip_id": clip_id,
                "expected_scene_class": clip["scene_class"],
                "rights_review": "pending_review",
                "scene_content_review": "pending_review",
                "privacy_review": "pending_review",
                "oracle_initial_pass": "pending_review",
                "blind_re_review": "pending_review",
                "adjudication": "pending_review",
                "final_status": "pending_review",
            }
        )

    if any(asset_root.joinpath("originals", clip["file_name"]).stat().st_size != item["metadata"]["bytes"] for clip, item in zip(config["clips"], inventory)):
        raise ValueError("original size changed during preparation")
    for clip in config["clips"]:
        source = asset_root / "originals" / clip["file_name"]
        if sha256_file(source) != clip["original_sha256"]:
            raise ValueError(f"original digest changed during preparation: {clip['clip_id']}")

    corpus_base = json.loads((repo_root / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))
    manifest = {**corpus_base, "corpus_version": "m1-a2-pending-review-v0", "clips": manifest_clips}
    rights = {"schema_version": "0.1.0", "receipts": rights_receipts}
    oracle_document = {
        "schema_version": "0.1.0",
        "annotation_version": "m1-a2-pending-v0",
        "annotations": oracle_annotations,
    }
    oracle_index = {
        "schema_version": "0.1.0",
        "review_workflow_status": "pending_review",
        "verified_annotations": 0,
        "annotations": [
            {
                "clip_id": item["clip_id"],
                "review_status": item["review_status"],
                "artifact_digest": item["artifact_digest"],
                "frame_count": item["frame_count"],
                "derivative_sha256": item["derivative_sha256"],
            }
            for item in oracle_annotations
        ],
    }
    public_install = {
        "schema_version": "0.1.0",
        "distribution": config["tooling"]["distribution"],
        "official_download_page": config["tooling"]["official_download_page"],
        "distribution_page": config["tooling"]["distribution_page"],
        "source_url": config["tooling"]["source_url"],
        "archive_bytes": config["tooling"]["archive_bytes"],
        "archive_sha256": config["tooling"]["archive_sha256"],
        "ffmpeg_sha256": config["tooling"]["ffmpeg_sha256"],
        "ffprobe_sha256": config["tooling"]["ffprobe_sha256"],
        "ffmpeg_version_line": config["tooling"]["ffmpeg_version_line"],
        "ffprobe_version_line": config["tooling"]["ffprobe_version_line"],
        "license": config["tooling"]["license"],
        "license_sha256": config["tooling"]["license_sha256"],
        "install_reference": "approved-asset:m1-a2/tools/ffmpeg-7.1.1",
        "system_path_modified": False,
        "administrator_privileges_used": False,
    }
    derivative_document = {
        "schema_version": "0.1.0",
        "run_id": config["run_id"],
        "run_kind": "m1_a2_deterministic_analysis_derivative",
        "tool_version": "ffmpeg-7.1.1",
        "results_eligible_for_topology_performance": False,
        "receipts": derivative_receipts,
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
    original_inventory = {
        "schema_version": "0.1.0",
        "run_id": config["run_id"],
        "original_immutable": True,
        "original_count": len(inventory),
        "duplicate_sha256_count": len(inventory) - len({item["original_sha256"] for item in inventory}),
        "clips": inventory,
    }
    for value in (manifest, rights, oracle_index, public_install, derivative_document, original_inventory):
        errors = public_sanitation_errors(value)
        if errors:
            raise ValueError(f"public sanitation failed: {errors}")

    write_json_new(asset_root / "inventory" / "original-inventory.json", original_inventory)
    write_json_new(asset_root / "receipts" / "derivative-receipts.json", derivative_document)
    write_json_new(asset_root / "receipts" / "frame-map-index.json", {"schema_version": "0.1.0", "clips": frame_map_index})
    write_json_new(asset_root / "metadata" / "corpus-manifest.pending.json", manifest)
    write_json_new(asset_root / "metadata" / "rights-receipts.pending.json", rights)
    write_json_new(asset_root / "metadata" / "oracle-annotations.pending.json", oracle_document)
    write_json_new(asset_root / "review-package" / "index.json", oracle_index)
    write_text_new(asset_root / "review-package" / "REVIEW_INSTRUCTIONS.md", review_instructions())
    checklist = asset_root / "review-package" / "review-checklist.csv"
    if checklist.exists():
        raise FileExistsError(f"refusing to overwrite {checklist}")
    with checklist.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)

    public_dir.mkdir(parents=True, exist_ok=False)
    write_json_new(public_dir / "original-inventory.json", original_inventory)
    write_json_new(public_dir / "ffmpeg-install-record.json", public_install)
    write_json_new(public_dir / "derivative-receipts.json", derivative_document)
    write_json_new(public_dir / "corpus-manifest.pending.json", manifest)
    write_json_new(public_dir / "rights-receipts.pending.json", rights)
    write_json_new(public_dir / "oracle-index.pending.json", oracle_index)

    reports = build_reports(
        manifest,
        rights,
        oracle_document,
        json.loads((repo_root / "configs" / "m1-topology-candidates.json").read_text(encoding="utf-8")),
        json.loads((repo_root / "configs" / "m1-measurement-contract.json").read_text(encoding="utf-8")),
        tracked_paths(repo_root),
    )
    admission = json.loads(reports["admission-report.json"])
    if admission["decision"] == "M1_CORPUS_AND_ORACLE_READY":
        raise ValueError("pending human review must not produce M1_CORPUS_AND_ORACLE_READY")
    write_reports(report_dir, reports)
    write_json_new(asset_root / "review-package" / "gate-report.json", admission)
    (asset_root / "verification").rmdir()

    return {
        "run_id": config["run_id"],
        "originals_verified_unchanged": len(inventory),
        "derivatives_created": len(derivative_receipts),
        "deterministic_repeat_matches": sum(item["deterministic_repeat_match"] for item in derivative_receipts),
        "oracle_verified": 0,
        "oracle_pending": len(oracle_annotations),
        "gate": admission["decision"],
        "human_review_required": True,
        "topology_performance_runs": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--public-output-dir", type=Path, required=True)
    parser.add_argument("--report-output-dir", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.plan:
        print(canonical_json(plan(config)), end="")
        return 0
    print(canonical_json(prepare(args, config)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
