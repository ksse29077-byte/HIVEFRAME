"""Topology geometry and analytical pre-rejection rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .synthetic_cases import SyntheticCase


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    label: str
    runtime_topology: str


CANDIDATES = (
    Candidate("T0", "Mono Eye", "mono_1x1"),
    Candidate("T1", "Global + Fixed 2x2", "uniform_2x2"),
    Candidate("T2", "Global + Motion-focused Eye", "motion_focused"),
)


def _area(box: dict[str, int]) -> int:
    return box["width"] * box["height"]


def _full(case: SyntheticCase) -> dict[str, int]:
    return {"x": 0, "y": 0, "width": case.width, "height": case.height}


def _grid_2x2(case: SyntheticCase) -> list[dict[str, int]]:
    widths = (case.width // 2, case.width - case.width // 2)
    heights = (case.height // 2, case.height - case.height // 2)
    boxes: list[dict[str, int]] = []
    y = 0
    for height in heights:
        x = 0
        for width in widths:
            boxes.append({"x": x, "y": y, "width": width, "height": height})
            x += width
        y += height
    return boxes


def _motion_focus(case: SyntheticCase) -> dict[str, int]:
    x1 = min(box.x for box in case.changes)
    y1 = min(box.y for box in case.changes)
    x2 = max(box.x + box.width for box in case.changes)
    y2 = max(box.y + box.height for box in case.changes)
    halo = max(2, min(case.width, case.height) // 64)
    x = max(0, x1 - halo)
    y = max(0, y1 - halo)
    return {
        "x": x,
        "y": y,
        "width": min(case.width, x2 + halo) - x,
        "height": min(case.height, y2 + halo) - y,
    }


def _intersects_change(
    field: dict[str, int],
    case: SyntheticCase,
) -> bool:
    x2 = field["x"] + field["width"]
    y2 = field["y"] + field["height"]
    return any(
        field["x"] < box.x + box.width
        and x2 > box.x
        and field["y"] < box.y + box.height
        and y2 > box.y
        for box in case.changes
    )


def generation_scopes(
    case: SyntheticCase,
    candidate: Candidate,
) -> list[dict[str, int]]:
    if candidate.candidate_id == "T0":
        return [_full(case)]
    if candidate.candidate_id == "T1":
        return [
            field for field in _grid_2x2(case) if _intersects_change(field, case)
        ]
    if candidate.candidate_id == "T2":
        return [_motion_focus(case)] if case.changes else []
    raise ValueError(f"Unknown candidate: {candidate.candidate_id}")


def receptive_fields(
    case: SyntheticCase,
    candidate: Candidate,
) -> list[dict[str, int]]:
    full = _full(case)
    if candidate.candidate_id == "T0":
        return [full]
    if candidate.candidate_id == "T1":
        return [full, *_grid_2x2(case)]
    if candidate.candidate_id == "T2":
        return [full, dict(full), _motion_focus(case)]
    raise ValueError(f"Unknown candidate: {candidate.candidate_id}")


def topology_geometry(
    case: SyntheticCase,
    candidate: Candidate,
    *,
    bytes_per_pixel: int = 1,
) -> dict[str, Any]:
    if bytes_per_pixel <= 0:
        raise ValueError("bytes_per_pixel must be positive.")
    fields = receptive_fields(case, candidate)
    spatial_pixels = case.width * case.height
    input_pixels = spatial_pixels * case.frames
    observed_pixels = sum(_area(field) * case.frames for field in fields)
    duplicated_pixels = max(0, observed_pixels - input_pixels)
    dirty_pixels = sum(box.width * box.height for box in case.changes)
    generated_fields = generation_scopes(case, candidate)
    generated_spatial_pixels = sum(_area(field) for field in generated_fields)
    generation_scope_ratio = generated_spatial_pixels / spatial_pixels
    scheduler_calls = len(fields)
    return {
        "input_spatial_pixels": spatial_pixels,
        "input_pixels": input_pixels,
        "input_bytes": input_pixels * bytes_per_pixel,
        "total_observation_pixels": observed_pixels,
        "total_observation_bytes": observed_pixels * bytes_per_pixel,
        "overlap_duplicate_pixels": duplicated_pixels,
        "overlap_duplicate_bytes": duplicated_pixels * bytes_per_pixel,
        "observation_multiplier_vs_mono": observed_pixels / input_pixels,
        "eye_count": len(fields),
        "coordinate_transform_count": len(fields),
        "fusion_input_count": len(fields),
        "scheduler_call_count": scheduler_calls,
        "spatial_dirty_pixels": dirty_pixels,
        "spatial_dirty_ratio": dirty_pixels / spatial_pixels,
        "receptive_fields": fields,
        "generation_scopes": generated_fields,
        "generation_scope_pixels": generated_spatial_pixels,
        "generation_scope_ratio": generation_scope_ratio,
        "potential_generation_savings_ratio": max(
            0.0,
            1.0 - generation_scope_ratio,
        ),
        "full_canvas_generate_candidate": generation_scope_ratio >= 1.0,
        "full_canvas_generate_reason": (
            "The declared change activates a full-canvas generation scope."
            if generation_scope_ratio >= 1.0
            else None
        ),
    }


def analytical_precheck(
    case: SyntheticCase,
    candidate: Candidate,
    geometry: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    if candidate.candidate_id == "T0":
        return {
            "status": "retained_for_probe",
            "reason": "Mono is the mandatory comparator.",
            "evidence": {"mandatory_comparator": True},
        }

    triggered: list[dict[str, Any]] = []
    if (
        thresholds["prune_full_canvas_generate_candidate"]
        and geometry["full_canvas_generate_candidate"]
    ):
        triggered.append(
            {
                "rule": "full_canvas_generate_candidate",
                "observed": True,
                "threshold": False,
                "reason": geometry["full_canvas_generate_reason"],
            }
        )
    if (
        geometry["observation_multiplier_vs_mono"]
        > thresholds["max_observation_multiplier_without_backend_savings"]
        and geometry["potential_generation_savings_ratio"]
        < thresholds["minimum_potential_generation_savings_to_keep"]
    ):
        triggered.append(
            {
                "rule": "observation_multiplier",
                "observed": geometry["observation_multiplier_vs_mono"],
                "threshold": thresholds[
                    "max_observation_multiplier_without_backend_savings"
                ],
                "reason": (
                    "Observation work exceeds the limit without enough possible "
                    "generation savings."
                ),
            }
        )
    if (
        geometry["input_pixels"] <= thresholds["small_input_max_pixels"]
        and candidate.candidate_id != "T0"
    ):
        triggered.append(
            {
                "rule": "small_input_management_cost",
                "observed": geometry["input_pixels"],
                "threshold": thresholds["small_input_max_pixels"],
                "reason": "The declared small input does not justify split management.",
            }
        )
    if (
        geometry["spatial_dirty_ratio"]
        >= thresholds["global_motion_dirty_ratio"]
    ):
        triggered.append(
            {
                "rule": "global_motion",
                "observed": geometry["spatial_dirty_ratio"],
                "threshold": thresholds["global_motion_dirty_ratio"],
                "reason": "Global change activates the complete spatial domain.",
            }
        )
    if triggered:
        return {
            "status": "analytically_pruned",
            "reason": triggered[0]["reason"],
            "evidence": {"triggered_rules": triggered, "geometry": geometry},
        }
    return {
        "status": "retained_for_probe",
        "reason": "No predeclared analytical rejection rule fired.",
        "evidence": {"triggered_rules": [], "geometry": geometry},
    }
