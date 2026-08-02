"""Dependency-free audit of the JSON Schema subset declared by M1-A.

This is deliberately not advertised as a complete JSON Schema implementation.
It evaluates every validation keyword currently used by the three M1-A schemas
so the runtime validators cannot silently accept instances that those schemas
reject.  Tests optionally cross-check fixtures with a third-party Draft 2020-12
engine when one is already available.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import re
from typing import Any


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"


def load_m1_schema(filename: str) -> dict[str, Any]:
    return json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported non-local schema reference: {reference}")
    current: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = current[part]
    if not isinstance(current, dict):
        raise ValueError(f"schema reference does not resolve to an object: {reference}")
    return current


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ValueError(f"unsupported schema type: {expected}")


def _unique_items(items: list[Any]) -> bool:
    encoded = [json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for item in items]
    return len(encoded) == len(set(encoded))


def _valid_date_time(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_declared_schema(
    value: Any,
    schema: dict[str, Any],
    *,
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """Validate the M1-A keyword subset and return stable path-based errors."""

    root = root_schema or schema
    if "$ref" in schema:
        return validate_declared_schema(value, _resolve_ref(root, schema["$ref"]), root_schema=root, path=path)

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(value, expected_type):
        return [f"{path}: schema expected {expected_type}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: schema const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: schema enum mismatch")

    if "oneOf" in schema:
        branches = [
            validate_declared_schema(value, branch, root_schema=root, path=path)
            for branch in schema["oneOf"]
        ]
        if sum(not branch_errors for branch_errors in branches) != 1:
            errors.append(f"{path}: schema oneOf requires exactly one matching branch")

    for branch in schema.get("allOf", []):
        errors.extend(validate_declared_schema(value, branch, root_schema=root, path=path))

    if "if" in schema:
        condition_matches = not validate_declared_schema(value, schema["if"], root_schema=root, path=path)
        selected = schema.get("then") if condition_matches else schema.get("else")
        if isinstance(selected, dict):
            errors.extend(validate_declared_schema(value, selected, root_schema=root, path=path))

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: schema required field missing")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                errors.extend(validate_declared_schema(child, properties[key], root_schema=root, path=child_path))
            elif additional is False:
                errors.append(f"{child_path}: schema additional property forbidden")
            elif isinstance(additional, dict):
                errors.extend(validate_declared_schema(child, additional, root_schema=root, path=child_path))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: schema minItems violated")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: schema maxItems violated")
        if schema.get("uniqueItems") is True and not _unique_items(value):
            errors.append(f"{path}: schema uniqueItems violated")
        prefix_items = schema.get("prefixItems", [])
        for index, child_schema in enumerate(prefix_items[: len(value)]):
            errors.extend(validate_declared_schema(value[index], child_schema, root_schema=root, path=f"{path}[{index}]"))
        items = schema.get("items")
        if items is False and len(value) > len(prefix_items):
            errors.append(f"{path}: schema additional array items forbidden")
        elif isinstance(items, dict):
            start = len(prefix_items) if prefix_items else 0
            for index in range(start, len(value)):
                errors.extend(validate_declared_schema(value[index], items, root_schema=root, path=f"{path}[{index}]"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: schema minLength violated")
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{path}: schema pattern mismatch")
        if schema.get("format") == "date-time" and not _valid_date_time(value):
            errors.append(f"{path}: schema date-time format mismatch")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: schema minimum violated")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: schema maximum violated")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: schema exclusiveMinimum violated")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: schema exclusiveMaximum violated")

    return errors


def validate_m1_schema(value: Any, filename: str) -> list[str]:
    schema = load_m1_schema(filename)
    return validate_declared_schema(value, schema)
