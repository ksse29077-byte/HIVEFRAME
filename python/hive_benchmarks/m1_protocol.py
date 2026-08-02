"""Shared, model-free helpers for the M1-A corpus and oracle protocol."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
WINDOWS_ABSOLUTE_RE = re.compile(r"(?:^|[\s\"'=])(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+\\)")
USER_PATH_RE = re.compile(r"(?:^|[\s\"'=])/(?:home|Users)/[^/\s]+/", re.IGNORECASE)
TEMP_PATH_RE = re.compile(r"(?:^|[\s\"'=])/(?:tmp|var/tmp)/[^\s\"']*", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"(?:api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{12,})",
    re.IGNORECASE,
)
URL_CREDENTIAL_RE = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)

ALLOWED_STORAGE_CLASSES = {
    "local_approved_artifact_store",
    "external_digest_store",
    "repository_metadata_only",
    "user_supplied_secure_storage",
}
ELIGIBLE_SOURCE_CLASSES = {
    "eligible_self_recorded",
    "eligible_public_domain",
    "eligible_cc0",
    "eligible_explicit_license",
}
BINARY_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def is_unavailable(value: Any, *, allowed_statuses: Iterable[str] = ("unavailable", "pending")) -> bool:
    return (
        isinstance(value, dict)
        and value.get("value") is None
        and value.get("status") in set(allowed_statuses)
        and isinstance(value.get("reason"), str)
        and bool(value["reason"].strip())
        and isinstance(value.get("method"), str)
        and bool(value["method"].strip())
    )


def iter_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")


def public_sanitation_errors(value: Any) -> list[str]:
    errors: list[str] = []
    for path, text in iter_strings(value):
        if WINDOWS_ABSOLUTE_RE.search(text):
            errors.append(f"{path}: Windows absolute or UNC path is not public-safe")
        if USER_PATH_RE.search(text):
            errors.append(f"{path}: user-specific absolute path is not public-safe")
        if TEMP_PATH_RE.search(text):
            errors.append(f"{path}: concrete temporary path is not public-safe")
        if SECRET_RE.search(text) or URL_CREDENTIAL_RE.search(text):
            errors.append(f"{path}: possible credential or secret is not public-safe")
    return errors


def tracked_binary_errors(paths: Iterable[str]) -> list[str]:
    return [f"tracked binary media is forbidden: {path}" for path in paths if Path(path).suffix.lower() in BINARY_VIDEO_SUFFIXES]


def require_keys(value: Any, keys: Iterable[str], path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected object"]
    return [f"{path}.{key}: required field missing" for key in keys if key not in value]


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
