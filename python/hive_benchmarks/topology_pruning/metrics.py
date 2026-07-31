"""Typed metric helpers for the M1-P0 analytical receipt."""

from __future__ import annotations

import math
from typing import Any


AVAILABLE_STATUSES = {"available", "derived", "collected"}
UNAVAILABLE_STATUSES = {"unavailable", "partially_available"}


def measured(
    value: int | float,
    unit: str,
    method: str,
    *,
    status: str = "collected",
    reason: str | None = None,
) -> dict[str, Any]:
    if status not in AVAILABLE_STATUSES:
        raise ValueError(f"Invalid available metric status: {status}")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("Metric values must be finite.")
    if numeric < 0:
        raise ValueError("Cost and resource metrics cannot be negative.")
    if not method or method == "not measured":
        raise ValueError("Available metrics require a real measurement method.")
    return {
        "value": value,
        "status": status,
        "reason": reason,
        "method": method,
        "unit": unit,
    }


def unavailable(
    unit: str,
    reason: str,
    *,
    method: str = "not measured",
    status: str = "unavailable",
) -> dict[str, Any]:
    if status not in UNAVAILABLE_STATUSES:
        raise ValueError(f"Invalid unavailable metric status: {status}")
    if not reason:
        raise ValueError("Unavailable metrics require a reason.")
    if not method:
        raise ValueError("Unavailable metrics require a method.")
    return {
        "value": None,
        "status": status,
        "reason": reason,
        "method": method,
        "unit": unit,
    }


def validate_metric(metric: dict[str, Any]) -> None:
    required = {"value", "status", "reason", "method", "unit"}
    missing = sorted(required - set(metric))
    if missing:
        raise ValueError(f"Metric is missing fields: {missing}")
    status = metric["status"]
    value = metric["value"]
    if status in UNAVAILABLE_STATUSES:
        if value is not None:
            raise ValueError(
                "Unavailable metrics must use null, never zero or a guessed value."
            )
        if not metric["reason"] or not metric["method"]:
            raise ValueError("Unavailable metrics require reason and method.")
        return
    if status not in AVAILABLE_STATUSES:
        raise ValueError(f"Unknown metric status: {status}")
    if value is None:
        raise ValueError("Available metrics require a value.")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError("Available cost metrics must be finite and non-negative.")
    if not metric["method"] or metric["method"] == "not measured":
        raise ValueError("Available metrics cannot claim 'not measured'.")


def metric_value(metric: dict[str, Any]) -> float | None:
    validate_metric(metric)
    if metric["value"] is None:
        return None
    return float(metric["value"])
