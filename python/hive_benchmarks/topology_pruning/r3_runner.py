"""Run the predeclared model-free M1-P0-R3 in-process boundary probe."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import importlib
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any, Iterable

import numpy as np

from hive_benchmarks.topology_pruning.paired_normalization import (
    deterministic_case_b_order,
    sha256_file,
)
from hive_benchmarks.topology_pruning.report import write_json
from hive_benchmarks.topology_pruning.synthetic_cases import CASES, generate_case
from hive_probes.rust_io_reference import run_pipeline


ROOT = Path(__file__).resolve().parents[3]
RUN_KIND = "m1_p0_r3_inprocess_shared_buffer"
CONFIG_PATH = ROOT / "configs" / "m1-p0-r3.inprocess-shared-buffer.json"
ARTIFACT_NAMES = (
    "predeclared-boundary-contract.json",
    "inprocess-boundary-results.json",
    "parity-report.json",
    "copy-accounting.json",
    "decision-report.md",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered or not 0 < quantile <= 1:
        raise ValueError("Invalid nearest-rank percentile request.")
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _git_blob_digest(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def validate_immutable_r2(config: dict[str, Any]) -> None:
    for path, expected in sorted(config["immutable_r2_git_blobs"].items()):
        artifact = ROOT / path
        if not artifact.is_file():
            raise ValueError(f"Immutable v1/R1/R2 artifact is missing: {path}")
        actual = _git_blob_digest(artifact)
        if actual != expected:
            raise ValueError(
                f"Immutable v1/R1/R2 Git blob changed for {path}: "
                f"expected {expected}, got {actual}"
            )


def validate_config(config: dict[str, Any]) -> None:
    if config.get("run_kind") != RUN_KIND:
        raise ValueError("Unexpected R3 run kind.")
    if config.get("case_id") != "case-b-high-resolution-local-change":
        raise ValueError("R3 is restricted to the existing Case B corpus.")
    if config.get("shape") != [8, 1080, 1920] or config.get("dtype") != "uint8":
        raise ValueError("R3 requires the exact packed uint8 Case B shape.")
    if config.get("topologies") != ["T0", "T1", "T2"]:
        raise ValueError("R3 admits exactly B/T0, B/T1, and B/T2.")
    if config.get("warmups") != 5 or config.get("repetitions") != 30:
        raise ValueError("R3 requires 5 warm-ups and 30 paired measured blocks.")
    pairing = config.get("pairing", {})
    if pairing.get("members_per_block") != ["T0", "T1", "T2"]:
        raise ValueError("Each R3 block must contain T0, T1, and T2.")
    if pairing.get("implementations_per_candidate") != ["python", "rust_inprocess"]:
        raise ValueError("Each R3 candidate must pair Python with Rust in-process.")
    for key in (
        "same_process",
        "same_sequence_object",
        "same_repetition_block",
        "independent_median_subtraction_forbidden",
    ):
        if pairing.get(key) is not True:
            raise ValueError(f"R3 pairing safeguard is missing: {key}")
    ffi = config.get("ffi", {})
    required = {
        "technology": "PyO3",
        "version": "0.29.0",
        "python_abi": "abi3-py312",
        "calls_per_candidate": 1,
        "per_eye_calls": 0,
        "input_copy_bytes_required": 0,
        "temporary_files_required": 0,
        "subprocesses_required": 0,
    }
    for key, expected in required.items():
        if ffi.get(key) != expected:
            raise ValueError(f"R3 FFI contract changed for {key}.")
    thresholds = config.get("thresholds", {})
    expected_thresholds = {
        "t1_t2_p50_reduction_min": 0.2,
        "t1_t2_p95_regression_max": 0.0,
        "t0_p50_regression_max": 0.05,
        "ffi_buffer_marshal_fraction_max": 0.1,
        "input_copy_bytes_max": 0,
        "subprocess_count_max": 0,
        "temporary_file_count_max": 0,
        "semantic_parity_required": 1.0,
    }
    for key, expected in expected_thresholds.items():
        if thresholds.get(key) != expected:
            raise ValueError(f"R3 threshold changed for {key}.")
    if set(config.get("decision_rules", {})) != {
        "RUST_CONTROL_PLANE_ADMITTED",
        "REFINE_SHARED_BUFFER_BOUNDARY",
        "OPTIMIZE_OUTPUT_MARSHAL",
        "PAUSE_CURRENT_INPROCESS_ADAPTER",
    }:
        raise ValueError("R3 decision set changed.")
    for field in (
        "h3_api_calls",
        "api_key_uses",
        "paid_api_runs",
        "customer_data_uses",
        "model_downloads",
        "model_loads",
        "cuda_runs",
        "wan_runs",
        "ltx_runs",
    ):
        if config["evidence_boundaries"].get(field) != 0:
            raise ValueError(f"R3 requires {field}=0.")


def _expected_hashes() -> dict[str, str]:
    r1 = load_json(
        ROOT / "reports" / "topology_pruning" / "r1" / "paired-normalization-results.json"
    )
    expected: dict[str, str] = {}
    for summary in r1["combination_summaries"]:
        if summary["case_id"] != "case-b-high-resolution-local-change":
            continue
        hashes = summary["semantic_hashes"]
        if len(hashes) != 1:
            raise ValueError("R1 Case B semantic hash is not deterministic.")
        expected[summary["candidate_id"]] = hashes[0]
    if set(expected) != {"T0", "T1", "T2"}:
        raise ValueError("R1 does not contain all R3 semantic controls.")
    return expected


def _artifact_paths(output_dir: Path) -> list[Path]:
    return [output_dir / name for name in ARTIFACT_NAMES]


def _assert_output_available(output_dir: Path) -> None:
    predeclared = output_dir / ARTIFACT_NAMES[0]
    if not predeclared.is_file():
        raise FileNotFoundError("The committed R3 predeclared contract is missing.")
    collisions = [path for path in _artifact_paths(output_dir)[1:] if path.exists()]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite R3 evidence: "
            + ", ".join(path.relative_to(ROOT).as_posix() for path in collisions)
        )
    unexpected = [
        path
        for path in output_dir.iterdir()
        if path.name not in {ARTIFACT_NAMES[0]}
    ]
    if unexpected:
        raise FileExistsError("R3 output directory contains undeclared artifacts.")


def _implementation_order(seed: int, phase: str, block: int, candidate: str) -> tuple[str, str]:
    return tuple(
        sorted(
            ("python", "rust_inprocess"),
            key=lambda implementation: hashlib.sha256(
                f"{seed}:{phase}:{block}:{candidate}:{implementation}".encode("utf-8")
            ).digest(),
        )
    )


def _extension() -> Any:
    return importlib.import_module("_hive_retina_boundary")


def _run_python(profile: dict[str, Any], topology: str, sequence: np.ndarray) -> dict[str, Any]:
    started = time.perf_counter_ns()
    result = run_pipeline(profile, topology, sequence)
    outer_total_ns = time.perf_counter_ns() - started
    return {
        "outer_total_ns": outer_total_ns,
        "pipeline_total_ns": result["durations_ns"]["total"],
        "semantic_hash": result["semantic_hash"],
        "bytes_copied": result["counters"]["bytes_copied"],
        "temporary_buffer_bytes": result["counters"]["temporary_buffer_bytes"],
    }


def _run_rust(
    extension: Any,
    view: memoryview,
    candidate: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    result = dict(
        extension.run_candidate(
            view,
            candidate,
            profile["profile_id"],
            profile["width"],
            profile["height"],
            profile["frames"],
            profile["seed"],
        )
    )
    wrapper_total_ns = time.perf_counter_ns() - started
    residual = wrapper_total_ns - int(result["rust_function_span_ns"])
    result["wrapper_total_ns"] = wrapper_total_ns
    result["ffi_enter_exit_residual_ns"] = residual
    result["ffi_enter_exit_residual_status"] = "collected"
    result["ffi_enter_exit_residual_method"] = (
        "outer Python extension-call span minus Rust function-entry span; signed and not subtracted"
    )
    return result


def _summaries(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[sample["candidate_id"]].append(sample)
    summaries: dict[str, dict[str, Any]] = {}
    for candidate, group in sorted(grouped.items()):
        python_values = [sample["python"]["outer_total_ns"] for sample in group]
        rust_values = [sample["rust"]["wrapper_total_ns"] for sample in group]
        p50_python = percentile(python_values, 0.50)
        p50_rust = percentile(rust_values, 0.50)
        p95_python = percentile(python_values, 0.95)
        p95_rust = percentile(rust_values, 0.95)
        boundary_values = [
            (
                sample["rust"]["ffi_enter_exit_residual_ns"]
                + sample["rust"]["buffer_acquisition_ns"]
                + sample["rust"]["output_marshal_ns"]
            )
            / sample["rust"]["wrapper_total_ns"]
            for sample in group
        ]
        summaries[candidate] = {
            "pairs": len(group),
            "python_p50_seconds": p50_python / 1_000_000_000,
            "python_p95_seconds": p95_python / 1_000_000_000,
            "rust_boundary_p50_seconds": p50_rust / 1_000_000_000,
            "rust_boundary_p95_seconds": p95_rust / 1_000_000_000,
            "p50_reduction_vs_python": 1.0 - p50_rust / p50_python,
            "p95_regression_vs_python": p95_rust / p95_python - 1.0,
            "ffi_buffer_marshal_fraction_p50": percentile(boundary_values, 0.50),
            "rust_core_p50_seconds": percentile(
                [sample["rust"]["rust_core_ns"] for sample in group], 0.50
            )
            / 1_000_000_000,
            "buffer_acquisition_p50_seconds": percentile(
                [sample["rust"]["buffer_acquisition_ns"] for sample in group], 0.50
            )
            / 1_000_000_000,
            "ffi_enter_exit_residual_p50_seconds": percentile(
                [sample["rust"]["ffi_enter_exit_residual_ns"] for sample in group], 0.50
            )
            / 1_000_000_000,
            "output_marshal_p50_seconds": percentile(
                [sample["rust"]["output_marshal_ns"] for sample in group], 0.50
            )
            / 1_000_000_000,
            "semantic_hashes_python": sorted({sample["python"]["semantic_hash"] for sample in group}),
            "semantic_hashes_rust": sorted({sample["rust"]["semantic_hash"] for sample in group}),
        }
    return summaries


def decide(
    config: dict[str, Any],
    summaries: dict[str, dict[str, Any]],
    parity: dict[str, Any],
    copy_accounting: dict[str, Any],
) -> dict[str, Any]:
    thresholds = config["thresholds"]
    safety = (
        parity["semantic_parity_rate"] == thresholds["semantic_parity_required"]
        and parity["deterministic_hashes"]
        and copy_accounting["input_copy_bytes"] <= thresholds["input_copy_bytes_max"]
        and copy_accounting["subprocess_count"] <= thresholds["subprocess_count_max"]
        and copy_accounting["temporary_file_count"] <= thresholds["temporary_file_count_max"]
        and copy_accounting["unavailable_values_are_null"]
    )
    if not safety:
        return {
            "decision": "PAUSE_CURRENT_INPROCESS_ADAPTER",
            "reason": "A predeclared semantic, deterministic, copy, or unavailable-value safeguard failed.",
        }
    latency = all(
        summaries[candidate]["p50_reduction_vs_python"]
        >= thresholds["t1_t2_p50_reduction_min"]
        and summaries[candidate]["p95_regression_vs_python"]
        <= thresholds["t1_t2_p95_regression_max"]
        and summaries[candidate]["ffi_buffer_marshal_fraction_p50"]
        <= thresholds["ffi_buffer_marshal_fraction_max"]
        for candidate in ("T1", "T2")
    )
    t0 = (
        -summaries["T0"]["p50_reduction_vs_python"]
        <= thresholds["t0_p50_regression_max"]
    )
    if latency and t0:
        return {
            "decision": "RUST_CONTROL_PLANE_ADMITTED",
            "reason": "All predeclared latency, boundary, copy, and semantic safety gates passed.",
        }
    failed = [
        candidate
        for candidate in ("T0", "T1", "T2")
        if summaries[candidate]["ffi_buffer_marshal_fraction_p50"]
        > thresholds["ffi_buffer_marshal_fraction_max"]
    ]
    if failed and all(
        summaries[candidate]["output_marshal_p50_seconds"]
        >= max(
            summaries[candidate]["buffer_acquisition_p50_seconds"],
            summaries[candidate]["ffi_enter_exit_residual_p50_seconds"],
        )
        for candidate in failed
    ):
        return {
            "decision": "OPTIMIZE_OUTPUT_MARSHAL",
            "reason": "Compact output marshaling is the largest failed boundary component.",
        }
    return {
        "decision": "REFINE_SHARED_BUFFER_BOUNDARY",
        "reason": "Semantic safety passed, but one or more predeclared latency or boundary thresholds failed.",
    }


def _measure_empty(extension: Any, repetitions: int) -> dict[str, Any]:
    values = []
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        extension.empty_boundary_probe()
        values.append(time.perf_counter_ns() - started)
    return {
        "samples": repetitions,
        "p50_seconds": percentile(values, 0.50) / 1_000_000_000,
        "p95_seconds": percentile(values, 0.95) / 1_000_000_000,
        "subtracted_from_candidate_results": False,
        "scope": "separate empty extension-call calibration without buffer or core work",
    }


def measure(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"R3 measurement requires Python 3.12, got {platform.python_version()}.")
    extension = _extension()
    if extension.pyo3_version != "0.29.0" or extension.python_abi != "abi3-py312":
        raise RuntimeError("Loaded extension does not match the predeclared PyO3/ABI contract.")
    case_b = next(case for case in CASES if case.case_id == config["case_id"])
    profile, sequence = generate_case(case_b, config["seed"])
    if sequence.shape != tuple(config["shape"]) or sequence.dtype != np.uint8:
        raise RuntimeError("Generated Case B input differs from the contract.")
    sequence.flags.writeable = False
    view = memoryview(sequence).toreadonly()
    if not view.readonly or not view.c_contiguous or view.shape != tuple(config["shape"]):
        raise RuntimeError("Case B could not be exported as the required read-only C buffer.")
    input_hash_before = hashlib.sha256(view).hexdigest()
    expected = _expected_hashes()
    topologies = config["runtime_topologies"]
    for block in range(config["warmups"]):
        for candidate in deterministic_case_b_order(config["seed"], "warmup", block):
            for implementation in _implementation_order(config["seed"], "warmup", block, candidate):
                result = (
                    _run_python(profile, topologies[candidate], sequence)
                    if implementation == "python"
                    else _run_rust(extension, view, candidate, profile)
                )
                if result["semantic_hash"] != expected[candidate]:
                    raise RuntimeError(f"R3 warm-up parity failed for {candidate}/{implementation}.")
    samples: list[dict[str, Any]] = []
    measured_started = time.perf_counter_ns()
    for block in range(config["repetitions"]):
        for order_index, candidate in enumerate(
            deterministic_case_b_order(config["seed"], "measured", block)
        ):
            results: dict[str, dict[str, Any]] = {}
            implementation_order = _implementation_order(
                config["seed"], "measured", block, candidate
            )
            for implementation in implementation_order:
                results[implementation] = (
                    _run_python(profile, topologies[candidate], sequence)
                    if implementation == "python"
                    else _run_rust(extension, view, candidate, profile)
                )
            if any(result["semantic_hash"] != expected[candidate] for result in results.values()):
                raise RuntimeError(f"R3 measured parity failed for {candidate}.")
            samples.append(
                {
                    "block_index": block,
                    "candidate_order_index": order_index,
                    "candidate_id": candidate,
                    "implementation_order": list(implementation_order),
                    "semantic_ref": f"{candidate}:{expected[candidate]}",
                    "python": results["python"],
                    "rust": results["rust_inprocess"],
                    "paired_boundary_delta_ns": (
                        results["rust_inprocess"]["wrapper_total_ns"]
                        - results["python"]["outer_total_ns"]
                    ),
                }
            )
    measured_wall_ns = time.perf_counter_ns() - measured_started
    input_hash_after = hashlib.sha256(view).hexdigest()
    if input_hash_before != input_hash_after:
        raise RuntimeError("Read-only Case B input changed during R3 measurement.")
    summaries = _summaries(samples)
    semantic_evidence = {
        f"{candidate}:{expected[candidate]}": {
            "candidate_id": candidate,
            "semantic_hash": expected[candidate],
            "input_sha256": input_hash_before,
        }
        for candidate in ("T0", "T1", "T2")
    }
    parity = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "pairs": len(samples),
        "pairs_per_candidate": {candidate: 30 for candidate in ("T0", "T1", "T2")},
        "semantic_parity_rate": 1.0,
        "deterministic_hashes": all(
            summaries[candidate]["semantic_hashes_python"]
            == summaries[candidate]["semantic_hashes_rust"]
            == [expected[candidate]]
            for candidate in ("T0", "T1", "T2")
        ),
        "input_hash_stable": input_hash_before == input_hash_after,
        "r1_hash_parity": True,
    }
    copy_accounting = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "input_bytes": int(sequence.nbytes),
        "input_copy_bytes": max(sample["rust"]["input_copy_bytes"] for sample in samples),
        "input_handoff_bytes_per_call": int(sequence.nbytes),
        "ffi_calls_per_candidate": 1,
        "per_eye_ffi_calls": 0,
        "subprocess_count": 0,
        "temporary_file_count": 0,
        "temporary_buffer_bytes_by_candidate": {
            candidate: max(
                sample["rust"]["temporary_buffer_bytes"]
                for sample in samples
                if sample["candidate_id"] == candidate
            )
            for candidate in ("T0", "T1", "T2")
        },
        "allocation_count": {
            "value": None,
            "status": "not_collected",
            "reason": "The Rust global allocator is not instrumented in R3.",
            "method": "requires an instrumented allocator",
        },
        "unavailable_values_are_null": True,
        "addresses_serialized": False,
    }
    result = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "implementation": "python_3_12_pyo3_0_29_abi3",
        "profile": config["profile"],
        "topologies": config["topologies"],
        "seed": config["seed"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pyo3": extension.pyo3_version,
        "python_abi": extension.python_abi,
        "measured_wall_seconds": measured_wall_ns / 1_000_000_000,
        "empty_boundary_overhead": _measure_empty(extension, config["repetitions"]),
        "semantic_evidence": semantic_evidence,
        "samples": samples,
        "summaries": summaries,
        "json_hot_path": False,
        "model_loaded": False,
        "cuda_used": False,
    }
    return result, parity, copy_accounting, decide(config, summaries, parity, copy_accounting)


def _decision_markdown(config: dict[str, Any], result: dict[str, Any], decision: dict[str, Any]) -> str:
    lines = [
        "# M1-P0-R3 In-process Shared-buffer Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        decision["reason"],
        "",
        "This model-free control-plane result does not claim real-video or model speedup.",
        "Compound Perception First remains the product direction; Mono remains only the comparator and safety fallback.",
        "",
        "| Candidate | Python p50 | Rust boundary p50 | p50 change | Python p95 | Rust p95 | boundary fraction |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate in config["topologies"]:
        item = result["summaries"][candidate]
        lines.append(
            f"| {candidate} | {item['python_p50_seconds']:.9f}s | "
            f"{item['rust_boundary_p50_seconds']:.9f}s | "
            f"{item['p50_reduction_vs_python']:+.2%} reduction | "
            f"{item['python_p95_seconds']:.9f}s | "
            f"{item['rust_boundary_p95_seconds']:.9f}s | "
            f"{item['ffi_buffer_marshal_fraction_p50']:.2%} |"
        )
    lines.extend(
        [
            "",
            "The run used 5 warm-ups and 30 same-process paired blocks per candidate.",
            "Input copies, subprocesses, temporary files, model loads, and CUDA runs were zero.",
            "",
        ]
    )
    return "\n".join(lines)


def plan(args: argparse.Namespace) -> dict[str, Any]:
    config = load_json(args.config)
    validate_config(config)
    validate_immutable_r2(config)
    output_dir = args.output_dir.resolve()
    contract_sha256 = sha256_file(args.config)
    return {
        "execution_started": False,
        "run_kind": config["run_kind"],
        "issue": config["issue"],
        "profile": config["profile"],
        "shape": config["shape"],
        "dtype": config["dtype"],
        "topologies": config["topologies"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "ffi": config["ffi"],
        "contract_sha256": contract_sha256,
        "expected_output_directory": output_dir.relative_to(ROOT).as_posix()
        if output_dir.is_relative_to(ROOT)
        else "<external-output-directory>",
        "expected_artifacts": list(ARTIFACT_NAMES),
        "model_loads": 0,
        "cuda_runs": 0,
    }


def execute(args: argparse.Namespace) -> dict[str, Any]:
    config = load_json(args.config)
    validate_config(config)
    validate_immutable_r2(config)
    actual_hash = sha256_file(args.config)
    if args.expect_contract_sha256 is None or args.expect_contract_sha256 != actual_hash:
        raise ValueError("R3 requires the exact plan contract hash before measurement.")
    _assert_output_available(args.output_dir)
    result, parity, copy_accounting, decision = measure(config)
    write_json(args.output_dir / "inprocess-boundary-results.json", result)
    write_json(args.output_dir / "parity-report.json", parity)
    write_json(args.output_dir / "copy-accounting.json", copy_accounting)
    decision_path = args.output_dir / "decision-report.md"
    if decision_path.exists():
        raise FileExistsError(f"Refusing to overwrite {decision_path.name}.")
    decision_path.write_text(_decision_markdown(config, result, decision), encoding="utf-8")
    return {
        "execution_started": True,
        "decision": decision["decision"],
        "pairs": len(result["samples"]),
        "artifacts": list(ARTIFACT_NAMES),
        "model_loads": 0,
        "cuda_runs": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--expect-contract-sha256")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = plan(args) if args.plan else execute(args)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
