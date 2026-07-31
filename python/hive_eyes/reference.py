"""Deterministic NumPy eyes for architecture experiments, not model inference."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import numpy as np

from hive_visual_state.contracts import (
    PixelBox,
    SCHEMA_VERSION,
    make_window,
    unsupported_measurement,
)


def validate_sequence(sequence: np.ndarray) -> tuple[int, int, int, int]:
    if not isinstance(sequence, np.ndarray):
        raise TypeError("Sequence must be a NumPy array.")
    if sequence.ndim != 4:
        raise ValueError("Sequence shape must be [frames, height, width, channels].")
    frames, height, width, channels = sequence.shape
    if frames < 2 or min(height, width, channels) < 1:
        raise ValueError("Sequence requires at least two non-empty frames.")
    if not np.issubdtype(sequence.dtype, np.number):
        raise TypeError("Sequence dtype must be numeric.")
    if not np.isfinite(sequence).all():
        raise ValueError("Sequence cannot contain NaN or infinity.")
    return int(frames), int(height), int(width), int(channels)


def sequence_sha256(sequence: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(sequence)
    digest = hashlib.sha256()
    digest.update(str(contiguous.dtype).encode("ascii"))
    digest.update(str(contiguous.shape).encode("ascii"))
    digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _round(value: float) -> float:
    return round(float(value), 8)


def _motion_map(sequence: np.ndarray) -> np.ndarray:
    delta = np.abs(np.diff(sequence.astype(np.float64), axis=0))
    return np.max(delta, axis=(0, 3))


def _region(
    *,
    region_id: str,
    box: PixelBox,
    state: str,
    confidence: float,
    metric: str,
    value: float | None,
    unit: str,
) -> dict[str, Any]:
    return {
        "region_id": region_id,
        "pixel_xywh": box.as_list(),
        "state": state,
        "confidence": _round(confidence),
        "evidence": {
            "metric": metric,
            "value": None if value is None else _round(value),
            "unit": unit,
        },
    }


def _unsupported_metrics() -> list[dict[str, Any]]:
    return [
        {
            "name": "gpu_kernel_seconds",
            **unsupported_measurement(
                unit="seconds",
                status="unsupported",
                reason="Reference eyes run on NumPy without CUDA.",
                measurement_method="requires a separate profiled backend run",
            ),
        },
        {
            "name": "actual_sparse_speedup",
            **unsupported_measurement(
                unit="ratio",
                status="not_collected",
                reason="No generation backend executes in the reference simulation.",
                measurement_method="requires a same-condition backend comparison",
            ),
        },
    ]


@dataclass(frozen=True)
class ReferenceEye:
    eye_id: str
    purpose: str
    eye_type: str
    receptive_boxes: tuple[PixelBox, ...]
    write_boxes: tuple[PixelBox, ...]
    spatial_scale: float = 1.0
    temporal_stride: int = 1

    def contract(self, sequence: np.ndarray) -> dict[str, Any]:
        frames, height, width, _ = validate_sequence(sequence)
        receptive_windows = [
            make_window(
                window_id=f"{self.eye_id}:rf:{index}",
                box=box,
                canvas_width=width,
                canvas_height=height,
                frames=frames,
            )
            for index, box in enumerate(self.receptive_boxes)
        ]
        write_windows = [
            make_window(
                window_id=f"{self.eye_id}:write:{index}",
                box=box,
                canvas_width=width,
                canvas_height=height,
                frames=frames,
            )
            for index, box in enumerate(self.write_boxes)
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "eye_id": self.eye_id,
            "eye_type": self.eye_type,
            "purpose": self.purpose,
            "receptive_field": {
                "coordinate_space": "pixel_xywh",
                "windows": receptive_windows,
            },
            "sampling": {
                "spatial_scale": self.spatial_scale,
                "temporal_stride": self.temporal_stride,
            },
            "write_policy": {
                "mode": "bounded" if write_windows else "read_only",
                "windows": write_windows,
            },
            "outputs": ["features", "regions", "confidence", "provenance"],
        }

    def _base_observation(
        self,
        sequence: np.ndarray,
        *,
        sequence_id: str,
        seed: int,
        features: dict[str, Any],
        regions: list[dict[str, Any]],
        confidence: float,
        algorithm: str,
    ) -> dict[str, Any]:
        contract = self.contract(sequence)
        return {
            "schema_version": SCHEMA_VERSION,
            "observation_id": f"{sequence_id}:{self.eye_id}",
            "eye_id": self.eye_id,
            "eye_type": self.eye_type,
            "source_sequence_id": sequence_id,
            "seed": seed,
            "receptive_field": contract["receptive_field"],
            "write_scope": contract["write_policy"],
            "features": features,
            "regions": regions,
            "confidence": _round(confidence),
            "provenance": {
                "eye_contract_id": f"{self.eye_id}@{SCHEMA_VERSION}",
                "algorithm": algorithm,
                "input_sha256": sequence_sha256(sequence),
            },
            "unsupported_metrics": _unsupported_metrics(),
        }


class GlobalLowResolutionEye(ReferenceEye):
    def observe(
        self, sequence: np.ndarray, *, sequence_id: str, seed: int
    ) -> dict[str, Any]:
        _, height, width, _ = validate_sequence(sequence)
        target_height = max(1, int(round(height * self.spatial_scale)))
        target_width = max(1, int(round(width * self.spatial_scale)))
        y_edges = np.linspace(0, height, target_height + 1, dtype=int)
        x_edges = np.linspace(0, width, target_width + 1, dtype=int)
        reduced = np.empty(
            (sequence.shape[0], target_height, target_width, sequence.shape[3]),
            dtype=np.float64,
        )
        for y in range(target_height):
            for x in range(target_width):
                reduced[:, y, x, :] = sequence[
                    :, y_edges[y] : y_edges[y + 1], x_edges[x] : x_edges[x + 1], :
                ].mean(axis=(1, 2))
        full_box = self.receptive_boxes[0]
        return self._base_observation(
            sequence,
            sequence_id=sequence_id,
            seed=seed,
            features={
                "mean_intensity": _round(sequence.mean()),
                "temporal_abs_delta_mean": _round(
                    np.abs(np.diff(reduced, axis=0)).mean()
                ),
                "low_resolution_shape": list(reduced.shape),
                "scene_context_available": True,
            },
            regions=[
                _region(
                    region_id=f"{self.eye_id}:context",
                    box=full_box,
                    state="uncertain",
                    confidence=0.6,
                    metric="context_only",
                    value=None,
                    unit="none",
                )
            ],
            confidence=0.8,
            algorithm="deterministic_mean_pool_v0",
        )


class RegionalEye(ReferenceEye):
    motion_threshold: float = 0.1

    def observe(
        self, sequence: np.ndarray, *, sequence_id: str, seed: int
    ) -> dict[str, Any]:
        box = self.receptive_boxes[0]
        motion = _motion_map(sequence)[box.y : box.y2, box.x : box.x2]
        changed_ratio = float((motion > self.motion_threshold).mean())
        state = "dirty" if changed_ratio > 0 else "stable"
        confidence = min(0.99, 0.8 + changed_ratio)
        return self._base_observation(
            sequence,
            sequence_id=sequence_id,
            seed=seed,
            features={
                "mean_intensity": _round(
                    sequence[:, box.y : box.y2, box.x : box.x2, :].mean()
                ),
                "changed_pixel_ratio": _round(changed_ratio),
                "motion_threshold": self.motion_threshold,
            },
            regions=[
                _region(
                    region_id=f"{self.eye_id}:owned",
                    box=box,
                    state=state,
                    confidence=confidence,
                    metric="changed_pixel_ratio",
                    value=changed_ratio,
                    unit="ratio",
                )
            ],
            confidence=confidence,
            algorithm="regional_frame_delta_v0",
        )


class BoundaryEye(ReferenceEye):
    motion_threshold: float = 0.1

    def observe(
        self, sequence: np.ndarray, *, sequence_id: str, seed: int
    ) -> dict[str, Any]:
        motion = _motion_map(sequence)
        regions = []
        ratios = []
        for index, box in enumerate(self.receptive_boxes):
            ratio = float(
                (
                    motion[box.y : box.y2, box.x : box.x2]
                    > self.motion_threshold
                ).mean()
            )
            ratios.append(ratio)
            state = "uncertain" if ratio > 0 else "stable"
            regions.append(
                _region(
                    region_id=f"{self.eye_id}:overlap:{index}",
                    box=box,
                    state=state,
                    confidence=0.9 if ratio > 0 else 0.85,
                    metric="boundary_changed_pixel_ratio",
                    value=ratio,
                    unit="ratio",
                )
            )
        return self._base_observation(
            sequence,
            sequence_id=sequence_id,
            seed=seed,
            features={
                "boundary_changed_pixel_ratio": _round(max(ratios)),
                "overlap_window_count": len(self.receptive_boxes),
            },
            regions=regions,
            confidence=0.9,
            algorithm="overlap_boundary_delta_v0",
        )


class MotionEye(ReferenceEye):
    motion_threshold: float = 0.1

    def observe(
        self, sequence: np.ndarray, *, sequence_id: str, seed: int
    ) -> dict[str, Any]:
        motion = _motion_map(sequence)
        changed = motion > self.motion_threshold
        regions: list[dict[str, Any]] = []
        if changed.any():
            ys, xs = np.where(changed)
            box = PixelBox(
                int(xs.min()),
                int(ys.min()),
                int(xs.max() - xs.min() + 1),
                int(ys.max() - ys.min() + 1),
            )
            regions.append(
                _region(
                    region_id=f"{self.eye_id}:motion",
                    box=box,
                    state="dirty",
                    confidence=0.99,
                    metric="max_frame_difference",
                    value=float(motion.max()),
                    unit="normalized_intensity",
                )
            )
        return self._base_observation(
            sequence,
            sequence_id=sequence_id,
            seed=seed,
            features={
                "changed_pixel_count": int(changed.sum()),
                "max_frame_difference": _round(motion.max()),
                "motion_threshold": self.motion_threshold,
            },
            regions=regions,
            confidence=0.99 if regions else 0.9,
            algorithm="frame_difference_bbox_v0",
        )


def build_reference_eyes(sequence: np.ndarray) -> list[ReferenceEye]:
    frames, height, width, _ = validate_sequence(sequence)
    del frames
    left_width = width // 2
    top_height = height // 2
    right_width = width - left_width
    bottom_height = height - top_height
    vertical_width = min(width, 4)
    horizontal_height = min(height, 4)
    vertical_x = max(0, width // 2 - vertical_width // 2)
    horizontal_y = max(0, height // 2 - horizontal_height // 2)
    full = PixelBox(0, 0, width, height)
    regional_boxes = (
        PixelBox(0, 0, left_width, top_height),
        PixelBox(left_width, 0, right_width, top_height),
        PixelBox(0, top_height, left_width, bottom_height),
        PixelBox(left_width, top_height, right_width, bottom_height),
    )
    eyes: list[ReferenceEye] = [
        GlobalLowResolutionEye(
            eye_id="global-lowres",
            purpose="Whole-scene context at reduced spatial resolution.",
            eye_type="global_low_resolution",
            receptive_boxes=(full,),
            write_boxes=(),
            spatial_scale=0.25,
        )
    ]
    for index, box in enumerate(regional_boxes):
        eyes.append(
            RegionalEye(
                eye_id=f"regional-{index}",
                purpose="Bounded observation and write ownership for one 2x2 region.",
                eye_type="regional",
                receptive_boxes=(box,),
                write_boxes=(box,),
            )
        )
    eyes.extend(
        [
            BoundaryEye(
                eye_id="boundary-overlap",
                purpose="Observe overlapping ownership boundaries for conflicts.",
                eye_type="overlap_boundary",
                receptive_boxes=(
                    PixelBox(vertical_x, 0, vertical_width, height),
                    PixelBox(0, horizontal_y, width, horizontal_height),
                ),
                write_boxes=(),
            ),
            MotionEye(
                eye_id="motion-difference",
                purpose="Detect temporal change without proposing writes.",
                eye_type="frame_difference_motion",
                receptive_boxes=(full,),
                write_boxes=(),
            ),
        ]
    )
    return eyes
