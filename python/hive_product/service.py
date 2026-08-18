"""Application service for the one-screen local-model-ready P0 flow."""

from __future__ import annotations

from base64 import b64decode
from pathlib import Path
from typing import Any
import binascii
import json
import os
import threading
import time
import uuid

from .backends import H3Backend, MiniMaxH3LocalBackend, MockH3Backend
from .comfyui_backend import BACKEND_KEY as COMFYUI_BACKEND_KEY, MiniMaxH3ComfyUIBackend
from .contracts import (
    BACKENDS,
    BackendFailure,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_DURATION_SECONDS,
    DEFAULT_RESOLUTION,
    FEEDBACK_DECISIONS,
    FEEDBACK_REASONS,
    FAST_PROFILE,
    IMAGE_TO_VIDEO,
    H3ContentItem,
    H3GenerationRequest,
    MAX_REFERENCE_BYTES,
    MAX_RETRY,
    MINIMAX_POLICY_STATE,
    MODEL,
    PROFILE,
    TEXT_TO_VIDEO,
    derive_training_eligibility,
    default_artifact_root,
    utc_now,
    validate_generation_mode,
    validate_prompt,
    validate_reference_media_type,
    validate_reference_name,
)
from .store import ProductStore


class ProductService:
    def __init__(
        self,
        *,
        artifact_root: Path | None = None,
        backend: H3Backend | None = None,
        local_backend: MiniMaxH3LocalBackend | None = None,
        comfyui_backend: MiniMaxH3ComfyUIBackend | H3Backend | None = None,
        fail_artifact_writes: bool = False,
        dev_mode: bool | None = None,
    ) -> None:
        self.store = ProductStore(artifact_root or default_artifact_root())
        mock = backend or MockH3Backend()
        self.backends: dict[str, H3Backend] = {
            mock.name: mock,
            "local_h3": local_backend or MiniMaxH3LocalBackend(),
            COMFYUI_BACKEND_KEY: comfyui_backend or MiniMaxH3ComfyUIBackend(),
        }
        self.fail_artifact_writes = fail_artifact_writes
        self.dev_mode = os.environ.get("HIVEFRAME_DEV_MODE") == "1" if dev_mode is None else dev_mode

    def create_job(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = validate_prompt(request.get("prompt"))
        backend_name = request.get("backend", COMFYUI_BACKEND_KEY)
        if backend_name not in BACKENDS or backend_name not in self.backends:
            raise ValueError("backend must be mock_h3, local_h3, or minimax_h3_comfyui_local")
        if backend_name == "mock_h3" and not self.dev_mode:
            raise ValueError("Mock H3 is available only in developer mode")
        requested_profile = request.get("profile", PROFILE)
        if not self.dev_mode and requested_profile != PROFILE:
            raise ValueError("the product release supports Standard Quality only")
        if requested_profile == FAST_PROFILE and backend_name != COMFYUI_BACKEND_KEY:
            raise ValueError("fast_2m_candidate requires the local ComfyUI H3 backend")
        if request.get("generation_consent") is not True:
            raise ValueError("generation_consent must be accepted before creating a job")
        mode = validate_generation_mode(request.get("mode", TEXT_TO_VIDEO))
        prepared_reference = self._prepare_reference(request.get("reference")) if mode == IMAGE_TO_VIDEO else None
        if mode == IMAGE_TO_VIDEO and prepared_reference is None:
            raise ValueError("image_to_video requires a first-frame image")
        content = [H3ContentItem("text", text=prompt)]
        generation_request = H3GenerationRequest.create(
            content=content,
            resolution=request.get("resolution", DEFAULT_RESOLUTION) if self.dev_mode else DEFAULT_RESOLUTION,
            duration_seconds=request.get("duration_seconds", DEFAULT_DURATION_SECONDS) if self.dev_mode else DEFAULT_DURATION_SECONDS,
            ratio=request.get("ratio", request.get("aspect_ratio", DEFAULT_ASPECT_RATIO)) if self.dev_mode else DEFAULT_ASPECT_RATIO,
            aigc_watermark=request.get("aigc_watermark", True),
            profile=requested_profile,
        )
        job_id = f"job_{uuid.uuid4().hex}"
        now = utc_now()
        values = {
            "job_id": job_id,
            "created_at": now,
            "updated_at": now,
            "backend": backend_name,
            "model": MODEL,
            "prompt": prompt,
            "reference_asset_id": None,
            "status": "queued",
            "backend_job_id": None,
            "error_code": None,
            "error_message": None,
            "output_asset_id": None,
            "receipt_id": None,
            "retry_count": 0,
            "profile": generation_request.profile,
            "duration_seconds": generation_request.duration_seconds,
            "resolution": generation_request.resolution,
            "aspect_ratio": generation_request.ratio,
            "request_json": json.dumps(generation_request.to_dict(), ensure_ascii=False, sort_keys=True),
            "generation_consent": True,
            "backend_state": "queued",
            "generation_mode": mode,
        }
        job = self.store.create_job(values)
        if prepared_reference is not None:
            asset = self.store.save_reference(job_id, *prepared_reference)
            content.append(H3ContentItem("image", role="first_frame", asset_id=asset["asset_id"]))
            generation_request = H3GenerationRequest.create(
                content=content,
                resolution=generation_request.resolution,
                duration_seconds=generation_request.duration_seconds,
                ratio=generation_request.requested_ratio,
                aigc_watermark=generation_request.aigc_watermark,
                profile=generation_request.profile,
            )
            job = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                reference_asset_id=asset["asset_id"],
                request_json=json.dumps(generation_request.to_dict(), ensure_ascii=False, sort_keys=True),
            )
        return self.public_job(job)

    @staticmethod
    def _prepare_reference(reference: Any) -> tuple[str, str, bytes] | None:
        if reference is None:
            return None
        if not isinstance(reference, dict):
            raise ValueError("reference must be an object")
        encoded = reference.get("content_base64")
        if not isinstance(encoded, str):
            raise ValueError("reference content_base64 is required")
        try:
            content = b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("reference content_base64 is invalid") from error
        if not content or len(content) > MAX_REFERENCE_BYTES:
            raise ValueError(f"reference image must contain 1 to {MAX_REFERENCE_BYTES} bytes")
        name = validate_reference_name(reference.get("name"))
        media_type = validate_reference_media_type(name, reference.get("media_type"))
        return (name, media_type, content)

    def execute_job(self, job_id: str, *, fixture: str = "success") -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["status"] != "queued":
            raise ValueError("only queued jobs can run")
        backend = self.backends[job["backend"]]
        self.store.update_job(job_id, updated_at=utc_now(), backend_state="queued", error_code=None, error_message=None)
        reference_sha = None
        reference_image = None
        if job["reference_asset_id"]:
            metadata, path = self.store.get_asset(job["reference_asset_id"])
            reference_sha = metadata["sha256"]
            reference_image = {
                "filename": metadata["filename"],
                "media_type": metadata["media_type"],
                "content": path.read_bytes(),
            }
        request = {
            "generation_request": H3GenerationRequest.from_dict(json.loads(job["request_json"])).to_dict(),
            "reference_sha256": reference_sha,
            "reference_image": reference_image,
            "fixture": fixture,
        }
        backend_job_id = None
        try:
            backend_job_id = backend.create_job(request)
            self.store.update_job(job_id, updated_at=utc_now(), backend_job_id=backend_job_id)
            deadline = time.monotonic() + float(getattr(backend, "poll_timeout_seconds", 30.0))
            status = backend.get_job_status(backend_job_id)
            while status in {"queued", "running"}:
                self.store.update_job(
                    job_id,
                    updated_at=utc_now(),
                    status=status,
                    backend_state=status,
                )
                if time.monotonic() >= deadline:
                    raise BackendFailure("timeout", "The backend job exceeded its bounded timeout.", True)
                time.sleep(float(getattr(backend, "poll_interval_seconds", 0.05)))
                status = backend.get_job_status(backend_job_id)
            if status == "cancelled":
                cancelled = self.store.update_job(
                    job_id,
                    updated_at=utc_now(),
                    status="cancelled",
                    backend_state="cancelled",
                )
                return self.public_job(cancelled)
            if status != "succeeded":
                raise BackendFailure("generation_failed", "The backend did not reach succeeded state.")
            result = backend.get_result(backend_job_id)
            if self.fail_artifact_writes:
                raise OSError("injected artifact save failure")
            output = self.store.save_result(job_id, result.filename, result.media_type, result.content)
            self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="running",
                backend_state="artifact_saved",
                output_asset_id=output["asset_id"],
                error_code=None,
                error_message=None,
            )
            receipt = backend.build_receipt(
                job_id=job_id,
                profile=job["profile"],
                status="succeeded",
                backend_job_id=backend_job_id,
                request_contract=request["generation_request"],
                output_sha256=output["sha256"],
                output_classification=result.metadata.get("output_classification", "mock_fixture"),
                reference_sha256=reference_sha,
                generation_consent=True,
                external_transfer_required=False,
                training_eligibility="evaluation_only",
            )
            receipt_asset = self.store.save_receipt(job_id, receipt)
            succeeded = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="succeeded",
                backend_state="generation_succeeded",
                receipt_id=receipt_asset["asset_id"],
            )
            return self.public_job(succeeded)
        except Exception as error:
            failure = backend.normalize_error(error)
            if isinstance(error, OSError):
                failure = BackendFailure("artifact_save_failed", "The result could not be saved.", True)
            failed = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="failed",
                backend_state="generation_failed",
                error_code=failure.code,
                error_message=failure.message,
            )
            receipt = backend.build_receipt(
                job_id=job_id,
                profile=job["profile"],
                status="failed",
                backend_job_id=backend_job_id,
                request_contract=request["generation_request"],
                error_code=failure.code,
                error_message=failure.message,
                retryable=failure.retryable,
                generation_consent=True,
                external_transfer_required=False,
                training_eligibility="evaluation_only",
            )
            try:
                receipt_asset = self.store.save_receipt(job_id, receipt)
                failed = self.store.update_job(job_id, updated_at=utc_now(), receipt_id=receipt_asset["asset_id"])
            except OSError:
                pass
            return self.public_job(failed)

    def execute_job_async(self, job_id: str, *, fixture: str = "success") -> None:
        threading.Thread(target=self.execute_job, kwargs={"job_id": job_id, "fixture": fixture}, daemon=True).start()

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["status"] != "failed":
            raise ValueError("only failed jobs can be retried")
        if job["retry_count"] >= MAX_RETRY:
            raise ValueError("maximum retry count reached")
        queued = self.store.update_job(
            job_id, updated_at=utc_now(), status="queued", retry_count=job["retry_count"] + 1,
            backend_job_id=None, backend_state="queued", error_code=None, error_message=None,
        )
        return self.public_job(queued)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if job["status"] not in {"queued", "running"} or not job["backend_job_id"]:
            return {**self.public_job(job), "cancel_status": "unsupported"}
        backend = self.backends[job["backend"]]
        result = backend.cancel_job(job["backend_job_id"])
        if result.get("status") == "cancelled":
            job = self.store.update_job(
                job_id,
                updated_at=utc_now(),
                status="cancelled",
                backend_state="cancelled",
            )
        return {**self.public_job(job), "cancel_status": result.get("status", "unsupported")}

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
            generation_consent=job["generation_consent"], training_opt_in=training_opt_in,
            output_training_rights_confirmed=False, deletion_requested=deletion_requested,
        )
        return self.store.save_feedback({
            "feedback_id": f"feedback_{uuid.uuid4().hex}", "job_id": job_id, "created_at": utc_now(),
            "decision": decision, "user_accepted": accepted, "feedback_reason": reason,
            "generation_consent": int(job["generation_consent"]), "training_opt_in": int(training_opt_in),
            "training_eligibility": eligibility, "deletion_requested": int(deletion_requested),
            "retention_status": retention,
        })

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self.public_job(self.store.get_job(job_id))

    def result_asset(self, job_id: str) -> tuple[dict[str, Any], Path]:
        job = self.store.get_job(job_id)
        if job["status"] != "succeeded" or not job["output_asset_id"]:
            raise KeyError("result is not available")
        return self.store.get_asset(job["output_asset_id"])

    def public_job(self, job: dict[str, Any]) -> dict[str, Any]:
        public = {key: job[key] for key in (
            "job_id", "created_at", "updated_at", "backend", "model", "reference_asset_id",
            "status", "backend_job_id", "backend_state", "error_code", "error_message",
            "output_asset_id", "receipt_id", "retry_count", "profile", "duration_seconds",
            "resolution", "aspect_ratio", "generation_consent",
            "generation_mode",
        )}
        public["result_url"] = f"/api/jobs/{job['job_id']}/result" if job["output_asset_id"] else None
        public["result_media_type"] = None
        public["result_filename"] = None
        if job["output_asset_id"]:
            try:
                metadata, _ = self.store.get_asset(job["output_asset_id"])
                public["result_media_type"] = metadata["media_type"]
                public["result_filename"] = metadata["filename"]
            except (KeyError, FileNotFoundError):
                pass
        public["max_retry"] = MAX_RETRY
        return public

    def public_config(self) -> dict[str, Any]:
        local_backend = self.backends[COMFYUI_BACKEND_KEY]
        local_status = local_backend.public_status()
        public_backends = {
            name: backend.public_status()
            for name, backend in self.backends.items()
            if name == COMFYUI_BACKEND_KEY or self.dev_mode and name == "mock_h3"
        }
        storage_ready = self.store.root.is_dir() and os.access(self.store.root, os.W_OK)
        readiness = dict(local_status.get("readiness", {}))
        readiness["storage"] = {
            "state": "ready" if storage_ready else "error",
            "label": "준비됨" if storage_ready else "오류",
        }
        return {
            "profile": PROFILE,
            "model_contract": MODEL,
            "default_backend": COMFYUI_BACKEND_KEY,
            "dev_mode": self.dev_mode,
            "backends": public_backends,
            "readiness": readiness,
            "can_generate": bool(local_status.get("can_generate")) and storage_ready,
            "quality": {
                "name": "Standard Quality",
                "width": 864,
                "height": 480,
                "frames": 124,
                "fps": 24,
                "steps": 20,
                "scheduler": "simple",
                "sampler": "res_multistep",
                "denoise": 1.0,
                "native_audio": True,
            },
            "resolution": DEFAULT_RESOLUTION,
            "duration_seconds": DEFAULT_DURATION_SECONDS,
            "ratio": DEFAULT_ASPECT_RATIO,
            "max_retry": MAX_RETRY,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            "legal_notice": "Terms, AUP, privacy, retention, and training controls are placeholders, not legal text.",
        }
