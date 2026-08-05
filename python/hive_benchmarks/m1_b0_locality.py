from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import time
from typing import Any, Iterable

import numpy as np


@dataclass(frozen=True)
class TranslationEstimate:
    dx_low: int
    dy_low: int
    dx_full: int
    dy_full: int
    score_sum: int
    score_count: int
    second_score_sum: int
    second_score_count: int
    confidence_status: str


def _nearest_rank(values: np.ndarray, quantile: float) -> int | None:
    if values.size == 0:
        return None
    ordered = np.sort(values.astype(np.int64, copy=False))
    index = max(0, math.ceil(quantile * ordered.size) - 1)
    return int(ordered[index])


def _nearest_rank_float(values: Iterable[float], quantile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _run_lengths(states: np.ndarray) -> np.ndarray:
    # Each row becomes an independent tile timeline with false sentinels.
    padded = np.pad(states.T.astype(np.uint8, copy=False), ((0, 0), (1, 1)))
    flattened = padded.reshape(-1)
    transitions = np.diff(flattened.astype(np.int8, copy=False))
    starts = np.flatnonzero(transitions == 1) + 1
    ends = np.flatnonzero(transitions == -1) + 1
    return (ends - starts).astype(np.int64, copy=False)


def _run_summary(states: np.ndarray) -> dict[str, int | float | None]:
    active_runs = _run_lengths(states)
    frozen_runs = _run_lengths(~states)
    active_total = int(states.sum(dtype=np.int64))
    persistent_pixels = int(active_runs[active_runs >= 2].sum(dtype=np.int64))
    return {
        "active_run_count": int(active_runs.size),
        "frozen_run_count": int(frozen_runs.size),
        "active_run_median": _nearest_rank(active_runs, 0.5),
        "active_run_p95": _nearest_rank(active_runs, 0.95),
        "frozen_run_median": _nearest_rank(frozen_runs, 0.5),
        "frozen_run_p95": _nearest_rank(frozen_runs, 0.95),
        "active_to_frozen_transitions": int(np.count_nonzero(states[:-1] & ~states[1:])),
        "frozen_to_active_transitions": int(np.count_nonzero(~states[:-1] & states[1:])),
        "one_frame_only_activity_ratio": (
            float(np.count_nonzero(active_runs == 1) / active_runs.size) if active_runs.size else 0.0
        ),
        "persistent_activity_ratio": float(persistent_pixels / active_total) if active_total else 0.0,
    }


def _tile_counts(mask: np.ndarray, tile_size: int) -> tuple[np.ndarray, np.ndarray]:
    height, width = mask.shape
    y_starts = np.arange(0, height, tile_size)
    x_starts = np.arange(0, width, tile_size)
    counts = np.add.reduceat(np.add.reduceat(mask.astype(np.int64), y_starts, axis=0), x_starts, axis=1)
    heights = np.minimum(tile_size, height - y_starts)
    widths = np.minimum(tile_size, width - x_starts)
    areas = heights[:, None] * widths[None, :]
    return counts, areas


def _activate(counts: np.ndarray, areas: np.ndarray, rule: dict[str, Any]) -> np.ndarray:
    numerator = int(rule["minimum_changed_numerator"])
    denominator = rule["minimum_changed_denominator"]
    if denominator is None:
        return counts >= numerator
    return counts * int(denominator) >= areas * numerator


def _dilate_tiles(active: np.ndarray, radius: int) -> np.ndarray:
    if radius == 0:
        return active.copy()
    padded = np.pad(active, radius, mode="constant", constant_values=False)
    result = np.zeros_like(active)
    rows, columns = active.shape
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            result |= padded[dy : dy + rows, dx : dx + columns]
    return result


def _candidate_slices(length: int, delta: int) -> tuple[slice, slice]:
    if delta >= 0:
        return slice(0, length - delta), slice(delta, length)
    return slice(-delta, length), slice(0, length + delta)


def _ratio_less(left_sum: int, left_count: int, right_sum: int, right_count: int) -> bool:
    return left_sum * right_count < right_sum * left_count


def estimate_global_translation(
    previous: np.ndarray,
    current: np.ndarray,
    translation_config: dict[str, Any],
) -> TranslationEstimate:
    stride = int(translation_config["full_resolution_scale"])
    offset = stride // 2
    previous_low = previous[offset::stride, offset::stride]
    current_low = current[offset::stride, offset::stride]
    expected = (
        int(translation_config["downsample_height"]),
        int(translation_config["downsample_width"]),
    )
    if previous_low.shape != expected or current_low.shape != expected:
        raise ValueError(f"Deterministic downsample shape {previous_low.shape} does not match {expected}.")

    candidates: list[tuple[int, int, int, int]] = []
    for dy in range(int(translation_config["search_min"]), int(translation_config["search_max"]) + 1):
        py, cy = _candidate_slices(previous_low.shape[0], dy)
        for dx in range(int(translation_config["search_min"]), int(translation_config["search_max"]) + 1):
            px, cx = _candidate_slices(previous_low.shape[1], dx)
            delta = np.abs(
                previous_low[py, px].astype(np.int16) - current_low[cy, cx].astype(np.int16)
            )
            candidates.append((int(delta.sum(dtype=np.int64)), int(delta.size), dx, dy))

    def better(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
        left_sum, left_count, left_dx, left_dy = left
        right_sum, right_count, right_dx, right_dy = right
        if _ratio_less(left_sum, left_count, right_sum, right_count):
            return True
        if _ratio_less(right_sum, right_count, left_sum, left_count):
            return False
        return (abs(left_dx) + abs(left_dy), abs(left_dy), abs(left_dx), left_dy, left_dx) < (
            abs(right_dx) + abs(right_dy),
            abs(right_dy),
            abs(right_dx),
            right_dy,
            right_dx,
        )

    ordered: list[tuple[int, int, int, int]] = []
    for candidate in candidates:
        insertion = len(ordered)
        for index, existing in enumerate(ordered):
            if better(candidate, existing):
                insertion = index
                break
        ordered.insert(insertion, candidate)
    best, second = ordered[0], ordered[1]
    margin = second[0] / second[1] - best[0] / best[1]
    status = (
        "collected"
        if margin >= float(translation_config["minimum_mad_margin_for_high_confidence"])
        else "low_confidence"
    )
    return TranslationEstimate(
        dx_low=best[2],
        dy_low=best[3],
        dx_full=best[2] * stride,
        dy_full=best[3] * stride,
        score_sum=best[0],
        score_count=best[1],
        second_score_sum=second[0],
        second_score_count=second[1],
        confidence_status=status,
    )


def compensated_difference(
    previous: np.ndarray,
    current: np.ndarray,
    estimate: TranslationEstimate,
) -> tuple[np.ndarray, int]:
    py, cy = _candidate_slices(previous.shape[0], estimate.dy_full)
    px, cx = _candidate_slices(previous.shape[1], estimate.dx_full)
    difference = np.full(previous.shape, 255, dtype=np.uint16)
    overlap = np.abs(previous[py, px].astype(np.int16) - current[cy, cx].astype(np.int16)).astype(
        np.uint16
    )
    difference[cy, cx] = overlap
    return difference, int(previous.size - overlap.size)


def _tile_key(source: str, threshold: int, tile_size: int, rule_id: str, halo: int) -> str:
    return f"{source}|{threshold}|{tile_size}|{rule_id}|{halo}"


def _digest(summary: dict[str, Any]) -> str:
    tokens: list[str] = [
        f"format={summary['pixel_format']}",
        f"shape={summary['frames']}x{summary['height']}x{summary['width']}",
    ]
    for item in summary["pixel_surface"]:
        tokens.append(
            "pixel="
            + ",".join(
                str(item[field]) for field in ("source", "threshold", "changed_pixels", "total_pixels")
            )
        )
    for item in summary.get("tile_surface", []):
        tokens.append(
            "tile="
            + ",".join(
                str(item[field])
                for field in (
                    "source",
                    "threshold",
                    "tile_size",
                    "activation_rule",
                    "halo_tiles",
                    "total_tiles",
                    "active_tiles",
                    "partial_edge_tiles",
                    "additional_closure_tiles",
                    "pairs_at_or_above_75_percent",
                    "pairs_at_or_above_90_percent",
                    "full_pressure_pairs",
                )
            )
        )
    for item in summary.get("temporal_persistence", []):
        tokens.append(
            "temporal="
            + ",".join(
                str(item[field])
                for field in (
                    "source",
                    "threshold",
                    "tile_size",
                    "activation_rule",
                    "halo_tiles",
                    "active_run_count",
                    "frozen_run_count",
                    "active_run_median",
                    "active_run_p95",
                    "frozen_run_median",
                    "frozen_run_p95",
                    "active_to_frozen_transitions",
                    "frozen_to_active_transitions",
                )
            )
        )
    for item in summary.get("translations", []):
        tokens.append(
            "translation="
            + ",".join(
                str(item[field])
                for field in (
                    "pair_index",
                    "dx_low",
                    "dy_low",
                    "dx_full",
                    "dy_full",
                    "score_sum",
                    "score_count",
                    "exposed_border_pixels",
                    "confidence_status",
                )
            )
        )
    return hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()


def analyze_gray_sequence(sequence: np.ndarray, config: dict[str, Any]) -> dict[str, Any]:
    if sequence.dtype != np.uint8 or sequence.ndim != 3:
        raise ValueError("gray8 sequence must be a uint8 [frames, height, width] array.")
    frames, height, width = map(int, sequence.shape)
    if frames < 2:
        raise ValueError("At least two frames are required.")
    expected = config["input_contract"]
    if (width, height) != (int(expected["width"]), int(expected["height"])) and not config.get(
        "allow_test_shape", False
    ):
        raise ValueError("Sequence shape does not match the fixed input contract.")

    thresholds = [int(value) for value in config["surface"]["gray8_thresholds"]]
    tile_sizes = [int(value) for value in config["surface"]["tile_sizes"]]
    rules = config["surface"]["activation_rules"]
    halos = [int(value) for value in config["surface"]["halo_tiles"]]
    pair_count = frames - 1
    total_pixels_per_surface = pair_count * height * width
    pixel_counts = {(source, threshold): 0 for source in ("raw", "translation_compensated") for threshold in thresholds}
    tile_accumulators: dict[str, dict[str, int]] = {}
    temporal_states: dict[str, list[np.ndarray]] = {}
    translations: list[dict[str, Any]] = []
    raw_global_delta: list[float] = []
    compensated_global_delta: list[float] = []
    translation_estimation_seconds = 0.0
    compensation_apply_seconds = 0.0

    for pair_index in range(pair_count):
        previous = sequence[pair_index]
        current = sequence[pair_index + 1]
        raw = np.abs(previous.astype(np.int16) - current.astype(np.int16)).astype(np.uint16)
        raw_global_delta.append(float(raw.mean(dtype=np.float64)))

        started = time.perf_counter()
        estimate = estimate_global_translation(previous, current, config["translation"])
        translation_estimation_seconds += time.perf_counter() - started
        started = time.perf_counter()
        compensated, exposed = compensated_difference(previous, current, estimate)
        compensation_apply_seconds += time.perf_counter() - started
        compensated_global_delta.append(float(compensated.mean(dtype=np.float64)))
        translations.append(
            {
                "pair_index": pair_index,
                "dx_low": estimate.dx_low,
                "dy_low": estimate.dy_low,
                "dx_full": estimate.dx_full,
                "dy_full": estimate.dy_full,
                "score_sum": estimate.score_sum,
                "score_count": estimate.score_count,
                "second_score_sum": estimate.second_score_sum,
                "second_score_count": estimate.second_score_count,
                "confidence_status": estimate.confidence_status,
                "exposed_border_pixels": exposed,
            }
        )

        for source, difference in (("raw", raw), ("translation_compensated", compensated)):
            for threshold in thresholds:
                changed = difference > threshold
                pixel_counts[(source, threshold)] += int(changed.sum(dtype=np.int64))
                for tile_size in tile_sizes:
                    counts, areas = _tile_counts(changed, tile_size)
                    partial_per_pair = int(np.count_nonzero(areas != tile_size * tile_size))
                    tile_total = int(counts.size)
                    for rule in rules:
                        base_active = _activate(counts, areas, rule)
                        base_count = int(base_active.sum(dtype=np.int64))
                        for halo in halos:
                            active = _dilate_tiles(base_active, halo)
                            active_count = int(active.sum(dtype=np.int64))
                            key = _tile_key(source, threshold, tile_size, rule["id"], halo)
                            accumulator = tile_accumulators.setdefault(
                                key,
                                {
                                    "source": source,
                                    "threshold": threshold,
                                    "tile_size": tile_size,
                                    "activation_rule": rule["id"],
                                    "halo_tiles": halo,
                                    "total_tiles": 0,
                                    "active_tiles": 0,
                                    "partial_edge_tiles": 0,
                                    "additional_closure_tiles": 0,
                                    "pairs_at_or_above_75_percent": 0,
                                    "pairs_at_or_above_90_percent": 0,
                                    "full_pressure_pairs": 0,
                                },
                            )
                            accumulator["total_tiles"] += tile_total
                            accumulator["active_tiles"] += active_count
                            accumulator["partial_edge_tiles"] += partial_per_pair
                            accumulator["additional_closure_tiles"] += active_count - base_count
                            accumulator["pairs_at_or_above_75_percent"] += int(active_count * 4 >= tile_total * 3)
                            accumulator["pairs_at_or_above_90_percent"] += int(active_count * 10 >= tile_total * 9)
                            accumulator["full_pressure_pairs"] += int(active_count == tile_total)
                            temporal_states.setdefault(key, []).append(active.reshape(-1).copy())

    pixel_surface = []
    for source in ("raw", "translation_compensated"):
        for threshold in thresholds:
            changed_pixels = pixel_counts[(source, threshold)]
            pixel_surface.append(
                {
                    "source": source,
                    "threshold": threshold,
                    "changed_pixels": changed_pixels,
                    "total_pixels": total_pixels_per_surface,
                    "changed_pixel_ratio": changed_pixels / total_pixels_per_surface,
                }
            )

    tile_surface: list[dict[str, Any]] = []
    temporal_persistence: list[dict[str, Any]] = []
    for source in ("raw", "translation_compensated"):
        for threshold in thresholds:
            for tile_size in tile_sizes:
                for rule in rules:
                    for halo in halos:
                        key = _tile_key(source, threshold, tile_size, rule["id"], halo)
                        item = dict(tile_accumulators[key])
                        item["active_tile_ratio"] = item["active_tiles"] / item["total_tiles"]
                        item["frozen_candidate_ratio"] = 1.0 - item["active_tile_ratio"]
                        base_active = item["active_tiles"] - item["additional_closure_tiles"]
                        item["halo_inflation_ratio"] = (
                            item["active_tiles"] / base_active if base_active else (1.0 if item["active_tiles"] == 0 else None)
                        )
                        tile_surface.append(item)
                        states = np.stack(temporal_states[key], axis=0)
                        temporal_persistence.append(
                            {
                                "source": source,
                                "threshold": threshold,
                                "tile_size": tile_size,
                                "activation_rule": rule["id"],
                                "halo_tiles": halo,
                                **_run_summary(states),
                            }
                        )

    exposed_total = sum(item["exposed_border_pixels"] for item in translations)
    low_confidence = sum(item["confidence_status"] != "collected" for item in translations)
    summary: dict[str, Any] = {
        "schema_version": "0.1.0",
        "implementation": "numpy_vectorized_reference",
        "pixel_format": "gray8",
        "frames": frames,
        "frame_pairs": pair_count,
        "width": width,
        "height": height,
        "pixel_surface": pixel_surface,
        "global_delta": {
            "raw_median": _nearest_rank_float(raw_global_delta, 0.5),
            "raw_p95": _nearest_rank_float(raw_global_delta, 0.95),
            "translation_compensated_median": _nearest_rank_float(compensated_global_delta, 0.5),
            "translation_compensated_p95": _nearest_rank_float(compensated_global_delta, 0.95),
        },
        "tile_surface": tile_surface,
        "temporal_persistence": temporal_persistence,
        "translations": translations,
        "translation_cost": {
            "estimation_seconds": translation_estimation_seconds,
            "apply_seconds": compensation_apply_seconds,
            "exposed_border_pixels": exposed_total,
            "exposed_border_ratio": exposed_total / total_pixels_per_surface,
            "low_confidence_pairs": low_confidence,
        },
    }
    summary["summary_digest"] = _digest(summary)
    return summary


def analyze_rgb_sequence(
    sequence: np.ndarray,
    config: dict[str, Any],
    gray_sequence: np.ndarray | None = None,
) -> dict[str, Any]:
    if sequence.dtype != np.uint8 or sequence.ndim != 4 or sequence.shape[-1] != 3:
        raise ValueError("rgb24 sequence must be a uint8 [frames, height, width, 3] array.")
    frames, height, width, _ = map(int, sequence.shape)
    if frames < 2:
        raise ValueError("At least two frames are required.")
    thresholds = [int(value) for value in config["surface"]["rgb24_thresholds"]]
    total_pixels = (frames - 1) * height * width
    counts = {threshold: 0 for threshold in thresholds}
    disagreement = {threshold: 0 for threshold in thresholds}
    for pair_index in range(frames - 1):
        delta = np.abs(
            sequence[pair_index].astype(np.int16) - sequence[pair_index + 1].astype(np.int16)
        ).max(axis=2)
        gray_delta = None
        if gray_sequence is not None:
            gray_delta = np.abs(
                gray_sequence[pair_index].astype(np.int16) - gray_sequence[pair_index + 1].astype(np.int16)
            )
        for threshold in thresholds:
            changed = delta > threshold
            counts[threshold] += int(changed.sum(dtype=np.int64))
            if gray_delta is not None:
                disagreement[threshold] += int(np.count_nonzero(changed != (gray_delta > threshold)))
    pixel_surface = [
        {
            "source": "rgb_raw",
            "threshold": threshold,
            "changed_pixels": counts[threshold],
            "total_pixels": total_pixels,
            "changed_pixel_ratio": counts[threshold] / total_pixels,
        }
        for threshold in thresholds
    ]
    summary: dict[str, Any] = {
        "schema_version": "0.1.0",
        "implementation": "numpy_vectorized_reference",
        "pixel_format": "rgb24",
        "frames": frames,
        "frame_pairs": frames - 1,
        "width": width,
        "height": height,
        "pixel_surface": pixel_surface,
        "luma_rgb_disagreement": [
            {
                "threshold": threshold,
                "disagreement_pixels": disagreement[threshold],
                "total_pixels": total_pixels,
                "disagreement_ratio": disagreement[threshold] / total_pixels,
                "status": "collected" if gray_sequence is not None else "unavailable",
            }
            for threshold in thresholds
        ],
    }
    summary["summary_digest"] = _digest(summary)
    return summary
