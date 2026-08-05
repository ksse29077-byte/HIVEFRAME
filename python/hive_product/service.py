"""Application service for the one-screen P0 user flow."""

from __future__ import annotations

from base64 import b64decode
from pathlib import Path
from typing import Any
import binascii
import threading
import uuid

from .backends import H3Backend, MockH3Backend
from .contracts import (
    BackendFailure,
    FEEDBACK_DECISIONS,
    FEEDBACK_REASONS,
    MAX_REFERENCE_BYTES,
    MAX_RETRY,
    MINIMAX_POLICY_STATE,
    MODEL,
    PROFILE,
    derive_training_eligibility,
    default_artifact_root,
    utc_now,
    validate_duration,
    validate_profile,
    validate_prompt,
    validate_reference_name,
)
from .store import ProductStore


class ProductService:
    def __init__(
        self,
        *,
        artifact_root: Path | None = None,
        backend: H3Backend | None = None,
        fail_artifact_writes: bool = False,
    ) -> None:
        self.store = ProductStore(artifact_root or default_artifact_root())
        self.backend = backend or MockH3Backend()
        self.fail_artifact_writes = fail_artifact_writes

    def create_job(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = validate_prompt(request.get("prompt"))
        profile = validate_profile(request.get("profile", PROFILE))
        duration = validate_duration(request.get("duration_seconds", 5))
        generation_consent = request.get("generation_consent") is True
        if not generation_consent:
            raise ValueError("generation_consent must be accepted before creating a job")
        prepared_reference: tuple[str, str, bytes] | None = None
        reference = request.get("reference")
        if reference is not None:
            if not isinstance(reference, dict):
                raise ValueError("reference must be an object")
            encoded = reference.get("content_base64")
            if not isinstance(encoded, str):
                raise ValueError("reference content_base64 is required")
            try:
                content = b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("reference content_base64 is invalid") from error
            # ProductStore performs the filename, type, size, and containment
            # checks before it writes any user bytes.
            if not content or len(content) > MAX_REFERENCE_BYTES:
                raise ValueError(f"reference image must contain 1 to {MAX_REFERENCE_BYTES} bytes")
            prepared_reference = (
                validate_reference_name(reference.get("name")),
                str(reference.get("media_type", "application/octet-stream")),
                content,
            )
        job_id = f"job_{uuid.uuid4().hex}"
        now = utc_now()
        values = {
            "job_id": job_id,
            "created_at": now,
            "updated_at": now,
            "backend": self.backend.name,
            "model": MODEL,
            "prompt": prompt,
            "reference_asset_id": None,
            "status": "queued",
            "provider_job_id": None,
            "error_code": None,
            "error_message": None,
            "output_asset_id": None,
            "receipt_id": None,
            "retry_count": 0,
            "profile": profile,
            "duration_seconds": duration,
            "generation_consent": True,
            "backend_transfer_consent": request.get("backend_transfer_consent") is True,
        }
        job = self.store.create_job(values)
        if prepared_reference is not None:
            asset = self.store.save_reference(
                job_id,
                prepared_reference[0],
                prepared_reference[1],
                prepared_reference[2],
            )
            job = self.store.update_job(job_id, updated_at=utc_now(), reference_asset_id=asset["asset_id"])
        return self.public_job(job)

    def execute_job(self, job_id: str, *, fixture: str = "success") -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["status"] != "queued":
            raise ValueError("only queued jobs can run")
        self.store.update_job(
            job_id,
            updated_at=utc_now(),
            status="running",
            error_code=None,
            error_message=None,
        )
        reference_sha = None
        if job["reference_asset_id"]:
            metadata, _ = self.store.get_asset(job["reference_asset_id"])
            reference_sha = metadata["sha256"]
        request = {
            "prompt": job["prompt"],
            "profile": job["profile"],
            "duration_seconds": job["duration_seconds"],
            "reference_sha256": reference_sha,
            "fixture": fixture,
        }
        try:
            provider_job_id = self.backend.create_job(request)
            self.store.update_job(job_id, updated_at=utc_now(), provider_job_id=provider_job_id)
            status = self.backend.get_job_status(provider_job_id)
            if status != "succeeded":
                raise RuntimeError(f"unsupported terminal provider status: {status}")
            result = self.backend.get_result(provider_job_id)
            if self.fail_artifact_writes:
                raise OSError("injected artifact save failure")
            output = self.store.save_result(job_id, result.filename, result.media_type, result.content)
            succeeded = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="succeeded",
                output_asset_id=output["asset_id"],
                error_code=None,
                error_message=None,
            )
            receipt = self.backend.build_receipt(
                job_id=job_id,
                profile=job["profile"],
                status="succeeded",
                output_sha256=output["sha256"],
                reference_sha256=reference_sha,
                generation_consent=True,
                backend_transfer_consent=job["backend_transfer_consent"],
                training_eligibility="evaluation_only",
            )
            receipt_asset = self.store.save_receipt(job_id, receipt)
            succeeded = self.store.update_job(job_id, updated_at=utc_now(), receipt_id=receipt_asset["asset_id"])
            return self.public_job(succeeded)
        except Exception as error:
            failure = self.backend.normalize_error(error)
            if isinstance(error, OSError):
                failure = BackendFailure("artifact_save_failure", "The result could not be saved.", True)
            failed = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="failed",
                error_code=failure.code,
                error_message=failure.message,
            )
            receipt = self.backend.build_receipt(
                job_id=job_id,
                profile=job["profile"],
                status="failed",
                error_code=failure.code,
                error_message=failure.message,
                retryable=failure.retryable,
                generation_consent=True,
                backend_transfer_consent=job["backend_transfer_consent"],
                training_eligibility="evaluation_only",
            )
            try:
                receipt_asset = self.store.save_receipt(job_id, receipt)
                failed = self.store.update_job(job_id, updated_at=utc_now(), receipt_id=receipt_asset["asset_id"])
            except OSError:
                pass
            return self.public_job(failed)

    def execute_job_async(self, job_id: str, *, fixture: str = "success") -> None:
        worker = threading.Thread(target=self.execute_job, kwargs={"job_id": job_id, "fixture": fixture}, daemon=True)
        worker.start()

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["status"] != "failed":
            raise ValueError("only failed jobs can be retried")
        if job["retry_count"] >= MAX_RETRY:
            raise ValueError("maximum retry count reached")
        queued = self.store.update_job(
            job_id,
            updated_at=utc_now(),
            status="queued",
            retry_count=job["retry_count"] + 1,
            provider_job_id=None,
            error_code=None,
            error_message=None,
        )
        return self.public_job(queued)

    def save_feedback(self, job_id: str, request: dict[str, Any]) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        decision = request.get("decision")
        if decision not in FEEDBACK_DECISIONS:
            raise ValueError("invalid feedback decision")
        if decision in {"accepted", "rejected"} and job["status"] != "succeeded":
            raise ValueError("accept/reject feedback requires a succeeded job")
        if decision == "retry_requested" and job["status"] != "failed":
            raise ValueError("retry feedback requires a failed job")
        reason = request.get("feedback_reason")
        if decision == "rejected" and reason not in FEEDBACK_REASONS:
            raise ValueError("a valid rejection reason is required")
        if reason is not None and reason not in FEEDBACK_REASONS:
            raise ValueError("invalid feedback reason")
        accepted = True if decision == "accepted" else False if decision == "rejected" else None
        training_opt_in = request.get("training_opt_in") is True
        deletion_requested = request.get("deletion_requested") is True
        eligibility, retention = derive_training_eligibility(
            generation_consent=job["generation_consent"],
            training_opt_in=training_opt_in,
            output_training_rights_confirmed=False,
            deletion_requested=deletion_requested,
        )
        values = {
            "feedback_id": f"feedback_{uuid.uuid4().hex}",
            "job_id": job_id,
            "created_at": utc_now(),
            "decision": decision,
            "user_accepted": accepted,
            "feedback_reason": reason,
            "generation_consent": int(job["generation_consent"]),
            "training_opt_in": int(training_opt_in),
            "training_eligibility": eligibility,
            "deletion_requested": int(deletion_requested),
            "retention_status": retention,
        }
        return self.store.save_feedback(values)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.public_job(self.store.get_job(job_id))

    def result_asset(self, job_id: str) -> tuple[dict[str, Any], Path]:
        job = self.store.get_job(job_id)
        if job["status"] != "succeeded" or not job["output_asset_id"]:
            raise KeyError("result is not available")
        return self.store.get_asset(job["output_asset_id"])

    @staticmethod
    def public_job(job: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: job[key]
            for key in (
                "job_id", "created_at", "updated_at", "backend", "model",
                "reference_asset_id", "status", "provider_job_id", "error_code",
                "error_message", "output_asset_id", "receipt_id", "retry_count",
                "profile", "duration_seconds", "generation_consent",
                "backend_transfer_consent",
            )
        }
        public["result_url"] = f"/api/jobs/{job['job_id']}/result" if job["output_asset_id"] else None
        public["max_retry"] = MAX_RETRY
        return public

    @staticmethod
    def public_config() -> dict[str, Any]:
        return {
            "profile": PROFILE,
            "model_contract": MODEL,
            "backend": "mock_h3",
            "live_h3_enabled": False,
            "live_call_count": 0,
            "duration_seconds": {"minimum": 3, "maximum": 8, "default": 5},
            "max_retry": MAX_RETRY,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            "legal_notice": "P0 terms, AUP, privacy, transfer-consent, and training-consent controls are placeholders, not legal text.",
        }
