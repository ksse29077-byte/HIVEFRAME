"""Decision and report rendering for M1-P0."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DECISIONS = {
    "PROCEED_TO_COST_SURFACE",
    "REFINE_COST_MODEL",
    "MONO_FIRST",
    "PAUSE_COMPOUND_INPUT",
}


def decide_gate(
    pruning_cases: list[dict[str, Any]],
    measured_cases: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    measured_false_stable = [
        case["accuracy"]["false_stable_rate"]
        for case in measured_cases
        if case["accuracy"]["false_stable_rate"] is not None
    ]
    if any(
        rate > thresholds["false_stable_max"] for rate in measured_false_stable
    ):
        return {
            "decision": "PAUSE_COMPOUND_INPUT",
            "reason": "Measured false-stable exceeded the predeclared limit.",
        }

    non_mono = [
        case
        for case in pruning_cases
        if case["candidate_id"] != "T0"
    ]
    errors = [
        case["comparison"]["relative_error"]
        for case in measured_cases
        if case["comparison"]["relative_error"] is not None
    ]
    excessive_errors = [
        error
        for error in errors
        if error > thresholds["prediction_relative_error_refine"]
    ]
    if len(excessive_errors) >= 2:
        return {
            "decision": "REFINE_COST_MODEL",
            "reason": (
                "Prediction error repeatedly exceeded the predeclared refine "
                "limit."
            ),
        }

    if non_mono and all(
        case["precheck"]["status"] == "analytically_pruned"
        for case in non_mono
    ):
        return {
            "decision": "MONO_FIRST",
            "reason": (
                "Every multi-eye candidate retains full-canvas generation or "
                "exceeds a predeclared input-cost rule."
            ),
        }

    motion = [
        case
        for case in measured_cases
        if case["candidate_id"] == "T2"
    ]
    if motion and all(
        case["accuracy"]["false_stable_rate"]
        <= thresholds["false_stable_max"]
        for case in motion
    ):
        return {
            "decision": "PROCEED_TO_COST_SURFACE",
            "reason": (
                "A motion-focused candidate survived pruning with bounded "
                "false-stable and acceptable cost prediction."
            ),
        }
    return {
        "decision": "REFINE_COST_MODEL",
        "reason": "Evidence is insufficient for another declared decision.",
    }


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing artifact: {path}")
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


def decision_markdown(summary: dict[str, Any]) -> str:
    decision = summary["decision"]["decision"]
    if decision not in DECISIONS:
        raise ValueError(f"Unknown M1-P0 decision: {decision}")
    lines = [
        "# M1-P0 Analytical Topology Pre-Gate Decision",
        "",
        f"Decision: **{decision}**",
        "",
        "This is a model-free pre-gate. It closes neither M0 nor M1 and is not "
        "a model, GPU, quality, or product-speed claim.",
        "",
        "## Result",
        "",
        summary["decision"]["reason"],
        "",
        f"- analytical combinations: {summary['analytical_combinations']}",
        f"- analytically pruned: {summary['pruned_combinations']}",
        f"- measured combinations: {summary['measured_combinations']}",
        f"- warm-ups per measured combination: {summary['warmups']}",
        f"- measured repetitions per combination: {summary['repetitions']}",
        f"- maximum false-stable: {summary['maximum_false_stable']:.6f}",
        "",
        "## Amdahl status",
        "",
        f"`{summary['amdahl']['status']}`. "
        "The local Rust control-plane factor is available, but the M0 "
        "input/orchestration fraction and end-to-end upper bound are unavailable.",
        "",
        "## Interpretation",
        "",
        "The current multi-eye reference retains a dirty full-scene generate "
        "candidate while observing at least twice the unique input. Those "
        "candidates are preserved as analytically pruned evidence rather than "
        "deleted or measured repeatedly.",
        "",
        "Model loads: 0.",
        "",
        "CUDA runs: 0.",
        "",
    ]
    return "\n".join(lines)
