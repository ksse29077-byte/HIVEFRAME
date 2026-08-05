"""Explicit contracts for the local-model-ready P0 product flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import os
import re


PROFILE = "standard"
MODEL = "MiniMax-H3"
DEFAULT_RESOLUTION = "768P"
DEFAULT_DURATION_SECONDS = 4
DEFAULT_ASPECT_RATIO = "16:9"
MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 15
MAX_PROMPT_CHARS = 2_000
MAX_REFERENCE_BYTES = 10 * 1024 * 1024
MAX_RETRY = 1

JOB_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}
BACKENDS = {"mock_h3", "local_h3", "minimax_h3_comfyui_local"}
RESOLUTIONS = {"768P", "2K"}
ASPECT_RATIOS = {"adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}
CONTENT_TYPES = {"text", "image", "video", "audio"}
CONTENT_ROLES = {
    "image": {"first_frame", "last_frame", "reference_image"},
    "video": {"reference_video"},
    "audio": {"reference_audio"},
}
FRAME_ROLES = {"first_frame", "last_frame"}
REFERENCE_ROLES = {"reference_image", "reference_video", "reference_audio"}
LOCAL_BACKEND_STATES = {
    "artifact_pending", "artifact_configured", "artifact_ready", "runtime_unavailable",
    "runtime_incompatible", "model_loading", "model_ready",
    "generation_running", "generation_succeeded", "generation_failed",
}
FEEDBACK_DECISIONS = {"accepted", "rejected", "retry_requested"}
FEEDBACK_REASONS = {
    "face", "hands", "motion", "camera", "background", "prompt_mismatch", "other",
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
        raise ValueError("duration_seconds must be between 4 and 15")
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


@dataclass(frozen=True)
class H3ContentItem:
    """Content item persisted by asset ID; URLs are intentionally unsupported."""

    content_type: str
    role: str | None = None
    text: str | None = None
    asset_id: str | None = None

    def validate(self) -> "H3ContentItem":
        if self.content_type not in CONTENT_TYPES:
            raise ValueError("unsupported content type")
        if self.content_type == "text":
            if self.role is not None or self.asset_id is not None:
                raise ValueError("text content cannot have a role or asset_id")
            validate_prompt(self.text)
            return self
        if self.role not in CONTENT_ROLES[self.content_type]:
            raise ValueError("content role does not match its content type")
        if not isinstance(self.asset_id, str):
            raise ValueError("media content requires asset_id")
        validate_public_id(self.asset_id, "asset_id")
        if self.text is not None:
            raise ValueError("media content cannot contain text")
        return self

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"type": self.content_type}
        if self.role is not None:
            result["role"] = self.role
        if self.text is not None:
            result["text"] = self.text
        if self.asset_id is not None:
            result["asset_id"] = self.asset_id
        return result

    @classmethod
    def from_dict(cls, value: Any) -> "H3ContentItem":
        if not isinstance(value, dict) or "url" in value:
            raise ValueError("content items must be objects and cannot contain URLs")
        return cls(
            content_type=value.get("type"),
            role=value.get("role"),
            text=value.get("text"),
            asset_id=value.get("asset_id"),
        ).validate()


@dataclass(frozen=True)
class H3GenerationRequest:
    content: tuple[H3ContentItem, ...]
    resolution: str = DEFAULT_RESOLUTION
    duration_seconds: int = DEFAULT_DURATION_SECONDS
    ratio: str = DEFAULT_ASPECT_RATIO
    requested_ratio: str = DEFAULT_ASPECT_RATIO
    aigc_watermark: bool = True
    profile: str = PROFILE

    @classmethod
    def create(
        cls,
        *,
        content: Iterable[H3ContentItem],
        resolution: Any = DEFAULT_RESOLUTION,
        duration_seconds: Any = DEFAULT_DURATION_SECONDS,
        ratio: Any = DEFAULT_ASPECT_RATIO,
        aigc_watermark: Any = True,
        profile: Any = PROFILE,
    ) -> "H3GenerationRequest":
        items = tuple(item.validate() for item in content)
        if not items or not any(item.content_type == "text" and item.text and item.text.strip() for item in items):
            raise ValueError("non-empty text content is required")
        roles = {item.role for item in items if item.role}
        if roles & FRAME_ROLES and roles & REFERENCE_ROLES:
            raise ValueError("frame roles and reference roles cannot be mixed")
        if roles == {"reference_audio"}:
            raise ValueError("reference_audio cannot be used without image or video reference content")
        if resolution not in RESOLUTIONS:
            raise ValueError("resolution must be 768P or 2K")
        duration = validate_duration(duration_seconds)
        if ratio not in ASPECT_RATIOS:
            raise ValueError("unsupported ratio")
        if not isinstance(aigc_watermark, bool):
            raise ValueError("aigc_watermark must be a boolean")
        requested_ratio = str(ratio)
        if roles & FRAME_ROLES:
            normalized_ratio = "adaptive"
        else:
            normalized_ratio = requested_ratio
        if not roles and normalized_ratio == "adaptive":
            raise ValueError("text-to-video requires a concrete aspect_ratio")
        return cls(
            content=items,
            resolution=str(resolution),
            duration_seconds=duration,
            ratio=normalized_ratio,
            requested_ratio=requested_ratio,
            aigc_watermark=aigc_watermark,
            profile=validate_profile(profile),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "H3GenerationRequest":
        if not isinstance(value, dict):
            raise ValueError("generation request must be an object")
        raw_content = value.get("content")
        if not isinstance(raw_content, list):
            raise ValueError("content must be a list")
        return cls.create(
            content=(H3ContentItem.from_dict(item) for item in raw_content),
            resolution=value.get("resolution", DEFAULT_RESOLUTION),
            duration_seconds=value.get("duration_seconds", DEFAULT_DURATION_SECONDS),
            ratio=value.get("requested_ratio", value.get("ratio", DEFAULT_ASPECT_RATIO)),
            aigc_watermark=value.get("aigc_watermark", True),
            profile=value.get("profile", PROFILE),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": MODEL,
            "profile": self.profile,
            "content": [item.to_dict() for item in self.content],
            "resolution": self.resolution,
            "duration_seconds": self.duration_seconds,
            "ratio": self.ratio,
            "requested_ratio": self.requested_ratio,
            "aigc_watermark": self.aigc_watermark,
        }


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

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class BackendResult:
    filename: str
    media_type: str
    content: bytes
    metadata: dict[str, Any]
