"""Deterministic synthetic cases declared by the M1-P0 work order."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from typing import Any

import numpy as np

from hive_probes.rust_io_reference import generate_sequence


@dataclass(frozen=True)
class ChangeBox:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class SyntheticCase:
    case_id: str
    label: str
    width: int
    height: int
    frames: int
    calibration_profile: str
    expected: str
    changes: tuple[ChangeBox, ...]


CASES = (
    SyntheticCase(
        case_id="case-a-low-resolution-simple",
        label="Low-resolution Simple",
        width=640,
        height=384,
        frames=16,
        calibration_profile="low",
        expected="Mono should dominate a small input with one local change.",
        changes=(ChangeBox(324, 112, 24, 32),),
    ),
    SyntheticCase(
        case_id="case-b-high-resolution-local-change",
        label="High-resolution Local Change",
        width=1920,
        height=1080,
        frames=8,
        calibration_profile="high",
        expected="Motion-focused remains plausible only if full-scene work disappears.",
        changes=(ChangeBox(968, 238, 72, 84),),
    ),
    SyntheticCase(
        case_id="case-c-global-motion",
        label="Global Motion",
        width=1280,
        height=720,
        frames=16,
        calibration_profile="medium",
        expected="Mono should dominate when every spatial location changes.",
        changes=(ChangeBox(0, 0, 1280, 720),),
    ),
)


def case_profile(case: SyntheticCase, seed: int = 101) -> dict[str, Any]:
    return {
        "profile_id": case.case_id,
        "width": case.width,
        "height": case.height,
        "frames": case.frames,
        "seed": seed,
        "change_regions": [asdict(box) for box in case.changes],
    }


def generate_case(
    case: SyntheticCase,
    seed: int = 101,
) -> tuple[dict[str, Any], np.ndarray]:
    profile = case_profile(case, seed)
    return profile, generate_sequence(profile)


def exact_dirty_mask(sequence: np.ndarray) -> np.ndarray:
    if sequence.ndim != 3 or sequence.shape[0] < 2:
        raise ValueError("Dirty-mask input must contain at least two frames.")
    return np.any(sequence[1:] != sequence[:-1], axis=0)


def case_receipt(case: SyntheticCase, seed: int = 101) -> dict[str, Any]:
    profile, sequence = generate_case(case, seed)
    dirty = exact_dirty_mask(sequence)
    return {
        "case_id": case.case_id,
        "label": case.label,
        "calibration_profile": case.calibration_profile,
        "width": case.width,
        "height": case.height,
        "frames": case.frames,
        "seed": seed,
        "input_pixels": int(sequence.size),
        "input_bytes": int(sequence.nbytes),
        "spatial_dirty_pixels": int(np.count_nonzero(dirty)),
        "spatial_dirty_ratio": float(np.count_nonzero(dirty) / dirty.size),
        "input_sha256": hashlib.sha256(sequence.tobytes(order="C")).hexdigest(),
        "expected": case.expected,
        "profile": profile,
    }
