"""Run the predeclared model-free M1-P0-R1 paired-Mono probe."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from hive_benchmarks.topology_pruning.candidates import CANDIDATES
from hive_benchmarks.topology_pruning.metrics import metric_value, unavailable
from hive_benchmarks.topology_pruning.paired_normalization import (
    CASE_B,
    RUN_KIND,
    assert_unavailable_values_are_null,
    decide_r1_gate,
    deterministic_case_b_order,
    paired_delta_records,
    percentile,
    sha256_file,
    summarize_paired_deltas,
    validate_config,
    validate_v1_hashes,
)
from hive_benchmarks.topology_pruning.report import write_json
from hive_benchmarks.topology_pruning.runner import _accuracy
from hive_benchmarks.topology_pruning.synthetic_cases import CASES, generate_case
from hive_probes.rust_io_reference import run_pipeline


ARTIFACT_NAMES = (
    "predeclared-model.json",
    "paired-normalization-results.json",
    "prediction-validation.json",
    "decision-report.md",
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return process.stdout.strip()


def _assert_clean_worktree() -> None:
    if _git("status", "--porcelain"):
        raise ValueError("R1 measurement requires the clean pre-measurement commit.")


def _artifact_paths(output_dir: Path) -> list[Path]:
    return [output_dir / name for name in ARTIFACT_NAMES]


def _assert_output_available(output_dir: Path) -> None:
    collisions = [path for path in _artifact_paths(output_dir) if path.exists()]
    if collisions:
        joined = ", ".join(path.as_posix() for path in collisions)
        raise FileExistsError(f"Refusing to overwrite R1 artifacts: {joined}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"R1 output directory is not empty: {output_dir}")


def _candidate_maps() -> tuple[dict[str, Any], dict[str, Any]]:
    by_id = {candidate.candidate_id: candidate for candidate in CANDIDATES}
    by_topology = {candidate.runtime_topology: candidate for candidate in CANDIDATES}
    return by_id, by_topology


def _v1_maps(
    analytical_model: dict[str, Any],
    v1_results: dict[str, Any],
) -> tuple[dict[str, float], dict[str, str], dict[str, dict[str, Any]]]:
    predicted: dict[str, float] = {}
    for record in analytical_model["cost_records"]:
        if record["case_id"] == CASE_B and record["candidate_id"] in {"T1", "T2"}:
            value = metric_value(record["cost"]["S_required"])
            if value is None:
                raise ValueError("v1 predicted paired delta is unavailable.")
            predicted[record["candidate_id"]] = value
    if set(predicted) != {"T1", "T2"}:
        raise ValueError("v1 analytical model lacks Case B T1/T2 predictions.")

    hashes: dict[str, str] = {}
    measurements: dict[str, dict[str, Any]] = {}
    for measurement in v1_results["measurements"]:
        key = f"{measurement['case_id']}/{measurement['candidate_id']}"
        hashes[key] = measurement["semantic_hash"]
        measurements[key] = measurement
    return predicted, hashes, measurements


def _phase_schedule(seed: int, phase: str, block_index: int) -> list[tuple[str, str]]:
    return [
        ("case-a-low-resolution-simple", "T0"),
        *[(CASE_B, candidate) for candidate in deterministic_case_b_order(seed, phase, block_index)],
        ("case-c-global-motion", "T0"),
    ]


def _execute_phase(
    *,
    phase: str,
    blocks: int,
    seed: int,
    prepared: dict[str, tuple[dict[str, Any], Any]],
    expected_hashes: dict[str, str],
) -> list[dict[str, Any]]:
    by_id, _ = _candidate_maps()
    samples: list[dict[str, Any]] = []
    for block_index in range(blocks):
        schedule = _phase_schedule(seed, phase, block_index)
        for order_index, (case_id, candidate_id) in enumerate(schedule):
            profile, sequence = prepared[case_id]
            candidate = by_id[candidate_id]
            process_cpu_started = time.process_time_ns()
            run = run_pipeline(profile, candidate.runtime_topology, sequence)
            process_cpu_seconds = (
                time.process_time_ns() - process_cpu_started
            ) / 1_000_000_000
            key = f"{case_id}/{candidate_id}"
            if run["semantic_hash"] != expected_hashes[key]:
                raise RuntimeError(f"R1 semantic hash changed for {key}.")
            assert_unavailable_values_are_null(
                run["semantic_result"]["compute_plan"]["claims"]
            )
            if phase == "measured":
                durations = {
                    name: nanoseconds / 1_000_000_000
                    for name, nanoseconds in run["durations_ns"].items()
                }
                samples.append(
                    {
                        "phase": phase,
                        "block_index": block_index,
                        "order_index": order_index,
                        "case_id": case_id,
                        "candidate_id": candidate_id,
                        "runtime_topology": candidate.runtime_topology,
                        "total_seconds": durations["total"],
                        "durations_seconds": durations,
                        "process_cpu_seconds": process_cpu_seconds,
                        "semantic_hash": run["semantic_hash"],
                        "accuracy": _accuracy(
                            sequence,
                            run["semantic_result"],
                        ),
                        "counters": run["counters"],
                    }
                )
    return samples


def _combination_summaries(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        grouped[f"{sample['case_id']}/{sample['candidate_id']}"] .append(sample)
    summaries: list[dict[str, Any]] = []
    for key, group in sorted(grouped.items()):
        totals = [float(sample["total_seconds"]) for sample in group]
        stage_names = sorted(group[0]["durations_seconds"])
        stage_summary = {
            stage: {
                "p50_seconds": percentile(
                    [sample["durations_seconds"][stage] for sample in group],
                    0.50,
                ),
                "p95_seconds": percentile(
                    [sample["durations_seconds"][stage] for sample in group],
                    0.95,
                ),
                "mean_seconds": statistics.fmean(
                    sample["durations_seconds"][stage] for sample in group
                ),
            }
            for stage in stage_names
        }
        summaries.append(
            {
                "combination": key,
                "case_id": group[0]["case_id"],
                "candidate_id": group[0]["candidate_id"],
                "samples": len(group),
                "p50_seconds": percentile(totals, 0.50),
                "p95_seconds": percentile(totals, 0.95),
                "mean_seconds": statistics.fmean(totals),
                "stage_summary": stage_summary,
                "semantic_hashes": sorted({sample["semantic_hash"] for sample in group}),
                "dirty_recall_min": min(sample["accuracy"]["dirty_recall"] for sample in group),
                "false_stable_max": max(sample["accuracy"]["false_stable_rate"] for sample in group),
                "logical_bytes_read": sorted({sample["counters"]["logical_bytes_read"] for sample in group}),
                "bytes_copied": sorted({sample["counters"]["bytes_copied"] for sample in group}),
                "temporary_buffer_bytes": sorted({sample["counters"]["temporary_buffer_bytes"] for sample in group}),
            }
        )
    return summaries


def _unavailable_metrics() -> dict[str, dict[str, Any]]:
    return {
        "backend_generation_seconds": unavailable(
            "seconds",
            "R1 is model-free and executes no admitted backend.",
            method="not measured; separate admitted backend experiment required",
        ),
        "audit_seconds": unavailable(
            "seconds",
            "R1 has no generated output to audit.",
            method="not measured; separate output audit required",
        ),
        "recovery_seconds": unavailable(
            "seconds",
            "R1 executes no backend repair or fallback path.",
            method="not measured; separate backend failure experiment required",
        ),
        "h3_generation_seconds": unavailable(
            "seconds",
            "MiniMax H3 has not passed Issue #39 admission and is not called.",
            method="not measured; no API key or API call",
        ),
        "gpu_kernel_seconds": unavailable(
            "seconds",
            "R1 has no CUDA execution path.",
            method="not measured; separate profiler/CUPTI run required",
        ),
        "end_to_end_speedup": unavailable(
            "ratio",
            "Generation, audit, repair, and complete M0 input share are unavailable.",
            method="cannot evaluate a complete-cost end-to-end comparison",
            status="partially_available",
        ),
    }


def _decision_markdown(
    *,
    decision: dict[str, str],
    paired: dict[str, dict[str, Any]],
    ranking: dict[str, Any],
    dirty_recall: float,
    false_stable: float,
    amdahl_status: str,
) -> str:
    lines = [
        "# M1-P0-R1 Same-run Mono Normalization Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        decision["reason"],
        "",
        "This is a backend-neutral model-free pre-gate refinement. It does not close M0 or M1 and is not a model, GPU, quality, product, or commercial speedup claim.",
        "",
        "## Paired delta validation",
        "",
        "| Candidate | Predicted delta ms | Measured p50 ms | Measured p95 ms | Relative error |",
        "|---|---:|---:|---:|---:|",
    ]
    for candidate in ("T1", "T2"):
        item = paired[candidate]
        lines.append(
            f"| {candidate} | {item['predicted_delta_seconds'] * 1000:.6f} | "
            f"{item['measured_delta_p50_seconds'] * 1000:.6f} | "
            f"{item['measured_delta_p95_seconds'] * 1000:.6f} | "
            f"{item['relative_error'] * 100:.2f}% |"
        )
    lines.extend(
        [
            "",
            f"Predicted ranking: `{' < '.join(ranking['predicted'])}`.",
            "",
            f"Measured ranking: `{' < '.join(ranking['measured'])}`.",
            "",
            f"Ranking match: `{str(ranking['match']).lower()}`.",
            "",
            f"Dirty recall minimum: `{dirty_recall:.6f}`.",
            "",
            f"False-stable maximum: `{false_stable:.6f}`.",
            "",
            f"Amdahl status: `{amdahl_status}`; no end-to-end bound is asserted.",
            "",
            "H3 API calls: 0.",
            "",
            "Paid API runs: 0.",
            "",
            "Model downloads: 0.",
            "",
            "Model loads: 0.",
            "",
            "CUDA runs: 0.",
            "",
        ]
    )
    return "\n".join(lines)


def plan(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_json(args.config)
    validate_config(config)
    return {
        "execution_started": False,
        "run_kind": config["run_kind"],
        "issue": config["issue"],
        "base_main_commit": config["base_main_commit"],
        "warmups": config["warmups"],
        "repetitions": config["repetitions"],
        "retained_combinations": config["retained_combinations"],
        "analytically_pruned_combinations": config["analytically_pruned_combinations"],
        "pairing": config["pairing"],
        "thresholds": config["thresholds"],
        "output_dir": args.output_dir.as_posix(),
        "expected_artifacts": [path.as_posix() for path in _artifact_paths(args.output_dir)],
    }


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_json(args.config)
    validate_config(config)
    _assert_clean_worktree()
    _assert_output_available(args.output_dir)
    validate_v1_hashes(ROOT, config["v1_immutable_sha256"])

    analytical_model_path = ROOT / "reports" / "topology_pruning" / "analytical-model.json"
    v1_results_path = ROOT / "reports" / "topology_pruning" / "minimal-probe-results.json"
    analytical_model = _load_json(analytical_model_path)
    v1_results = _load_json(v1_results_path)
    predicted_deltas, expected_hashes, v1_measurements = _v1_maps(
        analytical_model,
        v1_results,
    )
    premeasurement_commit = _git("rev-parse", "HEAD")
    predeclared_model = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "benchmark_status": "model_free_pre_gate_refinement",
        "premeasurement_commit": premeasurement_commit,
        "config_path": args.config.relative_to(ROOT).as_posix(),
        "config_sha256": sha256_file(args.config),
        "base_main_commit": config["base_main_commit"],
        "pr_38_merge_commit": config["pr_38_merge_commit"],
        "issue": config["issue"],
        "cost_model": config["cost_model"],
        "coefficient_sources": config["coefficient_sources"],
        "predicted_case_b_deltas_seconds": predicted_deltas,
        "pairing": config["pairing"],
        "thresholds": config["thresholds"],
        "gate_rules": config["gate_rules"],
        "retained_combinations": config["retained_combinations"],
        "analytically_pruned_combinations": config["analytically_pruned_combinations"],
        "v1_immutable_sha256": config["v1_immutable_sha256"],
        "evidence_boundaries": config["evidence_boundaries"],
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    write_json(args.output_dir / "predeclared-model.json", predeclared_model)

    prepared = {case.case_id: generate_case(case, int(config["seed"])) for case in CASES}
    _execute_phase(
        phase="warmup",
        blocks=int(config["warmups"]),
        seed=int(config["seed"]),
        prepared=prepared,
        expected_hashes=expected_hashes,
    )
    measured_started = time.perf_counter()
    samples = _execute_phase(
        phase="measured",
        blocks=int(config["repetitions"]),
        seed=int(config["seed"]),
        prepared=prepared,
        expected_hashes=expected_hashes,
    )
    runner_wall_seconds = time.perf_counter() - measured_started
    if len(samples) != len(config["retained_combinations"]) * int(config["repetitions"]):
        raise RuntimeError("R1 measured execution count differs from the predeclared scope.")

    paired_records = {
        candidate: paired_delta_records(samples, candidate)
        for candidate in ("T1", "T2")
    }
    paired_summaries = {
        candidate: summarize_paired_deltas(
            paired_records[candidate],
            predicted_deltas[candidate],
        )
        for candidate in ("T1", "T2")
    }
    combination_summaries = _combination_summaries(samples)
    dirty_recall = min(item["dirty_recall_min"] for item in combination_summaries)
    false_stable = max(item["false_stable_max"] for item in combination_summaries)
    deterministic_hashes = all(
        len(item["semantic_hashes"]) == 1
        and item["semantic_hashes"][0] == expected_hashes[item["combination"]]
        for item in combination_summaries
    )
    predicted_ranking = sorted(
        ("T0", "T1", "T2"),
        key=lambda candidate: (0.0 if candidate == "T0" else predicted_deltas[candidate], candidate),
    )
    measured_ranking = sorted(
        ("T0", "T1", "T2"),
        key=lambda candidate: (
            0.0 if candidate == "T0" else paired_summaries[candidate]["measured_delta_p50_seconds"],
            candidate,
        ),
    )
    ranking = {
        "predicted": predicted_ranking,
        "measured": measured_ranking,
        "match": predicted_ranking == measured_ranking,
        "basis": "T0=0 and Case B paired-delta p50 for T1/T2",
    }
    unavailable_metrics = _unavailable_metrics()
    assert_unavailable_values_are_null(unavailable_metrics)
    decision = decide_r1_gate(
        paired_summaries,
        ranking_match=ranking["match"],
        dirty_recall=dirty_recall,
        false_stable=false_stable,
        deterministic_hashes=deterministic_hashes,
        unavailable_semantics_valid=True,
        thresholds=config["thresholds"],
    )

    paired_results = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "benchmark_status": "model_free_pre_gate_refinement",
        "premeasurement_commit": premeasurement_commit,
        "seed": config["seed"],
        "warmups": config["warmups"],
        "repetition_blocks": config["repetitions"],
        "same_process": True,
        "same_prepared_sequence_objects": True,
        "runner_wall_seconds_measured_phase": runner_wall_seconds,
        "samples": samples,
        "combination_summaries": combination_summaries,
        "paired_records": paired_records,
        "paired_summaries": paired_summaries,
        "unavailable_metrics": unavailable_metrics,
        "evidence_boundaries": config["evidence_boundaries"],
    }
    v1_error = {
        key: measurement["comparison"]["relative_error"]
        for key, measurement in sorted(v1_measurements.items())
    }
    prediction_validation = {
        "schema_version": config["schema_version"],
        "run_kind": config["run_kind"],
        "premeasurement_commit": premeasurement_commit,
        "v1_absolute_relative_error": v1_error,
        "r1_paired_delta_validation": paired_summaries,
        "ranking": ranking,
        "dirty_recall_min": dirty_recall,
        "false_stable_max": false_stable,
        "deterministic_hashes": deterministic_hashes,
        "unavailable_semantics_valid": True,
        "amdahl": v1_results["summary"]["amdahl"],
        "decision": decision,
        "v1_artifacts_unchanged": True,
        "official_speedup_eligible": False,
        "m0_completion_eligible": False,
        "m1_completion_eligible": False,
    }
    assert_unavailable_values_are_null(prediction_validation)
    write_json(args.output_dir / "paired-normalization-results.json", paired_results)
    write_json(args.output_dir / "prediction-validation.json", prediction_validation)
    decision_path = args.output_dir / "decision-report.md"
    decision_path.write_text(
        _decision_markdown(
            decision=decision,
            paired=paired_summaries,
            ranking=ranking,
            dirty_recall=dirty_recall,
            false_stable=false_stable,
            amdahl_status=v1_results["summary"]["amdahl"]["status"],
        ),
        encoding="utf-8",
    )
    validate_v1_hashes(ROOT, config["v1_immutable_sha256"])
    return {
        "execution_started": True,
        "decision": decision["decision"],
        "premeasurement_commit": premeasurement_commit,
        "measured_combinations": len(combination_summaries),
        "measured_samples": len(samples),
        "paired_samples_per_candidate": config["repetitions"],
        "output_dir": args.output_dir.as_posix(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the model-free M1-P0-R1 same-run Mono probe.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "m1-p0-r1.same-run-mono-normalization.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "topology_pruning" / "r1",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the fixed R1 contract without executing the pipeline.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = plan(args) if args.plan else run_probe(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
