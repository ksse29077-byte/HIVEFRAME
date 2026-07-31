"""Predeclared paired-Mono normalization for the bounded M1-P0-R1 probe."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import math
from pathlib import Path
from typing import Any, Iterable


RUN_KIND = "m1_p0_r1_same_run_mono_normalization"
CASE_B = "case-b-high-resolution-local-change"
RETAINED_COMBINATIONS = (
    "case-a-low-resolution-simple/T0",
    f"{CASE_B}/T0",
    f"{CASE_B}/T1",
    f"{CASE_B}/T2",
    "case-c-global-motion/T0",
)
PRUNED_COMBINATIONS = (
    "case-a-low-resolution-simple/T1",
    "case-a-low-resolution-simple/T2",
    "case-c-global-motion/T1",
    "case-c-global-motion/T2",
)
GATE_DECISIONS = {
    "PROCEED_TO_COST_SURFACE",
    "REFINE_COST_MODEL",
    "MONO_FIRST",
    "PAUSE_COMPOUND_INPUT",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_v1_hashes(root: Path, expected: dict[str, str]) -> None:
    for relative, expected_hash in sorted(expected.items()):
        path = root / relative
        if not path.is_file():
            raise ValueError(f"Immutable v1 artifact is missing: {relative}")
        actual = sha256_file(path)
        if actual != expected_hash:
            raise ValueError(
                f"Immutable v1 artifact changed: {relative}; "
                f"expected {expected_hash}, got {actual}"
            )


def validate_config(config: dict[str, Any]) -> None:
    if config.get("run_kind") != RUN_KIND:
        raise ValueError(f"Unexpected R1 run kind: {config.get('run_kind')}")
    if int(config.get("warmups", -1)) != 5:
        raise ValueError("R1 warm-ups are fixed at 5.")
    if int(config.get("repetitions", 0)) < 20:
        raise ValueError("R1 requires at least 20 measured repetition blocks.")
    if tuple(config.get("retained_combinations", ())) != RETAINED_COMBINATIONS:
        raise ValueError("R1 retained combinations differ from immutable v1 scope.")
    if tuple(config.get("analytically_pruned_combinations", ())) != PRUNED_COMBINATIONS:
        raise ValueError("R1 analytical pruning differs from immutable v1 scope.")
    pairing = config.get("pairing", {})
    if pairing.get("case_id") != CASE_B:
        raise ValueError("R1 pairing is restricted to the retained Case B group.")
    if pairing.get("mono_candidate") != "T0":
        raise ValueError("R1 paired control must be T0 Mono.")
    if tuple(pairing.get("compound_candidates", ())) != ("T1", "T2"):
        raise ValueError("R1 paired candidates must remain T1 and T2.")
    if tuple(pairing.get("members_per_block", ())) != ("T0", "T1", "T2"):
        raise ValueError("Each Case B block must contain exactly T0, T1, and T2.")
    if not all(
        pairing.get(name) is True
        for name in (
            "same_process",
            "same_sequence_object",
            "same_repetition_block",
            "median_subtraction_forbidden",
        )
    ):
        raise ValueError("R1 same-run paired-normalization safeguards are required.")
    thresholds = config.get("thresholds", {})
    if float(thresholds.get("prediction_relative_error_max", -1)) != 0.35:
        raise ValueError("The immutable R1 relative-error threshold is 35%.")
    if float(thresholds.get("dirty_recall_required", -1)) != 1.0:
        raise ValueError("R1 requires dirty recall 1.0.")
    if float(thresholds.get("false_stable_required", -1)) != 0.0:
        raise ValueError("R1 requires false-stable 0.0.")
    boundaries = config.get("evidence_boundaries", {})
    for name in (
        "h3_api_calls",
        "paid_api_runs",
        "model_downloads",
        "model_loads",
        "cuda_runs",
    ):
        if boundaries.get(name) != 0:
            raise ValueError(f"R1 evidence boundary requires {name}=0.")


def deterministic_case_b_order(
    seed: int,
    phase: str,
    block_index: int,
) -> tuple[str, str, str]:
    if phase not in {"warmup", "measured"}:
        raise ValueError(f"Unknown R1 phase: {phase}")
    if block_index < 0:
        raise ValueError("Block index cannot be negative.")
    candidates = ("T0", "T1", "T2")
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: hashlib.sha256(
                f"{seed}:{phase}:{block_index}:{candidate}".encode("utf-8")
            ).digest(),
        )
    )


def observed_cost_terms(
    *,
    session_fixed: float,
    case_shared: float,
    topology_variable: float,
    measurement_noise: float,
) -> dict[str, float]:
    terms = {
        "C_session_fixed": float(session_fixed),
        "C_case_shared": float(case_shared),
        "C_topology_variable": float(topology_variable),
        "C_measurement_noise": float(measurement_noise),
    }
    if any(not math.isfinite(value) for value in terms.values()):
        raise ValueError("Observed cost terms must be finite.")
    if any(value < 0 for name, value in terms.items() if name != "C_measurement_noise"):
        raise ValueError("Fixed, shared, and topology-variable costs cannot be negative.")
    terms["C_observed"] = sum(terms.values())
    if terms["C_observed"] < 0:
        raise ValueError("Observed cost cannot be negative.")
    return terms


def paired_delta_records(
    samples: Iterable[dict[str, Any]],
    candidate_id: str,
) -> list[dict[str, Any]]:
    if candidate_id not in {"T1", "T2"}:
        raise ValueError("Paired deltas are defined only for retained T1/T2.")
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        if sample.get("phase") != "measured":
            continue
        if sample.get("case_id") != CASE_B:
            continue
        grouped[(sample["case_id"], int(sample["block_index"]))].append(sample)
    if not grouped:
        raise ValueError("No measured Case B blocks were supplied.")

    records: list[dict[str, Any]] = []
    for (case_id, block_index), block in sorted(grouped.items()):
        by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for sample in block:
            by_candidate[sample["candidate_id"]].append(sample)
        if set(by_candidate) != {"T0", "T1", "T2"}:
            raise ValueError(
                f"Case B block {block_index} is not a complete T0/T1/T2 block."
            )
        if any(len(items) != 1 for items in by_candidate.values()):
            raise ValueError(f"Case B block {block_index} contains duplicate samples.")
        mono = by_candidate["T0"][0]
        candidate = by_candidate[candidate_id][0]
        if mono["case_id"] != candidate["case_id"] or mono["block_index"] != candidate["block_index"]:
            raise ValueError("Paired samples must share case and repetition block.")
        mono_seconds = float(mono["total_seconds"])
        candidate_seconds = float(candidate["total_seconds"])
        records.append(
            {
                "case_id": case_id,
                "block_index": block_index,
                "candidate_id": candidate_id,
                "mono_order_index": mono["order_index"],
                "candidate_order_index": candidate["order_index"],
                "mono_seconds": mono_seconds,
                "candidate_seconds": candidate_seconds,
                "delta_seconds": candidate_seconds - mono_seconds,
            }
        )
    return records


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("Percentile requires at least one value.")
    if not 0 < quantile <= 1:
        raise ValueError("Nearest-rank quantile must be in (0, 1].")
    rank = max(1, math.ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def relative_error(predicted: float, measured: float) -> float:
    predicted_value = float(predicted)
    measured_value = float(measured)
    if not math.isfinite(predicted_value) or not math.isfinite(measured_value):
        raise ValueError("Prediction comparison values must be finite.")
    if measured_value == 0:
        raise ValueError("Relative error denominator cannot be zero.")
    return abs(predicted_value - measured_value) / abs(measured_value)


def summarize_paired_deltas(
    records: list[dict[str, Any]],
    predicted_delta_seconds: float,
) -> dict[str, Any]:
    deltas = [float(record["delta_seconds"]) for record in records]
    measured_p50 = percentile(deltas, 0.50)
    measured_p95 = percentile(deltas, 0.95)
    absolute_error = abs(float(predicted_delta_seconds) - measured_p50)
    return {
        "candidate_id": records[0]["candidate_id"],
        "pairs": len(records),
        "predicted_delta_seconds": float(predicted_delta_seconds),
        "measured_delta_p50_seconds": measured_p50,
        "measured_delta_p95_seconds": measured_p95,
        "absolute_error_seconds": absolute_error,
        "relative_error": relative_error(predicted_delta_seconds, measured_p50),
        "aggregation": "nearest_rank over same-block signed paired deltas",
    }


def assert_unavailable_values_are_null(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        status = value.get("status")
        if (
            "value" in value
            and status
            in {"unavailable", "uncollected", "unsupported", "partially_available"}
        ):
            if value.get("value", object()) is not None:
                raise ValueError(f"Unavailable metric is not null at {path}.")
            if not value.get("reason") or not value.get("method"):
                raise ValueError(f"Unavailable metric lacks reason/method at {path}.")
        for key, child in value.items():
            assert_unavailable_values_are_null(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_unavailable_values_are_null(child, f"{path}[{index}]")


def decide_r1_gate(
    paired_summaries: dict[str, dict[str, Any]],
    *,
    ranking_match: bool,
    dirty_recall: float,
    false_stable: float,
    deterministic_hashes: bool,
    unavailable_semantics_valid: bool,
    thresholds: dict[str, Any],
    all_compound_pruned: bool = False,
    downstream_opportunity_admitted: bool = False,
    downstream_opportunity_sufficient: bool | None = None,
) -> dict[str, str]:
    if (
        dirty_recall != float(thresholds["dirty_recall_required"])
        or false_stable != float(thresholds["false_stable_required"])
        or not deterministic_hashes
        or not unavailable_semantics_valid
    ):
        return {
            "decision": "PAUSE_COMPOUND_INPUT",
            "reason": "A safety, determinism, or unavailable-metric invariant failed.",
        }
    if all_compound_pruned or (
        downstream_opportunity_admitted and downstream_opportunity_sufficient is False
    ):
        return {
            "decision": "MONO_FIRST",
            "reason": "Admitted evidence shows compound overhead cannot be repaid.",
        }
    required = {"T1", "T2"}
    if set(paired_summaries) != required:
        return {
            "decision": "REFINE_COST_MODEL",
            "reason": "Both retained Case B paired summaries are required.",
        }
    errors_ok = all(
        paired_summaries[candidate]["relative_error"]
        <= float(thresholds["prediction_relative_error_max"])
        for candidate in sorted(required)
    )
    if errors_ok and ranking_match:
        return {
            "decision": "PROCEED_TO_COST_SURFACE",
            "reason": "Paired prediction, ranking, safety, determinism, and metric semantics passed.",
        }
    return {
        "decision": "REFINE_COST_MODEL",
        "reason": "Paired prediction error or ranking still fails the predeclared rule.",
    }
