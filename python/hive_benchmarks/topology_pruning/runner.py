"""Run the bounded M1-P0 analytical topology probe."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from hive_probes.rust_io_reference import benchmark_case, run_pipeline

from hive_benchmarks.topology_pruning.candidates import (
    CANDIDATES,
    analytical_precheck,
    topology_geometry,
)
from hive_benchmarks.topology_pruning.cost_model import (
    amdahl_bound,
    break_even_seconds,
    build_cost_record,
    prediction_error,
)
from hive_benchmarks.topology_pruning.metrics import (
    metric_value,
    unavailable,
)
from hive_benchmarks.topology_pruning.report import (
    decide_gate,
    decision_markdown,
    write_json,
)
from hive_benchmarks.topology_pruning.synthetic_cases import (
    CASES,
    case_receipt,
    exact_dirty_mask,
    generate_case,
)


RUN_KIND = "analytical_topology_pruning_probe"
SCHEMA_VERSION = "0.1.0"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _scope_mask(
    shape: tuple[int, int],
    units: list[dict[str, Any]],
) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.bool_)
    for unit in units:
        if unit["action"] not in {"generate", "reconcile"}:
            continue
        scope = unit["scope"]
        mask[
            scope["y"] : scope["y"] + scope["height"],
            scope["x"] : scope["x"] + scope["width"],
        ] = True
    return mask


def _accuracy(
    sequence: np.ndarray,
    semantic_result: dict[str, Any],
) -> dict[str, float]:
    dirty = exact_dirty_mask(sequence)
    selected = _scope_mask(
        (sequence.shape[1], sequence.shape[2]),
        semantic_result["compute_plan"]["units"],
    )
    actual = int(np.count_nonzero(dirty))
    predicted = int(np.count_nonzero(selected))
    true_positive = int(np.count_nonzero(dirty & selected))
    false_negative = actual - true_positive
    precision = 1.0 if predicted == 0 and actual == 0 else (
        0.0 if predicted == 0 else true_positive / predicted
    )
    recall = 1.0 if actual == 0 else true_positive / actual
    false_stable = 0.0 if actual == 0 else false_negative / actual
    return {
        "actual_dirty_pixels": actual,
        "selected_dirty_pixels": predicted,
        "true_positive_pixels": true_positive,
        "false_stable_pixels": false_negative,
        "dirty_precision": precision,
        "dirty_recall": recall,
        "false_stable_rate": false_stable,
    }


def _measurement(
    case_id: str,
    calibration_profile: str,
    candidate_id: str,
    topology: str,
    profile: dict[str, Any],
    sequence: np.ndarray,
    cost: dict[str, Any],
    warmups: int,
    repetitions: int,
) -> dict[str, Any]:
    benchmark = benchmark_case(
        profile,
        topology,
        warmups=warmups,
        repetitions=repetitions,
    )
    semantic = run_pipeline(profile, topology, sequence)["semantic_result"]
    predicted = metric_value(cost["predicted_probe_p50"])
    measured_p50 = metric_value(benchmark["metrics"]["p50_latency_seconds"])
    if predicted is None or measured_p50 is None:
        raise ValueError("Predicted and measured p50 must be available.")
    comparison = prediction_error(predicted, measured_p50)
    comparison.update(
        {
            "predicted_seconds": predicted,
            "measured_seconds": measured_p50,
            "predicted_S_required_seconds": metric_value(cost["S_required"]),
        }
    )
    metrics = dict(benchmark["metrics"])
    metrics["overlap_seconds_mean"] = unavailable(
        "seconds",
        "The v0 reference has no isolated overlap timer.",
        method="not separately instrumented",
    )
    return {
        "case_id": case_id,
        "calibration_profile": calibration_profile,
        "candidate_id": candidate_id,
        "runtime_topology": topology,
        "warmups": warmups,
        "repetitions": repetitions,
        "eye_count": benchmark["eye_count"],
        "semantic_hash": benchmark["semantic_hash"],
        "metrics": metrics,
        "accuracy": _accuracy(sequence, semantic),
        "comparison": comparison,
    }


def _attach_measured_break_even(measured: list[dict[str, Any]]) -> None:
    mono_by_case = {
        item["case_id"]: metric_value(item["metrics"]["p50_latency_seconds"])
        for item in measured
        if item["candidate_id"] == "T0"
    }
    for item in measured:
        candidate = metric_value(item["metrics"]["p50_latency_seconds"])
        mono = mono_by_case.get(item["case_id"])
        if candidate is None or mono is None:
            raise ValueError("Measured break-even requires candidate and Mono p50.")
        item["comparison"]["measured_S_required_seconds"] = break_even_seconds(
            candidate,
            mono,
        )


def _rankings(measured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in measured:
        grouped[item["case_id"]].append(item)
    results = []
    for case_id, items in sorted(grouped.items()):
        predicted = sorted(
            items,
            key=lambda item: (
                item["comparison"]["predicted_seconds"],
                item["candidate_id"],
            ),
        )
        actual = sorted(
            items,
            key=lambda item: (
                item["comparison"]["measured_seconds"],
                item["candidate_id"],
            ),
        )
        results.append(
            {
                "case_id": case_id,
                "status": (
                    "unavailable_single_candidate"
                    if len(items) < 2
                    else "available"
                ),
                "reason": (
                    "Analytical pruning left only the mandatory Mono comparator."
                    if len(items) < 2
                    else None
                ),
                "predicted_ranking": [
                    item["candidate_id"] for item in predicted
                ],
                "measured_ranking": [item["candidate_id"] for item in actual],
                "ranking_match": (
                    None
                    if len(items) < 2
                    else [
                        item["candidate_id"] for item in predicted
                    ]
                    == [item["candidate_id"] for item in actual]
                ),
            }
        )
    return results


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    config = _load_json(args.config)
    rust_report = _load_json(args.rust_report)
    if rust_report.get("decision", {}).get("decision") != "CONDITIONAL_ADMIT":
        raise ValueError("Merged Rust report is not CONDITIONAL_ADMIT.")
    if rust_report.get("model_loaded") or rust_report.get("cuda_used"):
        raise ValueError("Rust calibration must remain model-free and CPU-only.")

    seed = int(config["seed"])
    warmups = int(config["warmups"])
    repetitions = int(config["repetitions"])
    thresholds = config["thresholds"]
    analytical_cases: list[dict[str, Any]] = []
    measured_cases: list[dict[str, Any]] = []
    cost_records: list[dict[str, Any]] = []

    started = time.perf_counter()
    for case in CASES:
        profile, sequence = generate_case(case, seed)
        receipt = case_receipt(case, seed)
        for candidate in CANDIDATES:
            geometry = topology_geometry(case, candidate)
            cost = build_cost_record(
                rust_report,
                case.calibration_profile,
                candidate.runtime_topology,
                "mono_1x1",
                geometry,
            )
            precheck = analytical_precheck(
                case,
                candidate,
                geometry,
                thresholds,
            )
            analytical_cases.append(
                {
                    "case_id": case.case_id,
                    "candidate_id": candidate.candidate_id,
                    "candidate_label": candidate.label,
                    "runtime_topology": candidate.runtime_topology,
                    "case_receipt": receipt,
                    "geometry": geometry,
                    "precheck": precheck,
                    "S_required": cost["S_required"],
                }
            )
            cost_records.append(
                {
                    "case_id": case.case_id,
                    "candidate_id": candidate.candidate_id,
                    "cost": cost,
                }
            )
            if precheck["status"] == "retained_for_probe":
                measured_cases.append(
                    _measurement(
                        case.case_id,
                        case.calibration_profile,
                        candidate.candidate_id,
                        candidate.runtime_topology,
                        profile,
                        sequence,
                        cost,
                        warmups,
                        repetitions,
                    )
                )

    _attach_measured_break_even(measured_cases)
    rankings = _rankings(measured_cases)
    amdahl = amdahl_bound(rust_report)
    decision = decide_gate(analytical_cases, measured_cases, thresholds)
    maximum_false_stable = max(
        item["accuracy"]["false_stable_rate"] for item in measured_cases
    )
    summary = {
        "decision": decision,
        "analytical_combinations": len(analytical_cases),
        "pruned_combinations": sum(
            item["precheck"]["status"] == "analytically_pruned"
            for item in analytical_cases
        ),
        "measured_combinations": len(measured_cases),
        "warmups": warmups,
        "repetitions": repetitions,
        "maximum_false_stable": maximum_false_stable,
        "amdahl": amdahl,
    }
    common = {
        "schema_version": SCHEMA_VERSION,
        "run_kind": RUN_KIND,
        "benchmark_status": "model_free_pre_gate",
        "official_m0_run_receipt": False,
        "m0_completion_eligible": False,
        "m1_completion_eligible": False,
        "model_loaded": False,
        "cuda_used": False,
        "base_main_commit": config["base_main_commit"],
        "rust_probe_merge_commit": config["rust_probe_merge_commit"],
        "rust_probe_issue_35_closed": True,
        "analytical_issue": config["analytical_issue"],
        "seed": seed,
        "warmups": warmups,
        "repetitions": repetitions,
    }
    analytical_model = {
        **common,
        "cost_equation": (
            "C_total(T)=C_scout+C_route(T)+C_observe(T)+C_overlap(T)+"
            "C_fusion(T)+C_plan(T)+C_generation(T)+C_audit(T)+"
            "E[C_recovery|T]"
        ),
        "break_even_equation": (
            "S_required(T)=C_input_and_orchestration(T)-"
            "C_input_and_orchestration(Mono)"
        ),
        "thresholds": thresholds,
        "amdahl": amdahl,
        "cost_records": cost_records,
    }
    pruning_report = {
        **common,
        "cases": analytical_cases,
        "summary": {
            "total": len(analytical_cases),
            "pruned": summary["pruned_combinations"],
            "retained": summary["measured_combinations"],
        },
    }
    minimal_results = {
        **common,
        "measurements": measured_cases,
        "rankings": rankings,
        "runner_wall_seconds": time.perf_counter() - started,
        "summary": summary,
    }

    write_json(output_dir / "analytical-model.json", analytical_model)
    write_json(
        output_dir / "candidate-pruning-report.json",
        pruning_report,
    )
    write_json(output_dir / "minimal-probe-results.json", minimal_results)
    decision_path = output_dir / "decision-report.md"
    if decision_path.exists():
        raise FileExistsError(f"Refusing to overwrite {decision_path}")
    decision_path.write_text(
        decision_markdown(summary),
        encoding="utf-8",
    )
    return {
        "output_dir": output_dir.as_posix(),
        "decision": decision["decision"],
        "analytical_combinations": len(analytical_cases),
        "pruned_combinations": summary["pruned_combinations"],
        "measured_combinations": len(measured_cases),
        "execution_started": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the model-free M1-P0 topology pre-gate.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "m1-p0.analytical-topology-pruning.json",
    )
    parser.add_argument(
        "--rust-report",
        type=Path,
        default=ROOT / "reports" / "rust_io_admission" / "benchmark-summary.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "topology_pruning",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_probe(args)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
