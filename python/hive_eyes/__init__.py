"""Logical eyes used by the compound-eye v0 reference simulation."""

from .reference import (
    BoundaryEye,
    GlobalLowResolutionEye,
    MotionEye,
    RegionalEye,
    build_reference_eyes,
    validate_sequence,
)

__all__ = [
    "BoundaryEye",
    "GlobalLowResolutionEye",
    "MotionEye",
    "RegionalEye",
    "build_reference_eyes",
    "validate_sequence",
]
