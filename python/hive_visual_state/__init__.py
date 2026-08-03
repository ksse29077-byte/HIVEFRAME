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
from .selective_protocol import (
    COST_COMPONENTS,
    validate_backend_capability_matrix,
    validate_execution_topology,
    validate_protocol_config,
    validate_selective_compute_receipt,
    validate_selective_state_map,
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
    "COST_COMPONENTS",
    "validate_backend_capability_matrix",
    "validate_execution_topology",
    "validate_protocol_config",
    "validate_selective_compute_receipt",
    "validate_selective_state_map",
]
