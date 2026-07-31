"""Conservative deterministic fusion for compound-eye v0 observations."""

from __future__ import annotations

from typing import Any

from hive_visual_state.contracts import PixelBox, SCHEMA_VERSION, hash_json


def _source(observation: dict[str, Any], region: dict[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": observation["observation_id"],
        "eye_id": observation["eye_id"],
        "reported_state": region["state"],
        "confidence": region["confidence"],
    }


def fuse_observations(
    observations: list[dict[str, Any]],
    *,
    canvas: dict[str, int],
) -> dict[str, Any]:
    if not observations:
        raise ValueError("Sensory Fusion requires at least one observation.")
    sequence_ids = {item["source_sequence_id"] for item in observations}
    input_hashes = {item["provenance"]["input_sha256"] for item in observations}
    if len(sequence_ids) != 1 or len(input_hashes) != 1:
        raise ValueError("All observations must describe the same input sequence.")

    global_observation = next(
        (
            item
            for item in observations
            if item["eye_type"] == "global_low_resolution"
        ),
        None,
    )
    if global_observation is None:
        raise ValueError("SharedVisualState requires one global context eye.")

    motion_regions: list[tuple[dict[str, Any], dict[str, Any], PixelBox]] = []
    for observation in observations:
        if observation["eye_type"] == "frame_difference_motion":
            for region in observation["regions"]:
                motion_regions.append(
                    (observation, region, PixelBox(*region["pixel_xywh"]))
                )

    fused_regions: list[dict[str, Any]] = []
    for observation in observations:
        if observation["eye_type"] != "regional":
            continue
        for region in observation["regions"]:
            box = PixelBox(*region["pixel_xywh"])
            sources = [_source(observation, region)]
            intersecting_motion = [
                item for item in motion_regions if box.intersects(item[2])
            ]
            sources.extend(_source(item[0], item[1]) for item in intersecting_motion)
            reported = {source["reported_state"] for source in sources}
            if reported == {"stable"}:
                state = "stable"
            elif "dirty" in reported and region["state"] == "dirty":
                state = "dirty"
            else:
                state = "uncertain"
            fused_regions.append(
                {
                    "region_id": f"fused:{region['region_id']}",
                    "pixel_xywh": region["pixel_xywh"],
                    "state": state,
                    "confidence": round(
                        min(source["confidence"] for source in sources), 8
                    ),
                    "sources": sources,
                }
            )

    for observation in observations:
        if observation["eye_type"] != "overlap_boundary":
            continue
        for region in observation["regions"]:
            if region["state"] != "uncertain":
                continue
            fused_regions.append(
                {
                    "region_id": f"fused:{region['region_id']}",
                    "pixel_xywh": region["pixel_xywh"],
                    "state": "uncertain",
                    "confidence": region["confidence"],
                    "sources": [_source(observation, region)],
                }
            )

    observation_ids = sorted(item["observation_id"] for item in observations)
    observation_hashes = sorted(hash_json(item) for item in observations)
    state = {
        "schema_version": SCHEMA_VERSION,
        "state_id": f"{next(iter(sequence_ids))}:shared-v0",
        "source_sequence_id": next(iter(sequence_ids)),
        "canvas": canvas,
        "global_context": {
            "source_observation_id": global_observation["observation_id"],
            "mean_intensity": global_observation["features"]["mean_intensity"],
            "low_resolution_shape": global_observation["features"][
                "low_resolution_shape"
            ],
        },
        "regions": fused_regions,
        "observation_ids": observation_ids,
        "fusion_policy": "deterministic_conservative_v0",
        "provenance": {
            "input_sha256": next(iter(input_hashes)),
            "observation_sha256": observation_hashes,
        },
    }
    return state
