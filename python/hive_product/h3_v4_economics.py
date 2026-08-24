"""Pre-generation production-economics Gate for the bounded H3 V4 path."""

from __future__ import annotations

from typing import Any, Mapping

from .h3_bounded_host_source_oracle_v4 import (
    METADATA_D2H_BYTES,
    MINIMUM_CANDIDATE_H2D_BYTES,
    MINIMUM_PLANNED_Q_RATIO,
    SOURCE_CAPTURE_D2H_BYTES,
)


DECISION = "H3_V4_ECONOMICS_NOT_VIABLE"
COMPARABLE_BASELINE_SECONDS = 488.8473196999985
GLOBAL_ATTENTION_MIXING_SECONDS = 343.2285699157715
OBSERVED_C2_SCALAR_SECONDS = 0.041647456
OBSERVED_FAILED_PREFIX_SOURCE_D2H_BYTES = 627_501_056
P1_A2_RUNNING_TO_TERMINAL_SECONDS = 559.3130000000237
V4_SAMPLER_NODE_SECONDS = 604.2962358000223

UNKNOWN_SELECTIVE_COSTS = (
    "partial_attention_kernel_launch",
    "representative_query_gather",
    "reconstruction_and_output_scatter",
    "cache_read_write_and_identity_guard",
    "per_generation_gpu_plan_materialization",
    "rust_live_plan_compile",
)


def build_measured_hot_path_economics_gate(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the frozen production-shaped benchmark as a Formal Gate input."""

    economics_checks = dict(receipt.get("economics_checks", {}))
    required_checks = (
        "six_unknown_costs_measured",
        "unknown_runtime_cost_zero",
        "median_net_at_least_one_percent",
        "conservative_net_positive",
        "p95_overhead_no_loss",
        "vram_allocator_pass",
        "fallback_correctness_pass",
        "pipeline_contract_pass",
    )
    checks = {
        "schema_exact": receipt.get("schema_version")
        == "h3.v4-production-executor-hot-path.1",
        "benchmark_passed": receipt.get("passed") is True,
        "decision_viable": receipt.get("decision")
        == "H3_V4_HOT_PATH_ECONOMICS_VIABLE",
        "all_required_checks_pass": all(
            economics_checks.get(name) is True for name in required_checks
        ),
        "unknown_runtime_cost_zero": receipt.get("unknown_runtime_costs") == [],
        "no_generation": int(receipt.get("generation_count", -1)) == 0,
        "no_control_submission": int(receipt.get("control_submission_count", -1))
        == 0,
        "no_selective_generation": int(
            receipt.get("selective_generation_count", -1)
        )
        == 0,
        "no_partial_q_h3_generation": int(
            receipt.get("partial_q_h3_generation_count", -1)
        )
        == 0,
        "no_attention_omission_h3_generation": int(
            receipt.get("attention_omission_h3_generation_count", -1)
        )
        == 0,
    }
    return {
        "schema_version": "h3.v4-measured-hot-path-economics-gate.1",
        "passed": all(checks.values()),
        "checks": checks,
        "benchmark_checksum": receipt.get("sample_checksum"),
        "median": receipt.get("economics", {}).get("tiers", {}).get("median"),
        "conservative": receipt.get("economics", {})
        .get("tiers", {})
        .get("conservative"),
    }


def _cost(
    cost_id: str,
    classification: str,
    call_path: str,
    *,
    control_enabled: bool,
    selective_enabled: bool,
    correctness_if_disabled: str,
    expected_bytes: int | None,
    expected_seconds: float | None,
) -> dict[str, Any]:
    return {
        "cost_id": cost_id,
        "classification": classification,
        "call_path": call_path,
        "control_enabled": control_enabled,
        "selective_enabled": selective_enabled,
        "correctness_if_disabled": correctness_if_disabled,
        "expected_bytes": expected_bytes,
        "expected_seconds": expected_seconds,
    }


def build_precontrol_economics_gate(
    selective_runtime_cost_seconds: Mapping[str, float | None] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed Gate without loading H3 or submitting a prompt."""

    supplied = dict(selective_runtime_cost_seconds or {})
    runtime_costs = {name: supplied.get(name) for name in UNKNOWN_SELECTIVE_COSTS}
    unknown = [name for name, value in runtime_costs.items() if value is None]
    known_runtime_overhead = OBSERVED_C2_SCALAR_SECONDS + sum(
        float(value) for value in runtime_costs.values() if value is not None
    )
    avoided_q_upper = GLOBAL_ATTENTION_MIXING_SECONDS * MINIMUM_PLANNED_Q_RATIO
    predicted_net = None if unknown else avoided_q_upper - known_runtime_overhead
    predicted_percent = (
        None
        if predicted_net is None
        else predicted_net / COMPARABLE_BASELINE_SECONDS
    )
    required_q_ratio_known_cost_only = (
        COMPARABLE_BASELINE_SECONDS * 0.01 + OBSERVED_C2_SCALAR_SECONDS
    ) / GLOBAL_ATTENTION_MIXING_SECONDS

    costs = [
        _cost(
            "bounded_host_source_allocation",
            "CONTROL_ONLY",
            "V4HostSourceResources.__init__",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL holdout source unavailable",
            expected_bytes=OBSERVED_FAILED_PREFIX_SOURCE_D2H_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "source_capture_d2h",
            "CONTROL_ONLY",
            "H3ObserverControllerV4._refresh_cache",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL exact source lineage unavailable",
            expected_bytes=SOURCE_CAPTURE_D2H_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "candidate_source_h2d",
            "CONTROL_ONLY",
            "H3ObserverControllerV4._observe_full_compute_control",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL exact GPU oracle unavailable",
            expected_bytes=MINIMUM_CANDIDATE_H2D_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "compound_eye_scalar_d2h",
            "SELECTIVE_RUNTIME_REQUIRED",
            "ActiveQueryShadowPipeline callback",
            control_enabled=True,
            selective_enabled=True,
            correctness_if_disabled="no STABLE/ACTIVE/UNCERTAIN execution authority",
            expected_bytes=3_840,
            expected_seconds=OBSERVED_C2_SCALAR_SECONDS,
        ),
        _cost(
            "exact_gpu_oracle",
            "CONTROL_ONLY",
            "gpu_exact_oracle_metrics_indexed",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL false-safe evidence unavailable",
            expected_bytes=METADATA_D2H_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "holdout_199_record_construction",
            "CONTROL_ONLY",
            "H3ObserverControllerV4.finalize",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL holdout and false-safe proof unavailable",
            expected_bytes=METADATA_D2H_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "lineage_diagnostics",
            "CONTROL_ONLY",
            "compare_lineage and lineage_diagnostic_receipt",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL mismatch attribution unavailable",
            expected_bytes=0,
            expected_seconds=None,
        ),
        _cost(
            "rust_live_plan_compile",
            "SELECTIVE_RUNTIME_REQUIRED",
            "RustCachePlanV2Bridge.compile_generation",
            control_enabled=True,
            selective_enabled=True,
            correctness_if_disabled="no generation-scoped selective cache plan",
            expected_bytes=METADATA_D2H_BYTES,
            expected_seconds=runtime_costs["rust_live_plan_compile"],
        ),
        _cost(
            "rust_deterministic_replay",
            "CONTROL_ONLY",
            "runner post-terminal deterministic replay",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL determinism proof unavailable",
            expected_bytes=METADATA_D2H_BYTES,
            expected_seconds=None,
        ),
        _cost(
            "artifact_serialization",
            "CONTROL_ONLY",
            "runner private/public evidence serialization",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL durable evidence unavailable",
            expected_bytes=None,
            expected_seconds=None,
        ),
        _cost(
            "confusion_matrix_calculation",
            "CONTROL_ONLY",
            "H3ObserverControllerV4.finalize",
            control_enabled=True,
            selective_enabled=False,
            correctness_if_disabled="CONTROL false-safe Gate unavailable",
            expected_bytes=0,
            expected_seconds=None,
        ),
    ]
    costs.extend(
        _cost(
            name,
            "UNKNOWN" if runtime_costs[name] is None else "SELECTIVE_RUNTIME_REQUIRED",
            "future bounded executor hot path",
            control_enabled=False,
            selective_enabled=True,
            correctness_if_disabled="SELECTIVE output path is not implemented",
            expected_bytes=None,
            expected_seconds=runtime_costs[name],
        )
        for name in UNKNOWN_SELECTIVE_COSTS
        if name != "rust_live_plan_compile"
    )

    checks = {
        "comparable_baseline_present": True,
        "planned_q_reduction_at_least_three_percent": MINIMUM_PLANNED_Q_RATIO
        >= 0.03,
        "unknown_runtime_cost_zero": len(unknown) == 0,
        "predicted_net_saving_positive": predicted_net is not None
        and predicted_net > 0.0,
        "predicted_e2e_net_saving_at_least_one_percent": predicted_percent
        is not None
        and predicted_percent >= 0.01,
    }
    return {
        "schema_version": "h3.v4-production-economics-gate.1",
        "decision": None if all(checks.values()) else DECISION,
        "passed": all(checks.values()),
        "checks": checks,
        "measurement_comparability": {
            "p1_a2_running_to_terminal_seconds": P1_A2_RUNNING_TO_TERMINAL_SECONDS,
            "p1_a2_method": "client monotonic running-to-terminal span",
            "v4_sampler_node_seconds": V4_SAMPLER_NODE_SECONDS,
            "v4_method": "WebSocket sampler-node executing boundary",
            "direct_comparison": "NOT_COMPARABLE",
            "comparable_baseline_seconds": COMPARABLE_BASELINE_SECONDS,
            "comparable_baseline_source": "C4-S0 same-profile sampler CUDA-event surface",
        },
        "planned_q_reduction_ratio": MINIMUM_PLANNED_Q_RATIO,
        "global_attention_mixing_seconds": GLOBAL_ATTENTION_MIXING_SECONDS,
        "avoided_q_compute_upper_bound_seconds": avoided_q_upper,
        "known_selective_runtime_overhead_seconds": known_runtime_overhead,
        "unknown_selective_runtime_costs": unknown,
        "predicted_net_saving_seconds": predicted_net,
        "predicted_net_saving_ratio": predicted_percent,
        "required_q_reduction_ratio_known_cost_only": required_q_ratio_known_cost_only,
        "costs": costs,
        "claim_boundary": (
            "The avoided-Q value applies the planned ratio to the larger measured global-"
            "attention span, so it is an optimistic upper bound, not a speedup claim."
        ),
    }
