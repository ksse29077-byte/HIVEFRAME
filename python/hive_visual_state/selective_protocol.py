"""Protocol-only validators for future selective recompute experiments.

These helpers do not load a model, invoke a backend, or authorize skip. They
make unsafe counterexamples fail before any later backend experiment can use
an observation map as execution truth.
"""

from __future__ import annotations

from numbers import Real
from typing import Any, Iterable


STATE_MAP_KEYS = {
    "coordinate_space",
    "temporal_scope",
    "compute_unit_type",
    "frozen_regions",
    "active_regions",
    "uncertain_regions",
    "global_invalidation",
    "confidence",
    "evidence_source",
    "boundary_closure",
    "promotion_policy",
    "fallback_policy",
}

COST_COMPONENTS = (
    "scout",
    "change_detection",
    "eye_observation",
    "map_compile",
    "scheduling",
    "active_compute",
    "frozen_reuse",
    "transfer",
    "synchronization",
    "merge",
    "boundary",
    "audit",
    "repair",
    "fallback",
    "output",
    "total_wall",
)


def _require_keys(value: dict[str, Any], keys: Iterable[str], label: str) -> None:
    missing = sorted(set(keys) - set(value))
    if missing:
        raise ValueError(f"{label} is missing required keys: {missing}")


def _box(box: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("Every state region must be a pixel [x, y, width, height] box.")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in box):
        raise ValueError("State-region coordinates must be integers.")
    x, y, box_width, box_height = box
    if x < 0 or y < 0 or box_width <= 0 or box_height <= 0:
        raise ValueError("State-region boxes must have positive in-scope area.")
    if x + box_width > width or y + box_height > height:
        raise ValueError("State-region box exceeds the declared coordinate scope.")
    return x, y, box_width, box_height


def validate_selective_state_map(document: dict[str, Any]) -> None:
    _require_keys(document, STATE_MAP_KEYS, "Selective state map")
    coordinate_space = document["coordinate_space"]
    _require_keys(coordinate_space, {"width", "height", "unit"}, "coordinate_space")
    width = coordinate_space["width"]
    height = coordinate_space["height"]
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
        or coordinate_space["unit"] != "pixel"
    ):
        raise ValueError("coordinate_space must be a positive pixel canvas.")
    temporal_scope = document["temporal_scope"]
    _require_keys(
        temporal_scope,
        {"start_frame", "end_frame_exclusive"},
        "temporal_scope",
    )
    if (
        temporal_scope["start_frame"] < 0
        or temporal_scope["end_frame_exclusive"] <= temporal_scope["start_frame"]
    ):
        raise ValueError("temporal_scope is invalid.")
    if document["evidence_source"] in {"safe_skip_truth", "backend_compute_truth"}:
        raise ValueError("Observation-only evidence cannot be declared safe-skip truth.")

    occupancy = bytearray(width * height)
    for label, regions in (
        ("frozen", document["frozen_regions"]),
        ("active", document["active_regions"]),
        ("uncertain", document["uncertain_regions"]),
    ):
        if not isinstance(regions, list):
            raise ValueError(f"{label}_regions must be a list.")
        for candidate in regions:
            x, y, box_width, box_height = _box(candidate, width, height)
            for row in range(y, y + box_height):
                start = row * width + x
                for offset in range(box_width):
                    index = start + offset
                    if occupancy[index]:
                        raise ValueError("State regions overlap; the scope is not a partition.")
                    occupancy[index] = 1
    if any(value == 0 for value in occupancy):
        raise ValueError("Frozen, active, and uncertain regions must cover the full scope.")
    if document["global_invalidation"] and document["frozen_regions"]:
        raise ValueError("Global invalidation forbids preserving a frozen region.")
    if document["uncertain_regions"] and document["fallback_policy"] != "full_compute":
        raise ValueError("Uncertain regions require full-compute fallback.")


def validate_backend_capability_matrix(document: dict[str, Any]) -> None:
    _require_keys(
        document,
        {"schema_version", "backend_id", "capabilities", "fallback_policy"},
        "BackendCapabilityMatrix",
    )
    allowed = {"supported", "experimental", "unsupported", "not_checked"}
    if not document["capabilities"]:
        raise ValueError("A capability matrix must enumerate at least one selector.")
    for capability in document["capabilities"]:
        _require_keys(
            capability,
            {"compute_unit_type", "support_status", "evidence", "skip_authority"},
            "backend capability",
        )
        if capability["support_status"] not in allowed:
            raise ValueError("Backend capability support status is invalid.")
        if capability["support_status"] != "supported" and capability["skip_authority"]:
            raise ValueError("An unsupported or unverified selector cannot schedule skip.")
    if document["fallback_policy"] != "full_compute":
        raise ValueError("The protocol requires a full-compute fallback.")


def validate_execution_topology(document: dict[str, Any]) -> None:
    required = {
        "physical_cpu_cores",
        "logical_cpu_cores",
        "workers",
        "affinity",
        "ram_bytes",
        "gpu_devices",
        "vram_bytes",
        "worker_assignment",
        "compute_granularity",
        "spatial_parallelism",
        "temporal_parallelism",
        "batch_size",
        "streams",
        "queue_policy",
        "synchronization_policy",
        "merge_policy",
        "oversubscription_policy",
    }
    _require_keys(document, required, "ExecutionTopology")
    numeric_fields = (
        "physical_cpu_cores",
        "logical_cpu_cores",
        "workers",
        "ram_bytes",
        "vram_bytes",
        "batch_size",
        "streams",
    )
    for key in numeric_fields:
        _validate_nonnegative_integer_measurement(document[key], f"ExecutionTopology {key}")
    physical = document["physical_cpu_cores"]["value"]
    logical = document["logical_cpu_cores"]["value"]
    if physical is not None and logical is not None and physical > logical:
        raise ValueError("Physical CPU cores cannot exceed logical CPU cores.")


def _validate_measurement(measurement: Any, label: str) -> None:
    if not isinstance(measurement, dict):
        raise ValueError(f"{label} must be a measurement object.")
    _require_keys(measurement, {"value", "status", "reason", "method"}, label)
    if measurement["status"] == "unavailable":
        if measurement != {
            "value": None,
            "status": "unavailable",
            "reason": measurement["reason"],
            "method": "not measured",
        }:
            raise ValueError(
                f"{label} unavailable values require null, a reason, and method 'not measured'."
            )
        if not measurement["reason"]:
            raise ValueError(f"{label} unavailable reason cannot be empty.")
    elif measurement["status"] == "measured":
        if isinstance(measurement["value"], bool) or not isinstance(measurement["value"], Real):
            raise ValueError(f"{label} measured value must be numeric.")
        if not measurement["method"]:
            raise ValueError(f"{label} measurement method cannot be empty.")
    else:
        raise ValueError(f"{label} has an invalid measurement status.")


def _validate_nonnegative_integer_measurement(measurement: Any, label: str) -> None:
    _validate_measurement(measurement, label)
    value = measurement["value"]
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, int) or value < 0
    ):
        raise ValueError(f"{label} measured value must be a non-negative integer.")


def validate_selective_compute_receipt(document: dict[str, Any]) -> None:
    _require_keys(
        document,
        {
            "schema_version",
            "receipt_id",
            "run_status",
            "results_present",
            "costs",
            "resources",
            "fractions",
            "actual_backend_work_reduction",
            "quality_delta",
            "temporal_delta",
            "accepted_result",
            "claims",
        },
        "SelectiveComputeReceipt",
    )
    _require_keys(document["costs"], COST_COMPONENTS, "receipt costs")
    for name in COST_COMPONENTS:
        _validate_measurement(document["costs"][name], f"costs.{name}")
    _require_keys(
        document["resources"],
        {"ram", "vram", "copied_bytes", "transferred_bytes"},
        "receipt resources",
    )
    for name, measurement in document["resources"].items():
        _validate_measurement(measurement, f"resources.{name}")
    _require_keys(document["fractions"], {"active", "frozen", "uncertain"}, "fractions")
    for name in ("actual_backend_work_reduction", "quality_delta", "temporal_delta"):
        _validate_measurement(document[name], name)
    work = document["actual_backend_work_reduction"]
    for claim_name, claim in document["claims"].items():
        _validate_measurement(claim, f"claims.{claim_name}")
        if claim_name in {"speedup", "gpu_savings"} and claim["value"] is not None:
            if work["value"] is None or not document["accepted_result"]:
                raise ValueError(
                    f"{claim_name} requires measured actual backend work reduction "
                    "and an accepted result."
                )
    if document["run_status"] != "protocol_only" or document["results_present"] is not False:
        raise ValueError("This receipt contract is protocol-only with results_present=false.")
    result_measurements = [
        *(document["costs"][name] for name in COST_COMPONENTS),
        *document["resources"].values(),
        document["actual_backend_work_reduction"],
        document["quality_delta"],
        document["temporal_delta"],
        *document["claims"].values(),
    ]
    if any(
        measurement["value"] is not None or measurement["status"] != "unavailable"
        for measurement in result_measurements
    ):
        raise ValueError(
            "results_present=false forbids publishing measured performance results."
        )
    if any(value is not None for value in document["fractions"].values()):
        raise ValueError("results_present=false requires null result fractions.")
    if not document["results_present"] and document["accepted_result"]:
        raise ValueError("A protocol-only receipt cannot declare an accepted result.")


def validate_protocol_config(document: dict[str, Any]) -> None:
    _require_keys(
        document,
        {
            "protocol_status",
            "results_present",
            "model_runs",
            "cuda_runs",
            "backend_integration_runs",
            "topology_performance_runs",
            "paid_external_service_calls",
            "external_personal_data_transfers",
            "protected_evidence_changes",
        },
        "Selective recompute protocol config",
    )
    if document["protocol_status"] != "predeclared":
        raise ValueError("The protocol config must remain predeclared.")
    if document["results_present"] is not False:
        raise ValueError("Protocol-only configuration cannot contain results.")
    execution_counts = {
        name: document[name]
        for name in (
            "model_runs",
            "cuda_runs",
            "backend_integration_runs",
            "topology_performance_runs",
            "paid_external_service_calls",
            "external_personal_data_transfers",
        )
    }
    if any(value != 0 for value in execution_counts.values()):
        raise ValueError(
            "Protocol-only configuration cannot record model, CUDA, backend, "
            "topology, paid-service, or external-data execution."
        )
    if document["protected_evidence_changes"]:
        raise ValueError("The protocol cannot modify protected evidence.")
