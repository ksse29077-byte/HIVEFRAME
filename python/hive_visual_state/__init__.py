"""Backend-neutral visual-state contracts for compound-eye experiments."""

from .contracts import (
    PixelBox,
    build_compute_plan,
    hash_json,
    unsupported_measurement,
    validate_compute_plan,
    validate_eye_contract,
    validate_eye_observation,
    validate_shared_visual_state,
)

__all__ = [
    "PixelBox",
    "build_compute_plan",
    "hash_json",
    "unsupported_measurement",
    "validate_compute_plan",
    "validate_eye_contract",
    "validate_eye_observation",
    "validate_shared_visual_state",
]
