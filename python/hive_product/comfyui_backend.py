"""Loopback-only MiniMax H3 ComfyUI backend for the P0 product slice.

The adapter deliberately keeps the language/process boundary coarse: one
workflow is submitted to an already running (or explicitly started) local
ComfyUI instance and one small status/result contract is returned. Importing
this module performs no network, model, or GPU work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import json
import os
import socket
import subprocess
import time

from .backends import H3Backend
from .contracts import BackendFailure, BackendResult, MINIMAX_POLICY_STATE, MODEL


BACKEND_KEY = "minimax_h3_comfyui_local"
REQUIRED_MODELS = {
    "diffusion_model": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "text_encoder": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
}
REQUIRED_NODES = {
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "RandomNoise",
    "BasicScheduler",
    "KSamplerSelect",
    "BasicGuider",
    "SamplerCustomAdvanced",
    "MiniMaxH3ImageToVideo",
    "VAEDecode",
    "VAEDecodeAudio",
    "CreateVideo",
    "SaveVideo",
}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the supported range")
    return value


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else None


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


@dataclass(frozen=True)
class ComfyUIH3Config:
    asset_root: Path | None
    comfyui_root: Path | None
    base_url: str
    workflow: Path | None
    output_root: Path | None
    custom_nodes_root: Path | None = None
    poll_interval_seconds: float = 0.5
    timeout_seconds: float = 3_600.0

    @classmethod
    def from_env(cls) -> "ComfyUIH3Config":
        return cls(
            asset_root=_path_from_env("HIVEFRAME_H3_ASSET_ROOT"),
            comfyui_root=_path_from_env("HIVEFRAME_COMFYUI_ROOT"),
            base_url=os.environ.get("HIVEFRAME_COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            workflow=_path_from_env("HIVEFRAME_H3_WORKFLOW"),
            output_root=_path_from_env("HIVEFRAME_H3_OUTPUT_ROOT"),
            custom_nodes_root=_path_from_env("HIVEFRAME_COMFYUI_CUSTOM_NODES_ROOT"),
            poll_interval_seconds=_env_float("HIVEFRAME_COMFYUI_POLL_SECONDS", 0.5, 0.1, 10.0),
            timeout_seconds=_env_float("HIVEFRAME_COMFYUI_TIMEOUT_SECONDS", 3_600.0, 10.0, 14_400.0),
        )

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise BackendFailure("runtime_incompatible", "ComfyUI must use an HTTP loopback address.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BackendFailure("runtime_incompatible", "ComfyUI URL credentials and query values are unsupported.")
        if parsed.port is None:
            raise BackendFailure("runtime_incompatible", "ComfyUI URL must declare a loopback port.")
        repository_root = Path(__file__).resolve().parents[2]
        for value, label in (
            (self.asset_root, "asset root"),
            (self.comfyui_root, "ComfyUI root"),
            (self.workflow, "workflow"),
            (self.output_root, "output root"),
        ):
            if value is not None and _inside(value, repository_root):
                raise BackendFailure("runtime_incompatible", f"{label} must be outside the repository.")
        if self.workflow is not None and self.asset_root is not None and not _inside(self.workflow, self.asset_root):
            raise BackendFailure("runtime_incompatible", "The workflow must be inside the approved asset root.")
        if self.custom_nodes_root is not None and not _inside(self.custom_nodes_root, repository_root):
            raise BackendFailure(
                "runtime_incompatible", "Repository-owned custom nodes must stay inside the repository."
            )

    def public_status(self) -> dict[str, Any]:
        return {
            "asset_root": "configured" if self.asset_root else "not_configured",
            "comfyui_root": "configured" if self.comfyui_root else "not_configured",
            "base_url": "loopback_configured",
            "workflow": "configured" if self.workflow else "not_configured",
            "output_root": "configured" if self.output_root else "not_configured",
            "custom_nodes_root": "configured" if self.custom_nodes_root else "not_configured",
            "poll_interval_seconds": self.poll_interval_seconds,
            "timeout_seconds": self.timeout_seconds,
        }


class LoopbackComfyClient:
    """Small standard-library client restricted to the configured loopback."""

    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def json(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = {}
            message = detail.get("error", {}).get("message") if isinstance(detail.get("error"), dict) else None
            raise BackendFailure("comfyui_http_error", message or f"ComfyUI returned HTTP {error.code}.") from error
        except (URLError, TimeoutError, OSError) as error:
            raise BackendFailure("comfyui_unavailable", "The loopback ComfyUI runtime is unavailable.", True) from error

    def bytes(self, path: str) -> bytes:
        try:
            with urlopen(self.base_url + path, timeout=self.timeout_seconds) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise BackendFailure("output_missing", "The ComfyUI output could not be collected.") from error


class MiniMaxH3ComfyUIBackend(H3Backend):
    """Real local H3 backend using one loopback ComfyUI workflow submission."""

    name = BACKEND_KEY
    display_name = "Local H3 — ComfyUI"
    poll_interval_seconds = 0.5
    experimental_capabilities = {
        "regional_attention_output_reuse_correction_v1": {
            "default_enabled": False,
            "state": "structurally_not_admitted",
            "fallback": "standard_full_compute",
        }
    }

    def __init__(
        self,
        *,
        config: ComfyUIH3Config | None = None,
        client: LoopbackComfyClient | Any | None = None,
    ) -> None:
        self.config = config or ComfyUIH3Config.from_env()
        self.config.validate()
        self.client = client or LoopbackComfyClient(self.config.base_url)
        self.poll_interval_seconds = self.config.poll_interval_seconds
        self.poll_timeout_seconds = self.config.timeout_seconds
        self._jobs: dict[str, dict[str, Any]] = {}
        self._process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any | None = None
        self._runtime_started_here = False

    def inspect_runtime(self) -> dict[str, Any]:
        try:
            system = self.client.json("GET", "/system_stats")
            objects = self.client.json("GET", "/object_info")
            queue = self.client.json("GET", "/queue")
        except BackendFailure as error:
            return {
                "state": "runtime_unavailable",
                "reason": error.code,
                "loopback_only": True,
                "required_nodes_present": False,
            }
        node_names = set(objects) if isinstance(objects, dict) else set()
        missing = sorted(REQUIRED_NODES - node_names)
        recognized = {
            "diffusion_model": self._loader_has(objects, "UNETLoader", "unet_name", REQUIRED_MODELS["diffusion_model"]),
            "text_encoder": self._loader_has(objects, "CLIPLoader", "clip_name", REQUIRED_MODELS["text_encoder"]),
            "video_vae": self._loader_has(objects, "VAELoader", "vae_name", REQUIRED_MODELS["video_vae"]),
            "audio_vae": self._loader_has(objects, "VAELoader", "vae_name", REQUIRED_MODELS["audio_vae"]),
        }
        unrecognized = sorted(name for name, present in recognized.items() if not present)
        device = None
        if isinstance(system, dict):
            devices = system.get("devices")
            if isinstance(devices, list) and devices:
                device = devices[0]
        return {
            "state": "ready" if not missing and not unrecognized else "runtime_incompatible",
            "reason": None if not missing and not unrecognized else "required_nodes_missing" if missing else "model_paths_unrecognized",
            "loopback_only": True,
            "required_nodes_present": not missing,
            "missing_nodes": missing,
            "model_files_recognized": recognized,
            "unrecognized_model_logical_ids": unrecognized,
            "comfyui_version": system.get("system", {}).get("comfyui_version") if isinstance(system, dict) else None,
            "python_version": system.get("system", {}).get("python_version") if isinstance(system, dict) else None,
            "pytorch_version": system.get("system", {}).get("pytorch_version") if isinstance(system, dict) else None,
            "device_name": device.get("name") if isinstance(device, dict) else None,
            "device_type": device.get("type") if isinstance(device, dict) else None,
            "vram_total_bytes": device.get("vram_total") if isinstance(device, dict) else None,
            "queue_running": len(queue.get("queue_running", [])) if isinstance(queue, dict) else None,
            "queue_pending": len(queue.get("queue_pending", [])) if isinstance(queue, dict) else None,
        }

    @staticmethod
    def _loader_has(objects: Any, node_name: str, input_name: str, filename: str) -> bool:
        if not isinstance(objects, dict):
            return False
        node = objects.get(node_name)
        if not isinstance(node, dict):
            return False
        value = node.get("input", {}).get("required", {}).get(input_name)
        if not isinstance(value, list) or not value:
            return False
        options = value[0]
        return isinstance(options, list) and filename in options

    def inspect_assets(self) -> dict[str, Any]:
        root = self.config.asset_root
        if root is None or not root.is_dir():
            return {"state": "artifact_pending", "reason": "asset_root_missing", "models": {}}
        models: dict[str, dict[str, Any]] = {}
        for logical_id, filename in REQUIRED_MODELS.items():
            path = root / filename
            models[logical_id] = {
                "logical_filename": filename,
                "exists": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else None,
            }
        missing = sorted(name for name, value in models.items() if not value["exists"])
        return {
            "state": "ready" if not missing else "artifact_pending",
            "reason": None if not missing else "required_models_missing",
            "models": models,
            "missing_logical_ids": missing,
        }

    def inspect_workflow(self) -> dict[str, Any]:
        path = self.config.workflow
        if path is None or not path.is_file():
            return {"state": "artifact_pending", "reason": "workflow_missing"}
        try:
            workflow = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {"state": "runtime_incompatible", "reason": "workflow_invalid"}
        nodes = workflow.get("nodes")
        definitions = workflow.get("definitions", {}).get("subgraphs", [])
        if not isinstance(nodes, list) or not isinstance(definitions, list):
            return {"state": "runtime_incompatible", "reason": "api_workflow_required"}
        types = {str(node.get("type")) for node in nodes if isinstance(node, dict)}
        nested = {
            str(node.get("type"))
            for graph in definitions
            if isinstance(graph, dict)
            for node in graph.get("nodes", [])
            if isinstance(node, dict)
        }
        referenced = {name: self._contains_string(workflow, filename) for name, filename in REQUIRED_MODELS.items()}
        all_types = types | nested
        return {
            "state": "ready" if not (REQUIRED_NODES - all_types) else "runtime_incompatible",
            "reason": None if not (REQUIRED_NODES - all_types) else "workflow_nodes_missing",
            "workflow_kind": "ComfyUI UI workflow with embedded subgraph",
            "workflow_logical_id": path.stem,
            "workflow_sha256": sha256(path.read_bytes()).hexdigest(),
            "top_level_node_count": len(nodes),
            "embedded_node_count": sum(len(graph.get("nodes", [])) for graph in definitions if isinstance(graph, dict)),
            "referenced_models": referenced,
            "api_copy_required": True,
            "execution_profile": self._workflow_profile(),
        }

    @staticmethod
    def _contains_string(value: Any, needle: str) -> bool:
        if isinstance(value, str):
            return value == needle
        if isinstance(value, list):
            return any(MiniMaxH3ComfyUIBackend._contains_string(item, needle) for item in value)
        if isinstance(value, dict):
            return any(MiniMaxH3ComfyUIBackend._contains_string(item, needle) for item in value.values())
        return False

    @staticmethod
    def _workflow_profile() -> dict[str, Any]:
        return {
            "mode": "text_to_video_with_native_audio",
            "width": 864,
            "height": 480,
            "duration_seconds": 5,
            "frame_count": 124,
            "fps": 24,
            "steps": 20,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "denoise": 1.0,
            "seed": 101,
            "workflow_default_preserved": True,
        }

    def build_api_workflow(self, generation_request: Mapping[str, Any], *, output_prefix: str) -> dict[str, Any]:
        prompt = next(
            (
                str(item.get("text", "")).strip()
                for item in generation_request.get("content", [])
                if isinstance(item, dict) and item.get("type") == "text"
            ),
            "",
        )
        if not prompt:
            raise BackendFailure("bad_input", "A text prompt is required for the H3 workflow.")
        if not output_prefix or any(part in output_prefix for part in ("..", "\\", ":")):
            raise BackendFailure("bad_input", "The ComfyUI output prefix is unsafe.")
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": REQUIRED_MODELS["diffusion_model"], "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": REQUIRED_MODELS["text_encoder"], "type": "minimax", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": REQUIRED_MODELS["video_vae"]}},
            "4": {"class_type": "VAELoader", "inputs": {"vae_name": REQUIRED_MODELS["audio_vae"]}},
            "5": {"class_type": "RandomNoise", "inputs": {"noise_seed": 101}},
            "6": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": 20, "denoise": 1.0}},
            "7": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "width": 864, "height": 480, "length": 124}},
            "9": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["8", 0]}},
            "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0], "guider": ["9", 0], "sampler": ["7", 0], "sigmas": ["6", 0], "latent_image": ["8", 1]}},
            "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
            "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
            "13": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "audio": ["12", 0], "fps": 24.0, "bit_depth": 8}},
            "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": output_prefix, "format": "mp4", "codec": "auto"}},
        }

    def start(self) -> dict[str, Any]:
        if self._is_reachable():
            return {"status": "already_running", "started_here": False, "loopback_only": True}
        root = self.config.comfyui_root
        asset_root = self.config.asset_root
        output_root = self.config.output_root
        if root is None or asset_root is None or output_root is None:
            raise BackendFailure("runtime_unavailable", "ComfyUI start paths are not configured.")
        main = root / "main.py"
        python = root / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
        if not main.is_file() or not python.is_file():
            raise BackendFailure("runtime_unavailable", "The configured ComfyUI installation is incomplete.")
        output_root.mkdir(parents=True, exist_ok=True)
        runtime_root = output_root / "runtime"
        runtime_root.mkdir(exist_ok=True)
        for child in ("input", "output", "temp", "user"):
            (output_root / child).mkdir(exist_ok=True)
        extra_paths = runtime_root / "h3-extra-model-paths.yaml"
        quoted_root = str(asset_root).replace("'", "''")
        extra_config = (
            "hiveframe.h3:\n"
            f"  base_path: '{quoted_root}'\n"
            "  diffusion_models: '.'\n"
            "  text_encoders: '.'\n"
            "  vae: '.'\n"
        )
        if self.config.custom_nodes_root is not None:
            quoted_nodes = str(self.config.custom_nodes_root).replace("'", "''")
            extra_config += "hiveframe.c1:\n" f"  custom_nodes: '{quoted_nodes}'\n"
        extra_paths.write_text(extra_config, encoding="utf-8")
        log_path = runtime_root / "comfyui-runtime.log"
        self._log_handle = log_path.open("ab")
        parsed = urlparse(self.config.base_url)
        command = [
            str(python), str(main),
            "--listen", "127.0.0.1",
            "--port", str(parsed.port),
            "--extra-model-paths-config", str(extra_paths),
            "--input-directory", str(output_root / "input"),
            "--output-directory", str(output_root / "output"),
            "--temp-directory", str(output_root / "temp"),
            "--user-directory", str(output_root / "user"),
            "--disable-auto-launch",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            command,
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._runtime_started_here = True
        deadline = time.monotonic() + min(180.0, self.config.timeout_seconds)
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise BackendFailure("comfyui_start_failed", "The local ComfyUI process exited during startup.")
            if self._is_reachable():
                return {"status": "started", "started_here": True, "loopback_only": True}
            time.sleep(0.5)
        raise BackendFailure("comfyui_start_timeout", "The local ComfyUI process did not become ready in time.")

    def start_runtime(self) -> dict[str, Any]:
        """Start the configured loopback runtime without changing global config."""
        return self.start()

    def stop(self) -> dict[str, Any]:
        if not self._runtime_started_here or self._process is None:
            return {"status": "not_owned", "stopped": False}
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=10)
        return_code = self._process.returncode
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        self._runtime_started_here = False
        return {"status": "stopped", "stopped": True, "return_code": return_code}

    def stop_runtime(self) -> dict[str, Any]:
        """Stop only the runtime process owned by this adapter instance."""
        return self.stop()

    def _is_reachable(self) -> bool:
        parsed = urlparse(self.config.base_url)
        try:
            with socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 8188), timeout=0.5):
                return True
        except OSError:
            return False

    def create_job(self, request: Mapping[str, Any]) -> str:
        runtime = self.inspect_runtime()
        assets = self.inspect_assets()
        workflow = self.inspect_workflow()
        if runtime["state"] != "ready":
            raise BackendFailure("comfyui_dependency_required", "Required ComfyUI H3 nodes are unavailable.")
        if assets["state"] != "ready":
            raise BackendFailure("artifact_not_found", "Required local H3 model files are unavailable.")
        if workflow["state"] != "ready":
            raise BackendFailure("comfyui_api_workflow_required", "The approved H3 workflow cannot be converted safely.")
        generation_request = request["generation_request"]
        request_digest = sha256(json.dumps(generation_request, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        output_prefix = f"hiveframe/p0-h3-{request_digest[:16]}"
        prompt = self.build_api_workflow(generation_request, output_prefix=output_prefix)
        submitted_perf = time.monotonic()
        submitted_at = _utc_now()
        self._sample_resources(None)
        response = self.client.json("POST", "/prompt", {"prompt": prompt, "client_id": "hiveframe-p0"})
        prompt_id = response.get("prompt_id") if isinstance(response, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id:
            raise BackendFailure("comfyui_submit_failed", "ComfyUI did not return a prompt ID.")
        self._jobs[prompt_id] = {
            "status": "queued",
            "submitted_at": submitted_at,
            "submitted_perf": submitted_perf,
            "first_running_perf": None,
            "first_running_at": None,
            "completed_perf": None,
            "completed_at": None,
            "request_sha256": request_digest,
            "workflow_sha256": workflow["workflow_sha256"],
            "profile": workflow["execution_profile"],
            "peak_vram_bytes": None,
            "peak_host_ram_bytes": None,
            "sample_count": 0,
            "retry_count": 0,
            "output_prefix": output_prefix,
            "node_errors": response.get("node_errors", {}) if isinstance(response, dict) else {},
        }
        self._sample_resources(prompt_id)
        return prompt_id

    def submit_workflow(self, request: Mapping[str, Any]) -> str:
        """Submit one coarse-grained API workflow through the backend contract."""
        return self.create_job(request)

    def get_job_status(self, backend_job_id: str) -> str:
        job = self._require_job(backend_job_id)
        self._sample_resources(backend_job_id)
        history = self.get_history(backend_job_id)
        if history is not None:
            status = history.get("status", {}) if isinstance(history, dict) else {}
            status_str = str(status.get("status_str", "")).lower() if isinstance(status, dict) else ""
            completed = bool(status.get("completed")) if isinstance(status, dict) else False
            if status_str in {"error", "failed"}:
                job["status"] = "failed"
                job["completed_perf"] = time.monotonic()
                job["completed_at"] = _utc_now()
                raise BackendFailure("comfyui_execution_failed", self._history_error_message(history))
            if completed or status_str in {"success", "succeeded"}:
                job["status"] = "succeeded"
                if job["completed_perf"] is None:
                    job["completed_perf"] = time.monotonic()
                    job["completed_at"] = _utc_now()
                return "succeeded"
        queue = self.client.json("GET", "/queue")
        running_ids = self._queue_ids(queue.get("queue_running", []) if isinstance(queue, dict) else [])
        pending_ids = self._queue_ids(queue.get("queue_pending", []) if isinstance(queue, dict) else [])
        if backend_job_id in running_ids:
            job["status"] = "running"
            if job["first_running_perf"] is None:
                job["first_running_perf"] = time.monotonic()
                job["first_running_at"] = _utc_now()
            return "running"
        if backend_job_id in pending_ids:
            job["status"] = "queued"
            return "queued"
        return str(job["status"])

    @staticmethod
    def _queue_ids(entries: list[Any]) -> set[str]:
        result: set[str] = set()
        for entry in entries:
            if isinstance(entry, (list, tuple)) and len(entry) > 1 and isinstance(entry[1], str):
                result.add(entry[1])
        return result

    def get_history(self, backend_job_id: str) -> dict[str, Any] | None:
        response = self.client.json("GET", f"/history/{backend_job_id}")
        if not isinstance(response, dict):
            return None
        value = response.get(backend_job_id)
        return value if isinstance(value, dict) else None

    def collect_result(self, backend_job_id: str) -> BackendResult:
        job = self._require_job(backend_job_id)
        history = self.get_history(backend_job_id)
        if history is None:
            raise BackendFailure("output_missing", "ComfyUI history has no completed output.")
        descriptor = self._find_video_descriptor(history.get("outputs"))
        if descriptor is None:
            raise BackendFailure("output_missing", "ComfyUI history contains no video output.")
        filename = descriptor.get("filename")
        subfolder = descriptor.get("subfolder", "")
        output_type = descriptor.get("type", "output")
        if not isinstance(filename, str) or Path(filename).name != filename or Path(filename).suffix.lower() not in ALLOWED_VIDEO_SUFFIXES:
            raise BackendFailure("unsupported_output_contract", "ComfyUI returned an unsafe or unsupported video filename.")
        if not isinstance(subfolder, str) or ".." in Path(subfolder).parts or Path(subfolder).is_absolute():
            raise BackendFailure("unsupported_output_contract", "ComfyUI returned an unsafe output subfolder.")
        query = urlencode({"filename": filename, "subfolder": subfolder, "type": output_type})
        content = self.client.bytes("/view?" + query)
        if not content:
            raise BackendFailure("output_missing", "ComfyUI returned an empty video output.")
        media_type = "video/mp4" if Path(filename).suffix.lower() == ".mp4" else "video/webm"
        metrics = self._metrics(job)
        return BackendResult(
            filename=filename,
            media_type=media_type,
            content=content,
            metadata={
                "mock": False,
                "output_classification": "comfyui_local_video",
                "prompt_id": backend_job_id,
                "workflow_sha256": job["workflow_sha256"],
                "execution_profile": dict(job["profile"]),
                "metrics": metrics,
            },
        )

    @classmethod
    def _find_video_descriptor(cls, outputs: Any) -> dict[str, Any] | None:
        if not isinstance(outputs, dict):
            return None
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            for key in ("video", "videos", "gifs", "files", "images"):
                candidates = output.get(key)
                if isinstance(candidates, dict):
                    candidates = [candidates]
                if not isinstance(candidates, list):
                    continue
                for candidate in candidates:
                    if isinstance(candidate, dict) and Path(str(candidate.get("filename", ""))).suffix.lower() in ALLOWED_VIDEO_SUFFIXES:
                        return candidate
        return None

    def get_result(self, backend_job_id: str) -> BackendResult:
        return self.collect_result(backend_job_id)

    def cancel_job(self, backend_job_id: str) -> dict[str, Any]:
        job = self._require_job(backend_job_id)
        if job["status"] == "queued":
            self.client.json("POST", "/queue", {"delete": [backend_job_id]})
            job["status"] = "cancelled"
            return {"status": "cancelled", "scope": "queued_prompt"}
        if job["status"] == "running":
            self.client.json("POST", "/interrupt", {})
            job["status"] = "cancelled"
            return {"status": "cancelled", "scope": "running_prompt"}
        return {"status": "unsupported", "reason": "generation_not_active"}

    def normalize_error(self, error: BaseException) -> BackendFailure:
        if isinstance(error, BackendFailure):
            return error
        if isinstance(error, TimeoutError):
            return BackendFailure("timeout", "The ComfyUI H3 job timed out.", True)
        if isinstance(error, MemoryError):
            return BackendFailure("out_of_memory", "The ComfyUI H3 job ran out of memory.")
        return BackendFailure("generation_failed", "The local ComfyUI H3 job failed.", True)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        prompt_id = fields.get("backend_job_id")
        job = self._jobs.get(prompt_id) if isinstance(prompt_id, str) else None
        workflow = self.inspect_workflow()
        runtime = self.inspect_runtime()
        return {
            "receipt_version": "p0.comfyui.local.1",
            "backend": self.name,
            "backend_display_name": self.display_name,
            "model_contract": self.model,
            "mock": False,
            "network_scope": "loopback_only",
            "external_api_call_count": 0,
            "model_download_count": 0,
            "workflow_logical_id": workflow.get("workflow_logical_id"),
            "workflow_sha256": workflow.get("workflow_sha256"),
            "execution_profile": workflow.get("execution_profile"),
            "configuration": self.config.public_status(),
            "runtime": {
                key: runtime.get(key)
                for key in ("comfyui_version", "python_version", "pytorch_version", "device_name", "device_type", "vram_total_bytes")
            },
            "metrics": self._metrics(job) if job is not None else self._unsupported_metrics("job_metrics_unavailable"),
            "policy_state": dict(MINIMAX_POLICY_STATE),
            **fields,
        }

    def public_status(self) -> dict[str, Any]:
        assets = self.inspect_assets()
        workflow = self.inspect_workflow()
        if assets["state"] != "ready" or workflow["state"] != "ready":
            reason = assets.get("reason") if assets["state"] != "ready" else workflow.get("reason")
            return {
                "name": self.name,
                "display_name": self.display_name,
                "state": "unavailable",
                "selectable": True,
                "can_generate": False,
                "message": "Local H3 — ComfyUI unavailable",
                "reason": reason,
                "execution_profile": workflow.get("execution_profile"),
                "configuration": self.config.public_status(),
            }
        runtime = self.inspect_runtime()
        can_generate = runtime["state"] == assets["state"] == workflow["state"] == "ready"
        state = "ready" if can_generate else "unavailable"
        reason = next((item.get("reason") for item in (runtime, assets, workflow) if item.get("state") != "ready"), None)
        return {
            "name": self.name,
            "display_name": self.display_name,
            "state": state,
            "selectable": True,
            "can_generate": can_generate,
            "message": "Local H3 — ComfyUI ready" if can_generate else "Local H3 — ComfyUI unavailable",
            "reason": reason,
            "execution_profile": workflow.get("execution_profile"),
            "configuration": self.config.public_status(),
        }

    def _require_job(self, backend_job_id: str) -> dict[str, Any]:
        job = self._jobs.get(backend_job_id)
        if job is None:
            raise BackendFailure("output_missing", "The ComfyUI H3 job is unknown.")
        return job

    def _sample_resources(self, backend_job_id: str | None) -> None:
        try:
            system = self.client.json("GET", "/system_stats")
        except BackendFailure:
            return
        if backend_job_id is None:
            return
        job = self._jobs.get(backend_job_id)
        if job is None:
            return
        sys_info = system.get("system", {}) if isinstance(system, dict) else {}
        devices = system.get("devices", []) if isinstance(system, dict) else []
        device = devices[0] if isinstance(devices, list) and devices and isinstance(devices[0], dict) else {}
        vram_total = device.get("vram_total")
        vram_free = device.get("vram_free")
        ram_total = sys_info.get("ram_total")
        ram_free = sys_info.get("ram_free")
        used_vram = vram_total - vram_free if isinstance(vram_total, int) and isinstance(vram_free, int) else None
        used_ram = ram_total - ram_free if isinstance(ram_total, int) and isinstance(ram_free, int) else None
        if used_vram is not None:
            job["peak_vram_bytes"] = max(job["peak_vram_bytes"] or 0, used_vram)
        if used_ram is not None:
            job["peak_host_ram_bytes"] = max(job["peak_host_ram_bytes"] or 0, used_ram)
        job["sample_count"] += 1

    @staticmethod
    def _unsupported_metric(reason: str) -> dict[str, Any]:
        return {"value": None, "support_status": "not_collected", "reason": reason}

    @classmethod
    def _unsupported_metrics(cls, reason: str) -> dict[str, Any]:
        return {
            "queue_wait_seconds": cls._unsupported_metric(reason),
            "generation_wall_seconds": cls._unsupported_metric(reason),
            "total_wall_seconds": cls._unsupported_metric(reason),
            "model_load_seconds": cls._unsupported_metric("ComfyUI history does not isolate model loading."),
            "peak_vram_bytes": cls._unsupported_metric(reason),
            "peak_host_ram_bytes": cls._unsupported_metric(reason),
        }

    @classmethod
    def _metrics(cls, job: Mapping[str, Any] | None) -> dict[str, Any]:
        if job is None:
            return cls._unsupported_metrics("job_metrics_unavailable")
        submitted = job.get("submitted_perf")
        running = job.get("first_running_perf")
        completed = job.get("completed_perf")
        queue_wait = running - submitted if isinstance(running, float) and isinstance(submitted, float) else None
        generation = completed - running if isinstance(completed, float) and isinstance(running, float) else None
        total = completed - submitted if isinstance(completed, float) and isinstance(submitted, float) else None

        def measured(value: Any, unit: str, method: str) -> dict[str, Any]:
            if value is None:
                return cls._unsupported_metric("Required timestamps or samples were not collected.")
            return {"value": value, "unit": unit, "support_status": "collected", "measurement_method": method}

        return {
            "submitted_at": job.get("submitted_at"),
            "first_running_at": job.get("first_running_at"),
            "completed_at": job.get("completed_at"),
            "queue_wait_seconds": measured(queue_wait, "seconds", "client monotonic span"),
            "generation_wall_seconds": measured(generation, "seconds", "client monotonic running-to-terminal span"),
            "total_wall_seconds": measured(total, "seconds", "client monotonic submit-to-terminal span"),
            "model_load_seconds": cls._unsupported_metric("ComfyUI history does not isolate model loading from execution."),
            "peak_vram_bytes": measured(job.get("peak_vram_bytes"), "bytes", "ComfyUI system_stats system-sampled device usage"),
            "peak_host_ram_bytes": measured(job.get("peak_host_ram_bytes"), "bytes", "ComfyUI system_stats system-wide RAM usage"),
            "resource_sample_count": job.get("sample_count", 0),
            "retry_count": job.get("retry_count", 0),
        }

    @staticmethod
    def _history_error_message(history: Mapping[str, Any]) -> str:
        status = history.get("status")
        messages = status.get("messages", []) if isinstance(status, dict) else []
        for message in reversed(messages if isinstance(messages, list) else []):
            if isinstance(message, (list, tuple)) and len(message) > 1 and message[0] == "execution_error":
                detail = message[1]
                if isinstance(detail, dict):
                    text = detail.get("exception_message") or detail.get("exception_type")
                    if isinstance(text, str) and text:
                        return text[:500]
        return "ComfyUI reported an execution failure."
