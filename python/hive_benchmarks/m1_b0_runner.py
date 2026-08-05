from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

from hive_benchmarks.m1_b0_contract import load_config
from hive_benchmarks.m1_b0_locality import analyze_gray_sequence, analyze_rgb_sequence


WIDTH = 832
HEIGHT = 480
FPS = 16
FFMPEG_RELATIVE = Path("tools/ffmpeg-7.1.1/bin/ffmpeg.exe")
FFPROBE_RELATIVE = Path("tools/ffmpeg-7.1.1/bin/ffprobe.exe")
LOCAL_SUBDIR = Path("m1_b0_locality")
UNAVAILABLE = {
    "value": None,
    "status": "unavailable",
    "reason": "No model, backend tensor contract, CUDA allocator, or GPU measurement is in M1-B0 scope.",
    "method": "not measured",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json_new(path: Path, value: Any) -> None:
    if path.exists():
        raise RuntimeError(f"OUTPUT_COLLISION: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    if temporary.exists():
        raise RuntimeError(f"PARTIAL_OUTPUT_COLLISION: {temporary.name}")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def _config_paths(repository: Path, asset_root: Path) -> tuple[Path, Path, Path, Path]:
    config = repository / "configs/m1_b0_model_free_locality.json"
    ffmpeg = asset_root / FFMPEG_RELATIVE
    ffprobe = asset_root / FFPROBE_RELATIVE
    local_root = asset_root / LOCAL_SUBDIR
    return config, ffmpeg, ffprobe, local_root


def _derivative_path(asset_root: Path, clip_id: str) -> Path:
    return asset_root / "derivatives" / f"{clip_id}-analysis-832x480-16fps-ffv1.mkv"


def _run_checked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, check=False, **kwargs)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise RuntimeError(f"COMMAND_FAILED({result.returncode}): {stderr[-4000:]}")
    return result


def _input_integrity(repository: Path, asset_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    _, ffmpeg, ffprobe, _ = _config_paths(repository, asset_root)
    if not ffmpeg.is_file() or not ffprobe.is_file():
        raise RuntimeError("APPROVED_FFMPEG_MISSING")
    tools = config["tools"]
    if _sha256_file(ffmpeg) != tools["ffmpeg_sha256"] or _sha256_file(ffprobe) != tools["ffprobe_sha256"]:
        raise RuntimeError("APPROVED_FFMPEG_HASH_MISMATCH")
    records = []
    for clip in config["input_contract"]["clips"]:
        path = _derivative_path(asset_root, clip["clip_id"])
        if not path.is_file():
            raise RuntimeError(f"DERIVATIVE_MISSING:{clip['clip_id']}")
        digest = _sha256_file(path)
        if digest != clip["sha256"] or path.stat().st_size != clip["bytes"]:
            raise RuntimeError(f"DERIVATIVE_INTEGRITY_MISMATCH:{clip['clip_id']}")
        probe = _run_checked(
            [
                str(ffprobe), "-v", "error", "-select_streams", "v:0",
                "-count_frames", "-show_entries",
                "stream=codec_name,width,height,r_frame_rate,nb_read_frames",
                "-of", "json", str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        expected = {
            "codec_name": "ffv1",
            "width": WIDTH,
            "height": HEIGHT,
            "r_frame_rate": "16/1",
            "nb_read_frames": str(clip["frames"]),
        }
        if any(stream.get(key) != value for key, value in expected.items()):
            raise RuntimeError(f"DERIVATIVE_METADATA_MISMATCH:{clip['clip_id']}:{stream}")
        records.append(
            {
                "clip_id": clip["clip_id"],
                "asset_id": f"approved-asset:m1-a2/{clip['clip_id']}-analysis-ffv1",
                "frames": clip["frames"],
                "frame_pairs": clip["frames"] - 1,
                "width": WIDTH,
                "height": HEIGHT,
                "fps": FPS,
                "codec": "ffv1",
                "container": "matroska",
                "bytes": clip["bytes"],
                "derivative_sha256": digest,
                "hash_verified": True,
            }
        )
    return {
        "schema_version": "0.1.0",
        "run_kind": "m1_b0_input_integrity",
        "protocol_revision": config["protocol_revision"],
        "inputs": records,
        "tools": {
            "ffmpeg": {"version": tools["ffmpeg_version"], "sha256": tools["ffmpeg_sha256"]},
            "ffprobe": {"version": tools["ffprobe_version"], "sha256": tools["ffprobe_sha256"]},
        },
        "all_verified": True,
    }


def prepare(repository: Path, asset_root: Path) -> None:
    config_path, ffmpeg, _, local_root = _config_paths(repository, asset_root)
    config = load_config(config_path)
    if local_root.exists():
        raise RuntimeError("LOCAL_OUTPUT_ROOT_ALREADY_EXISTS")
    integrity = _input_integrity(repository, asset_root, config)
    raw_root = local_root / "raw"
    raw_root.mkdir(parents=True)
    raw_records = []
    for clip in config["input_contract"]["clips"]:
        clip_id = clip["clip_id"]
        source = _derivative_path(asset_root, clip_id)
        for pixel_format, extension, multiplier in (("gray8", "gray8", 1), ("rgb24", "rgb24", 3)):
            output = raw_root / f"{clip_id}.{extension}"
            _run_checked(
                [
                    str(ffmpeg), "-v", "error", "-nostdin", "-n", "-i", str(source),
                    "-map", "0:v:0", "-pix_fmt", pixel_format, "-f", "rawvideo", str(output),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            expected_bytes = clip["frames"] * WIDTH * HEIGHT * multiplier
            if output.stat().st_size != expected_bytes:
                raise RuntimeError(f"RAW_SIZE_MISMATCH:{clip_id}:{pixel_format}")
            raw_records.append(
                {
                    "clip_id": clip_id,
                    "pixel_format": pixel_format,
                    "asset_id": f"approved-asset:m1-a2/m1_b0_locality/raw/{clip_id}.{extension}",
                    "bytes": expected_bytes,
                    "sha256": _sha256_file(output),
                }
            )
    _write_json_new(local_root / "input-integrity.json", integrity)
    _write_json_new(local_root / "raw-manifest.json", {"schema_version": "0.1.0", "files": raw_records})


def _load_raw(local_root: Path, clip_id: str, pixel_format: str, frames: int) -> np.memmap:
    extension = "gray8" if pixel_format == "gray8" else "rgb24"
    shape = (frames, HEIGHT, WIDTH) if pixel_format == "gray8" else (frames, HEIGHT, WIDTH, 3)
    return np.memmap(local_root / "raw" / f"{clip_id}.{extension}", dtype=np.uint8, mode="r", shape=shape)


def _float_equal(left: float, right: float, tolerance: float) -> bool:
    return abs(left - right) <= tolerance


def _compare_values(left: Any, right: Any, path: str, mismatches: list[str], tolerance: float) -> None:
    excluded = {"implementation", "translation_cost", "luma_rgb_disagreement"}
    if path.rsplit("/", 1)[-1] in excluded:
        return
    if isinstance(left, dict):
        if not isinstance(right, dict):
            mismatches.append(f"{path}:type")
            return
        for key in left:
            if key in excluded:
                continue
            if key not in right:
                mismatches.append(f"{path}/{key}:missing")
            else:
                _compare_values(left[key], right[key], f"{path}/{key}", mismatches, tolerance)
        return
    if isinstance(left, list):
        if not isinstance(right, list) or len(left) != len(right):
            mismatches.append(f"{path}:length")
            return
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            _compare_values(left_item, right_item, f"{path}/{index}", mismatches, tolerance)
        return
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None or not _float_equal(float(left), float(right), tolerance):
            mismatches.append(f"{path}:float:{left}!={right}")
    elif left != right:
        mismatches.append(f"{path}:{left}!={right}")


def _rust_command(
    binary: Path,
    config: Path,
    input_path: str,
    output: Path,
    clip_id: str,
    pixel_format: str,
    frames: int,
    input_sha256: str,
    warmups: int,
    repeats: int,
) -> list[str]:
    return [
        str(binary), "--input", input_path, "--output", str(output), "--config", str(config),
        "--clip-id", clip_id, "--format", pixel_format, "--width", str(WIDTH),
        "--height", str(HEIGHT), "--frames", str(frames), "--warmups", str(warmups),
        "--repeats", str(repeats), "--expected-input-sha256", input_sha256,
    ]


def parity(repository: Path, asset_root: Path, binary: Path) -> None:
    config_path, _, _, local_root = _config_paths(repository, asset_root)
    config = load_config(config_path)
    raw_manifest = json.loads((local_root / "raw-manifest.json").read_text(encoding="utf-8"))
    raw_by_key = {(item["clip_id"], item["pixel_format"]): item for item in raw_manifest["files"]}
    parity_root = local_root / "parity"
    if parity_root.exists():
        raise RuntimeError("PARITY_OUTPUT_ALREADY_EXISTS")
    parity_root.mkdir(parents=True)
    records = []
    mismatches: list[dict[str, Any]] = []
    tolerance = float(config["parity"]["float_absolute_tolerance"])
    for clip in config["input_contract"]["clips"]:
        clip_id = clip["clip_id"]
        gray = _load_raw(local_root, clip_id, "gray8", clip["frames"])
        for pixel_format in ("gray8", "rgb24"):
            sequence = gray if pixel_format == "gray8" else _load_raw(local_root, clip_id, "rgb24", clip["frames"])
            started = time.perf_counter()
            python_summary = (
                analyze_gray_sequence(sequence, config)
                if pixel_format == "gray8"
                else analyze_rgb_sequence(sequence, config, gray)
            )
            python_seconds = time.perf_counter() - started
            python_output = parity_root / f"{clip_id}-{pixel_format}-numpy.json"
            _write_json_new(python_output, python_summary)
            raw_item = raw_by_key[(clip_id, pixel_format)]
            extension = "gray8" if pixel_format == "gray8" else "rgb24"
            rust_output = parity_root / f"{clip_id}-{pixel_format}-rust.json"
            command = _rust_command(
                binary, config_path, str(local_root / "raw" / f"{clip_id}.{extension}"), rust_output,
                clip_id, pixel_format, clip["frames"], raw_item["sha256"], 0, 1,
            )
            external_started = time.perf_counter()
            _run_checked(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            rust_external_seconds = time.perf_counter() - external_started
            rust_record = json.loads(rust_output.read_text(encoding="utf-8"))
            rust_summary = rust_record["summary"]
            item_mismatches: list[str] = []
            _compare_values(python_summary, rust_summary, "summary", item_mismatches, tolerance)
            record = {
                "clip_id": clip_id,
                "pixel_format": pixel_format,
                "passed": not item_mismatches,
                "python_summary_digest": python_summary["summary_digest"],
                "rust_summary_digest": rust_summary["summary_digest"],
                "python_analysis_seconds": python_seconds,
                "rust_analysis_seconds": rust_record["execution"]["analysis_seconds"][0],
                "rust_external_seconds": rust_external_seconds,
            }
            records.append(record)
            if item_mismatches:
                mismatches.append({"clip_id": clip_id, "pixel_format": pixel_format, "items": item_mismatches})
                _write_json_new(parity_root / "parity-failure.json", {"records": records, "mismatches": mismatches})
                raise RuntimeError(f"NUMPY_RUST_PARITY_MISMATCH:{clip_id}:{pixel_format}")
    _write_json_new(
        local_root / "parity-report.json",
        {"schema_version": "0.1.0", "passed": True, "clip_format_pairs": len(records), "records": records, "mismatches": []},
    )


def _profile_stats(values: Iterable[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        raise RuntimeError("EMPTY_PROFILE")
    def nearest(q: float) -> float:
        return ordered[max(0, int(np.ceil(q * len(ordered))) - 1)]
    return {"minimum": ordered[0], "p50": nearest(0.5), "p95": nearest(0.95), "maximum": ordered[-1]}


def _decode_once(ffmpeg: Path, source: Path, pixel_format: str) -> float:
    started = time.perf_counter()
    _run_checked(
        [str(ffmpeg), "-v", "error", "-nostdin", "-i", str(source), "-map", "0:v:0", "-pix_fmt", pixel_format, "-f", "rawvideo", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return time.perf_counter() - started


def _rust_resident_once(
    binary: Path, config_path: Path, local_root: Path, clip: dict[str, Any], raw_item: dict[str, Any], output: Path,
    warmups: int, repeats: int,
) -> tuple[float, dict[str, Any]]:
    command = _rust_command(
        binary, config_path, str(local_root / "raw" / f"{clip['clip_id']}.gray8"), output,
        clip["clip_id"], "gray8", clip["frames"], raw_item["sha256"], warmups, repeats,
    )
    started = time.perf_counter()
    _run_checked(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    external = time.perf_counter() - started
    return external, json.loads(output.read_text(encoding="utf-8"))


def _streaming_once(
    binary: Path, config_path: Path, ffmpeg: Path, source: Path, output: Path,
    clip: dict[str, Any], raw_item: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    rust_command = _rust_command(
        binary, config_path, "-", output, clip["clip_id"], "gray8", clip["frames"], raw_item["sha256"], 0, 1,
    )
    ffmpeg_command = [
        str(ffmpeg), "-v", "error", "-nostdin", "-i", str(source), "-map", "0:v:0",
        "-pix_fmt", "gray8", "-f", "rawvideo", "-",
    ]
    started = time.perf_counter()
    decoder = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert decoder.stdout is not None
    detector = subprocess.Popen(rust_command, stdin=decoder.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    decoder.stdout.close()
    _, detector_stderr = detector.communicate()
    decoder_stderr = decoder.stderr.read() if decoder.stderr else b""
    decoder_return = decoder.wait()
    external = time.perf_counter() - started
    if decoder_return != 0 or detector.returncode != 0:
        raise RuntimeError(
            "STREAMING_FAILED:"
            + decoder_stderr.decode("utf-8", errors="replace")[-2000:]
            + detector_stderr.decode("utf-8", errors="replace")[-2000:]
        )
    return external, json.loads(output.read_text(encoding="utf-8"))


def _suite_worker(
    binary: Path, config_path: Path, local_root: Path, clips: list[dict[str, Any]], raw_by_clip: dict[str, dict[str, Any]],
    worker_root: Path, worker_count: int,
) -> dict[str, Any]:
    root = worker_root / f"workers-{worker_count}"
    root.mkdir(parents=True)
    started = time.perf_counter()
    def execute(clip: dict[str, Any]) -> dict[str, Any]:
        output = root / f"{clip['clip_id']}.json"
        external, record = _rust_resident_once(binary, config_path, local_root, clip, raw_by_clip[clip["clip_id"]], output, 0, 1)
        return {"clip_id": clip["clip_id"], "external_seconds": external, "analysis_seconds": record["execution"]["analysis_seconds"][0]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        records = list(executor.map(execute, clips))
    wall = time.perf_counter() - started
    pairs = sum(clip["frames"] - 1 for clip in clips)
    return {
        "worker_count": worker_count,
        "worker_unit": "concurrent_cpu_process_launched_by_thread_pool_not_gpu_stream",
        "suite_wall_seconds": wall,
        "frame_pairs": pairs,
        "pairs_per_second": pairs / wall,
        "clip_records": records,
    }


def benchmark(repository: Path, asset_root: Path, binary: Path) -> None:
    config_path, ffmpeg, _, local_root = _config_paths(repository, asset_root)
    config = load_config(config_path)
    if not (local_root / "parity-report.json").exists():
        raise RuntimeError("PARITY_GATE_MISSING")
    parity_report = json.loads((local_root / "parity-report.json").read_text(encoding="utf-8"))
    if not parity_report["passed"]:
        raise RuntimeError("PARITY_GATE_FAILED")
    benchmark_root = local_root / "benchmarks"
    if benchmark_root.exists():
        raise RuntimeError("BENCHMARK_OUTPUT_ALREADY_EXISTS")
    benchmark_root.mkdir(parents=True)
    raw_manifest = json.loads((local_root / "raw-manifest.json").read_text(encoding="utf-8"))
    raw_by_clip = {item["clip_id"]: item for item in raw_manifest["files"] if item["pixel_format"] == "gray8"}
    clips = config["input_contract"]["clips"]
    decode_records = []
    resident_records = []
    streaming_records = []
    for clip in clips:
        source = _derivative_path(asset_root, clip["clip_id"])
        decode_times = [_decode_once(ffmpeg, source, "gray8") for _ in range(3)]
        decode_records.append({"clip_id": clip["clip_id"], "repeats": decode_times, "statistics": _profile_stats(decode_times)})

        resident_output = benchmark_root / "resident" / f"{clip['clip_id']}.json"
        resident_output.parent.mkdir(parents=True, exist_ok=True)
        resident_external, resident = _rust_resident_once(
            binary, config_path, local_root, clip, raw_by_clip[clip["clip_id"]], resident_output, 1, 5,
        )
        resident_records.append(
            {
                "clip_id": clip["clip_id"],
                "warmups": 1,
                "analysis_repeats": resident["execution"]["analysis_seconds"],
                "analysis_statistics": _profile_stats(resident["execution"]["analysis_seconds"]),
                "external_command_seconds": resident_external,
                "input_read_seconds": resident["execution"]["input_read_seconds"],
            }
        )

        streaming_times = []
        streaming_analysis = []
        for repeat in range(4):
            output = benchmark_root / "streaming" / f"{clip['clip_id']}-repeat-{repeat}.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            external, record = _streaming_once(binary, config_path, ffmpeg, source, output, clip, raw_by_clip[clip["clip_id"]])
            if repeat > 0:
                streaming_times.append(external)
                streaming_analysis.append(record["execution"]["analysis_seconds"][0])
        streaming_records.append(
            {
                "clip_id": clip["clip_id"],
                "warmups": 1,
                "external_repeats": streaming_times,
                "external_statistics": _profile_stats(streaming_times),
                "analysis_repeats": streaming_analysis,
                "analysis_statistics": _profile_stats(streaming_analysis),
            }
        )

    logical_threads = os.cpu_count() or 1
    required_workers = [value for value in config["benchmark"]["required_worker_sweep"] if value <= logical_threads]
    diagnostic_workers = [value for value in config["benchmark"]["optional_oversubscription_diagnostics"] if value <= logical_threads]
    worker_root = benchmark_root / "worker-sweep"
    worker_records = [
        _suite_worker(binary, config_path, local_root, clips, raw_by_clip, worker_root, worker)
        for worker in required_workers + diagnostic_workers
    ]
    baseline = next(item for item in worker_records if item["worker_count"] == 1)
    for item in worker_records:
        speedup = baseline["suite_wall_seconds"] / item["suite_wall_seconds"]
        item["speedup_vs_one_worker"] = speedup
        item["parallel_efficiency"] = speedup / item["worker_count"]
        item["classification"] = "required" if item["worker_count"] in required_workers else "oversubscription_diagnostic"

    receipt = {
        "schema_version": "0.1.0",
        "run_kind": "m1_b0_cost_profiles",
        "protocol_revision": config["protocol_revision"],
        "profiles": {
            "decode_only": {"pixel_format": "gray8", "records": decode_records, "decode_cost_included": True, "comparison_cost_included": False},
            "resident_warm": {"pixel_format": "gray8", "records": resident_records, "decode_cost_included": False, "input_read_reported_separately": True},
            "streaming": {"pixel_format": "gray8", "records": streaming_records, "decode_transfer_compare_included": True, "implementation": "ffmpeg_pipe_to_rust_stdin"},
        },
        "worker_scaling": worker_records,
        "cold_disk_benchmark": {"performed": False, "os_file_cache_flushed": False, "reason": "The protocol forbids claiming cold-disk behavior without controlled cache eviction."},
        "process_metrics": {
            "scheduling_overhead": {**UNAVAILABLE, "reason": "No validated scheduler instrumentation was enabled."},
            "peak_rss": {**UNAVAILABLE, "reason": "A process-tree peak RSS sampler was not enabled for this model-free run."},
            "cpu_utilization": {**UNAVAILABLE, "reason": "A validated process-tree CPU sampler was not enabled for this model-free run."},
        },
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "logical_threads": logical_threads,
            "physical_cores": {**UNAVAILABLE, "reason": "Standard-library-only runner does not infer physical core topology."},
            "ram_bytes": {**UNAVAILABLE, "reason": "Standard-library-only runner does not infer installed physical RAM."},
            "rust_binary_sha256": _sha256_file(binary),
            "ffmpeg_version": config["tools"]["ffmpeg_version"],
            "ffmpeg_sha256": config["tools"]["ffmpeg_sha256"],
        },
        "claim_boundary": dict(config["claim_boundary"]),
    }
    _write_json_new(local_root / "benchmark-receipt.json", receipt)


def _bundle_manifest(local_root: Path) -> dict[str, Any]:
    files = []
    for path in sorted(item for item in local_root.rglob("*") if item.is_file()):
        if path.name == "bundle-manifest.json" or path.name.endswith(".partial"):
            continue
        files.append({"relative_name": path.relative_to(local_root).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256_file(path)})
    digest = _canonical_digest(files)
    return {
        "schema_version": "0.1.0",
        "asset_id": "approved-asset:m1-a2/m1_b0_locality/bundle-manifest-v1",
        "digest_method": "sha256_of_canonical_file_inventory",
        "bytes": sum(item["bytes"] for item in files),
        "file_count": len(files),
        "sha256": digest,
        "tracked_by_git": False,
        "files": files,
    }


def finalize(repository: Path, asset_root: Path) -> None:
    config_path, _, _, local_root = _config_paths(repository, asset_root)
    config = load_config(config_path)
    integrity = json.loads((local_root / "input-integrity.json").read_text(encoding="utf-8"))
    parity_report = json.loads((local_root / "parity-report.json").read_text(encoding="utf-8"))
    benchmark_receipt = json.loads((local_root / "benchmark-receipt.json").read_text(encoding="utf-8"))
    if not integrity["all_verified"] or not parity_report["passed"]:
        raise RuntimeError("FINAL_GATE_INPUT_OR_PARITY_FAILED")
    bundle = _bundle_manifest(local_root)
    _write_json_new(local_root / "bundle-manifest.json", bundle)

    clip_summaries = []
    csv_rows = []
    raw_manifest = json.loads((local_root / "raw-manifest.json").read_text(encoding="utf-8"))
    raw_by_key = {(item["clip_id"], item["pixel_format"]): item for item in raw_manifest["files"]}
    for input_record in integrity["inputs"]:
        clip_id = input_record["clip_id"]
        gray = json.loads((local_root / "parity" / f"{clip_id}-gray8-numpy.json").read_text(encoding="utf-8"))
        rgb = json.loads((local_root / "parity" / f"{clip_id}-rgb24-numpy.json").read_text(encoding="utf-8"))
        clip_summaries.append(
            {
                "clip_id": clip_id,
                "gray8_summary_digest": gray["summary_digest"],
                "rgb24_summary_digest": rgb["summary_digest"],
                "global_delta": gray["global_delta"],
                "translation_cost": gray["translation_cost"],
                "raw_pixel_surface": [item for item in gray["pixel_surface"] if item["source"] == "raw"],
                "translation_compensated_pixel_surface": [item for item in gray["pixel_surface"] if item["source"] == "translation_compensated"],
                "rgb_pixel_surface": rgb["pixel_surface"],
                "luma_rgb_disagreement": rgb["luma_rgb_disagreement"],
                "tile_surface": gray["tile_surface"],
                "temporal_persistence": gray["temporal_persistence"],
            }
        )
        for item in gray["tile_surface"]:
            csv_rows.append({"clip_id": clip_id, **item})

    inputs = []
    for item in integrity["inputs"]:
        inputs.append(
            {
                "clip_id": item["clip_id"],
                "asset_id": item["asset_id"],
                "frames": item["frames"],
                "frame_pairs": item["frame_pairs"],
                "width": item["width"],
                "height": item["height"],
                "fps": item["fps"],
                "derivative_sha256": item["derivative_sha256"],
                "decoded_logical_bytes": raw_by_key[(item["clip_id"], "gray8")]["bytes"],
                "hash_verified": True,
            }
        )
    unavailable = {name: dict(UNAVAILABLE) for name in config["unavailable_memory_metrics"]}
    result = {
        "schema_version": "0.1.0",
        "protocol_revision": config["protocol_revision"],
        "run_kind": config["run_kind"],
        "decision": "M1_B0_LOCALITY_SURFACE_MEASURED",
        "inputs": inputs,
        "surface": {
            "configuration": config["surface"],
            "translation": config["translation"],
            "clip_results": clip_summaries,
            "claim": "Observed pixel/tile locality and future selective-compute research opportunity only; not safe-skip truth.",
        },
        "cost_profiles": benchmark_receipt["profiles"] | {"worker_scaling": benchmark_receipt["worker_scaling"]},
        "parity": {"passed": True, "clip_format_pairs": parity_report["clip_format_pairs"], "mismatches": []},
        "local_artifact_bundle": {key: bundle[key] for key in ("asset_id", "bytes", "sha256", "tracked_by_git")},
        "unavailable_memory_metrics": unavailable,
        "claim_boundary": {key: config["claim_boundary"][key] for key in (
            "model_runs", "cuda_runs", "gpu_runs", "backend_integration_runs", "selective_compute_runs",
            "vram_measurement_runs", "product_speedup_results", "safe_skip_truth_count", "verified_compute_relevance_oracles",
        )},
    }
    result["summary_digest"] = _canonical_digest(result)
    reports = repository / "reports/m1_b0"
    _write_json_new(reports / "input_integrity_report.json", integrity)
    _write_json_new(reports / "benchmark_receipt.json", benchmark_receipt)
    _write_json_new(reports / "locality_opportunity_summary.json", result)
    csv_path = reports / "locality_opportunity_summary.csv"
    if csv_path.exists():
        raise RuntimeError("OUTPUT_COLLISION: locality_opportunity_summary.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)


def plan(repository: Path, asset_root: Path) -> None:
    config_path, ffmpeg, ffprobe, local_root = _config_paths(repository, asset_root)
    config = load_config(config_path)
    print(
        json.dumps(
            {
                "execution_started": False,
                "protocol_revision": config["protocol_revision"],
                "clips": [clip["clip_id"] for clip in config["input_contract"]["clips"]],
                "asset_root_accessible": asset_root.is_dir(),
                "approved_ffmpeg_present": ffmpeg.is_file(),
                "approved_ffprobe_present": ffprobe.is_file(),
                "local_output_exists": local_root.exists(),
                "claim_boundary": config["claim_boundary"],
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="HIVEFRAME M1-B0 model-free locality measurement runner")
    parser.add_argument("phase", choices=("plan", "prepare", "parity", "benchmark", "finalize"))
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--rust-binary", type=Path)
    arguments = parser.parse_args()
    repository = arguments.repository.resolve()
    asset_root = arguments.asset_root.resolve()
    if arguments.phase == "plan":
        plan(repository, asset_root)
    elif arguments.phase == "prepare":
        prepare(repository, asset_root)
    elif arguments.phase == "parity":
        if arguments.rust_binary is None:
            parser.error("--rust-binary is required for parity")
        parity(repository, asset_root, arguments.rust_binary.resolve())
    elif arguments.phase == "benchmark":
        if arguments.rust_binary is None:
            parser.error("--rust-binary is required for benchmark")
        benchmark(repository, asset_root, arguments.rust_binary.resolve())
    else:
        finalize(repository, asset_root)


if __name__ == "__main__":
    main()
