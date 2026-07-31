"""Small, strict helpers for the compound-eye v0 reference contracts.

The JSON Schemas are the interchange definitions. These checks deliberately
cover semantic invariants that JSON Schema alone does not express, such as
pixel/normalized coordinate agreement and bounded write scopes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable


SCHEMA_VERSION = "0.1.0"
EYE_TYPES = {
    "global_low_resolution",
    "regional",
    "overlap_boundary",
    "frame_difference_motion",
}
REGION_STATES = {"dirty", "stable", "uncertain"}


def _rounded(value: float) -> float:
    return round(float(value), 8)


def hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def unsupported_measurement(
    *,
    unit: str,
    reason: str,
    measurement_method: str,
    status: str = "not_collected",
) -> dict[str, Any]:
    if status not in {"unsupported", "not_collected"}:
        raise ValueError(f"Unsupported measurement status: {status}")
    return {
        "value": None,
        "unit": unit,
        "support_status": status,
        "reason": reason,
        "measurement_method": measurement_method,
    }


@dataclass(frozen=True)
class PixelBox:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.x < 0 or self.y < 0:
            raise ValueError("PixelBox origin must be non-negative.")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("PixelBox dimensions must be positive.")

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    def as_list(self) -> list[int]:
        return [self.x, self.y, self.width, self.height]

    def normalized(self, canvas_width: int, canvas_height: int) -> list[float]:
        self.assert_within(canvas_width, canvas_height)
        return [
            _rounded(self.x / canvas_width),
            _rounded(self.y / canvas_height),
            _rounded(self.width / canvas_width),
            _rounded(self.height / canvas_height),
        ]

    def assert_within(self, canvas_width: int, canvas_height: int) -> None:
        if self.x2 > canvas_width or self.y2 > canvas_height:
            raise ValueError(
                f"PixelBox {self.as_list()} exceeds "
                f"{canvas_width}x{canvas_height} canvas."
            )

    def intersects(self, other: "PixelBox") -> bool:
        return not (
            self.x2 <= other.x
            or other.x2 <= self.x
            or self.y2 <= other.y
            or other.y2 <= self.y
        )

    def contains(self, other: "PixelBox") -> bool:
        return (
            self.x <= other.x
            and self.y <= other.y
            and self.x2 >= other.x2
            and self.y2 >= other.y2
        )


def make_window(
    *,
    window_id: str,
    box: PixelBox,
    canvas_width: int,
    canvas_height: int,
    frames: int,
) -> dict[str, Any]:
    box.assert_within(canvas_width, canvas_height)
    return {
        "window_id": window_id,
        "pixel_xywh": box.as_list(),
        "normalized_xywh": box.normalized(canvas_width, canvas_height),
        "frame_range": [0, frames],
        "local_to_global": {
            "scale_xy": [1.0, 1.0],
            "offset_xy": [box.x, box.y],
        },
    }


def _require_keys(value: dict[str, Any], keys: Iterable[str], label: str) -> None:
    missing = sorted(set(keys) - set(value))
    if missing:
        raise ValueError(f"{label} is missing required keys: {missing}")


def _validate_window(
    window: dict[str, Any],
    *,
    canvas_width: int,
    canvas_height: int,
    frames: int,
) -> PixelBox:
    _require_keys(
        window,
        {
            "window_id",
            "pixel_xywh",
            "normalized_xywh",
            "frame_range",
            "local_to_global",
        },
        "window",
    )
    box = PixelBox(*[int(value) for value in window["pixel_xywh"]])
    box.assert_within(canvas_width, canvas_height)
    expected_normalized = box.normalized(canvas_width, canvas_height)
    actual_normalized = [_rounded(value) for value in window["normalized_xywh"]]
    if actual_normalized != expected_normalized:
        raise ValueError(
            f"Window {window['window_id']} normalized coordinates do not "
            "match its pixel coordinates."
        )
    if window["frame_range"] != [0, frames]:
        raise ValueError(f"Window {window['window_id']} has an invalid frame range.")
    transform = window["local_to_global"]
    if transform["scale_xy"] != [1.0, 1.0]:
        raise ValueError("Reference windows use an identity pixel scale.")
    if transform["offset_xy"] != [box.x, box.y]:
        raise ValueError("Window local-to-global offset does not match its origin.")
    return box


def validate_eye_contract(
    contract: dict[str, Any],
    *,
    canvas_width: int,
    canvas_height: int,
    frames: int,
) -> None:
    _require_keys(
        contract,
        {
            "schema_version",
            "eye_id",
            "eye_type",
            "purpose",
            "receptive_field",
            "sampling",
            "write_policy",
            "outputs",
        },
        "EyeContract",
    )
    if contract["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported EyeContract schema version.")
    if contract["eye_type"] not in EYE_TYPES:
        raise ValueError(f"Unknown eye type: {contract['eye_type']}")
    windows = contract["receptive_field"]["windows"]
    if not windows:
        raise ValueError("An eye must declare at least one receptive window.")
    receptive_boxes = [
        _validate_window(
            window,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            frames=frames,
        )
        for window in windows
    ]
    write_policy = contract["write_policy"]
    if write_policy["mode"] == "read_only" and write_policy["windows"]:
        raise ValueError("A read-only eye cannot declare write windows.")
    for write_window in write_policy["windows"]:
        write_box = _validate_window(
            write_window,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            frames=frames,
        )
        if not any(box.contains(write_box) for box in receptive_boxes):
            raise ValueError("Write scope exceeds the eye receptive field.")


def validate_eye_observation(
    observation: dict[str, Any],
    contract: dict[str, Any],
    *,
    canvas_width: int,
    canvas_height: int,
    frames: int,
) -> None:
    _require_keys(
        observation,
        {
            "schema_version",
            "observation_id",
            "eye_id",
            "eye_type",
            "source_sequence_id",
            "seed",
            "receptive_field",
            "write_scope",
            "features",
            "regions",
            "confidence",
            "provenance",
            "unsupported_metrics",
        },
        "EyeObservation",
    )
    if observation["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported EyeObservation schema version.")
    if observation["eye_id"] != contract["eye_id"]:
        raise ValueError("Observation eye ID does not match its contract.")
    if observation["eye_type"] != contract["eye_type"]:
        raise ValueError("Observation eye type does not match its contract.")
    if observation["receptive_field"] != contract["receptive_field"]:
        raise ValueError("Observation receptive field differs from its contract.")
    if observation["write_scope"] != contract["write_policy"]:
        raise ValueError("Observation write scope differs from its contract.")
    validate_eye_contract(
        contract,
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        frames=frames,
    )
    write_boxes = [
        PixelBox(*window["pixel_xywh"])
        for window in observation["write_scope"]["windows"]
    ]
    for region in observation["regions"]:
        if region["state"] not in REGION_STATES:
            raise ValueError(f"Unknown region state: {region['state']}")
        box = PixelBox(*region["pixel_xywh"])
        box.assert_within(canvas_width, canvas_height)
        if (
            observation["write_scope"]["mode"] == "bounded"
            and not any(scope.contains(box) for scope in write_boxes)
        ):
            raise ValueError("Observation region exceeds its bounded write scope.")
    for metric in observation["unsupported_metrics"]:
        if metric["value"] is not None:
            raise ValueError("Unsupported metrics must use null, never a fake number.")
        if metric["support_status"] not in {"unsupported", "not_collected"}:
            raise ValueError("Unsupported metric status is invalid.")


def validate_shared_visual_state(state: dict[str, Any]) -> None:
    _require_keys(
        state,
        {
            "schema_version",
            "state_id",
            "source_sequence_id",
            "canvas",
            "global_context",
            "regions",
            "observation_ids",
            "fusion_policy",
            "provenance",
        },
        "SharedVisualState",
    )
    if state["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported SharedVisualState schema version.")
    if state["fusion_policy"] != "deterministic_conservative_v0":
        raise ValueError("Unknown fusion policy.")
    observation_ids = set(state["observation_ids"])
    if state["global_context"]["source_observation_id"] not in observation_ids:
        raise ValueError("Global context has no source observation.")
    for region in state["regions"]:
        if region["state"] not in REGION_STATES:
            raise ValueError("Shared state contains an unknown region state.")
        if not region["sources"]:
            raise ValueError("Fused regions must preserve at least one source.")
        for source in region["sources"]:
            if source["observation_id"] not in observation_ids:
                raise ValueError("Fused region source is missing from provenance.")


def build_compute_plan(state: dict[str, Any]) -> dict[str, Any]:
    validate_shared_visual_state(state)
    decision_by_state = {
        "dirty": "generate",
        "stable": "reuse_cache",
        "uncertain": "reconcile",
    }
    selectors_by_state = {
        "dirty": {
            "patch": True,
            "token": "region_only",
            "block": "backend_decides",
            "timestep": "backend_decides",
            "resolution": "full",
            "cache": "bypass",
        },
        "stable": {
            "patch": False,
            "token": "none",
            "block": "none",
            "timestep": "none",
            "resolution": "none",
            "cache": "reuse",
        },
        "uncertain": {
            "patch": True,
            "token": "backend_decides",
            "block": "backend_decides",
            "timestep": "candidate",
            "resolution": "backend_decides",
            "cache": "refresh",
        },
    }
    reason_by_state = {
        "dirty": "Observed change requires selective generation.",
        "stable": "No observed change; cache reuse is a candidate, not a speedup claim.",
        "uncertain": "Conflicting or boundary evidence requires reconciliation.",
    }
    execution_units = []
    for index, region in enumerate(state["regions"]):
        source_ids = sorted(
            {source["observation_id"] for source in region["sources"]}
        )
        execution_units.append(
            {
                "unit_id": f"unit-{index:03d}",
                "region_id": region["region_id"],
                "pixel_xywh": region["pixel_xywh"],
                "observed_state": region["state"],
                "decision": decision_by_state[region["state"]],
                "selectors": selectors_by_state[region["state"]],
                "confidence": region["confidence"],
                "source_observation_ids": source_ids,
                "reason": reason_by_state[region["state"]],
            }
        )
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": f"{state['state_id']}:compute-plan-v0",
        "source_state_id": state["state_id"],
        "policy": "selective_generation_reference_v0",
        "execution_units": execution_units,
        "claims": {
            "actual_sparse_speedup": unsupported_measurement(
                unit="ratio",
                status="not_collected",
                reason=(
                    "The reference simulation does not execute a generation backend."
                ),
                measurement_method="requires same-condition backend experiment",
            ),
            "gpu_kernel_seconds": unsupported_measurement(
                unit="seconds",
                status="unsupported",
                reason="The reference simulation has no CUDA execution path.",
                measurement_method="requires a GPU profiler in a separate run",
            ),
        },
    }
    validate_compute_plan(plan)
    return plan


def validate_compute_plan(plan: dict[str, Any]) -> None:
    _require_keys(
        plan,
        {
            "schema_version",
            "plan_id",
            "source_state_id",
            "policy",
            "execution_units",
            "claims",
        },
        "ComputePlan",
    )
    if plan["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported ComputePlan schema version.")
    if plan["policy"] != "selective_generation_reference_v0":
        raise ValueError("Unknown compute-plan policy.")
    for unit in plan["execution_units"]:
        expected = {
            "dirty": "generate",
            "stable": "reuse_cache",
            "uncertain": "reconcile",
        }[unit["observed_state"]]
        if unit["decision"] != expected:
            raise ValueError("Compute decision contradicts observed region state.")
    for claim in plan["claims"].values():
        if claim["value"] is not None:
            raise ValueError("Unmeasured compute claims must be null.")
