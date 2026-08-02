"""Conservative rights and consent validation for M1-A video metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m1_protocol import (
    ELIGIBLE_SOURCE_CLASSES,
    is_sha256,
    is_unavailable,
    load_json,
    public_sanitation_errors,
    require_keys,
)


REQUIRED_RECEIPT_KEYS = (
    "clip_id", "original_sha256", "source_class", "rights_basis", "rights_holder",
    "license_identifier", "official_source_reference", "terms_digest", "attribution_obligation",
    "permissions", "identifiable_people", "consent_basis", "consent_status", "restrictions",
    "review_status", "reviewed_at", "review_method", "evidence_digest",
)
REQUIRED_PERMISSIONS = ("research", "commercial", "copy", "derivative", "redistribution")


def validate_rights_receipt(receipt: Any, path: str = "$.receipts[]") -> list[str]:
    errors = require_keys(receipt, REQUIRED_RECEIPT_KEYS, path)
    if errors or not isinstance(receipt, dict):
        return errors
    if not is_sha256(receipt["original_sha256"]):
        errors.append(f"{path}.original_sha256: expected SHA-256")
    if receipt["source_class"] not in ELIGIBLE_SOURCE_CLASSES | {"pending_rights_review", "rejected"}:
        errors.append(f"{path}.source_class: unsupported classification")
    review_status = receipt["review_status"]
    if review_status not in {"admitted", "pending", "rejected"}:
        errors.append(f"{path}.review_status: invalid status")
    permissions = receipt.get("permissions")
    if not isinstance(permissions, dict):
        errors.append(f"{path}.permissions: expected object")
    else:
        for permission in REQUIRED_PERMISSIONS:
            if not isinstance(permissions.get(permission), bool):
                errors.append(f"{path}.permissions.{permission}: expected boolean")
    attribution = receipt.get("attribution_obligation")
    if not isinstance(attribution, dict) or not isinstance(attribution.get("required"), bool):
        errors.append(f"{path}.attribution_obligation: expected required/text object")
    elif attribution["required"] and (not isinstance(attribution.get("text"), str) or not attribution["text"].strip()):
        errors.append(f"{path}.attribution_obligation.text: required attribution text missing")
    identifiable = receipt.get("identifiable_people")
    consent = receipt.get("consent_status")
    if identifiable is True and consent != "verified":
        errors.append(f"{path}.consent_status: identifiable people require verified consent")
    if consent not in {"not_required", "verified", "pending", "rejected"}:
        errors.append(f"{path}.consent_status: invalid status")
    for field in ("rights_basis", "rights_holder", "license_identifier", "official_source_reference", "terms_digest", "evidence_digest"):
        value = receipt.get(field)
        if value is None or value == "":
            errors.append(f"{path}.{field}: missing values require explicit unavailable/pending metadata")
        elif field.endswith("digest") and not (is_sha256(value) or is_unavailable(value)):
            errors.append(f"{path}.{field}: expected SHA-256 or explicit unavailable/pending metadata")
    if review_status == "admitted":
        if receipt["source_class"] not in ELIGIBLE_SOURCE_CLASSES:
            errors.append(f"{path}: admitted receipt requires an eligible source class")
        if not all(permissions.get(permission) is True for permission in REQUIRED_PERMISSIONS):
            errors.append(f"{path}: admitted receipt requires all declared permissions")
        if consent in {"pending", "rejected"} or identifiable is not False and consent != "verified":
            errors.append(f"{path}: admitted receipt lacks a resolved consent basis")
        for field in ("rights_basis", "rights_holder", "license_identifier", "official_source_reference", "terms_digest", "evidence_digest"):
            if is_unavailable(receipt[field]):
                errors.append(f"{path}.{field}: admitted receipt cannot use pending/unavailable evidence")
    errors.extend(public_sanitation_errors(receipt))
    return errors


def validate_rights_document(document: Any) -> list[str]:
    errors = require_keys(document, ("schema_version", "receipts"), "$")
    if errors or not isinstance(document, dict):
        return errors
    if document["schema_version"] != "0.1.0":
        errors.append("$.schema_version: expected 0.1.0")
    receipts = document.get("receipts")
    if not isinstance(receipts, list):
        return errors + ["$.receipts: expected array"]
    seen: set[str] = set()
    for index, receipt in enumerate(receipts):
        errors.extend(validate_rights_receipt(receipt, f"$.receipts[{index}]"))
        if isinstance(receipt, dict):
            clip_id = receipt.get("clip_id")
            if clip_id in seen:
                errors.append(f"$.receipts[{index}].clip_id: duplicate {clip_id}")
            seen.add(clip_id)
    return errors


def summarize_rights(document: dict[str, Any]) -> dict[str, Any]:
    counts = {status: 0 for status in ("admitted", "pending", "rejected")}
    for receipt in document.get("receipts", []):
        status = receipt.get("review_status")
        if status in counts:
            counts[status] += 1
    errors = validate_rights_document(document)
    return {"schema_version": "0.1.0", "counts": counts, "valid": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rights_document", type=Path)
    args = parser.parse_args()
    summary = summarize_rights(load_json(args.rights_document))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
