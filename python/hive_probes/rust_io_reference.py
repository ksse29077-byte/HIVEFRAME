"""Model-free Python reference for the Rust I/O admission experiment.

This module preserves the existing Compound-Eye contract semantics while
adding configurable topologies and measurable orchestration spans. It never
imports Torch, a model backend, or CUDA.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import platform
import sys
import threading
import time
from typing import Any

import numpy as np


SCHEMA_VERSION = "0.1.0"
RUN_KIND = "rust_io_admission_probe"
TOPOLOGIES = (
    "mono_1x1",
    "uniform_2x2",
    "uniform_4x4",
    "overlap_2x2",
    "motion_focused",
)


def _box(x: int, y: int, width: int, height: int) -> dict[str, int]:
    if min(x, y) < 0 or min(width, height) <= 0:
        raise ValueError("PixelBox origin and dimensions are invalid.")
    return {"x": x, "y": y, "width": width, "height": height}


def _x2(box: dict[str, int]) -> int:
    return box["x"] + box["width"]


def _y2(box: dict[str, int]) -> int:
    return box["y"] + box["height"]


def _area(box: dict[str, int]) -> int:
    return box["width"] * box["height"]


def _contains(outer: dict[str, int], inner: dict[str, int]) -> bool:
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and _x2(outer) >= _x2(inner)
        and _y2(outer) >= _y2(inner)
    )


def _intersects(left: dict[str, int], right: dict[str, int]) -> bool:
    return not (
        _x2(left) <= right["x"]
        or _x2(right) <= left["x"]
        or _y2(left) <= right["y"]
        or _y2(right) <= left["y"]
    )


def _expand(
    box: dict[str, int],
    halo: int,
    width: int,
    height: int,
) -> dict[str, int]:
    x = max(0, box["x"] - halo)
    y = max(0, box["y"] - halo)
    x2 = min(width, _x2(box) + halo)
    y2 = min(height, _y2(box) + halo)
    return _box(x, y, x2 - x, y2 - y)


def input_profile(name: str, seed: int = 101) -> dict[str, Any]:
    profiles = {
        "low": (
            640,
            384,
            16,
            [_box(324, 112, 24, 32)],
        ),
        "medium": (
            1280,
            720,
            16,
            [
                _box(646, 176, 48, 52),
                _box(286, 364, 64, 48),
            ],
        ),
        "high": (
            1920,
            1080,
            8,
            [
                _box(968, 238, 72, 84),
                _box(442, 544, 96, 68),
                _box(1420, 784, 110, 72),
            ],
        ),
        "extended": (
            3840,
            2160,
            4,
            [
                _box(1932, 480, 128, 144),
                _box(872, 1092, 180, 100),
            ],
        ),
    }
    try:
        width, height, frames, changes = profiles[name]
    except KeyError as error:
        raise ValueError(f"Unknown input profile: {name}") from error
    profile = {
        "profile_id": name,
        "width": width,
        "height": height,
        "frames": frames,
        "seed": seed,
        "change_regions": changes,
    }
    validate_profile(profile)
    return profile


def validate_profile(profile: dict[str, Any]) -> None:
    if (
        profile["frames"] < 2
        or profile["width"] <= 0
        or profile["height"] <= 0
    ):
        raise ValueError(
            "Input shape must contain at least two non-empty grayscale frames."
        )
    canvas = _box(0, 0, profile["width"], profile["height"])
    if any(not _contains(canvas, region) for region in profile["change_regions"]):
        raise ValueError("Synthetic change region exceeds the input canvas.")


def validate_sequence(profile: dict[str, Any], sequence: np.ndarray) -> None:
    validate_profile(profile)
    expected = (profile["frames"], profile["height"], profile["width"])
    if not isinstance(sequence, np.ndarray):
        raise TypeError("Sequence must be a NumPy array.")
    if sequence.shape != expected:
        raise ValueError(
            f"Input shape {sequence.shape} does not match declared shape {expected}."
        )
    if sequence.dtype != np.uint8:
        raise TypeError("Admission frames must use packed uint8 grayscale storage.")


def generate_sequence(profile: dict[str, Any]) -> np.ndarray:
    validate_profile(profile)
    y, x = np.indices(
        (profile["height"], profile["width"]),
        dtype=np.uint64,
    )
    base = (
        (np.uint64(profile["seed"]) + x * np.uint64(3) + y * np.uint64(5))
        % np.uint64(64)
    ).astype(np.uint8)
    sequence = np.repeat(base[None, :, :], profile["frames"], axis=0)
    for region in profile["change_regions"]:
        view = sequence[
            profile["frames"] // 2 :,
            region["y"] : _y2(region),
            region["x"] : _x2(region),
        ]
        view[:] = np.minimum(view.astype(np.uint16) + 160, 255).astype(np.uint8)
    validate_sequence(profile, sequence)
    return sequence


def _input_sha256(sequence: np.ndarray) -> str:
    return hashlib.sha256(sequence.tobytes(order="C")).hexdigest()


def _motion_map(
    profile: dict[str, Any],
    sequence: np.ndarray,
) -> tuple[np.ndarray, int, int]:
    differences = sequence[1:] != sequence[:-1]
    motion = np.any(differences, axis=0)
    logical_reads = 2 * (profile["frames"] - 1) * profile["width"] * profile["height"]
    temporary_bytes = int(differences.nbytes + motion.nbytes)
    return motion, logical_reads, temporary_bytes


def _motion_bbox(
    motion: np.ndarray,
    region: dict[str, int] | None = None,
) -> dict[str, int] | None:
    if region is None:
        x0, y0 = 0, 0
        view = motion
    else:
        x0, y0 = region["x"], region["y"]
        view = motion[y0 : _y2(region), x0 : _x2(region)]
    ys, xs = np.where(view)
    if len(xs) == 0:
        return None
    return _box(
        x0 + int(xs.min()),
        y0 + int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )


def _grid_boxes(
    profile: dict[str, Any],
    columns: int,
    rows: int,
) -> list[dict[str, int]]:
    boxes = []
    for row in range(rows):
        y = row * profile["height"] // rows
        y2 = (row + 1) * profile["height"] // rows
        for column in range(columns):
            x = column * profile["width"] // columns
            x2 = (column + 1) * profile["width"] // columns
            boxes.append(_box(x, y, x2 - x, y2 - y))
    return boxes


def _route(
    eye_id: str,
    eye_type: str,
    receptive: dict[str, int],
    write_scope: dict[str, int] | None,
    overlap: bool,
) -> dict[str, Any]:
    return {
        "eye_id": eye_id,
        "eye_type": eye_type,
        "receptive_field": receptive,
        "write_scope": write_scope,
        "local_to_global": [receptive["x"], receptive["y"]],
        "overlap": overlap,
    }


def route_eyes(
    profile: dict[str, Any],
    topology: str,
    motion: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    if topology not in TOPOLOGIES:
        raise ValueError(f"Unknown eye topology: {topology}")
    full = _box(0, 0, profile["width"], profile["height"])

    def global_route() -> dict[str, Any]:
        return _route("global-context", "global_context", dict(full), None, False)

    if topology == "mono_1x1":
        return [_route("mono-0", "mono", dict(full), dict(full), False)]
    if topology in {"uniform_2x2", "uniform_4x4"}:
        size = 2 if topology == "uniform_2x2" else 4
        routes = [global_route()]
        for index, scope in enumerate(_grid_boxes(profile, size, size)):
            routes.append(
                _route(
                    f"regional-{size}x{size}-{index:02d}",
                    "regional",
                    dict(scope),
                    scope,
                    False,
                )
            )
        return routes
    if topology == "overlap_2x2":
        halo = max(4, min(profile["width"], profile["height"]) // 32)
        routes = [global_route()]
        for index, scope in enumerate(_grid_boxes(profile, 2, 2)):
            routes.append(
                _route(
                    f"overlap-2x2-{index:02d}",
                    "overlap_regional",
                    _expand(
                        scope,
                        halo,
                        profile["width"],
                        profile["height"],
                    ),
                    scope,
                    True,
                )
            )
        return routes
    if motion is None:
        raise ValueError(
            "motion_focused routing requires a frame-difference map."
        )
    routes = [
        global_route(),
        _route("motion-detector", "motion_detector", dict(full), None, False),
    ]
    changed = _motion_bbox(motion)
    if changed is not None:
        halo = max(2, min(profile["width"], profile["height"]) // 64)
        focused = _expand(
            changed,
            halo,
            profile["width"],
            profile["height"],
        )
        routes.append(
            _route(
                "motion-focus-00",
                "motion_focused",
                focused,
                dict(focused),
                False,
            )
        )
    return routes


def _changed_count(motion: np.ndarray, region: dict[str, int]) -> int:
    return int(
        np.count_nonzero(
            motion[
                region["y"] : _y2(region),
                region["x"] : _x2(region),
            ]
        )
    )


def _region_checksum(
    sequence: np.ndarray,
    region: dict[str, int],
) -> tuple[int, int]:
    view = sequence[
        :,
        region["y"] : _y2(region),
        region["x"] : _x2(region),
    ]
    return int(view.sum(dtype=np.uint64)), int(view.size)


def _observe(
    profile: dict[str, Any],
    sequence: np.ndarray,
    input_sha256: str,
    routes: list[dict[str, Any]],
    motion: np.ndarray,
) -> tuple[list[dict[str, Any]], int]:
    observations = []
    logical_reads = 0
    for route in routes:
        receptive_changed = _changed_count(motion, route["receptive_field"])
        write_changed = (
            0
            if route["write_scope"] is None
            else _changed_count(motion, route["write_scope"])
        )
        checksum, reads = _region_checksum(sequence, route["receptive_field"])
        logical_reads += reads
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
                "observation_id": (
                    f"{profile['profile_id']}:{route['eye_id']}"
                ),
                "eye_id": route["eye_id"],
                "state": state,
                "changed_pixels": receptive_changed,
                "motion_bbox": _motion_bbox(
                    motion,
                    route["receptive_field"],
                ),
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


def _fuse(
    routes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    sequence_id = observations[0]["provenance"]["source_sequence_id"]
    global_route = next(
        (route for route in routes if route["eye_type"] == "global_context"),
        None,
    )
    motion_route = next(
        (route for route in routes if route["eye_type"] == "motion_detector"),
        None,
    )
    global_source = (
        None
        if global_route is None
        else f"{sequence_id}:{global_route['eye_id']}"
    )
    motion_source = (
        None
        if motion_route is None
        else f"{sequence_id}:{motion_route['eye_id']}"
    )
    regions = []
    for route_index, route in enumerate(routes):
        scope = route["write_scope"]
        if scope is None:
            continue
        primary = observations[route_index]
        state = primary["state"]
        sources = [
            source
            for source in (global_source, motion_source)
            if source is not None
        ]
        sources.append(primary["observation_id"])
        if route["overlap"]:
            for other_index, other_route in enumerate(routes):
                if (
                    other_index == route_index
                    or other_route["write_scope"] is None
                ):
                    continue
                other = observations[other_index]
                if (
                    _intersects(other_route["receptive_field"], scope)
                    and other["changed_pixels"] > 0
                    and other["state"] != primary["state"]
                ):
                    state = "uncertain"
                    sources.append(other["observation_id"])
        regions.append(
            {
                "region_id": f"fused:{route['eye_id']}",
                "scope": scope,
                "state": state,
                "confidence": primary["confidence"],
                "sources": sorted(set(sources)),
            }
        )
    return {
        "policy": "deterministic_conservative_io_v0",
        "regions": regions,
        "observation_ids": sorted(
            observation["observation_id"] for observation in observations
        ),
    }


def _unsupported_claims() -> list[dict[str, Any]]:
    return [
        {
            "name": "actual_sparse_speedup",
            "value": None,
            "unit": "ratio",
            "status": "uncollected",
            "reason": "The admission probe does not execute a model backend.",
            "method": "requires a same-condition backend experiment",
        },
        {
            "name": "gpu_kernel_seconds",
            "value": None,
            "unit": "seconds",
            "status": "unsupported",
            "reason": "The admission probe has no CUDA execution path.",
            "method": "requires a separate GPU profiler run",
        },
    ]


def _compile_plan(shared_state: dict[str, Any]) -> dict[str, Any]:
    actions = {
        "dirty": "generate",
        "stable": "reuse_cache",
        "uncertain": "reconcile",
    }
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


def semantic_hash(result: dict[str, Any]) -> str:
    encoded = json.dumps(
        result,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_pipeline(
    profile: dict[str, Any],
    topology: str,
    sequence: np.ndarray,
) -> dict[str, Any]:
    validate_sequence(profile, sequence)
    total_started = time.perf_counter_ns()
    input_sha256 = _input_sha256(sequence)
    logical_reads = 0
    temporary_buffer_bytes = 0

    routing_started = time.perf_counter_ns()
    precomputed_motion = None
    if topology == "motion_focused":
        (
            precomputed_motion,
            motion_reads,
            motion_temporary,
        ) = _motion_map(profile, sequence)
        logical_reads += motion_reads
        temporary_buffer_bytes += motion_temporary
    routes = route_eyes(profile, topology, precomputed_motion)
    routing_ns = time.perf_counter_ns() - routing_started

    coordinate_started = time.perf_counter_ns()
    transform_checksum = sum(
        route["local_to_global"][0]
        + route["local_to_global"][1]
        + route["receptive_field"]["width"]
        + route["receptive_field"]["height"]
        for route in routes
    )
    if transform_checksum < 0:
        raise AssertionError("Unreachable transform checksum.")
    coordinate_ns = time.perf_counter_ns() - coordinate_started

    observation_started = time.perf_counter_ns()
    if precomputed_motion is None:
        motion, motion_reads, motion_temporary = _motion_map(profile, sequence)
        logical_reads += motion_reads
        temporary_buffer_bytes += motion_temporary
    else:
        motion = precomputed_motion
    observations, observation_reads = _observe(
        profile,
        sequence,
        input_sha256,
        routes,
        motion,
    )
    logical_reads += observation_reads
    observation_ns = time.perf_counter_ns() - observation_started

    fusion_started = time.perf_counter_ns()
    shared_state = _fuse(routes, observations)
    fusion_ns = time.perf_counter_ns() - fusion_started

    plan_started = time.perf_counter_ns()
    compute_plan = _compile_plan(shared_state)
    plan_ns = time.perf_counter_ns() - plan_started

    overlap_numerator = 0
    overlap_denominator = 0
    for route in routes:
        if route["write_scope"] is None:
            continue
        overlap_denominator += _area(route["write_scope"])
        overlap_numerator += max(
            0,
            _area(route["receptive_field"]) - _area(route["write_scope"]),
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
            route["receptive_field"],
            route["write_scope"],
        ):
            raise ValueError("Write scope exceeds receptive field.")
    for claim in compute_plan["claims"]:
        if claim["value"] is not None or claim["status"] not in {
            "unsupported",
            "uncollected",
        }:
            raise ValueError("Unsupported metric semantics are invalid.")
    return {
        "semantic_result": semantic,
        "semantic_hash": semantic_hash(semantic),
        "durations_ns": {
            "total": time.perf_counter_ns() - total_started,
            "routing": routing_ns,
            "coordinate_transform": coordinate_ns,
            "observation": observation_ns,
            "fusion": fusion_ns,
            "compute_plan": plan_ns,
        },
        "counters": {
            "logical_bytes_read": logical_reads,
            "bytes_copied": 0,
            "temporary_buffer_bytes": temporary_buffer_bytes,
            "overlap_numerator": overlap_numerator,
            "overlap_denominator": overlap_denominator,
        },
    }


def _percentile(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _mean_seconds(values: list[int]) -> float:
    return sum(values) / len(values) / 1_000_000_000


def _collected(value: float, unit: str, method: str) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": "collected",
        "reason": None,
        "method": method,
    }


def _unavailable(
    unit: str,
    status: str,
    reason: str,
    method: str,
) -> dict[str, Any]:
    return {
        "value": None,
        "unit": unit,
        "status": status,
        "reason": reason,
        "method": method,
    }


def _peak_rss_bytes() -> tuple[int | None, str, str | None]:
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_process_memory_info.restype = wintypes.BOOL
        handle = get_current_process()
        success = get_process_memory_info(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if success:
            return (
                int(counters.PeakWorkingSetSize),
                "Windows GetProcessMemoryInfo PeakWorkingSetSize",
                None,
            )
        return None, "Windows GetProcessMemoryInfo", "API call failed."
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        multiplier = 1 if sys.platform == "darwin" else 1024
        return int(peak * multiplier), "getrusage RUSAGE_SELF ru_maxrss", None
    except (ImportError, OSError) as error:
        return None, "operating-system process sampler", str(error)


def benchmark_case(
    profile: dict[str, Any],
    topology: str,
    warmups: int,
    repetitions: int,
) -> dict[str, Any]:
    if repetitions <= 0:
        raise ValueError("Measured repetitions must be positive.")
    sequence = generate_sequence(profile)
    baseline = run_pipeline(profile, topology, sequence)
    expected_hash = baseline["semantic_hash"]
    for _ in range(warmups):
        if run_pipeline(profile, topology, sequence)["semantic_hash"] != expected_hash:
            raise RuntimeError("Warm-up semantic hash changed.")

    durations = {
        name: []
        for name in (
            "total",
            "routing",
            "coordinate_transform",
            "observation",
            "fusion",
            "compute_plan",
        )
    }
    process_cpu = []
    last = baseline
    for _ in range(repetitions):
        cpu_started = time.process_time_ns()
        run = run_pipeline(profile, topology, sequence)
        process_cpu.append(time.process_time_ns() - cpu_started)
        if run["semantic_hash"] != expected_hash:
            raise RuntimeError("Measured semantic hash changed.")
        for name in durations:
            durations[name].append(run["durations_ns"][name])
        last = run

    p50_ns = _percentile(durations["total"], 0.50)
    p95_ns = _percentile(durations["total"], 0.95)
    p50_seconds = p50_ns / 1_000_000_000
    counters = last["counters"]
    denominator = counters["overlap_denominator"]
    overlap_ratio = (
        0.0
        if denominator == 0
        else counters["overlap_numerator"] / denominator
    )
    peak_rss, rss_method, rss_reason = _peak_rss_bytes()
    metrics = {
        "total_wall_seconds_mean": _collected(
            _mean_seconds(durations["total"]),
            "seconds",
            "steady_clock_mean",
        ),
        "p50_latency_seconds": _collected(
            p50_seconds,
            "seconds",
            "nearest_rank",
        ),
        "p95_latency_seconds": _collected(
            p95_ns / 1_000_000_000,
            "seconds",
            "nearest_rank",
        ),
        "routing_seconds_mean": _collected(
            _mean_seconds(durations["routing"]),
            "seconds",
            "steady_clock_mean",
        ),
        "coordinate_transform_seconds_mean": _collected(
            _mean_seconds(durations["coordinate_transform"]),
            "seconds",
            "steady_clock_mean",
        ),
        "observation_seconds_mean": _collected(
            _mean_seconds(durations["observation"]),
            "seconds",
            "steady_clock_mean",
        ),
        "fusion_seconds_mean": _collected(
            _mean_seconds(durations["fusion"]),
            "seconds",
            "steady_clock_mean",
        ),
        "compute_plan_seconds_mean": _collected(
            _mean_seconds(durations["compute_plan"]),
            "seconds",
            "steady_clock_mean",
        ),
        "frames_per_second": _collected(
            profile["frames"] / p50_seconds,
            "frames/second",
            "frames divided by p50 core latency",
        ),
        "bytes_processed": _collected(
            float(sequence.nbytes),
            "bytes",
            "packed input length",
        ),
        "logical_bytes_read": _collected(
            float(counters["logical_bytes_read"]),
            "bytes",
            "algorithmic read accounting",
        ),
        "bytes_copied": _collected(
            float(counters["bytes_copied"]),
            "bytes",
            "explicit pixel-buffer copies",
        ),
        "temporary_buffer_bytes": _collected(
            float(counters["temporary_buffer_bytes"]),
            "bytes",
            "dominant pixel-sized temporary buffers",
        ),
        "overlap_ratio": _collected(
            overlap_ratio,
            "ratio",
            "extra receptive area / write area",
        ),
        "peak_rss_bytes": (
            _collected(float(peak_rss), "bytes", rss_method)
            if peak_rss is not None
            else _unavailable(
                "bytes",
                "uncollected",
                rss_reason or "Peak RSS sampler unavailable.",
                rss_method,
            )
        ),
        "allocation_count": _unavailable(
            "allocations",
            "unsupported",
            "Python and NumPy allocators are not jointly instrumented.",
            "requires coordinated allocator instrumentation",
        ),
        "process_cpu_seconds": _collected(
            _mean_seconds(process_cpu),
            "seconds",
            "time.process_time_ns mean",
        ),
        "thread_count": _collected(
            float(threading.active_count()),
            "threads",
            "threading.active_count after measured case",
        ),
    }
    return {
        "profile_id": profile["profile_id"],
        "topology": topology,
        "warmups": warmups,
        "repetitions": repetitions,
        "eye_count": len(baseline["semantic_result"]["eyes"]),
        "semantic_hash": expected_hash,
        "semantic_result": baseline["semantic_result"],
        "metrics": dict(sorted(metrics.items())),
    }


def benchmark_suite(
    profile_names: list[str],
    topology_names: list[str],
    *,
    seed: int,
    warmups: int,
    repetitions: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    cases = []
    for profile_name in profile_names:
        profile = input_profile(profile_name, seed)
        for topology in topology_names:
            cases.append(
                benchmark_case(
                    profile,
                    topology,
                    warmups,
                    repetitions,
                )
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RUN_KIND,
        "implementation": "python",
        "benchmark_status": "model_free_orchestration_admission",
        "official_wan_baseline": False,
        "environment": {
            "implementation": "python",
            "package_version": platform.python_version(),
            "operating_system": platform.system().lower(),
            "architecture": platform.machine().lower(),
            "numpy_version": np.__version__,
        },
        "profiles": profile_names,
        "topologies": topology_names,
        "warmups": warmups,
        "repetitions": repetitions,
        "core_suite_wall_seconds": time.perf_counter() - started,
        "cases": cases,
        "unsupported_metrics": [
            {
                "name": "ffi_end_to_end_seconds",
                "value": None,
                "unit": "seconds",
                "status": "uncollected",
                "reason": "PyO3 and FFI are outside this admission probe.",
                "method": "requires a separate shared-buffer integration experiment",
            },
            {
                "name": "estimated_wan_end_to_end_gain",
                "value": None,
                "unit": "ratio",
                "status": "uncollected",
                "reason": (
                    "M0 does not contain an eligible isolated "
                    "input-orchestration span."
                ),
                "method": (
                    "requires an attributable same-condition M0 input-side span"
                ),
            },
        ],
    }
