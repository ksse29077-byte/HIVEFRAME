"""Deterministic arithmetic audit for committed M1-P0-R2 evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from hive_benchmarks.topology_pruning.r2_attribution import STAGE_TAXONOMY
from hive_benchmarks.topology_pruning.r2_runner import percentile


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(root: Path) -> dict[str, Any]:
    report_root = root / "reports" / "topology_pruning"
    success = report_root / "r2"
    python_result = _load(success / "python-stage-attribution.json")
    rust_result = _load(success / "rust-boundary-results.json")
    parity = _load(success / "parity-report.json")
    config = _load(root / "configs" / "m1-p0-r2.rust-compound-runtime.json")
    attempt_001 = _load(report_root / "r2-failures" / "attempt-001" / "failure.json")
    attempt_002 = _load(report_root / "r2-failures" / "attempt-002" / "failure.json")
    decision_text = (success / "decision-report.md").read_text(encoding="utf-8")

    assertions = 0

    def check(condition: bool, message: str) -> None:
        nonlocal assertions
        assertions += 1
        if not condition:
            raise AssertionError(message)

    for candidate in ("T1", "T2"):
        for record in python_result["paired_attribution"][candidate]["records"]:
            stage_deltas = record["stage_delta_exclusive_ns"]
            check(record["equation_holds"] is True, "paired equation marker failed")
            check(record["candidate_id"] == candidate, "paired candidate changed")
            check(0 <= record["block_index"] < 20, "paired block changed")
            check(set(stage_deltas) == set(STAGE_TAXONOMY), "paired taxonomy changed")
            check(
                sum(stage_deltas.values()) == record["attributed_stage_delta_sum_ns"],
                "exclusive stage sum changed",
            )
            check(
                record["instrumented_paired_delta_ns"]
                == record["attributed_stage_delta_sum_ns"]
                + record["unattributed_remainder_ns"],
                "signed attribution identity changed",
            )

    semantic_evidence = python_result["semantic_evidence"]
    for sample in python_result["samples"]:
        record = semantic_evidence.get(sample["semantic_ref"])
        check(
            record is not None
            and record["candidate_id"] == sample["candidate_id"]
            and record["semantic_hash"] == sample["semantic_hash"]
            and "semantic_result" not in sample["attributed"],
            "semantic reference changed",
        )

    rust_groups = {
        candidate: [
            sample for sample in rust_result["samples"] if sample["candidate_id"] == candidate
        ]
        for candidate in ("T0", "T1", "T2")
    }
    amortized = rust_result["boundary"]["amortized_boundary_seconds_per_execution"]
    for candidate, group in rust_groups.items():
        summary = rust_result["summaries"][candidate]
        totals = [sample["durations_ns"]["total_ns"] for sample in group]
        check(len(group) == 20, "Rust candidate sample count changed")
        check(
            sorted({sample["semantic_hash"] for sample in group})
            == summary["semantic_hashes"],
            "Rust semantic summary changed",
        )
        check(
            math.isclose(summary["core_p50_seconds"], percentile(totals, 0.50) / 1e9),
            "Rust p50 changed",
        )
        check(
            math.isclose(summary["core_p95_seconds"], percentile(totals, 0.95) / 1e9),
            "Rust p95 changed",
        )
        check(
            math.isclose(
                summary["benchmark_amortized_boundary_inclusive_p50_seconds"],
                summary["core_p50_seconds"] + amortized,
            ),
            "Rust boundary-inclusive p50 changed",
        )

    for candidate in ("T0", "T1", "T2"):
        group = [
            sample
            for sample in python_result["samples"]
            if sample["candidate_id"] == candidate
        ]
        totals = [sample["uninstrumented_total_ns"] for sample in group]
        summary = python_result["uninstrumented_summaries"][candidate]
        check(
            math.isclose(summary["p50_seconds"], percentile(totals, 0.50) / 1e9),
            "Python p50 changed",
        )
        check(
            math.isclose(summary["p95_seconds"], percentile(totals, 0.95) / 1e9),
            "Python p95 changed",
        )

    for index, stage in enumerate(STAGE_TAXONOMY):
        check(config["stage_taxonomy"][index] == stage, "stage taxonomy order changed")

    boundary = rust_result["boundary"]
    copies = rust_result["copy_accounting"]
    expected_amortized = max(
        0.0,
        boundary["python_wrapper_seconds"]
        + boundary["process_call_seconds"]
        - boundary["rust_internal_suite_seconds"],
    ) / boundary["pipeline_executions_in_process"]
    check(boundary["pipeline_executions_in_process"] == 78, "suite count changed")
    check(
        copies["total_boundary_copied_bytes"]
        == copies["python_input_file_write_bytes"]
        + copies["rust_input_file_read_copy_bytes"],
        "boundary copy total changed",
    )
    check(
        copies["temporary_boundary_bytes"]
        == copies["input_bytes"] + copies["rust_output_file_bytes"],
        "temporary boundary bytes changed",
    )
    check(math.isclose(copies["copied_input_multiples"], 2.0), "copy multiple changed")
    check(math.isclose(amortized, expected_amortized), "suite amortization changed")
    check("Decision: **REFINE_RUST_BOUNDARY**" in decision_text, "final Gate changed")
    check(boundary["ffi_call_seconds"]["value"] is None, "unsupported FFI value changed")
    check(
        boundary["ffi_call_seconds"]["status"] == "not_collected",
        "unsupported FFI status changed",
    )
    check(parity["semantic_parity"] is True, "semantic parity changed")
    check(parity["deterministic_hashes"] is True, "determinism changed")
    check(
        attempt_001["results_eligible"] is False
        and attempt_002["results_eligible"] is False,
        "failed evidence eligibility changed",
    )

    if assertions != 350:
        raise AssertionError(f"R2 arithmetic audit shape changed: {assertions} assertions")
    return {
        "assertions": assertions,
        "failures": 0,
        "decision": "REFINE_RUST_BOUNDARY",
        "measurement_reruns": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit committed R2 arithmetic evidence.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
