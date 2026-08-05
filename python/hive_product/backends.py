"""Offline Mock and local-model-ready MiniMax H3 backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import gc
import json

from .contracts import BackendFailure, BackendResult, MINIMAX_POLICY_STATE, MODEL
from .local_pipeline import LocalH3Config, LocalPipelineFactory, release_optional_cuda_cache


class H3Backend(ABC):
    name: str
    display_name: str
    model: str = MODEL

    @abstractmethod
    def create_job(self, request: Mapping[str, Any]) -> str: ...

    @abstractmethod
    def get_job_status(self, backend_job_id: str) -> str: ...

    @abstractmethod
    def get_result(self, backend_job_id: str) -> BackendResult: ...

    @abstractmethod
    def cancel_job(self, backend_job_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def normalize_error(self, error: BaseException) -> BackendFailure: ...

    @abstractmethod
    def build_receipt(self, **fields: Any) -> dict[str, Any]: ...

    @abstractmethod
    def public_status(self) -> dict[str, Any]: ...


class MockH3Backend(H3Backend):
    """Deterministic offline product fixture; never presented as real H3."""

    name = "mock_h3"
    display_name = "Mock H3"

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    def create_job(self, request: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            {
                "request": request["generation_request"],
                "reference_sha256": request.get("reference_sha256"),
                "fixture": request.get("fixture", "success"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        backend_job_id = f"mock-{sha256(canonical).hexdigest()[:24]}"
        self._jobs[backend_job_id] = {"request": dict(request), "fixture": str(request.get("fixture", "success"))}
        return backend_job_id

    def get_job_status(self, backend_job_id: str) -> str:
        job = self._jobs.get(backend_job_id)
        if job is None:
            raise BackendFailure("output_missing", "Mock result does not exist.")
        if job["fixture"] in {"success", "no_result"}:
            return "succeeded"
        raise self._fixture_failure(job["fixture"])

    def get_result(self, backend_job_id: str) -> BackendResult:
        job = self._jobs.get(backend_job_id)
        if job is None or job["fixture"] == "no_result":
            raise BackendFailure("output_missing", "The Mock backend returned no result.")
        request = job["request"]["generation_request"]
        text = next(item["text"] for item in request["content"] if item["type"] == "text")
        payload = {
            "kind": "hiveframe_mock_video_result",
            "backend": "Mock H3",
            "notice": "No video was generated and no network call was made.",
            "model_contract": self.model,
            "resolution": request["resolution"],
            "duration_seconds": request["duration_seconds"],
            "ratio": request["ratio"],
            "prompt_sha256": sha256(text.encode("utf-8")).hexdigest(),
            "reference_sha256": job["request"].get("reference_sha256"),
        }
        content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return BackendResult(
            filename="hiveframe-mock-result.json",
            media_type="application/json",
            content=content,
            metadata={"mock": True, "network_call_count": 0, "output_classification": "mock_fixture"},
        )

    def cancel_job(self, backend_job_id: str) -> dict[str, Any]:
        return {"status": "unsupported", "reason": "Mock jobs finish synchronously.", "backend_job_id": backend_job_id}

    def normalize_error(self, error: BaseException) -> BackendFailure:
        if isinstance(error, BackendFailure):
            return error
        if isinstance(error, TimeoutError):
            return BackendFailure("timeout", "The Mock backend timed out.", True)
        return BackendFailure("generation_failed", "The Mock backend failed.", True)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        return {
            "receipt_version": "p0.local.1",
            "backend": self.name,
            "backend_display_name": self.display_name,
            "model_contract": self.model,
            "mock": True,
            "network_call_count": 0,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            **fields,
        }

    def public_status(self) -> dict[str, Any]:
        return {"name": self.name, "display_name": self.display_name, "state": "ready", "selectable": True}

    @staticmethod
    def _fixture_failure(fixture: str) -> BackendFailure:
        failures = {
            "timeout": BackendFailure("timeout", "The Mock backend timed out.", True),
            "rate_limit": BackendFailure("mock_rate_limit", "The Mock fixture simulated a rate limit.", True),
            "provider_failure": BackendFailure("mock_provider_failure", "The Mock fixture simulated a failure.", True),
        }
        return failures.get(fixture, BackendFailure("bad_input", "Unknown Mock fixture."))


class MiniMaxH3LocalBackend(H3Backend):
    """Coarse-grained local H3 adapter that waits safely for official files."""

    name = "local_h3"
    display_name = "Local H3"

    def __init__(
        self,
        *,
        config: LocalH3Config | None = None,
        pipeline_factory: LocalPipelineFactory | None = None,
    ) -> None:
        self.config = config or LocalH3Config.from_env()
        self.pipeline_factory = pipeline_factory or LocalPipelineFactory()
        self.pipeline: Any | None = None
        self.state = "artifact_pending"
        self._jobs: dict[str, dict[str, Any]] = {}

    def inspect_runtime(self) -> dict[str, Any]:
        if not self.config.local_enabled:
            return {"state": "runtime_unavailable", "reason": "local_backend_disabled", "imports_attempted": False}
        if self.config.trust_remote_code:
            return {"state": "runtime_incompatible", "reason": "trust_remote_code_requires_explicit_admission", "imports_attempted": False}
        if not self.config.local_files_only:
            return {"state": "runtime_incompatible", "reason": "automatic_download_disabled", "imports_attempted": False}
        return {"state": "artifact_configured", "reason": None, "imports_attempted": False}

    def _record_artifact_state(self, artifact_state: str) -> None:
        active_states = {
            "model_loading", "model_ready", "generation_running",
            "generation_succeeded", "generation_failed",
        }
        if self.state not in active_states:
            self.state = artifact_state

    def inspect_model_source(self) -> dict[str, Any]:
        repository_root = Path(__file__).resolve().parents[2]
        root_status = "not_configured"
        if self.config.model_root:
            configured_root = Path(self.config.model_root).expanduser().resolve()
            root_status = "invalid" if configured_root == repository_root or repository_root in configured_root.parents else "valid"
        if not self.config.model_source:
            self._record_artifact_state("artifact_pending")
            return {
                "state": "artifact_pending", "source_status": "not_configured",
                "revision_status": "not_configured", "model_root_status": root_status,
            }
        resolved_source = self.config.resolve_local_source()
        if resolved_source is not None and (resolved_source == repository_root or repository_root in resolved_source.parents):
            self._record_artifact_state("artifact_pending")
            return {
                "state": "artifact_pending", "source_status": "invalid",
                "revision_status": "configured" if self.config.revision else "not_configured",
                "model_root_status": root_status,
            }
        if root_status == "invalid" or (self.config.local_files_only and resolved_source is None):
            self._record_artifact_state("artifact_pending")
            return {
                "state": "artifact_pending",
                "source_status": "invalid",
                "revision_status": "configured" if self.config.revision else "not_configured",
                "model_root_status": root_status,
            }
        self._record_artifact_state("artifact_configured")
        return {
            "state": "artifact_configured",
            "source_status": "valid",
            "revision_status": "configured" if self.config.revision else "not_configured",
            "model_root_status": root_status,
        }

    def prepare_model(self) -> dict[str, Any]:
        source = self.inspect_model_source()
        if source["state"] == "artifact_pending":
            return {**source, "download_started": False, "network_call_count": 0}
        return {**source, "download_started": False, "network_call_count": 0}

    def load_model(self) -> dict[str, Any]:
        source = self.inspect_model_source()
        if source["source_status"] == "not_configured":
            raise BackendFailure("model_source_not_configured", "Local H3 model source is not configured.")
        if source["source_status"] != "valid":
            raise BackendFailure("artifact_not_found", "The configured Local H3 artifact is not available.")
        if not self.config.local_enabled:
            raise BackendFailure("local_backend_unavailable", "Local H3 is disabled until the runtime is explicitly admitted.")
        if not self.config.local_files_only:
            raise BackendFailure("runtime_incompatible", "Automatic model download is disabled in P0-LR.")
        if self.config.dtype not in {"bfloat16", "float16", "float32"}:
            raise BackendFailure("unsupported_dtype", "The configured Local H3 dtype is unsupported.")
        if not self.config.device_map:
            raise BackendFailure("unsupported_device_map", "The configured Local H3 device map is unsupported.")
        if self.config.trust_remote_code:
            raise BackendFailure("runtime_incompatible", "trust_remote_code requires separate explicit admission.")
        self.state = "model_loading"
        self.pipeline = self.pipeline_factory.create(
            model_source=self.config.model_source,
            revision=self.config.revision,
            dtype=self.config.dtype,
            device_map=self.config.device_map,
            local_files_only=self.config.local_files_only,
            trust_remote_code=self.config.trust_remote_code,
            resolved_local_source=self.config.resolve_local_source(),
        )
        self.state = "model_ready"
        return {"state": self.state, "network_call_count": 0}

    def unload_model(self) -> dict[str, Any]:
        self.pipeline = None
        gc.collect()
        release_optional_cuda_cache()
        self.state = "artifact_configured" if self.inspect_model_source()["source_status"] == "valid" else "artifact_pending"
        return {"state": self.state}

    def create_job(self, request: Mapping[str, Any]) -> str:
        if self.pipeline is None:
            try:
                self.load_model()
            except BackendFailure as error:
                if error.code in {"model_source_not_configured", "artifact_not_found"}:
                    raise BackendFailure("local_backend_unavailable", "Local H3 is waiting for official model files.") from error
                raise
        backend_job_id = f"local-{sha256(json.dumps(request['generation_request'], sort_keys=True).encode()).hexdigest()[:24]}"
        self.state = "generation_running"
        try:
            result = self.generate_video(request)
        except Exception:
            self.state = "generation_failed"
            raise
        self._jobs[backend_job_id] = {"status": "succeeded", "result": result}
        self.state = "generation_succeeded"
        return backend_job_id

    def get_job_status(self, backend_job_id: str) -> str:
        job = self._jobs.get(backend_job_id)
        if job is None:
            raise BackendFailure("output_missing", "Local H3 output is missing.")
        return str(job["status"])

    def generate_video(self, request: Mapping[str, Any]) -> BackendResult:
        if self.pipeline is None:
            raise BackendFailure("local_backend_unavailable", "Local H3 is not loaded.")
        try:
            raw = self.pipeline(request["generation_request"])
        except BackendFailure:
            raise
        except Exception as error:
            raise BackendFailure("generation_failed", "Local H3 generation failed.", True) from error
        normalized = self.normalize_output(raw)
        if not isinstance(normalized.get("result"), BackendResult):
            code = "unsupported_output_contract" if normalized["classification"] in {"provisional_image_output", "provisional_video_frames"} else "output_missing"
            raise BackendFailure(code, "Local H3 did not return a supported video output.")
        return normalized["result"]

    def get_result(self, backend_job_id: str) -> BackendResult:
        job = self._jobs.get(backend_job_id)
        if job is None:
            raise BackendFailure("output_missing", "Local H3 output is missing.")
        return job["result"]

    def cancel_generation(self, backend_job_id: str) -> dict[str, Any]:
        job = self._jobs.get(backend_job_id)
        if job is None:
            return {"status": "unsupported", "reason": "generation_not_found"}
        if job["status"] == "succeeded":
            return {"status": "unsupported", "reason": "generation_already_finished"}
        job["status"] = "cancelled"
        return {"status": "cancelled"}

    def cancel_job(self, backend_job_id: str) -> dict[str, Any]:
        return self.cancel_generation(backend_job_id)

    @staticmethod
    def normalize_output(raw: Any) -> dict[str, Any]:
        candidate = raw
        classification = "unsupported"
        video_hint = False
        if raw is None:
            return {"classification": "output_missing", "result": None}
        if isinstance(raw, BackendResult):
            return {
                "classification": "provisional_video_output" if raw.media_type.startswith("video/") else "unsupported_output_contract",
                "result": raw if raw.media_type.startswith("video/") else None,
            }
        if isinstance(raw, Mapping):
            if "videos" in raw:
                candidate = raw["videos"]
                video_hint = True
            elif "video" in raw:
                candidate = raw["video"]
                video_hint = True
            elif "path" in raw:
                candidate = raw["path"]
            elif "frames" in raw:
                return {"classification": "provisional_video_frames", "result": None}
            elif "images" in raw or "image" in raw:
                return {"classification": "provisional_image_output", "result": None}
            else:
                return {"classification": "unsupported_output_contract", "result": None}
        elif hasattr(raw, "frames"):
            return {"classification": "provisional_video_frames", "result": None}
        elif hasattr(raw, "videos"):
            candidate = raw.videos
            video_hint = True
        elif hasattr(raw, "video"):
            candidate = raw.video
            video_hint = True
        elif hasattr(raw, "images"):
            return {"classification": "provisional_image_output", "result": None}
        if isinstance(candidate, (list, tuple)):
            if not candidate:
                return {"classification": "output_missing", "result": None}
            candidate = candidate[0]
            if isinstance(candidate, BackendResult):
                return MiniMaxH3LocalBackend.normalize_output(candidate)
            if not video_hint:
                return {"classification": "provisional_video_frames", "result": None}
        if isinstance(candidate, (str, Path)):
            path = Path(candidate)
            if path.is_file() and path.suffix.lower() in {".mp4", ".webm", ".mov"}:
                classification = "provisional_video_output"
                return {
                    "classification": classification,
                    "result": BackendResult(path.name, "video/mp4", path.read_bytes(), {"output_classification": classification}),
                }
        return {
            "classification": "provisional_video_output" if video_hint else "unsupported_output_contract",
            "result": None,
        }

    def normalize_error(self, error: BaseException) -> BackendFailure:
        if isinstance(error, BackendFailure):
            return error
        if isinstance(error, TimeoutError):
            return BackendFailure("timeout", "Local H3 generation timed out.", True)
        if isinstance(error, MemoryError):
            return BackendFailure("out_of_memory", "Local H3 ran out of memory.")
        return BackendFailure("generation_failed", "Local H3 generation failed.", True)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        source = self.inspect_model_source()
        configuration = self.config.public_status()
        configuration["model_source"] = source["source_status"]
        configuration["revision"] = source["revision_status"]
        configuration["model_root"] = source["model_root_status"]
        return {
            "receipt_version": "p0.local.1",
            "backend": self.name,
            "backend_display_name": self.display_name,
            "model_contract": self.model,
            "backend_state": self.state,
            "configuration": configuration,
            "network_call_count": 0,
            "policy_state": dict(MINIMAX_POLICY_STATE),
            **fields,
        }

    def public_status(self) -> dict[str, Any]:
        source = self.inspect_model_source()
        configuration = self.config.public_status()
        configuration["model_source"] = source["source_status"]
        configuration["revision"] = source["revision_status"]
        configuration["model_root"] = source["model_root_status"]
        displayed_state = self.state if self.pipeline is not None else source["state"]
        can_generate = (
            self.config.local_enabled
            and source["source_status"] == "valid"
            and not self.config.trust_remote_code
        )
        return {
            "name": self.name,
            "display_name": self.display_name,
            "state": displayed_state,
            "selectable": True,
            "can_generate": can_generate,
            "message": "Local H3: Waiting for official model files" if source["state"] == "artifact_pending" else "Local H3 configured",
            "configuration": configuration,
        }


# Compatibility import only: the API-first shell no longer exists.
MiniMaxH3Backend = MiniMaxH3LocalBackend
