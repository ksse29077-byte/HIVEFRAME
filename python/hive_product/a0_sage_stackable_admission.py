"""Offline A0 admission for immutable F0 Standard/SageAttention artifacts.

The module never starts ComfyUI or a model. Private paths, per-frame metrics,
prompts, media, and full manifests stay in the caller-supplied external root.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
import argparse
import heapq
import json
import math


@dataclass(frozen=True)
class ArtifactSet:
    standard_video: Path
    sage_video: Path
    historical_contact_sheet: Path
    historical_side_by_side: Path
    provenance: dict[str, Any]


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_file_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    actual = _hash_file(path)
    if actual != expected:
        raise ValueError(f"{label} SHA-256 mismatch")


def _metric_value(receipt: Mapping[str, Any], field: str) -> float:
    metrics = receipt.get("metrics")
    value = metrics.get(field) if isinstance(metrics, Mapping) else None
    if isinstance(value, Mapping):
        value = value.get("value")
    if not isinstance(value, (int, float)):
        raise ValueError(f"receipt metric {field} is unavailable")
    return float(value)


def validate_f0_artifacts(
    *,
    config: Mapping[str, Any],
    standard_summary_path: Path,
    sage_summary_path: Path,
    pair_manifest_path: Path,
) -> ArtifactSet:
    """Validate existing private artifacts without returning public paths."""
    historical = config["historical_f0"]
    expected_output = config["fixed_output_contract"]
    standard = _load_object(standard_summary_path)
    sage = _load_object(sage_summary_path)
    pair = _load_object(pair_manifest_path)

    for summary, mode, run_id, digest in (
        (standard, "standard", historical["standard_run_id"], historical["standard_output_sha256"]),
        (sage, "sage-auto", historical["sage_run_id"], historical["sage_output_sha256"]),
    ):
        if summary.get("mode") != mode or summary.get("run_id") != run_id:
            raise ValueError(f"{mode} run provenance mismatch")
        if summary.get("terminal_status") != "succeeded" or summary.get("retry_count") != 0:
            raise ValueError(f"{mode} run is not a successful retry-zero artifact")
        result = summary.get("result")
        receipt = summary.get("receipt")
        integrity = summary.get("integrity")
        if not all(isinstance(item, Mapping) for item in (result, receipt, integrity)):
            raise ValueError(f"{mode} summary is incomplete")
        if result.get("sha256") != digest or receipt.get("output_sha256") != digest:
            raise ValueError(f"{mode} recorded output hash mismatch")
        if receipt.get("workflow_sha256") != historical["workflow_sha256"]:
            raise ValueError(f"{mode} workflow hash mismatch")
        for field in ("width", "height", "decoded_frame_count", "black_frame_count", "corrupted_frame_count"):
            if integrity.get(field) != expected_output[field]:
                raise ValueError(f"{mode} integrity field {field} mismatch")
        if float(integrity.get("fps", -1)) != float(expected_output["fps"]):
            raise ValueError(f"{mode} FPS mismatch")
        if integrity.get("codec") != expected_output["codec"]:
            raise ValueError(f"{mode} codec mismatch")
        if int(integrity.get("audio_stream_count", 0)) < int(expected_output["minimum_audio_stream_count"]):
            raise ValueError(f"{mode} native audio is missing")

    if pair.get("schema_version") != "f0.sage.comparison.private.1":
        raise ValueError("pair manifest schema mismatch")
    if pair.get("standard_run_id") != historical["standard_run_id"] or pair.get("sage_run_id") != historical["sage_run_id"]:
        raise ValueError("pair run mapping mismatch")
    if pair.get("fixed_profile_match") is not True or pair.get("prompt_hash_match") is not True:
        raise ValueError("pair profile or prompt hash does not match")

    runtime_checks = {
        "standard_submit_to_terminal_seconds": _metric_value(standard["receipt"], "total_wall_seconds"),
        "sage_submit_to_terminal_seconds": _metric_value(sage["receipt"], "total_wall_seconds"),
        "standard_runner_total_seconds": float(standard["phase_metrics"]["runner_total_seconds"]["value"]),
        "sage_runner_total_seconds": float(sage["phase_metrics"]["runner_total_seconds"]["value"]),
    }
    for key, actual in runtime_checks.items():
        if not math.isclose(actual, float(historical[key]), rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(f"historical runtime field {key} mismatch")

    standard_video = Path(str(standard["result"]["private_path"]))
    sage_video = Path(str(sage["result"]["private_path"]))
    contact = pair.get("contact_sheet")
    side = pair.get("side_by_side_preview")
    if not isinstance(contact, Mapping) or not isinstance(side, Mapping):
        raise ValueError("historical review artifacts are not declared")
    contact_path = Path(str(contact.get("path", "")))
    side_path = Path(str(side.get("path", "")))
    _require_file_hash(standard_video, historical["standard_output_sha256"], "Standard video")
    _require_file_hash(sage_video, historical["sage_output_sha256"], "Sage video")
    _require_file_hash(contact_path, historical["contact_sheet_sha256"], "historical contact sheet")
    _require_file_hash(side_path, historical["side_by_side_sha256"], "historical side-by-side")
    return ArtifactSet(
        standard_video=standard_video,
        sage_video=sage_video,
        historical_contact_sheet=contact_path,
        historical_side_by_side=side_path,
        provenance={
            "status": "F0_ARTIFACTS_REUSED",
            "standard_run_id": historical["standard_run_id"],
            "sage_run_id": historical["sage_run_id"],
            "workflow_sha256": historical["workflow_sha256"],
            "standard_output_sha256": historical["standard_output_sha256"],
            "sage_output_sha256": historical["sage_output_sha256"],
            "historical_contact_sheet_sha256": historical["contact_sheet_sha256"],
            "historical_side_by_side_sha256": historical["side_by_side_sha256"],
            "new_generation_count": 0,
            "retry_count": 0,
        },
    )


def _frame_ssim(a: Any, b: Any, np: Any) -> float:
    mean_a = float(np.mean(a))
    mean_b = float(np.mean(b))
    centered_a = a - mean_a
    centered_b = b - mean_b
    variance_a = float(np.mean(centered_a * centered_a))
    variance_b = float(np.mean(centered_b * centered_b))
    covariance = float(np.mean(centered_a * centered_b))
    c1 = (0.01 * 255.0) ** 2
    c2 = (0.03 * 255.0) ** 2
    denominator = (mean_a * mean_a + mean_b * mean_b + c1) * (variance_a + variance_b + c2)
    return ((2 * mean_a * mean_b + c1) * (2 * covariance + c2) / denominator) if denominator else 1.0


def _ratio(value: float, reference: float) -> float | None:
    return value / reference if reference > 0 else None


def _within(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def automatic_screen(metrics: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    integrity_passed = bool(metrics.get("output_integrity_passed"))
    checks = {
        "output_integrity": integrity_passed,
        "normalized_mae": float(metrics["normalized_mae"]) <= float(gate["normalized_mae_max"]),
        "motion_energy_ratio": _within(
            metrics.get("motion_energy_ratio"),
            float(gate["motion_energy_ratio_min"]),
            float(gate["motion_energy_ratio_max"]),
        ),
        "spatial_gradient_energy_ratio": _within(
            metrics.get("spatial_gradient_energy_ratio"),
            float(gate["spatial_gradient_energy_ratio_min"]),
            float(gate["spatial_gradient_energy_ratio_max"]),
        ),
        "temporal_difference_energy_ratio": _within(
            metrics.get("temporal_difference_energy_ratio"),
            float(gate["temporal_difference_energy_ratio_min"]),
            float(gate["temporal_difference_energy_ratio_max"]),
        ),
    }
    return {
        "status": "AUTOMATIC_REGRESSION_SCREEN_PASSED" if all(checks.values()) else "AUTOMATIC_REGRESSION_SCREEN_FAILED",
        "checks": checks,
        "passed": all(checks.values()),
        "ssim_role": "pair_similarity_diagnostic_only",
        "quality_at_least_standard_proven": False,
        "visual_equivalence": "not_proven",
        "human_visual_review": "required",
    }


def decide(*, artifacts_valid: bool, runtime_positive: bool, screen_passed: bool, config: Mapping[str, Any]) -> dict[str, Any]:
    decisions = config["decisions"]
    component = config["component_contract"]
    if not artifacts_valid:
        decision = decisions["runtime_rejected"]
        disposition = "FALLBACK_ONLY"
        status = "UNAVAILABLE"
    elif not runtime_positive:
        decision = decisions["current_environment_no_gain"]
        disposition = "FALLBACK_ONLY"
        status = "UNAVAILABLE_CURRENT_ENVIRONMENT"
    elif not screen_passed:
        decision = decisions["automatic_quality_fail"]
        disposition = "KEEP_AS_OPTIONAL_EVIDENCE"
        status = "EVIDENCE_ONLY"
    else:
        decision = decisions["automatic_pass"]
        disposition = component["success_disposition"]
        status = component["success_status"]
    return {
        "decision": decision,
        "disposition": disposition,
        "component_status": status,
        "product_default": False,
        "product_promotion": 0,
        "final_cumulative_two_x_goal_reached": False,
        "standard_full_compute_fallback": "preserved",
        "human_visual_review": "PENDING_HUMAN_REVIEW" if screen_passed else "not_started",
    }


def _selected_review_indices(fixed: Iterable[int], motion_candidates: Iterable[tuple[float, int]], limit: int) -> list[int]:
    selected = set(int(value) for value in fixed)
    for _, index in sorted(motion_candidates, reverse=True):
        if index not in selected:
            selected.add(index)
            limit -= 1
            if limit == 0:
                break
    return sorted(selected)


def compare_videos(artifacts: ArtifactSet, *, output_root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    try:
        import av
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("PyAV, NumPy, and Pillow are required for A0 offline analysis") from error

    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError("private A0 output root already contains artifacts")
    output_root.mkdir(parents=True, exist_ok=True)
    ssim_values: list[float] = []
    mae_values: list[float] = []
    standard_motion_squared: list[float] = []
    sage_motion_squared: list[float] = []
    standard_temporal_absolute: list[float] = []
    sage_temporal_absolute: list[float] = []
    standard_gradients: list[float] = []
    sage_gradients: list[float] = []
    black_counts = {"standard": 0, "sage": 0}
    fixed = set(int(value) for value in config["visual_review"]["fixed_frame_indices"])
    fixed_frames: dict[int, tuple[Any, Any]] = {}
    motion_heap: list[tuple[float, int, Any, Any]] = []
    previous_standard = previous_sage = None
    standard_stream_info: dict[str, Any] = {}
    sage_stream_info: dict[str, Any] = {}

    with av.open(str(artifacts.standard_video)) as standard_container, av.open(str(artifacts.sage_video)) as sage_container:
        standard_stream = standard_container.streams.video[0]
        sage_stream = sage_container.streams.video[0]
        standard_stream_info = {
            "codec": standard_stream.codec_context.name,
            "fps": float(standard_stream.average_rate),
            "audio_stream_count": len(list(standard_container.streams.audio)),
        }
        sage_stream_info = {
            "codec": sage_stream.codec_context.name,
            "fps": float(sage_stream.average_rate),
            "audio_stream_count": len(list(sage_container.streams.audio)),
        }
        standard_frames = standard_container.decode(video=0)
        sage_frames = sage_container.decode(video=0)
        index = 0
        while True:
            left = next(standard_frames, None)
            right = next(sage_frames, None)
            if left is None or right is None:
                if left is not None or right is not None:
                    raise RuntimeError("Standard and Sage decoded frame counts differ")
                break
            left_rgb = left.to_ndarray(format="rgb24")
            right_rgb = right.to_ndarray(format="rgb24")
            if left_rgb.shape != right_rgb.shape:
                raise RuntimeError("Standard and Sage frame shapes differ")
            a = left.to_ndarray(format="gray").astype(np.float64)
            b = right.to_ndarray(format="gray").astype(np.float64)
            ssim_values.append(_frame_ssim(a, b, np))
            mae_values.append(float(np.mean(np.abs(a - b))) / 255.0)
            standard_gradients.append(float(np.mean(np.abs(np.diff(a, axis=0)))) + float(np.mean(np.abs(np.diff(a, axis=1)))))
            sage_gradients.append(float(np.mean(np.abs(np.diff(b, axis=0)))) + float(np.mean(np.abs(np.diff(b, axis=1)))))
            black_counts["standard"] += int(float(np.mean(a)) <= 1.0)
            black_counts["sage"] += int(float(np.mean(b)) <= 1.0)
            if index in fixed:
                fixed_frames[index] = (left_rgb.copy(), right_rgb.copy())
            if previous_standard is not None and previous_sage is not None:
                standard_delta = a - previous_standard
                sage_delta = b - previous_sage
                standard_motion = float(np.mean(standard_delta * standard_delta))
                sage_motion = float(np.mean(sage_delta * sage_delta))
                standard_motion_squared.append(standard_motion)
                sage_motion_squared.append(sage_motion)
                standard_temporal_absolute.append(float(np.mean(np.abs(standard_delta))))
                sage_temporal_absolute.append(float(np.mean(np.abs(sage_delta))))
                entry = (standard_motion, index, left_rgb.copy(), right_rgb.copy())
                if len(motion_heap) < int(config["visual_review"]["additional_motion_frame_count"]) + len(fixed):
                    heapq.heappush(motion_heap, entry)
                elif standard_motion > motion_heap[0][0]:
                    heapq.heapreplace(motion_heap, entry)
            previous_standard = a
            previous_sage = b
            index += 1

    if not ssim_values:
        raise RuntimeError("A0 comparison decoded zero frames")
    motion_lookup = [(score, index) for score, index, _, _ in motion_heap]
    selected = _selected_review_indices(
        fixed,
        motion_lookup,
        int(config["visual_review"]["additional_motion_frame_count"]),
    )
    dynamic_frames = {index: (left, right) for _, index, left, right in motion_heap}
    review_frames = {**dynamic_frames, **fixed_frames}
    missing = [index for index in selected if index not in review_frames]
    if missing:
        raise RuntimeError(f"review frames were not retained: {missing}")

    width = next(iter(review_frames.values()))[0].shape[1]
    height = next(iter(review_frames.values()))[0].shape[0]
    label_height = 28
    contact = Image.new("RGB", (width * 3, (height + label_height) * len(selected)), "white")
    draw = ImageDraw.Draw(contact)
    for row, index in enumerate(selected):
        left_rgb, right_rgb = review_frames[index]
        difference = np.clip(np.abs(left_rgb.astype(np.int16) - right_rgb.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
        y = row * (height + label_height)
        draw.text((8, y + 6), f"frame {index}: Standard", fill="black")
        draw.text((width + 8, y + 6), f"frame {index}: Sage", fill="black")
        draw.text((width * 2 + 8, y + 6), f"frame {index}: |difference| x4", fill="black")
        contact.paste(Image.fromarray(left_rgb), (0, y + label_height))
        contact.paste(Image.fromarray(right_rgb), (width, y + label_height))
        contact.paste(Image.fromarray(difference), (width * 2, y + label_height))
    contact_path = output_root / "a0-standard-sage-difference-contact-sheet.png"
    contact.save(contact_path)

    standard_motion = sum(standard_motion_squared) / len(standard_motion_squared)
    sage_motion = sum(sage_motion_squared) / len(sage_motion_squared)
    standard_temporal = sum(standard_temporal_absolute) / len(standard_temporal_absolute)
    sage_temporal = sum(sage_temporal_absolute) / len(sage_temporal_absolute)
    standard_gradient = sum(standard_gradients) / len(standard_gradients)
    sage_gradient = sum(sage_gradients) / len(sage_gradients)
    ordered_ssim = sorted(ssim_values)
    p05_ssim = ordered_ssim[max(0, math.ceil(len(ordered_ssim) * 0.05) - 1)]
    expected = config["fixed_output_contract"]
    output_integrity = {
        "standard": {
            **standard_stream_info,
            "width": width,
            "height": height,
            "decoded_frame_count": len(ssim_values),
            "black_frame_count": black_counts["standard"],
            "corrupted_frame_count": 0,
        },
        "sage": {
            **sage_stream_info,
            "width": width,
            "height": height,
            "decoded_frame_count": len(ssim_values),
            "black_frame_count": black_counts["sage"],
            "corrupted_frame_count": 0,
        },
    }
    output_integrity_passed = all(
        item["codec"] == expected["codec"]
        and item["width"] == expected["width"]
        and item["height"] == expected["height"]
        and item["decoded_frame_count"] == expected["decoded_frame_count"]
        and item["fps"] == expected["fps"]
        and item["audio_stream_count"] >= expected["minimum_audio_stream_count"]
        and item["black_frame_count"] == expected["black_frame_count"]
        and item["corrupted_frame_count"] == expected["corrupted_frame_count"]
        for item in output_integrity.values()
    )
    metrics = {
        "paired_frame_count": len(ssim_values),
        "mean_ssim": sum(ssim_values) / len(ssim_values),
        "p05_ssim": p05_ssim,
        "min_ssim": min(ssim_values),
        "normalized_mae": sum(mae_values) / len(mae_values),
        "standard_motion_energy": standard_motion,
        "sage_motion_energy": sage_motion,
        "motion_energy_ratio": _ratio(sage_motion, standard_motion),
        "standard_spatial_gradient_energy": standard_gradient,
        "sage_spatial_gradient_energy": sage_gradient,
        "spatial_gradient_energy_ratio": _ratio(sage_gradient, standard_gradient),
        "standard_temporal_difference_energy": standard_temporal,
        "sage_temporal_difference_energy": sage_temporal,
        "temporal_difference_energy_ratio": _ratio(sage_temporal, standard_temporal),
        "output_integrity": output_integrity,
        "output_integrity_passed": output_integrity_passed,
        "method": "frame-aligned grayscale global SSIM/MAE, adjacent-frame squared motion energy, spatial absolute-gradient energy, and adjacent-frame absolute temporal-difference energy",
    }
    screen = automatic_screen(metrics, config["automatic_catastrophic_regression_gate"])
    runtime_positive = float(config["historical_f0"]["submit_speedup"]) > 1.0 and float(config["historical_f0"]["runner_speedup"]) > 1.0
    decision = decide(artifacts_valid=True, runtime_positive=runtime_positive, screen_passed=screen["passed"], config=config)
    private_report = {
        "schema_version": "a0.sage.offline-analysis.private.1",
        "provenance": artifacts.provenance,
        "private_sources": {
            "standard_video": str(artifacts.standard_video),
            "sage_video": str(artifacts.sage_video),
            "historical_contact_sheet": str(artifacts.historical_contact_sheet),
            "historical_side_by_side": str(artifacts.historical_side_by_side),
        },
        "metrics": {**metrics, "per_frame_ssim": ssim_values, "per_frame_normalized_mae": mae_values},
        "automatic_screen": screen,
        "decision": decision,
    }
    report_path = output_root / "a0-offline-analysis-private.json"
    report_path.write_text(json.dumps(private_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    review_manifest = {
        "schema_version": "a0.sage.visual-review.private.1",
        "status": config["visual_review"]["status_before_human_review"],
        "instructions": "Review Standard, Sage, and amplified difference rows for temporal, structural, identity, geometry, flicker, and artifact regressions. Do not mark Quality >= Standard from automatic metrics alone.",
        "selected_frame_indices": selected,
        "standard_video": str(artifacts.standard_video),
        "sage_video": str(artifacts.sage_video),
        "historical_side_by_side": str(artifacts.historical_side_by_side),
        "difference_contact_sheet": str(contact_path),
        "automatic_screen_status": screen["status"],
        "human_decision": None,
    }
    review_path = output_root / "a0-visual-review-manifest.json"
    review_path.write_text(json.dumps(review_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "schema_version": "a0.sage.public-summary.1",
        "provenance": artifacts.provenance,
        "historical_runtime": {
            key: config["historical_f0"][key]
            for key in (
                "standard_submit_to_terminal_seconds",
                "sage_submit_to_terminal_seconds",
                "submit_speedup",
                "time_reduction_percent",
                "standard_runner_total_seconds",
                "sage_runner_total_seconds",
                "runner_speedup",
            )
        },
        "metrics": {key: value for key, value in metrics.items() if key != "output_integrity"},
        "output_integrity": output_integrity,
        "automatic_screen": screen,
        "review": {
            "status": review_manifest["status"],
            "selected_frame_indices": selected,
            "contact_sheet_sha256": _hash_file(contact_path),
            "manifest_sha256": _hash_file(review_path),
        },
        "component": {
            "component_id": config["component_contract"]["component_id"],
            "component_type": config["component_contract"]["component_type"],
            "stackable": screen["passed"] and runtime_positive,
            **decision,
            "remaining_independent_acceleration_required": True,
        },
        "claims": {
            "historical_f0_decision_preserved": True,
            "standalone_1_3x_gate_used": False,
            "standalone_2_0x_gate_used": False,
            "quality_at_least_standard_proven": False,
            "speedup_claim": 0,
            "product_promotion": 0,
            "compound_eye_started": False,
            "rust_attention_work_started": False,
            "a1_started": False,
        },
    }


def public_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Strip private-only keys recursively before stdout or Git use."""
    forbidden = {"path", "private_path", "private_sources", "prompt", "content"}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in forbidden or key.endswith("_path"):
            continue
        if isinstance(item, Mapping):
            result[key] = public_projection(item)
        elif isinstance(item, list):
            result[key] = [public_projection(entry) if isinstance(entry, Mapping) else entry for entry in item]
        else:
            result[key] = item
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run model-free A0 SageAttention artifact admission.")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--standard-summary", required=True, type=Path)
    parser.add_argument("--sage-summary", required=True, type=Path)
    parser.add_argument("--pair-manifest", required=True, type=Path)
    parser.add_argument("--private-output-dir", required=True, type=Path)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    config = _load_object(args.config)
    if args.plan:
        print(json.dumps({
            "execution_started": False,
            "operation": "offline_existing_F0_artifact_validation_and_quality_screen",
            "new_generation_count": 0,
            "retry_count": 0,
            "fixed_gate": config["automatic_catastrophic_regression_gate"],
            "human_review_required": True,
        }, sort_keys=True))
        return 0
    artifacts = validate_f0_artifacts(
        config=config,
        standard_summary_path=args.standard_summary,
        sage_summary_path=args.sage_summary,
        pair_manifest_path=args.pair_manifest,
    )
    summary = compare_videos(artifacts, output_root=args.private_output_dir, config=config)
    print(json.dumps(public_projection(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
