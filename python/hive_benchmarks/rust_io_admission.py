"""Run the model-free Python/Rust Compound I/O admission comparison."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hive_probes.rust_io_reference import TOPOLOGIES, benchmark_suite


DEFAULT_PROFILES = ("low", "medium", "high")
FLOAT_TOLERANCE = 1e-9


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _semantic_differences(
    left: Any,
    right: Any,
    *,
    path: str = "$",
) -> list[dict[str, Any]]:
    if isinstance(left, bool) or isinstance(right, bool):
        return [] if left == right else [{"path": path, "python": left, "rust": right}]
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, int) and isinstance(right, int):
            matches = left == right
        else:
            matches = abs(float(left) - float(right)) <= FLOAT_TOLERANCE
        return [] if matches else [{"path": path, "python": left, "rust": right}]
    if type(left) is not type(right):
        return [
            {
                "path": path,
                "python_type": type(left).__name__,
                "rust_type": type(right).__name__,
            }
        ]
    if isinstance(left, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append(
                    {
                        "path": f"{path}.{key}",
                        "python": left.get(key, "<missing>"),
                        "rust": right.get(key, "<missing>"),
                    }
                )
            else:
                differences.extend(
                    _semantic_differences(
                        left[key],
                        right[key],
                        path=f"{path}.{key}",
                    )
                )
        return differences
    if isinstance(left, list):
        if len(left) != len(right):
            return [
                {
                    "path": path,
                    "python_length": len(left),
                    "rust_length": len(right),
                }
            ]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(
                _semantic_differences(
                    left_item,
                    right_item,
                    path=f"{path}[{index}]",
                )
            )
        return differences
    return [] if left == right else [{"path": path, "python": left, "rust": right}]


def _case_map(suite: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (case["profile_id"], case["topology"]): case
        for case in suite["cases"]
    }


def compare_suites(
    python_suite: dict[str, Any],
    rust_suite: dict[str, Any],
) -> dict[str, Any]:
    python_cases = _case_map(python_suite)
    rust_cases = _case_map(rust_suite)
    keys = sorted(set(python_cases) | set(rust_cases))
    results = []
    all_passed = True
    for profile, topology in keys:
        python_case = python_cases.get((profile, topology))
        rust_case = rust_cases.get((profile, topology))
        if python_case is None or rust_case is None:
            differences = [
                {
                    "path": "$",
                    "reason": "Case missing from one implementation.",
                }
            ]
        else:
            differences = _semantic_differences(
                python_case["semantic_result"],
                rust_case["semantic_result"],
            )
            if python_case["semantic_hash"] != rust_case["semantic_hash"]:
                differences.append(
                    {
                        "path": "$.semantic_hash",
                        "python": python_case["semantic_hash"],
                        "rust": rust_case["semantic_hash"],
                    }
                )
        passed = not differences
        all_passed = all_passed and passed
        results.append(
            {
                "profile_id": profile,
                "topology": topology,
                "status": "passed" if passed else "failed",
                "python_semantic_hash": (
                    None if python_case is None else python_case["semantic_hash"]
                ),
                "rust_semantic_hash": (
                    None if rust_case is None else rust_case["semantic_hash"]
                ),
                "differences": differences,
            }
        )
    return {
        "schema_version": "0.1.0",
        "kind": "rust_io_admission_parity_report",
        "float_tolerance": FLOAT_TOLERANCE,
        "integer_comparison": "exact",
        "status": "passed" if all_passed else "failed",
        "cases": results,
        "model_loaded": False,
        "cuda_used": False,
    }


def _metric_value(case: dict[str, Any], name: str) -> float | None:
    return case["metrics"][name]["value"]


def _reduction(python_value: float | None, rust_value: float | None) -> float | None:
    if python_value is None or rust_value is None or python_value == 0:
        return None
    return 1.0 - rust_value / python_value


def compare_performance(
    python_suite: dict[str, Any],
    rust_suite: dict[str, Any],
) -> list[dict[str, Any]]:
    python_cases = _case_map(python_suite)
    rust_cases = _case_map(rust_suite)
    comparisons = []
    for key in sorted(set(python_cases) & set(rust_cases)):
        python_case = python_cases[key]
        rust_case = rust_cases[key]
        p50_python = _metric_value(python_case, "p50_latency_seconds")
        p50_rust = _metric_value(rust_case, "p50_latency_seconds")
        p95_python = _metric_value(python_case, "p95_latency_seconds")
        p95_rust = _metric_value(rust_case, "p95_latency_seconds")
        copied_python = _metric_value(python_case, "bytes_copied")
        copied_rust = _metric_value(rust_case, "bytes_copied")
        temporary_python = _metric_value(python_case, "temporary_buffer_bytes")
        temporary_rust = _metric_value(rust_case, "temporary_buffer_bytes")
        comparisons.append(
            {
                "profile_id": key[0],
                "topology": key[1],
                "python": {
                    "p50_seconds": p50_python,
                    "p95_seconds": p95_python,
                    "bytes_copied": copied_python,
                    "temporary_buffer_bytes": temporary_python,
                    "eye_count": python_case["eye_count"],
                },
                "rust": {
                    "p50_seconds": p50_rust,
                    "p95_seconds": p95_rust,
                    "bytes_copied": copied_rust,
                    "temporary_buffer_bytes": temporary_rust,
                    "eye_count": rust_case["eye_count"],
                },
                "reduction": {
                    "p50": _reduction(p50_python, p50_rust),
                    "p95": _reduction(p95_python, p95_rust),
                    "copied_bytes": _reduction(copied_python, copied_rust),
                    "temporary_buffer_bytes": _reduction(
                        temporary_python,
                        temporary_rust,
                    ),
                },
            }
        )
    return comparisons


def decide_admission(
    parity: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> dict[str, Any]:
    if parity["status"] != "passed":
        return {
            "decision": "REJECT",
            "required_gate": "failed",
            "performance_candidate_gate": "not_evaluated",
            "reason": "Python/Rust semantic parity failed.",
        }
    qualifying = []
    for comparison in comparisons:
        reduction = comparison["reduction"]
        conditions = {
            "p50_at_least_20_percent": (
                reduction["p50"] is not None and reduction["p50"] >= 0.20
            ),
            "p95_at_least_25_percent": (
                reduction["p95"] is not None and reduction["p95"] >= 0.25
            ),
            "copied_bytes_at_least_25_percent": (
                reduction["copied_bytes"] is not None
                and reduction["copied_bytes"] >= 0.25
            ),
            "temporary_bytes_at_least_25_percent": (
                reduction["temporary_buffer_bytes"] is not None
                and reduction["temporary_buffer_bytes"] >= 0.25
            ),
        }
        if any(conditions.values()):
            qualifying.append(
                {
                    "profile_id": comparison["profile_id"],
                    "topology": comparison["topology"],
                    "conditions": conditions,
                }
            )
    if not qualifying:
        return {
            "decision": "DEFER",
            "required_gate": "passed",
            "performance_candidate_gate": "failed",
            "reason": (
                "Parity passed, but no representative case met the "
                "predeclared core-pipeline admission threshold."
            ),
            "qualifying_cases": [],
        }
    return {
        "decision": "CONDITIONAL_ADMIT",
        "required_gate": "passed",
        "performance_candidate_gate": "passed",
        "reason": (
            "Core orchestration parity and at least one performance admission "
            "threshold passed, but PyO3/FFI, shared-buffer, backend, and "
            "end-to-end impact remain unmeasured."
        ),
        "qualifying_cases": qualifying,
    }


def _format_percent(value: float | None) -> str:
    return "unavailable" if value is None else f"{value * 100:.2f}%"


def decision_markdown(
    decision: dict[str, Any],
    comparisons: list[dict[str, Any]],
    *,
    warmups: int,
    repetitions: int,
) -> str:
    lines = [
        "# Rust I/O Admission Decision",
        "",
        f"Decision: **{decision['decision']}**",
        "",
        "This is a model-free control-plane admission result. It is not a Wan, "
        "GPU, quality, or commercial speedup claim.",
        "",
        "## Execution contract",
        "",
        f"- warm-ups: {warmups}",
        f"- measured repetitions: {repetitions}",
        "- input generation and process startup: excluded from core spans",
        "- Python/Rust process startup: reported separately",
        "- model loads: 0",
        "- CUDA runs: 0",
        "",
        "## Core comparison",
        "",
        "| Profile | Topology | Python p50 (ms) | Rust p50 (ms) | "
        "p50 reduction | p95 reduction | Temporary reduction |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in comparisons:
        lines.append(
            "| {profile_id} | {topology} | {python_ms:.3f} | {rust_ms:.3f} | "
            "{p50} | {p95} | {temporary} |".format(
                profile_id=item["profile_id"],
                topology=item["topology"],
                python_ms=item["python"]["p50_seconds"] * 1000,
                rust_ms=item["rust"]["p50_seconds"] * 1000,
                p50=_format_percent(item["reduction"]["p50"]),
                p95=_format_percent(item["reduction"]["p95"]),
                temporary=_format_percent(
                    item["reduction"]["temporary_buffer_bytes"]
                ),
            )
        )
    lines.extend(
        [
            "",
            "## Gate rationale",
            "",
            decision["reason"],
            "",
            "The result cannot become `ADMIT` until process/FFI overhead and "
            "the candidate pipeline's attributable share of accepted-result "
            "end-to-end cost are measured.",
            "",
        ]
    )
    return "\n".join(lines)


def _worker(
    output: Path,
    profiles: list[str],
    topologies: list[str],
    seed: int,
    warmups: int,
    repetitions: int,
) -> int:
    if output.exists():
        raise SystemExit(f"Worker output already exists: {output}")
    suite = benchmark_suite(
        profiles,
        topologies,
        seed=seed,
        warmups=warmups,
        repetitions=repetitions,
    )
    _write_json(output, suite)
    return 0


def _run_process(command: list[str], *, label: str) -> tuple[float, str, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=os.environ.copy(),
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit {completed.returncode}.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return elapsed, completed.stdout, completed.stderr


def run_admission(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    profiles = list(args.profiles)
    topologies = list(args.topologies)
    with tempfile.TemporaryDirectory(prefix="hiveframe-rust-io-") as temp:
        temp_dir = Path(temp)
        python_output = temp_dir / "python-suite.json"
        rust_output = temp_dir / "rust-suite.json"
        python_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker-python-output",
            str(python_output),
            "--profiles",
            *profiles,
            "--topologies",
            *topologies,
            "--seed",
            str(args.seed),
            "--warmups",
            str(args.warmups),
            "--repetitions",
            str(args.repetitions),
        ]
        rust_command = [
            str(args.rust_binary),
            "suite",
            "--profiles",
            ",".join(profiles),
            "--topologies",
            ",".join(topologies),
            "--seed",
            str(args.seed),
            "--warmups",
            str(args.warmups),
            "--repetitions",
            str(args.repetitions),
            "--output",
            str(rust_output),
        ]
        python_process_seconds, _, python_stderr = _run_process(
            python_command,
            label="Python worker",
        )
        rust_process_seconds, rust_stdout, rust_stderr = _run_process(
            rust_command,
            label="Rust worker",
        )
        python_suite = json.loads(python_output.read_text(encoding="utf-8"))
        rust_suite = json.loads(rust_output.read_text(encoding="utf-8"))

    parity = compare_suites(python_suite, rust_suite)
    comparisons = compare_performance(python_suite, rust_suite)
    decision = decide_admission(parity, comparisons)
    summary = {
        "schema_version": "0.1.0",
        "kind": "rust_io_admission_probe",
        "benchmark_status": "model_free_orchestration_admission",
        "official_wan_baseline": False,
        "quality_eligible": False,
        "speedup_comparison_eligible": False,
        "model_loaded": False,
        "cuda_used": False,
        "seed": args.seed,
        "profiles": profiles,
        "topologies": topologies,
        "extended_profile": {
            "status": "skipped",
            "reason": (
                "The optional 4K profile was not needed for the default "
                "admission decision; the high profile already exercised "
                "multi-region 1080p routing."
            ),
        },
        "warmups": args.warmups,
        "repetitions": args.repetitions,
        "process_scope": {
            "python_external_command_seconds": python_process_seconds,
            "rust_external_command_seconds": rust_process_seconds,
            "python_core_suite_seconds": python_suite["core_suite_wall_seconds"],
            "rust_core_suite_seconds": rust_suite["core_suite_wall_seconds"],
            "python_interpreter_startup_is_in_external_only": True,
            "rust_process_startup_is_in_external_only": True,
            "compilation_seconds": {
                "value": None,
                "unit": "seconds",
                "status": "uncollected",
                "reason": "Compilation was completed before the benchmark command.",
                "method": "requires a separately timed clean build",
            },
        },
        "commands": {
            "python_worker": (
                "python -m hive_benchmarks.rust_io_admission "
                "--worker-python-output <temporary-file> ..."
            ),
            "rust_worker": (
                "hive-retina-runtime suite --output <temporary-file> ..."
            ),
        },
        "python_environment": python_suite["environment"],
        "rust_environment": rust_suite["environment"],
        "python_cases": python_suite["cases"],
        "rust_cases": rust_suite["cases"],
        "comparisons": comparisons,
        "decision": decision,
        "unsupported_metrics": {
            "estimated_wan_end_to_end_gain": {
                "value": None,
                "unit": "ratio",
                "status": "uncollected",
                "reason": (
                    "M0 has no eligible isolated input-orchestration span for "
                    "this candidate pipeline."
                ),
                "method": (
                    "requires an attributable same-condition M0 input-side span"
                ),
            },
            "ffi_end_to_end_seconds": {
                "value": None,
                "unit": "seconds",
                "status": "uncollected",
                "reason": "PyO3 and FFI are outside this probe.",
                "method": "requires a separate shared-buffer integration probe",
            },
        },
        "worker_diagnostics": {
            "python_stderr": python_stderr,
            "rust_stdout": rust_stdout,
            "rust_stderr": rust_stderr,
        },
    }
    _write_json(output_dir / "benchmark-summary.json", summary)
    _write_json(output_dir / "parity-report.json", parity)
    (output_dir / "decision-report.md").write_text(
        decision_markdown(
            decision,
            comparisons,
            warmups=args.warmups,
            repetitions=args.repetitions,
        ),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare model-free Python and Rust Compound I/O paths."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/rust_io_admission"),
    )
    parser.add_argument("--rust-binary", type=Path)
    parser.add_argument("--profiles", nargs="+", default=list(DEFAULT_PROFILES))
    parser.add_argument("--topologies", nargs="+", default=list(TOPOLOGIES))
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--repetitions", type=int, default=30)
    parser.add_argument("--worker-python-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker_python_output is not None:
        return _worker(
            args.worker_python_output,
            list(args.profiles),
            list(args.topologies),
            args.seed,
            args.warmups,
            args.repetitions,
        )
    if args.rust_binary is None:
        raise SystemExit("--rust-binary is required for the admission comparison.")
    summary = run_admission(args)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "kind": summary["kind"],
                "decision": summary["decision"]["decision"],
                "output_dir": args.output_dir.as_posix(),
                "model_loaded": False,
                "cuda_used": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
