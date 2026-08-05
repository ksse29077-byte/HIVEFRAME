"""Offline P0 backend adapters.

The MiniMax adapter deliberately contains no HTTP client and cannot make a
live call. P1 owns official API revalidation and live admission.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
from typing import Any, Mapping
import json
import os

from .contracts import BackendFailure, BackendResult, MINIMAX_POLICY_STATE, MODEL


class H3Backend(ABC):
    name: str
    model: str = MODEL

    @abstractmethod
    def create_job(self, request: Mapping[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_job_status(self, provider_job_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_result(self, provider_job_id: str) -> BackendResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_job(self, provider_job_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def normalize_error(self, error: BaseException) -> BackendFailure:
        raise NotImplementedError

    @abstractmethod
    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        raise NotImplementedError


class MockH3Backend(H3Backend):
    """Deterministic offline fixture backend used by P0."""

    name = "mock_h3"

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    def create_job(self, request: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            {
                "duration_seconds": request["duration_seconds"],
                "profile": request["profile"],
                "prompt": request["prompt"],
                "reference_sha256": request.get("reference_sha256"),
                "fixture": request.get("fixture", "success"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        provider_job_id = f"mock-{sha256(canonical).hexdigest()[:24]}"
        fixture = str(request.get("fixture", "success"))
        self._jobs[provider_job_id] = {"request": dict(request), "fixture": fixture}
        return provider_job_id

    def get_job_status(self, provider_job_id: str) -> str:
        job = self._jobs.get(provider_job_id)
        if job is None:
            raise BackendFailure("no_result", "Mock result does not exist.", False)
        fixture = job["fixture"]
        if fixture == "success":
            return "succeeded"
        if fixture == "no_result":
            return "succeeded"
        raise self._fixture_failure(fixture)

    def get_result(self, provider_job_id: str) -> BackendResult:
        job = self._jobs.get(provider_job_id)
        if job is None or job["fixture"] == "no_result":
            raise BackendFailure("no_result", "The provider returned no result.", False)
        request = job["request"]
        payload = {
            "kind": "hiveframe_mock_video_result",
            "notice": "No video was generated and no network call was made.",
            "model_contract": self.model,
            "profile": request["profile"],
            "duration_seconds": request["duration_seconds"],
            "prompt_sha256": sha256(request["prompt"].encode("utf-8")).hexdigest(),
            "reference_sha256": request.get("reference_sha256"),
        }
        content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return BackendResult(
            filename="hiveframe-mock-result.json",
            media_type="application/json",
            content=content,
            metadata={"mock": True, "live_call_count": 0},
        )

    def cancel_job(self, provider_job_id: str) -> dict[str, Any]:
        return {
            "status": "unsupported",
            "reason": "Mock jobs finish synchronously; cancellation is not supported in P0.",
            "provider_job_id": provider_job_id,
        }

    def normalize_error(self, error: BaseException) -> BackendFailure:
        if isinstance(error, BackendFailure):
            return error
        if isinstance(error, TimeoutError):
            return BackendFailure("timeout", "The backend timed out.", True)
        return BackendFailure("provider_failure", "The backend failed.", True)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        return {
            "receipt_version": "p0.1",
            "backend": self.name,
            "model_contract": self.model,
            "live_mode": False,
            "live_call_count": 0,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            **fields,
        }

    @staticmethod
    def _fixture_failure(fixture: str) -> BackendFailure:
        failures = {
            "timeout": BackendFailure("timeout", "The mock backend timed out.", True),
            "rate_limit": BackendFailure("rate_limit", "The mock backend was rate limited.", True),
            "provider_failure": BackendFailure("provider_failure", "The mock provider failed.", True),
        }
        return failures.get(fixture, BackendFailure("bad_input", "Unknown mock fixture.", False))


class MiniMaxH3Backend(H3Backend):
    """P0 contract shell. It never performs an HTTP request."""

    name = "minimax_h3"

    def __init__(self, *, live_enabled: bool | None = None) -> None:
        if live_enabled is None:
            live_enabled = os.environ.get("HIVEFRAME_H3_LIVE_ENABLED", "").lower() == "true"
        self.live_enabled = bool(live_enabled)

    @property
    def api_key_available(self) -> bool:
        return bool(os.environ.get("MINIMAX_API_KEY"))

    def create_job(self, request: Mapping[str, Any]) -> str:
        if not self.live_enabled:
            raise BackendFailure("live_disabled", "Live MiniMax H3 mode is disabled in P0.", False)
        if not self.api_key_available:
            raise BackendFailure("missing_api_key", "MINIMAX_API_KEY is not configured.", False)
        raise BackendFailure(
            "live_not_implemented",
            "P0 contains no live MiniMax transport; use the separately approved P1 integration.",
            False,
        )

    def get_job_status(self, provider_job_id: str) -> str:
        raise BackendFailure("live_not_implemented", "Live status polling is not implemented in P0.", False)

    def get_result(self, provider_job_id: str) -> BackendResult:
        raise BackendFailure("no_result", "No live result is available in P0.", False)

    def cancel_job(self, provider_job_id: str) -> dict[str, Any]:
        return {
            "status": "unsupported",
            "reason": "MiniMax H3 cancellation must be rechecked against official P1 API documentation.",
            "provider_job_id": provider_job_id,
        }

    def normalize_error(self, error: BaseException) -> BackendFailure:
        if isinstance(error, BackendFailure):
            return error
        if isinstance(error, TimeoutError):
            return BackendFailure("timeout", "The provider request timed out.", True)
        status = getattr(error, "status", None)
        if status == 429:
            return BackendFailure("rate_limit", "The provider rate limit was reached.", True, 429)
        if isinstance(status, int) and status >= 500:
            return BackendFailure("provider_failure", "The provider reported a server failure.", True, status)
        return BackendFailure("provider_failure", "The provider request failed.", True, status)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        return {
            "receipt_version": "p0.1",
            "backend": self.name,
            "model_contract": self.model,
            "live_mode": self.live_enabled,
            "live_call_count": 0,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            **fields,
        }
