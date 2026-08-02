"""Human-oracle contract validation without video decode, models, or CUDA."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .m1_protocol import is_sha256, load_json, public_sanitation_errors, require_keys, sha256_json
from .m1_schema_contract import validate_m1_schema


PRIMARY_STATES = {"dirty", "stable", "uncertain"}
ALL_STATES = PRIMARY_STATES | {"preserve"}


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_intersect(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]) -> bool:
    values = (_orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b))
    return values[0] * values[1] < 0 and values[2] * values[3] < 0


def _polygon_self_intersects(points: list[tuple[float, float]]) -> bool:
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or (second + 1) % count == first:
                continue
            c, d = points[second], points[(second + 1) % count]
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _spans_intersect(left: dict[int, list[tuple[int, int]]], right: dict[int, list[tuple[int, int]]]) -> bool:
    for row in left.keys() & right.keys():
        a = _merge_intervals(left[row])
        b = _merge_intervals(right[row])
        i = j = 0
        while i < len(a) and j < len(b):
            if max(a[i][0], b[j][0]) < min(a[i][1], b[j][1]):
                return True
            if a[i][1] <= b[j][1]:
                i += 1
            else:
                j += 1
    return False


def _spans_area(spans: dict[int, list[tuple[int, int]]]) -> int:
    return sum(end - start for intervals in spans.values() for start, end in _merge_intervals(intervals))


def geometry_spans(geometry: Any, width: int, height: int, path: str) -> tuple[dict[int, list[tuple[int, int]]], list[str]]:
    errors: list[str] = []
    spans: dict[int, list[tuple[int, int]]] = {}
    if not isinstance(geometry, dict):
        return spans, [f"{path}: expected geometry object"]
    kind = geometry.get("type")
    if kind == "bbox":
        box = geometry.get("xywh")
        if not isinstance(box, list) or len(box) != 4 or not all(isinstance(item, int) for item in box):
            return spans, [f"{path}.xywh: expected four integers"]
        x, y, w, h = box
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            return spans, [f"{path}.xywh: region is outside canvas bounds"]
        for row in range(y, y + h):
            spans[row] = [(x, x + w)]
    elif kind == "rle":
        size = geometry.get("size")
        counts = geometry.get("counts")
        starts_with = geometry.get("starts_with")
        if size != [height, width]:
            errors.append(f"{path}.size: RLE canvas does not match annotation canvas")
        if not isinstance(counts, list) or not counts or not all(isinstance(item, int) and item >= 0 for item in counts):
            errors.append(f"{path}.counts: expected non-negative run lengths")
        elif sum(counts) != width * height:
            errors.append(f"{path}.counts: run lengths do not cover the canvas")
        elif starts_with not in {0, 1}:
            errors.append(f"{path}.starts_with: expected 0 or 1")
        else:
            offset = 0
            state = starts_with
            for length in counts:
                if state == 1 and length:
                    remaining = length
                    cursor = offset
                    while remaining:
                        row, column = divmod(cursor, width)
                        take = min(remaining, width - column)
                        spans.setdefault(row, []).append((column, column + take))
                        cursor += take
                        remaining -= take
                offset += length
                state = 1 - state
    elif kind == "polygon":
        raw_points = geometry.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            return spans, [f"{path}.points: at least three points are required"]
        try:
            points = [(float(point[0]), float(point[1])) for point in raw_points]
        except (TypeError, ValueError, IndexError):
            return spans, [f"{path}.points: malformed coordinate"]
        if any(not (0 <= x <= width and 0 <= y <= height) for x, y in points):
            errors.append(f"{path}.points: polygon is outside canvas bounds")
        if _polygon_self_intersects(points):
            errors.append(f"{path}.points: polygon self-intersects")
        if not errors:
            min_row = max(0, math.floor(min(y for _, y in points)))
            max_row = min(height, math.ceil(max(y for _, y in points)))
            for row in range(min_row, max_row):
                scan_y = row + 0.5
                intersections: list[float] = []
                for index, (x1, y1) in enumerate(points):
                    x2, y2 = points[(index + 1) % len(points)]
                    if (y1 <= scan_y < y2) or (y2 <= scan_y < y1):
                        intersections.append(x1 + (scan_y - y1) * (x2 - x1) / (y2 - y1))
                row_spans: list[tuple[int, int]] = []
                for index in range(0, len(sorted(intersections)) - 1, 2):
                    ordered = sorted(intersections)
                    start = max(0, math.ceil(ordered[index] - 0.5))
                    end = min(width, math.ceil(ordered[index + 1] - 0.5))
                    if start < end:
                        row_spans.append((start, end))
                if row_spans:
                    spans[row] = row_spans
    else:
        errors.append(f"{path}.type: unsupported geometry type")
    return spans, errors


def _validate_transition(transition: Any, annotation: dict[str, Any], path: str) -> list[str]:
    required = ("transition_id", "frame_interval", "scene_cut", "camera_motion", "full_reobserve", "invalidated_object_ids", "regions")
    errors = require_keys(transition, required, path)
    if errors or not isinstance(transition, dict):
        return errors
    interval = transition["frame_interval"]
    if not isinstance(interval, list) or len(interval) != 2 or not all(isinstance(item, int) for item in interval):
        errors.append(f"{path}.frame_interval: expected [from_frame, to_frame]")
    elif interval[1] != interval[0] + 1 or interval[0] < 0 or interval[1] >= annotation["frame_count"]:
        errors.append(f"{path}.frame_interval: transitions must map adjacent valid frames")
    width, height = annotation["canvas"]
    object_ids = {item.get("object_id") for item in annotation.get("object_catalog", []) if isinstance(item, dict)}
    semantic_payloads = annotation.get("semantic_payloads", {})
    by_state: dict[str, list[dict[int, list[tuple[int, int]]]]] = {state: [] for state in ALL_STATES}
    seen_region_ids: set[str] = set()
    for index, region in enumerate(transition.get("regions", [])):
        region_path = f"{path}.regions[{index}]"
        errors.extend(require_keys(region, ("region_id", "state", "geometry", "object_ids", "change_causes", "confidence", "semantic_ref", "semantic_hash"), region_path))
        if not isinstance(region, dict):
            continue
        if region.get("region_id") in seen_region_ids:
            errors.append(f"{region_path}.region_id: duplicate region id")
        seen_region_ids.add(region.get("region_id"))
        state = region.get("state")
        if state not in ALL_STATES:
            errors.append(f"{region_path}.state: invalid state")
            continue
        spans, geometry_errors = geometry_spans(region.get("geometry"), width, height, f"{region_path}.geometry")
        errors.extend(geometry_errors)
        by_state[state].append(spans)
        unknown_objects = set(region.get("object_ids", [])) - object_ids
        if unknown_objects:
            errors.append(f"{region_path}.object_ids: unknown ids {sorted(unknown_objects)}")
        semantic_ref = region.get("semantic_ref")
        if semantic_ref not in semantic_payloads:
            errors.append(f"{region_path}.semantic_ref: missing payload reference")
        elif region.get("semantic_hash") != sha256_json(semantic_payloads[semantic_ref]):
            errors.append(f"{region_path}.semantic_hash: payload digest mismatch")
        if "mask" in region or "semantic_payload" in region:
            errors.append(f"{region_path}: full mask or semantic payload repetition is forbidden")
    for first_index, first in enumerate(PRIMARY_STATES):
        for second in list(PRIMARY_STATES)[first_index + 1:]:
            if any(_spans_intersect(left, right) for left in by_state[first] for right in by_state[second]):
                errors.append(f"{path}: {first} and {second} regions overlap")
    if any(_spans_intersect(preserve, other) for preserve in by_state["preserve"] for state in ("dirty", "uncertain") for other in by_state[state]):
        errors.append(f"{path}: preserve may overlap stable only, never dirty or uncertain")
    primary_union: dict[int, list[tuple[int, int]]] = {}
    for state in PRIMARY_STATES:
        for spans in by_state[state]:
            for row, intervals in spans.items():
                primary_union.setdefault(row, []).extend(intervals)
    if _spans_area(primary_union) != width * height:
        errors.append(f"{path}: dirty/stable/uncertain regions must partition the full canvas")
    if transition.get("scene_cut"):
        if transition.get("full_reobserve") is not True:
            errors.append(f"{path}: scene cut requires full_reobserve=true")
        if by_state["stable"] or by_state["uncertain"] or by_state["preserve"]:
            errors.append(f"{path}: scene cut invalidates stable, uncertain, and preserve regions")
        used_objects = {object_id for region in transition.get("regions", []) for object_id in region.get("object_ids", [])}
        if used_objects and not used_objects.issubset(set(transition.get("invalidated_object_ids", []))):
            errors.append(f"{path}: scene cut must invalidate referenced pre-cut object ids")
    elif transition.get("full_reobserve") is True:
        errors.append(f"{path}: full_reobserve without a scene cut requires separate protocol justification")
    return errors


def validate_annotation(annotation: Any, path: str = "$.annotations[]") -> list[str]:
    required = (
        "clip_id", "source_sha256", "derivative_sha256", "canvas", "frame_count", "object_catalog",
        "semantic_payloads", "transitions", "annotation_provenance", "annotation_method",
        "review_protocol", "review_status", "confidence", "disagreement", "artifact_digest",
    )
    errors = require_keys(annotation, required, path)
    if errors or not isinstance(annotation, dict):
        return errors
    if not is_sha256(annotation["source_sha256"]) or not is_sha256(annotation["derivative_sha256"]):
        errors.append(f"{path}: source and derivative digests must be SHA-256")
    canvas = annotation.get("canvas")
    if not isinstance(canvas, list) or len(canvas) != 2 or not all(isinstance(item, int) and item > 0 for item in canvas):
        return errors + [f"{path}.canvas: expected positive [width, height]"]
    if not isinstance(annotation.get("frame_count"), int) or annotation["frame_count"] < 2:
        return errors + [f"{path}.frame_count: expected at least two frames"]
    catalog_ids = [item.get("object_id") for item in annotation.get("object_catalog", []) if isinstance(item, dict)]
    if len(catalog_ids) != len(set(catalog_ids)):
        errors.append(f"{path}.object_catalog: duplicate object id")
    transitions = annotation.get("transitions")
    if not isinstance(transitions, list):
        return errors + [f"{path}.transitions: expected array"]
    for index, transition in enumerate(transitions):
        errors.extend(_validate_transition(transition, annotation, f"{path}.transitions[{index}]"))
    intervals = [tuple(item.get("frame_interval", [])) for item in transitions if isinstance(item, dict)]
    expected = [(frame, frame + 1) for frame in range(annotation["frame_count"] - 1)]
    if intervals != expected:
        errors.append(f"{path}.transitions: transition mapping must cover every adjacent frame once in order")
    if annotation.get("review_protocol") not in {"independent_multi_reviewer", "time_separated_blind_self_review"}:
        errors.append(f"{path}.review_protocol: invalid review protocol")
    if annotation.get("review_status") == "verified" and annotation.get("review_protocol") == "time_separated_blind_self_review":
        if not annotation.get("disagreement"):
            errors.append(f"{path}.disagreement: self-review must record disagreement/adjudication, including an explicit no-disagreement record")
    expected_digest = sha256_json({key: value for key, value in annotation.items() if key != "artifact_digest"})
    if annotation.get("artifact_digest") != expected_digest:
        errors.append(f"{path}.artifact_digest: annotation digest mismatch")
    errors.extend(public_sanitation_errors(annotation))
    return errors


def validate_oracle_document(document: Any) -> list[str]:
    errors = validate_m1_schema(document, "m1-oracle-annotation.schema.json")
    errors.extend(require_keys(document, ("schema_version", "annotation_version", "annotations"), "$"))
    if errors or not isinstance(document, dict):
        return errors
    if document["schema_version"] != "0.1.0":
        errors.append("$.schema_version: expected 0.1.0")
    annotations = document.get("annotations")
    if not isinstance(annotations, list):
        return errors + ["$.annotations: expected array"]
    seen: set[str] = set()
    for index, annotation in enumerate(annotations):
        errors.extend(validate_annotation(annotation, f"$.annotations[{index}]"))
        if isinstance(annotation, dict):
            clip_id = annotation.get("clip_id")
            if clip_id in seen:
                errors.append(f"$.annotations[{index}].clip_id: duplicate {clip_id}")
            seen.add(clip_id)
    return errors


def summarize_oracles(document: dict[str, Any]) -> dict[str, Any]:
    errors = validate_oracle_document(document)
    annotations = document.get("annotations", [])
    return {
        "schema_version": "0.1.0",
        "valid": not errors,
        "errors": errors,
        "counts": {
            "total": len(annotations),
            "verified": sum(item.get("review_status") == "verified" for item in annotations),
            "pending": sum(item.get("review_status") == "pending" for item in annotations),
            "rejected": sum(item.get("review_status") == "rejected" for item in annotations),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("oracle_document", type=Path)
    args = parser.parse_args()
    summary = summarize_oracles(load_json(args.oracle_document))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
