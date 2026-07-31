"""Analytical cost model calibrated only from merged Rust-probe evidence."""

from __future__ import annotations

from typing import Any

from .metrics import measured, metric_value, unavailable


COMPONENT_METRICS = {
    "C_route": "routing_seconds_mean",
    "C_observe": "observation_seconds_mean",
    "C_fusion": "fusion_seconds_mean",
    "C_plan": "compute_plan_seconds_mean",
}


def _case_map(
    report: dict[str, Any],
    language: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    key = f"{language}_cases"
    if key not in report:
        raise ValueError(f"Rust report is missing {key}.")
    return {
        (case["profile_id"], case["topology"]): case for case in report[key]
    }


def _metric(case: dict[str, Any], name: str) -> float:
    try:
        metric = case["metrics"][name]
    except KeyError as error:
        raise ValueError(f"Calibration case is missing metric {name}.") from error
    value = metric_value(metric)
    if value is None:
        raise ValueError(f"Calibration metric {name} is unavailable.")
    return value


def break_even_seconds(candidate_cost: float, mono_cost: float) -> float:
    if candidate_cost < 0 or mono_cost < 0:
        raise ValueError("Break-even cost inputs cannot be negative.")
    return max(0.0, candidate_cost - mono_cost)


def build_cost_record(
    report: dict[str, Any],
    calibration_profile: str,
    topology: str,
    mono_topology: str,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    rust_cases = _case_map(report, "rust")
    python_cases = _case_map(report, "python")
    key = (calibration_profile, topology)
    mono_key = (calibration_profile, mono_topology)
    if key not in rust_cases or mono_key not in rust_cases:
        raise ValueError(f"Missing Rust calibration for {key} or {mono_key}.")
    if key not in python_cases:
        raise ValueError(f"Missing Python calibration for {key}.")

    rust_case = rust_cases[key]
    mono_case = rust_cases[mono_key]
    input_orchestration = _metric(rust_case, "p50_latency_seconds")
    mono_input_orchestration = _metric(mono_case, "p50_latency_seconds")
    required_savings = break_even_seconds(
        input_orchestration,
        mono_input_orchestration,
    )
    fixed_components = sum(
        _metric(rust_case, name)
        for name in (
            "routing_seconds_mean",
            "coordinate_transform_seconds_mean",
            "fusion_seconds_mean",
            "compute_plan_seconds_mean",
        )
    )
    eye_count = int(rust_case["eye_count"])
    if eye_count <= 0:
        raise ValueError("Calibration eye count must be positive.")

    components: dict[str, dict[str, Any]] = {}
    for component, metric_name in COMPONENT_METRICS.items():
        components[component] = measured(
            _metric(rust_case, metric_name),
            "seconds",
            f"merged Rust Probe {metric_name}",
        )
    components["C_scout"] = (
        unavailable(
            "seconds",
            "Motion detection is included in routing and was not isolated.",
            method="merged Rust Probe routing aggregate",
        )
        if topology == "motion_focused"
        else measured(
            0.0,
            "seconds",
            "structural absence: this topology has no scout stage",
            status="derived",
        )
    )
    components["C_overlap"] = measured(
        0.0,
        "seconds",
        "structural absence: selected M1-P0 candidates have no halo stage",
        status="derived",
    )
    components["C_generation"] = unavailable(
        "seconds",
        "The model-free probe does not execute backend generation.",
    )
    components["C_audit"] = unavailable(
        "seconds",
        "No output quality or safety audit executes in this probe.",
    )
    components["E_C_recovery"] = unavailable(
        "seconds",
        "No backend failure or repair path executes in this probe.",
    )

    return {
        "calibration_profile": calibration_profile,
        "topology": topology,
        "cost_equation": (
            "C_total(T)=C_scout+C_route(T)+C_observe(T)+C_overlap(T)+"
            "C_fusion(T)+C_plan(T)+C_generation(T)+C_audit(T)+"
            "E[C_recovery|T]"
        ),
        "components": components,
        "C_input_and_orchestration": measured(
            input_orchestration,
            "seconds",
            "merged Rust Probe p50 core latency",
        ),
        "C_total": unavailable(
            "seconds",
            "Generation, audit, and recovery components are unavailable.",
            status="partially_available",
        ),
        "mono_input_and_orchestration": measured(
            mono_input_orchestration,
            "seconds",
            "merged Rust Probe Mono p50 core latency",
        ),
        "S_required": measured(
            required_savings,
            "seconds",
            "max(0, candidate Rust p50 - Mono Rust p50)",
            status="derived",
            reason=(
                "Minimum downstream output savings required to repay measured "
                "input/orchestration overhead."
            ),
        ),
        "fixed_eye_cost_proxy": measured(
            fixed_components / eye_count,
            "seconds/eye",
            (
                "merged Rust routing+coordinate+fusion+plan means divided by "
                "reported eye count; proxy, not isolated allocation cost"
            ),
            status="derived",
        ),
        "predicted_probe_p50": measured(
            _metric(python_cases[key], "p50_latency_seconds"),
            "seconds",
            "merged Python reference p50 for matching shape/topology",
        ),
        "logical_input_bytes": measured(
            geometry["input_bytes"],
            "bytes",
            "declared packed uint8 input geometry",
            status="derived",
        ),
        "total_observation_bytes": measured(
            geometry["total_observation_bytes"],
            "bytes",
            "sum(receptive-field pixels * frames * bytes_per_pixel)",
            status="derived",
        ),
        "overlap_duplicate_bytes": measured(
            geometry["overlap_duplicate_bytes"],
            "bytes",
            "max(total observation bytes - unique input bytes, 0)",
            status="derived",
        ),
        "copied_bytes": rust_case["metrics"]["bytes_copied"],
        "temporary_buffer_bytes": rust_case["metrics"]["temporary_buffer_bytes"],
        "eye_count": measured(
            geometry["eye_count"],
            "eyes",
            "declared topology geometry",
            status="derived",
        ),
        "coordinate_transform_count": measured(
            geometry["coordinate_transform_count"],
            "transforms",
            "one local-to-global transform per declared Eye",
            status="derived",
        ),
        "fusion_input_count": measured(
            geometry["fusion_input_count"],
            "observations",
            "one Fusion input per declared Eye",
            status="derived",
        ),
        "scheduler_call_count": measured(
            geometry["scheduler_call_count"],
            "calls",
            "one candidate unit per declared Eye in the v0 reference",
            status="derived",
        ),
    }


def amdahl_bound(report: dict[str, Any]) -> dict[str, Any]:
    speedups: list[float] = []
    for item in report.get("comparisons", []):
        python_p50 = item["python"]["p50_seconds"]
        rust_p50 = item["rust"]["p50_seconds"]
        if python_p50 is not None and rust_p50 is not None and rust_p50 > 0:
            speedups.append(float(python_p50 / rust_p50))
    if not speedups:
        raise ValueError("Rust Probe has no usable p50 speedup evidence.")
    return {
        "status": "partially_available",
        "formula": "Speedup_max=1/((1-f_input)+f_input/s_control)",
        "s_control": {
            "status": "available",
            "minimum": min(speedups),
            "maximum": max(speedups),
            "method": "merged Rust Probe Python p50 / Rust p50",
        },
        "f_input": unavailable(
            "ratio",
            "M0 does not isolate eligible input/orchestration share.",
            method="not measured in M0 Single-Eye Cost Truth",
        ),
        "end_to_end_upper_bound": unavailable(
            "ratio",
            "Amdahl optimized fraction f_input is unavailable.",
            method="cannot evaluate 1/((1-f)+f/s) without f",
        ),
        "meaning": (
            "Only the local control-plane speedup factor is available. No "
            "end-to-end Wan or product bound is asserted."
        ),
    }


def prediction_error(
    predicted_seconds: float,
    measured_seconds: float,
) -> dict[str, float]:
    if predicted_seconds < 0 or measured_seconds < 0:
        raise ValueError("Predicted and measured costs cannot be negative.")
    absolute = abs(predicted_seconds - measured_seconds)
    relative = 0.0 if measured_seconds == 0 else absolute / measured_seconds
    return {
        "absolute_error_seconds": absolute,
        "relative_error": relative,
    }
