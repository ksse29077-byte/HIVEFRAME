"""Exclusive/inclusive Python stage attribution for M1-P0-R2.

This module is model-free. It deliberately reuses the merged reference
semantics while exposing the Python control-plane work as a nested span tree.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import gc
import hashlib
import json
import math
import time
from typing import Any, Iterator

import numpy as np

from hive_probes.rust_io_reference import (
    SCHEMA_VERSION,
    TOPOLOGIES,
    _area,
    _contains,
    _intersects,
    _motion_bbox,
    _unsupported_claims,
    _x2,
    _y2,
    route_eyes,
    validate_sequence,
)


STAGE_TAXONOMY = (
    "input_validation",
    "eye_contract_construction",
    "eye_setup",
    "routing",
    "coordinate_transform",
    "mask_construction",
    "crop_view_construction",
    "array_allocation",
    "explicit_copy",
    "observation",
    "overlap_handling",
    "fusion_input_conversion",
    "fusion",
    "shared_visual_state_construction",
    "compute_plan_construction",
    "receipt_construction",
    "json_serialization",
    "garbage_collection",
)


@dataclass
class _ActiveSpan:
    name: str
    parent: str | None
    started_ns: int
    child_inclusive_ns: int = 0


@dataclass
class SpanRecorder:
    records: list[dict[str, Any]] = field(default_factory=list)
    _stack: list[_ActiveSpan] = field(default_factory=list)

    @contextmanager
    def span(self, name: str) -> Iterator[None]:
        parent = self._stack[-1].name if self._stack else None
        active = _ActiveSpan(name=name, parent=parent, started_ns=time.perf_counter_ns())
        self._stack.append(active)
        try:
            yield
        finally:
            ended_ns = time.perf_counter_ns()
            current = self._stack.pop()
            inclusive_ns = ended_ns - current.started_ns
            exclusive_ns = inclusive_ns - current.child_inclusive_ns
            if exclusive_ns < 0:
                raise RuntimeError(f"Negative exclusive duration for {name}.")
            self.records.append(
                {
                    "stage": name,
                    "parent": parent,
                    "inclusive_ns": inclusive_ns,
                    "exclusive_ns": exclusive_ns,
                    "call_count": 1,
                    "support_status": "collected",
                    "measurement_method": "time.perf_counter_ns nested span",
                }
            )
            if self._stack:
                self._stack[-1].child_inclusive_ns += inclusive_ns


def _input_sha256(sequence: np.ndarray) -> str:
    if not sequence.flags.c_contiguous:
        raise ValueError("R2 requires a contiguous packed input buffer.")
    return hashlib.sha256(memoryview(sequence).cast("B")).hexdigest()


def _observation_from_views(
    profile: dict[str, Any],
    input_sha256: str,
    crops: list[dict[str, Any]],
    motion: np.ndarray,
) -> tuple[list[dict[str, Any]], int]:
    observations: list[dict[str, Any]] = []
    logical_reads = 0
    for crop in crops:
        route = crop["route"]
        sequence_view = crop["sequence_view"]
        motion_view = crop["motion_view"]
        write_motion_view = crop["write_motion_view"]
        receptive_changed = int(np.count_nonzero(motion_view))
        write_changed = (
            0 if write_motion_view is None else int(np.count_nonzero(write_motion_view))
        )
        checksum = int(sequence_view.sum(dtype=np.uint64))
        logical_reads += int(sequence_view.size)
        if route["write_scope"] is None:
            state = "uncertain"
        elif write_changed > 0:
            state = "dirty"
        elif receptive_changed > 0:
            state = "uncertain"
        else:
            state = "stable"
        confidence = {"dirty": 0.99, "stable": 0.9, "uncertain": 0.75}[state]
        observations.append(
            {
                "observation_id": f"{profile['profile_id']}:{route['eye_id']}",
                "eye_id": route["eye_id"],
                "state": state,
                "changed_pixels": receptive_changed,
                "motion_bbox": _motion_bbox(motion, route["receptive_field"]),
                "region_checksum": checksum,
                "confidence": confidence,
                "provenance": {
                    "source_sequence_id": profile["profile_id"],
                    "algorithm": "packed_u8_frame_difference_v0",
                    "input_sha256": input_sha256,
                },
            }
        )
    return observations, logical_reads


def _fusion_inputs(
    routes: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> dict[str, Any]:
    sequence_id = observations[0]["provenance"]["source_sequence_id"]
    global_route = next(
        (route for route in routes if route["eye_type"] == "global_context"), None
    )
    motion_route = next(
        (route for route in routes if route["eye_type"] == "motion_detector"), None
    )
    return {
        "sequence_id": sequence_id,
        "global_source": None
        if global_route is None
        else f"{sequence_id}:{global_route['eye_id']}",
        "motion_source": None
        if motion_route is None
        else f"{sequence_id}:{motion_route['eye_id']}",
    }


def _overlap_sources(
    routes: list[dict[str, Any]], observations: list[dict[str, Any]]
) -> dict[int, list[str]]:
    conflicts: dict[int, list[str]] = {}
    for route_index, route in enumerate(routes):
        scope = route["write_scope"]
        if scope is None or not route["overlap"]:
            continue
        primary = observations[route_index]
        sources: list[str] = []
        for other_index, other_route in enumerate(routes):
            if other_index == route_index or other_route["write_scope"] is None:
                continue
            other = observations[other_index]
            if (
                _intersects(other_route["receptive_field"], scope)
                and other["changed_pixels"] > 0
                and other["state"] != primary["state"]
            ):
                sources.append(other["observation_id"])
        conflicts[route_index] = sources
    return conflicts


def _fused_regions(
    routes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    fusion_inputs: dict[str, Any],
    conflicts: dict[int, list[str]],
) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for route_index, route in enumerate(routes):
        scope = route["write_scope"]
        if scope is None:
            continue
        primary = observations[route_index]
        sources = [
            source
            for source in (
                fusion_inputs["global_source"],
                fusion_inputs["motion_source"],
            )
            if source is not None
        ]
        sources.append(primary["observation_id"])
        sources.extend(conflicts.get(route_index, ()))
        regions.append(
            {
                "region_id": f"fused:{route['eye_id']}",
                "scope": scope,
                "state": "uncertain" if conflicts.get(route_index) else primary["state"],
                "confidence": primary["confidence"],
                "sources": sorted(set(sources)),
            }
        )
    return regions


def _compute_plan(shared_state: dict[str, Any]) -> dict[str, Any]:
    actions = {"dirty": "generate", "stable": "reuse_cache", "uncertain": "reconcile"}
    return {
        "policy": "backend_neutral_candidate_v0",
        "units": [
            {
                "unit_id": f"unit-{index:03d}",
                "action": actions[region["state"]],
                "scope": region["scope"],
                "source_observation_ids": region["sources"],
            }
            for index, region in enumerate(shared_state["regions"])
        ],
        "claims": _unsupported_claims(),
    }


def run_attributed(
    profile: dict[str, Any], topology: str, sequence: np.ndarray
) -> dict[str, Any]:
    recorder = SpanRecorder()
    logical_reads = 0
    allocated_bytes = 0
    temporary_bytes = 0
    json_bytes = 0

    with recorder.span("total"):
        with recorder.span("input_validation"):
            validate_sequence(profile, sequence)

        with recorder.span("receipt_construction"):
            input_sha256 = _input_sha256(sequence)

        with recorder.span("routing"):
            with recorder.span("eye_contract_construction"):
                if topology not in TOPOLOGIES:
                    raise ValueError(f"Unknown eye topology: {topology}")
                eye_contract = (profile["profile_id"], topology, profile["seed"])
                if eye_contract[1] != topology:
                    raise AssertionError("Eye contract construction failed.")

            with recorder.span("array_allocation"):
                differences = np.empty(
                    (profile["frames"] - 1, profile["height"], profile["width"]),
                    dtype=np.bool_,
                )
                motion = np.empty((profile["height"], profile["width"]), dtype=np.bool_)
                allocated_bytes = int(differences.nbytes + motion.nbytes)
                temporary_bytes += allocated_bytes

            with recorder.span("mask_construction"):
                np.not_equal(sequence[1:], sequence[:-1], out=differences)
                np.logical_or.reduce(differences, axis=0, out=motion)
                logical_reads += 2 * int(differences.size)

            with recorder.span("eye_setup"):
                routes = route_eyes(profile, topology, motion)

            with recorder.span("coordinate_transform"):
                transform_checksum = sum(
                    route["local_to_global"][0]
                    + route["local_to_global"][1]
                    + route["receptive_field"]["width"]
                    + route["receptive_field"]["height"]
                    for route in routes
                )
                if transform_checksum < 0:
                    raise AssertionError("Unreachable coordinate checksum.")

        with recorder.span("observation"):
            with recorder.span("crop_view_construction"):
                crops: list[dict[str, Any]] = []
                for route in routes:
                    receptive = route["receptive_field"]
                    write_scope = route["write_scope"]
                    crops.append(
                        {
                            "route": route,
                            "sequence_view": sequence[
                                :,
                                receptive["y"] : _y2(receptive),
                                receptive["x"] : _x2(receptive),
                            ],
                            "motion_view": motion[
                                receptive["y"] : _y2(receptive),
                                receptive["x"] : _x2(receptive),
                            ],
                            "write_motion_view": None
                            if write_scope is None
                            else motion[
                                write_scope["y"] : _y2(write_scope),
                                write_scope["x"] : _x2(write_scope),
                            ],
                        }
                    )
            observations, observation_reads = _observation_from_views(
                profile, input_sha256, crops, motion
            )
            logical_reads += observation_reads

        with recorder.span("fusion"):
            with recorder.span("fusion_input_conversion"):
                fusion_inputs = _fusion_inputs(routes, observations)
            with recorder.span("overlap_handling"):
                conflicts = _overlap_sources(routes, observations)
            regions = _fused_regions(routes, observations, fusion_inputs, conflicts)
            with recorder.span("shared_visual_state_construction"):
                shared_state = {
                    "policy": "deterministic_conservative_io_v0",
                    "regions": regions,
                    "observation_ids": sorted(
                        observation["observation_id"] for observation in observations
                    ),
                }

        with recorder.span("compute_plan_construction"):
            compute_plan = _compute_plan(shared_state)

        with recorder.span("receipt_construction"):
            overlap_numerator = 0
            overlap_denominator = 0
            for route in routes:
                if route["write_scope"] is None:
                    continue
                overlap_denominator += _area(route["write_scope"])
                overlap_numerator += max(
                    0, _area(route["receptive_field"]) - _area(route["write_scope"])
                )
            semantic = {
                "schema_version": SCHEMA_VERSION,
                "profile_id": profile["profile_id"],
                "topology": topology,
                "input": {
                    "width": profile["width"],
                    "height": profile["height"],
                    "frames": profile["frames"],
                    "seed": profile["seed"],
                    "byte_length": int(sequence.nbytes),
                    "sha256": input_sha256,
                },
                "eyes": routes,
                "observations": observations,
                "shared_visual_state": shared_state,
                "compute_plan": compute_plan,
            }
            for route in routes:
                if route["local_to_global"] != [
                    route["receptive_field"]["x"],
                    route["receptive_field"]["y"],
                ]:
                    raise ValueError("Local-to-global transform mismatch.")
                if route["write_scope"] is not None and not _contains(
                    route["receptive_field"], route["write_scope"]
                ):
                    raise ValueError("Write scope exceeds receptive field.")
            with recorder.span("json_serialization"):
                encoded = json.dumps(
                    semantic,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                json_bytes = len(encoded)
            semantic_digest = hashlib.sha256(encoded).hexdigest()

        with recorder.span("garbage_collection"):
            gc.collect(0)

    by_stage: dict[str, dict[str, Any]] = {}
    total_record = next(record for record in recorder.records if record["stage"] == "total")
    for stage in STAGE_TAXONOMY:
        matching = [record for record in recorder.records if record["stage"] == stage]
        if not matching:
            if stage != "explicit_copy":
                raise RuntimeError(f"Missing attributed stage: {stage}")
            by_stage[stage] = {
                "stage": stage,
                "parent": None,
                "inclusive_ns": 0,
                "exclusive_ns": 0,
                "call_count": 0,
                "support_status": "collected",
                "measurement_method": "no explicit copy operation in NumPy view path",
            }
            continue
        by_stage[stage] = {
            "stage": stage,
            "parent": matching[0]["parent"],
            "inclusive_ns": sum(record["inclusive_ns"] for record in matching),
            "exclusive_ns": sum(record["exclusive_ns"] for record in matching),
            "call_count": len(matching),
            "support_status": "collected",
            "measurement_method": "time.perf_counter_ns nested span",
        }
    attributed_ns = sum(record["exclusive_ns"] for record in by_stage.values())
    unattributed_ns = total_record["inclusive_ns"] - attributed_ns
    if unattributed_ns < 0:
        raise RuntimeError("Attributed Python time exceeds the total span.")
    return {
        "semantic_result": semantic,
        "semantic_hash": semantic_digest,
        "total_ns": total_record["inclusive_ns"],
        "stages": by_stage,
        "attributed_exclusive_ns": attributed_ns,
        "unattributed_ns": unattributed_ns,
        "counters": {
            "logical_bytes_read": logical_reads,
            "array_allocation_bytes": allocated_bytes,
            "bytes_copied": 0,
            "temporary_buffer_bytes": temporary_bytes,
            "json_serialization_bytes": json_bytes,
        },
    }


def calibrate_instrumentation(repetitions: int) -> dict[str, Any]:
    if repetitions <= 0:
        raise ValueError("Instrumentation calibration repetitions must be positive.")
    totals: list[int] = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        recorder = SpanRecorder()
        with recorder.span("total"):
            with recorder.span("routing"):
                for child in (
                    "eye_contract_construction",
                    "array_allocation",
                    "mask_construction",
                    "eye_setup",
                    "coordinate_transform",
                ):
                    with recorder.span(child):
                        pass
            with recorder.span("observation"):
                with recorder.span("crop_view_construction"):
                    pass
            with recorder.span("fusion"):
                for child in (
                    "fusion_input_conversion",
                    "overlap_handling",
                    "shared_visual_state_construction",
                ):
                    with recorder.span(child):
                        pass
            with recorder.span("input_validation"):
                pass
            with recorder.span("compute_plan_construction"):
                pass
            with recorder.span("receipt_construction"):
                with recorder.span("json_serialization"):
                    pass
            with recorder.span("garbage_collection"):
                pass
        totals.append(time.perf_counter_ns() - started)
    ordered = sorted(totals)
    return {
        "repetitions": repetitions,
        "p50_ns": ordered[math.ceil(0.50 * len(ordered)) - 1],
        "p95_ns": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "method": "empty nested span tree measured with time.perf_counter_ns",
        "subtracted_from_results": False,
    }
