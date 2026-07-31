"""Run the predeclared model-free M1-P0-R2 attribution and Rust boundary probe."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any, Iterable

from hive_benchmarks.topology_pruning.paired_normalization import (
    assert_unavailable_values_are_null,
    deterministic_case_b_order,
    sha256_file,
)
from hive_benchmarks.topology_pruning.r2_attribution import (
    STAGE_TAXONOMY,
    calibrate_instrumentation,
    run_attributed,
)
from hive_benchmarks.topology_pruning.report import write_json
from hive_benchmarks.topology_pruning.synthetic_cases import CASES, generate_case
from hive_probes.rust_io_reference import run_pipeline


ROOT = Path(__file__).resolve().parents[3]
RUN_KIND = "m1_p0_r2_rust_compound_runtime"
ARTIFACT_NAMES = (
    "predeclared-attribution-model.json",
    "python-stage-attribution.json",
    "rust-boundary-results.json",
    "parity-report.json",
    "decision-report.md",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=not binary,
        encoding=None if binary else "utf-8",
    )
    return completed.stdout if binary else completed.stdout.strip()


def validate_immutable_git_blobs(config: dict[str, Any]) -> None:
    for path, expected in sorted(config["immutable_git_blob_sha256"].items()):
        artifact = ROOT / path
        if not artifact.is_file():
            raise ValueError(f"Immutable v1/R1 artifact is missing: {path}")
        content = artifact.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise ValueError(
                f"Immutable v1/R1 Git blob changed for {path}: expected {expected}, got {actual}"
            )


def validate_config(config: dict[str, Any]) -> None:
    if config.get("run_kind") != RUN_KIND:
        raise ValueError("Unexpected R2 run kind.")
    if (
        config.get("profile") != "case-b-high-resolution-local-change"
        or config.get("case_id") != "case-b-high-resolution-local-change"
    ):
        raise ValueError("R2 is restricted to the existing Case B profile.")
    if config.get("topologies") != ["T0", "T1", "T2"]:
        raise ValueError("R2 must retain exactly B/T0, B/T1, and B/T2.")
    if config.get("warmups") != 5 or config.get("repetitions") != 20:
        raise ValueError("R2 is fixed at 5 warm-ups and 20 measured blocks.")
    if tuple(config.get("stage_taxonomy", ())) != STAGE_TAXONOMY:
        raise ValueError("R2 stage taxonomy changed.")
    pairing = config.get("pairing", {})
    if pairing.get("members_per_block") != ["T0", "T1", "T2"]:
        raise ValueError("R2 pairing requires one T0/T1/T2 set per block.")
    if not all(
        pairing.get(name) is True
        for name in (
            "same_process",
            "same_sequence_object",
            "same_repetition_block",
            "independent_median_subtraction_forbidden",
        )
    ):
        raise ValueError("R2 paired-attribution safeguards changed.")
    boundary = config.get("rust_boundary", {})
    if boundary.get("calls_per_suite") != 1 or boundary.get("input_handoffs_per_suite") != 1:
        raise ValueError("R2 requires one coarse Rust batch and one input handoff.")
    if boundary.get("per_eye_round_trips_forbidden") is not True:
        raise ValueError("Per-eye Python/Rust round trips are forbidden.")
    decisions = set(config.get("decision_rules", {}))
    if decisions != {
        "RUST_RUNTIME_VIABLE",
        "REFINE_RUST_BOUNDARY",
        "OPTIMIZE_COMPOUND_RUNTIME",
        "PAUSE_CURRENT_IMPLEMENTATION",
    }:
        raise ValueError("R2 decision set changed.")
    evidence = config.get("evidence_boundaries", {})
    for field in (
        "h3_api_calls",
        "api_key_uses",
        "paid_api_runs",
        "model_downloads",
        "model_loads",
        "cuda_runs",
    ):
        if evidence.get(field) != 0:
            raise ValueError(f"R2 requires {field}=0.")


def _artifact_paths(output_dir: Path) -> list[Path]:
    return [output_dir / name for name in ARTIFACT_NAMES]


def _assert_output_available(output_dir: Path) -> None:
    collisions = [path for path in _artifact_paths(output_dir) if path.exists()]
    if collisions:
        raise FileExistsError(
            "Refusing to overwrite R2 artifacts: "
            + ", ".join(path.as_posix() for path in collisions)
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"R2 output directory is not empty: {output_dir}")


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered or not 0 < quantile <= 1:
        raise ValueError("Invalid nearest-rank percentile request.")
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _expected_hashes() -> dict[str, str]:
    r1 = _load_json(ROOT / "reports" / "topology_pruning" / "r1" / "paired-normalization-results.json")
    expected: dict[str, str] = {}
    for summary in r1["combination_summaries"]:
        if summary["case_id"] != "case-b-high-resolution-local-change":
            continue
        hashes = summary["semantic_hashes"]
        if len(hashes) != 1:
            raise ValueError("R1 Case B semantic hash is not deterministic.")
        expected[summary["candidate_id"]] = hashes[0]
    if set(expected) != {"T0", "T1", "T2"}:
        raise ValueError("R1 does not contain the complete Case B hash set.")
    return expected


def _summaries(samples: list[dict[str, Any]], total_field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[sample["candidate_id"]].append(sample)
    return {
        candidate: {
            "samples": len(group),
            "p50_seconds": percentile(
                [sample[total_field] / 1_000_000_000 for sample in group], 0.50
            ),
            "p95_seconds": percentile(
                [sample[total_field] / 1_000_000_000 for sample in group], 0.95
            ),
            "semantic_hashes": sorted({sample["semantic_hash"] for sample in group}),
        }
        for candidate, group in sorted(grouped.items())
    }


def _paired_python_attribution(
    samples: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    by_block: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for sample in samples:
        by_block[int(sample["block_index"])][sample["candidate_id"]] = sample
    if len(by_block) != config["repetitions"]:
        raise ValueError("R2 Python block count differs from the declaration.")
    result: dict[str, Any] = {}
    for candidate in ("T1", "T2"):
        records = []
        for block_index, block in sorted(by_block.items()):
            if set(block) != {"T0", "T1", "T2"}:
                raise ValueError(f"Incomplete R2 Python block {block_index}.")
            mono = block["T0"]
            compound = block[candidate]
            stage_deltas = {
                stage: compound["attributed"]["stages"][stage]["exclusive_ns"]
                - mono["attributed"]["stages"][stage]["exclusive_ns"]
                for stage in STAGE_TAXONOMY
            }
            attributed_delta_ns = sum(stage_deltas.values())
            attributed_total_delta_ns = (
                compound["attributed"]["total_ns"] - mono["attributed"]["total_ns"]
            )
            unattributed_delta_ns = (
                compound["attributed"]["unattributed_ns"]
                - mono["attributed"]["unattributed_ns"]
            )
            if attributed_total_delta_ns != attributed_delta_ns + unattributed_delta_ns:
                raise RuntimeError("R2 attribution equation failed at block level.")
            records.append(
                {
                    "block_index": block_index,
                    "candidate_id": candidate,
                    "uninstrumented_paired_delta_ns": compound["uninstrumented_total_ns"]
                    - mono["uninstrumented_total_ns"],
                    "instrumented_paired_delta_ns": attributed_total_delta_ns,
                    "stage_delta_exclusive_ns": stage_deltas,
                    "attributed_stage_delta_sum_ns": attributed_delta_ns,
                    "unattributed_remainder_ns": unattributed_delta_ns,
                    "equation_holds": True,
                }
            )
        instrumented_p50 = percentile(
            [record["instrumented_paired_delta_ns"] for record in records], 0.50
        )
        attributed_p50 = percentile(
            [record["attributed_stage_delta_sum_ns"] for record in records], 0.50
        )
        unattributed_p50 = percentile(
            [record["unattributed_remainder_ns"] for record in records], 0.50
        )
        stage_summary = {
            stage: {
                "p50_delta_seconds": percentile(
                    [record["stage_delta_exclusive_ns"][stage] for record in records], 0.50
                )
                / 1_000_000_000,
                "p95_delta_seconds": percentile(
                    [record["stage_delta_exclusive_ns"][stage] for record in records], 0.95
                )
                / 1_000_000_000,
                "aggregation": "nearest-rank over same-block exclusive stage deltas",
            }
            for stage in STAGE_TAXONOMY
        }
        result[candidate] = {
            "pairs": len(records),
            "records": records,
            "uninstrumented_paired_delta_p50_seconds": percentile(
                [record["uninstrumented_paired_delta_ns"] for record in records], 0.50
            )
            / 1_000_000_000,
            "uninstrumented_paired_delta_p95_seconds": percentile(
                [record["uninstrumented_paired_delta_ns"] for record in records], 0.95
            )
            / 1_000_000_000,
            "instrumented_paired_delta_p50_seconds": instrumented_p50 / 1_000_000_000,
            "instrumented_paired_delta_p95_seconds": percentile(
                [record["instrumented_paired_delta_ns"] for record in records], 0.95
            )
            / 1_000_000_000,
            "attributed_stage_delta_sum_p50_seconds": attributed_p50 / 1_000_000_000,
            "unattributed_remainder_p50_seconds": unattributed_p50 / 1_000_000_000,
            "attributed_percentage": None
            if instrumented_p50 == 0
            else attributed_p50 / instrumented_p50,
            "unattributed_percentage": None
            if instrumented_p50 == 0
            else unattributed_p50 / instrumented_p50,
            "stages": stage_summary,
        }
    return result


def _python_measurement(
    config: dict[str, Any], profile: dict[str, Any], sequence: Any, expected: dict[str, str]
) -> dict[str, Any]:
    calibration = calibrate_instrumentation(config["instrumentation_calibration_repetitions"])
    runtime_topologies = config["runtime_topologies"]
    for block_index in range(config["warmups"]):
        for candidate in deterministic_case_b_order(config["seed"], "warmup", block_index):
            topology = runtime_topologies[candidate]
            plain = run_pipeline(profile, topology, sequence)
            attributed = run_attributed(profile, topology, sequence)
            if plain["semantic_hash"] != expected[candidate] or attributed["semantic_hash"] != expected[candidate]:
                raise RuntimeError(f"Python warm-up semantic parity failed for {candidate}.")
    samples: list[dict[str, Any]] = []
    measured_started = time.perf_counter_ns()
    for block_index in range(config["repetitions"]):
        for order_index, candidate in enumerate(
            deterministic_case_b_order(config["seed"], "measured", block_index)
        ):
            topology = runtime_topologies[candidate]
            plain = run_pipeline(profile, topology, sequence)
            attributed = run_attributed(profile, topology, sequence)
            if plain["semantic_hash"] != attributed["semantic_hash"] or plain["semantic_hash"] != expected[candidate]:
                raise RuntimeError(f"Python measured semantic parity failed for {candidate}.")
            samples.append(
                {
                    "block_index": block_index,
                    "order_index": order_index,
                    "candidate_id": candidate,
                    "topology": topology,
                    "semantic_hash": plain["semantic_hash"],
                    "uninstrumented_total_ns": plain["durations_ns"]["total"],
                    "uninstrumented_durations_ns": plain["durations_ns"],
                    "attributed": attributed,
                }
            )
    measured_wall_ns = time.perf_counter_ns() - measured_started
    if len(samples) != config["repetitions"] * 3:
        raise RuntimeError("R2 Python measured sample count differs from the declaration.")
    return {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "implementation": "python_numpy_attributed",
        "profile": config["profile"],
        "seed": config["seed"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "instrumentation_calibration": calibration,
        "measured_wall_seconds": measured_wall_ns / 1_000_000_000,
        "samples": samples,
        "uninstrumented_summaries": _summaries(samples, "uninstrumented_total_ns"),
        "paired_attribution": _paired_python_attribution(samples, config),
        "execution_order": "uninstrumented then attributed for each deterministic candidate",
    }


def _rust_measurement(
    config: dict[str, Any], sequence: Any, rust_binary: Path, expected: dict[str, str]
) -> dict[str, Any]:
    if not rust_binary.is_file():
        raise FileNotFoundError(f"R2 Rust binary is missing: {rust_binary}")
    with tempfile.TemporaryDirectory(prefix="hiveframe-r2-") as temporary:
        temporary_path = Path(temporary)
        input_path = temporary_path / "case-b.bin"
        rust_output = temporary_path / "rust-r2.json"
        write_started = time.perf_counter_ns()
        input_path.write_bytes(memoryview(sequence).cast("B"))
        python_input_write_ns = time.perf_counter_ns() - write_started
        command = [
            str(rust_binary),
            "r2-batch",
            "--profile",
            config["profile"],
            "--input",
            str(input_path),
            "--output",
            str(rust_output),
            "--warmups",
            str(config["warmups"]),
            "--repetitions",
            str(config["repetitions"]),
            "--seed",
            str(config["seed"]),
        ]
        call_started = time.perf_counter_ns()
        completed = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
        process_call_ns = time.perf_counter_ns() - call_started
        if completed.returncode != 0:
            raise RuntimeError(
                f"R2 Rust batch failed ({completed.returncode}).\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        parse_started = time.perf_counter_ns()
        envelope = _load_json(rust_output)
        python_parse_ns = time.perf_counter_ns() - parse_started
        output_file_bytes = rust_output.stat().st_size
    report = envelope["report"]
    samples = report["samples"]
    if len(samples) != config["repetitions"] * 3:
        raise RuntimeError("R2 Rust measured sample count differs from the declaration.")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[sample["candidate_id"]].append(sample)
        if sample["semantic_hash"] != expected[sample["candidate_id"]]:
            raise RuntimeError(f"Rust semantic parity failed for {sample['candidate_id']}.")
    summaries = {
        candidate: {
            "samples": len(group),
            "core_p50_seconds": percentile(
                [sample["durations_ns"]["total_ns"] for sample in group], 0.50
            )
            / 1_000_000_000,
            "core_p95_seconds": percentile(
                [sample["durations_ns"]["total_ns"] for sample in group], 0.95
            )
            / 1_000_000_000,
            "semantic_hashes": sorted({sample["semantic_hash"] for sample in group}),
            "logical_bytes_read": sorted({sample["counters"]["logical_bytes_read"] for sample in group}),
            "core_copied_bytes": sorted({sample["counters"]["bytes_copied"] for sample in group}),
            "temporary_buffer_bytes": sorted(
                {sample["counters"]["temporary_buffer_bytes"] for sample in group}
            ),
        }
        for candidate, group in sorted(grouped.items())
    }
    pipeline_executions = 3 + (config["warmups"] + config["repetitions"]) * 3
    internal_ns = int(report["suite_internal_wall_ns"])
    boundary_overhead_ns = max(0, process_call_ns - internal_ns)
    amortized_boundary_ns = boundary_overhead_ns / pipeline_executions
    for summary in summaries.values():
        summary["benchmark_amortized_boundary_inclusive_p50_seconds"] = (
            summary["core_p50_seconds"] + amortized_boundary_ns / 1_000_000_000
        )
    input_bytes = int(sequence.nbytes)
    copied_bytes = input_bytes + int(envelope["boundary"]["input_copy_bytes"])
    return {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "implementation": report["implementation"],
        "transport": envelope["transport"],
        "command": command,
        "samples": samples,
        "summaries": summaries,
        "boundary": {
            "process_call_seconds": process_call_ns / 1_000_000_000,
            "rust_internal_suite_seconds": internal_ns / 1_000_000_000,
            "python_input_write_seconds": python_input_write_ns / 1_000_000_000,
            "rust_input_read_seconds": envelope["boundary"]["input_read_ns"] / 1_000_000_000,
            "python_output_parse_seconds": python_parse_ns / 1_000_000_000,
            "rust_serialization_probe_seconds": envelope["boundary"]["serialization_probe_ns"] / 1_000_000_000,
            "ffi_call_seconds": envelope["boundary"]["ffi_call_seconds"],
            "pipeline_executions_in_process": pipeline_executions,
            "amortized_boundary_seconds_per_execution": amortized_boundary_ns / 1_000_000_000,
            "scope_note": "benchmark-suite amortization; not a single-call product latency claim",
        },
        "copy_accounting": {
            "input_bytes": input_bytes,
            "python_input_file_write_bytes": input_bytes,
            "rust_input_file_read_copy_bytes": envelope["boundary"]["input_copy_bytes"],
            "total_boundary_copied_bytes": copied_bytes,
            "copied_input_multiples": copied_bytes / input_bytes,
            "rust_output_serialization_probe_bytes": envelope["boundary"]["serialization_probe_bytes"],
            "rust_output_file_bytes": output_file_bytes,
            "temporary_boundary_bytes": input_bytes + output_file_bytes,
        },
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def decide(
    config: dict[str, Any], python_result: dict[str, Any], rust_result: dict[str, Any]
) -> dict[str, Any]:
    thresholds = config["thresholds"]
    parity = all(
        len(rust_result["summaries"][candidate]["semantic_hashes"]) == 1
        and rust_result["summaries"][candidate]["semantic_hashes"]
        == python_result["uninstrumented_summaries"][candidate]["semantic_hashes"]
        for candidate in ("T0", "T1", "T2")
    )
    deterministic = parity
    copy_ok = (
        rust_result["copy_accounting"]["copied_input_multiples"]
        <= thresholds["copied_input_multiples_max"]
    )
    comparisons: dict[str, Any] = {}
    for candidate in ("T0", "T1", "T2"):
        python_p50 = python_result["uninstrumented_summaries"][candidate]["p50_seconds"]
        rust_core = rust_result["summaries"][candidate]["core_p50_seconds"]
        rust_boundary = rust_result["summaries"][candidate][
            "benchmark_amortized_boundary_inclusive_p50_seconds"
        ]
        comparisons[candidate] = {
            "python_p50_seconds": python_p50,
            "rust_core_p50_seconds": rust_core,
            "rust_boundary_inclusive_p50_seconds": rust_boundary,
            "rust_core_reduction_ratio": (python_p50 - rust_core) / python_p50,
            "rust_boundary_inclusive_reduction_ratio": (python_p50 - rust_boundary) / python_p50,
        }
    core_better = all(
        comparisons[candidate]["rust_core_reduction_ratio"]
        > thresholds["rust_core_reduction_required"]
        for candidate in ("T1", "T2")
    )
    boundary_better = all(
        comparisons[candidate]["rust_boundary_inclusive_reduction_ratio"]
        > thresholds["rust_boundary_inclusive_reduction_required"]
        for candidate in ("T1", "T2")
    )
    ffi_collected = rust_result["boundary"]["ffi_call_seconds"]["status"] == "collected"
    attribution_ok = all(
        python_result["paired_attribution"][candidate]["attributed_percentage"] is not None
        and python_result["paired_attribution"][candidate]["attributed_percentage"]
        >= thresholds["python_attributed_percentage_min"]
        for candidate in ("T1", "T2")
    )
    if not (parity and deterministic and copy_ok):
        decision = "PAUSE_CURRENT_IMPLEMENTATION"
        reason = "Semantic parity, determinism, or fixed copy safety failed."
    elif core_better and boundary_better and (
        ffi_collected or not thresholds["ffi_collected_required_for_viable"]
    ):
        decision = "RUST_RUNTIME_VIABLE"
        reason = "Rust core and boundary-inclusive T1/T2 costs are lower with complete boundary evidence."
    elif core_better:
        decision = "REFINE_RUST_BOUNDARY"
        reason = "Rust core improves T1/T2, but FFI or boundary evidence is incomplete or offsets the gain."
    elif attribution_ok:
        decision = "OPTIMIZE_COMPOUND_RUNTIME"
        reason = "Python overhead is attributable, but the current Rust core does not remove it."
    else:
        decision = "PAUSE_CURRENT_IMPLEMENTATION"
        reason = "Current attribution and Rust evidence do not identify an economic implementation path."
    return {
        "decision": decision,
        "reason": reason,
        "semantic_parity": parity,
        "deterministic_hashes": deterministic,
        "copy_limit_passed": copy_ok,
        "python_attribution_passed": attribution_ok,
        "rust_core_better_t1_t2": core_better,
        "rust_boundary_better_t1_t2": boundary_better,
        "ffi_collected": ffi_collected,
        "comparisons": comparisons,
    }


def _decision_markdown(decision: dict[str, Any], config: dict[str, Any]) -> str:
    lines = [
        "# M1-P0-R2 Rust Compound Runtime Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        decision["reason"],
        "",
        "Compound Perception First remains the product direction. Mono is the comparator and safety fallback, not the R2 product decision.",
        "",
        "| Candidate | Python p50 ms | Rust core p50 ms | Boundary-inclusive p50 ms | Core change | Boundary change |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in ("T0", "T1", "T2"):
        item = decision["comparisons"][candidate]
        lines.append(
            f"| {candidate} | {item['python_p50_seconds'] * 1000:.6f} | "
            f"{item['rust_core_p50_seconds'] * 1000:.6f} | "
            f"{item['rust_boundary_inclusive_p50_seconds'] * 1000:.6f} | "
            f"{item['rust_core_reduction_ratio'] * 100:.2f}% | "
            f"{item['rust_boundary_inclusive_reduction_ratio'] * 100:.2f}% |"
        )
    lines.extend(
        [
            "",
            f"Semantic parity: `{str(decision['semantic_parity']).lower()}`.",
            "",
            f"Deterministic hashes: `{str(decision['deterministic_hashes']).lower()}`.",
            "",
            f"FFI collected: `{str(decision['ffi_collected']).lower()}`; the v0 transport is one coarse subprocess batch.",
            "",
            "H3 API calls: 0. API-key uses: 0. Paid runs: 0. Model downloads: 0. Model loads: 0. CUDA runs: 0.",
            "",
            "This is model-free CPU control-plane evidence, not backend, quality, end-to-end, or commercial speedup evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def plan(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_json(args.config)
    validate_config(config)
    validate_immutable_git_blobs(config)
    return {
        "execution_started": False,
        "run_kind": config["run_kind"],
        "issue": config["issue"],
        "base_main_commit": config["base_main_commit"],
        "profile": config["profile"],
        "case_id": config["case_id"],
        "topologies": config["topologies"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "stage_taxonomy": config["stage_taxonomy"],
        "rust_boundary": config["rust_boundary"],
        "thresholds": config["thresholds"],
        "output_dir": args.output_dir.as_posix(),
        "expected_artifacts": [path.as_posix() for path in _artifact_paths(args.output_dir)],
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_json(args.config)
    validate_config(config)
    if _git("status", "--porcelain"):
        raise ValueError("R2 measurement requires a clean pre-measurement commit.")
    _assert_output_available(args.output_dir)
    validate_immutable_git_blobs(config)
    premeasurement_commit = _git("rev-parse", "HEAD")
    predeclared = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "premeasurement_commit": premeasurement_commit,
        "config_path": args.config.relative_to(ROOT).as_posix(),
        "config_sha256": sha256_file(args.config),
        "base_main_commit": config["base_main_commit"],
        "pr_41_merge_commit": config["pr_41_merge_commit"],
        "issue": config["issue"],
        "profile": config["profile"],
        "case_id": config["case_id"],
        "topologies": config["topologies"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "stage_taxonomy": config["stage_taxonomy"],
        "span_nesting": config["span_nesting"],
        "instrumentation": config["instrumentation"],
        "attribution_equation": config["attribution_equation"],
        "pairing": config["pairing"],
        "rust_boundary": config["rust_boundary"],
        "copy_accounting": config["copy_accounting"],
        "thresholds": config["thresholds"],
        "decision_rules": config["decision_rules"],
        "immutable_git_blob_sha256": config["immutable_git_blob_sha256"],
        "evidence_boundaries": config["evidence_boundaries"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.output_dir / "predeclared-attribution-model.json", predeclared)

    case_b = next(case for case in CASES if case.case_id == config["case_id"])
    profile, sequence = generate_case(case_b, config["seed"])
    expected = _expected_hashes()
    python_result = _python_measurement(config, profile, sequence, expected)
    rust_result = _rust_measurement(config, sequence, args.rust_binary, expected)
    decision = decide(config, python_result, rust_result)
    parity = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "premeasurement_commit": premeasurement_commit,
        "semantic_parity": decision["semantic_parity"],
        "deterministic_hashes": decision["deterministic_hashes"],
        "expected_hashes": expected,
        "python_hashes": {
            candidate: python_result["uninstrumented_summaries"][candidate]["semantic_hashes"]
            for candidate in ("T0", "T1", "T2")
        },
        "rust_hashes": {
            candidate: rust_result["summaries"][candidate]["semantic_hashes"]
            for candidate in ("T0", "T1", "T2")
        },
        "copy_limit_passed": decision["copy_limit_passed"],
        "evidence_boundaries": config["evidence_boundaries"],
    }
    assert_unavailable_values_are_null(rust_result)
    write_json(args.output_dir / "python-stage-attribution.json", python_result)
    write_json(args.output_dir / "rust-boundary-results.json", rust_result)
    write_json(args.output_dir / "parity-report.json", parity)
    (args.output_dir / "decision-report.md").write_text(
        _decision_markdown(decision, config), encoding="utf-8"
    )
    validate_immutable_git_blobs(config)
    return {
        "execution_started": True,
        "decision": decision["decision"],
        "premeasurement_commit": premeasurement_commit,
        "python_samples": len(python_result["samples"]),
        "rust_samples": len(rust_result["samples"]),
        "output_dir": args.output_dir.as_posix(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run model-free M1-P0-R2 attribution.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "m1-p0-r2.rust-compound-runtime.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "topology_pruning" / "r2",
    )
    parser.add_argument(
        "--rust-binary",
        type=Path,
        default=ROOT / "target" / "release" / "hive-retina-runtime.exe",
    )
    parser.add_argument("--plan", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = plan(args) if args.plan else run_probe(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
