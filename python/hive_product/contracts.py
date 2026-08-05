"""Small, explicit contracts for the P0 product flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import re


PROFILE = "standard"
MODEL = "MiniMax-H3"
MIN_DURATION_SECONDS = 3
MAX_DURATION_SECONDS = 8
MAX_PROMPT_CHARS = 2_000
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_RETRY = 1

JOB_STATUSES = {"queued", "running", "succeeded", "failed"}
FEEDBACK_DECISIONS = {"accepted", "rejected", "retry_requested"}
FEEDBACK_REASONS = {
    "face",
    "hands",
    "motion",
    "camera",
    "background",
    "prompt_mismatch",
    "other",
}
TRAINING_ELIGIBILITY = {
    "evaluation_only",
    "preference_only",
    "training_allowed",
    "quarantined",
    "deleted",
}
ALLOWED_REFERENCE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


MINIMAX_POLICY_STATE = {
    "excluded_territory_authorization": "verified_private_evidence",
    "commercial_product_use": "authorized_with_conditions",
    "safeguards_required": True,
    "end_user_flow_down_required": True,
    "output_training_rights": "unknown_pending_written_confirmation",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_artifact_root() -> Path:
    configured = os.environ.get("HIVEFRAME_ARTIFACT_ROOT")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "HIVEFRAME" / "P0"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "hiveframe" / "p0"


def validate_prompt(prompt: Any) -> str:
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("prompt is required")
    if len(cleaned) > MAX_PROMPT_CHARS:
        raise ValueError(f"prompt must be at most {MAX_PROMPT_CHARS} characters")
    return cleaned


def validate_profile(profile: Any) -> str:
    if profile != PROFILE:
        raise ValueError(f"only the {PROFILE!r} profile is supported")
    return PROFILE


def validate_duration(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("duration_seconds must be an integer")
    if not MIN_DURATION_SECONDS <= value <= MAX_DURATION_SECONDS:
        raise ValueError("duration_seconds must be between 3 and 8")
    return value


def validate_reference_name(name: Any) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("reference filename is required")
    if name != Path(name).name or ".." in name or "/" in name or "\\" in name or "\x00" in name:
        raise ValueError("reference filename contains an unsafe path")
    if Path(name).suffix.lower() not in ALLOWED_REFERENCE_SUFFIXES:
        raise ValueError("reference image must be PNG, JPEG, or WebP")
    return name


def validate_public_id(value: str, label: str = "id") -> str:
    if not SAFE_ID.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return value


def derive_training_eligibility(
    *,
    generation_consent: bool,
    training_opt_in: bool,
    output_training_rights_confirmed: bool,
    deletion_requested: bool,
    deletion_completed: bool = False,
) -> tuple[str, str]:
    if deletion_completed:
        return "deleted", "deleted"
    if deletion_requested:
        return "quarantined", "pending_deletion"
    if not generation_consent:
        return "quarantined", "retained_pending_review"
    if training_opt_in and output_training_rights_confirmed:
        return "training_allowed", "retained"
    if training_opt_in:
        return "preference_only", "retained"
    return "evaluation_only", "retained"


@dataclass(frozen=True)
class BackendFailure(Exception):
    code: str
    message: str
    retryable: bool = False
    provider_status: int | None = None

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class BackendResult:
    filename: str
    media_type: str
    content: bytes
    metadata: dict[str, Any]
