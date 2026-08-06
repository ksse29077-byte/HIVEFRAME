"""C0 Local H3 execution-phase telemetry without ComfyUI core patches.

The module keeps public evidence aggregate-only.  The full WebSocket stream,
resource samples, runtime log, prompt, generated media, and private receipt
belong in the repository-external run root supplied by the operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from typing import Any, Mapping
from urllib.parse import urlencode, urlparse
import argparse
import asyncio
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

from .comfyui_backend import MiniMaxH3ComfyUIBackend
from .sageattention_probe import SAGE_NODE_CLASS, _load_private_prompt


C0_SCHEMA_VERSION = "c0.h3.phase.1"
HISTORICAL_STANDARD_SUBMIT_SECONDS = 586.9724998
SAFE_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
TERMINAL_EVENTS = {"execution_success", "execution_error", "execution_interrupted"}
HOOK_STATES = {
    "observable_now",
    "controllable_now",
    "requires_custom_node",
    "requires_runtime_wrapper",
    "requires_comfyui_core_patch",
    "not_found",
    "unsafe",
}

NODE_ROLES = {
    "1": ("diffusion model loader", "model_and_encoder_loading", True, True),
    "2": ("text encoder loader", "model_and_encoder_loading", True, True),
    "3": ("video VAE loader", "model_and_encoder_loading", True, True),
    "4": ("audio VAE loader", "model_and_encoder_loading", True, True),
    "5": ("deterministic noise", "prompt_conditioning", False, True),
    "6": ("scheduler preparation", "prompt_conditioning", False, True),
    "7": ("sampler selection", "prompt_conditioning", False, True),
    "8": ("MiniMax H3 text conditioning and AV latent", "prompt_conditioning", True, False),
    "9": ("guider preparation", "prompt_conditioning", False, True),
    "10": ("denoising sampler", "denoising", True, True),
    "11": ("video VAE decode", "vae_video_decode", False, True),
    "12": ("audio VAE decode", "vae_audio_decode", True, False),
    "13": ("video assembly", "encoding", False, True),
    "14": ("MP4 encode and save", "encoding", False, True),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def unsupported(reason: str, method: str, *, unit: str = "seconds", scope: str = "runtime") -> dict[str, Any]:
    return {
        "value": None,
        "unit": unit,
        "scope": scope,
        "support_status": "unavailable",
        "unsupported_reason": reason,
        "measurement_method": method,
    }


def measured(value: float | int, unit: str, method: str, *, scope: str, aggregation: str = "single") -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "scope": scope,
        "support_status": "collected",
        "unsupported_reason": None,
        "measurement_method": method,
        "aggregation": aggregation,
    }


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def validate_hook_map(hooks: list[Mapping[str, Any]]) -> None:
    required = {
        "hook_id",
        "status",
        "h3_specific",
        "backend_independent",
        "expected_overhead",
        "data_copied",
        "gpu_synchronization",
        "cache_candidate",
        "invalidation_required",
        "full_compute_fallback",
        "rust_ffi_fit",
        "compound_eye_connection",
    }
    for hook in hooks:
        missing = required - hook.keys()
        if missing:
            raise ValueError(f"hook map entry is incomplete: {sorted(missing)}")
        if hook["status"] not in HOOK_STATES:
            raise ValueError(f"unsupported hook status: {hook['status']}")


@dataclass
class EventTimeline:
    workflow: Mapping[str, Mapping[str, Any]]
    prompt_id: str | None = None
    submitted_monotonic: float | None = None
    current_node: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    progress: list[dict[str, Any]] = field(default_factory=list)
    node_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    terminal_event: str | None = None
    terminal_monotonic: float | None = None
    parser_wall_seconds: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        for node_id, node in self.workflow.items():
            logical, phase, h3_specific, backend_independent = NODE_ROLES.get(
                str(node_id), ("unclassified", "unattributed", False, False)
            )
            self.node_state[str(node_id)] = {
                "node_id": str(node_id),
                "class_type": node.get("class_type"),
                "logical_role": logical,
                "phase": phase,
                "start_monotonic": None,
                "end_monotonic": None,
                "cached": False,
                "output_observed": False,
                "error_observed": False,
                "gpu_related": str(node_id) in {"1", "2", "3", "4", "8", "10", "11", "12", "13"},
                "h3_specific": h3_specific,
                "backend_independent": backend_independent,
            }

    def active_context(self) -> dict[str, Any]:
        with self._lock:
            latest = self.progress[-1] if self.progress else None
            return {
                "node_id": self.current_node,
                "step": latest.get("value") if latest and latest.get("node_id") == self.current_node else None,
                "step_max": latest.get("max") if latest and latest.get("node_id") == self.current_node else None,
            }

    def ingest(self, message: Mapping[str, Any], received_monotonic: float) -> bool:
        started = time.perf_counter()
        event_type = message.get("type")
        data = message.get("data")
        if not isinstance(event_type, str) or not isinstance(data, Mapping):
            return False
        event_prompt = data.get("prompt_id")
        if self.prompt_id and event_prompt not in {None, self.prompt_id}:
            return False
        compact = {
            "type": event_type,
            "received_at": _utc_now(),
            "monotonic_seconds_since_submit": (
                received_monotonic - self.submitted_monotonic
                if self.submitted_monotonic is not None
                else None
            ),
            "data": {
                key: data.get(key)
                for key in ("prompt_id", "node", "display_node", "value", "max", "node_id", "node_type")
                if key in data
            },
        }
        with self._lock:
            self.events.append(compact)
            if event_type == "execution_cached":
                for node_id in data.get("nodes", []) if isinstance(data.get("nodes"), list) else []:
                    if str(node_id) in self.node_state:
                        self.node_state[str(node_id)]["cached"] = True
            elif event_type == "executing":
                self._close_current(received_monotonic)
                node_id = data.get("node")
                self.current_node = str(node_id) if node_id is not None else None
                if self.current_node in self.node_state:
                    self.node_state[self.current_node]["start_monotonic"] = received_monotonic
            elif event_type == "progress":
                self.progress.append(
                    {
                        "node_id": str(data.get("node")) if data.get("node") is not None else self.current_node,
                        "value": data.get("value"),
                        "max": data.get("max"),
                        "received_monotonic": received_monotonic,
                    }
                )
            elif event_type == "executed":
                node_id = str(data.get("node")) if data.get("node") is not None else self.current_node
                if node_id in self.node_state:
                    self.node_state[node_id]["output_observed"] = True
            elif event_type in {"execution_error", "execution_interrupted"}:
                node_id = str(data.get("node_id")) if data.get("node_id") is not None else self.current_node
                if node_id in self.node_state:
                    self.node_state[node_id]["error_observed"] = True
            if event_type in TERMINAL_EVENTS:
                self._close_current(received_monotonic)
                self.terminal_event = event_type
                self.terminal_monotonic = received_monotonic
        self.parser_wall_seconds += time.perf_counter() - started
        return event_type in TERMINAL_EVENTS

    def _close_current(self, now: float) -> None:
        if self.current_node in self.node_state:
            state = self.node_state[self.current_node]
            if state["start_monotonic"] is not None and state["end_monotonic"] is None:
                state["end_monotonic"] = now

    def node_timeline(self) -> list[dict[str, Any]]:
        result = []
        for node_id in sorted(self.node_state, key=lambda item: int(item) if item.isdigit() else item):
            state = dict(self.node_state[node_id])
            start = state.pop("start_monotonic")
            end = state.pop("end_monotonic")
            state["start_seconds_since_submit"] = (
                start - self.submitted_monotonic if start is not None and self.submitted_monotonic is not None else None
            )
            state["end_seconds_since_submit"] = (
                end - self.submitted_monotonic if end is not None and self.submitted_monotonic is not None else None
            )
            state["observed_wall_seconds"] = end - start if start is not None and end is not None else None
            state["measurement_method"] = "WebSocket executing boundary"
            state["support_status"] = "collected" if state["observed_wall_seconds"] is not None else "not_observed"
            result.append(state)
        return result

    def progress_summary(self) -> dict[str, Any]:
        records = [item for item in self.progress if isinstance(item.get("value"), int) and isinstance(item.get("max"), int)]
        intervals: list[float] = []
        if records:
            node_start = self.node_state.get(str(records[0].get("node_id")), {}).get("start_monotonic")
            previous = node_start
            for item in records:
                current = item["received_monotonic"]
                if previous is not None and current >= previous:
                    intervals.append(current - previous)
                previous = current
        public_records = [
            {
                "node_id": item.get("node_id"),
                "value": item.get("value"),
                "max": item.get("max"),
                "seconds_since_submit": item["received_monotonic"] - self.submitted_monotonic
                if self.submitted_monotonic is not None
                else None,
            }
            for item in records
        ]
        return {
            "semantic": "observed_progress_interval",
            "not_claimed_as": "exact GPU denoising step duration",
            "records": public_records,
            "interval_count": len(intervals),
            "mean_seconds": mean(intervals) if intervals else None,
            "median_seconds": median(intervals) if intervals else None,
            "p90_seconds": percentile(intervals, 0.90),
            "first_seconds": intervals[0] if intervals else None,
            "last_seconds": intervals[-1] if intervals else None,
            "measurement_method": "client receive timestamps for ComfyUI progress events",
        }

    def phase_attribution(
        self,
        *,
        runner_total_seconds: float,
        runtime_startup_seconds: float,
        result_collection_seconds: float,
        shutdown_seconds: float,
    ) -> dict[str, Any]:
        buckets = {
            "model_and_encoder_loading": 0.0,
            "prompt_conditioning": 0.0,
            "denoising": 0.0,
            "vae_video_decode": 0.0,
            "vae_audio_decode": 0.0,
            "encoding": 0.0,
        }
        for node in self.node_timeline():
            duration = node.get("observed_wall_seconds")
            phase = node.get("phase")
            if isinstance(duration, (float, int)) and phase in buckets:
                buckets[phase] += float(duration)
        measured_union = runtime_startup_seconds + result_collection_seconds + shutdown_seconds + sum(buckets.values())
        unattributed = max(0.0, runner_total_seconds - measured_union)

        def row(seconds: float, confidence: str, method: str, note: str | None = None) -> dict[str, Any]:
            return {
                "seconds": seconds,
                "percentage_of_runner_total": seconds / runner_total_seconds * 100 if runner_total_seconds else None,
                "confidence": confidence,
                "measurement_method": method,
                "note": note,
            }

        phases = {
            "runtime_startup": row(runtime_startup_seconds, "high", "runner monotonic launch-to-API-ready span"),
            "model_and_encoder_loading": row(
                buckets["model_and_encoder_loading"],
                "medium",
                "WebSocket loader-node boundaries",
                "This covers loader-node setup only; lazy materialization and CPU/GPU transfer may occur inside the sampler span.",
            ),
            "prompt_conditioning": row(buckets["prompt_conditioning"], "medium", "WebSocket node boundaries"),
            "denoising": row(
                buckets["denoising"],
                "medium",
                "SamplerCustomAdvanced WebSocket node boundary",
                "The span includes lazy model materialization and sampler orchestration; it is not GPU-kernel-only time.",
            ),
            "vae_video_decode": row(buckets["vae_video_decode"], "medium", "VAEDecode node boundary"),
            "vae_audio_decode": row(buckets["vae_audio_decode"], "medium", "VAEDecodeAudio node boundary"),
            "encoding": row(buckets["encoding"], "medium", "CreateVideo and SaveVideo node boundaries"),
            "result_collection": row(result_collection_seconds, "high", "runner monotonic terminal-to-verified-result span"),
            "runtime_shutdown": row(shutdown_seconds, "high", "runner monotonic owned-runtime stop span"),
            "unattributed": row(
                unattributed,
                "high",
                "runner total minus union of non-overlapping observed spans",
                "Includes queue gaps and setup/finalization not represented by another phase.",
            ),
        }
        return {
            "scope": "runner entry through owned runtime stop",
            "runner_total_seconds": runner_total_seconds,
            "submit_to_terminal_seconds": (
                self.terminal_monotonic - self.submitted_monotonic
                if self.terminal_monotonic is not None and self.submitted_monotonic is not None
                else None
            ),
            "phases": phases,
            "non_overlapping_union_seconds": measured_union,
            "unattributed_seconds": unattributed,
        }


class ResourceSampler:
    def __init__(self, backend: MiniMaxH3ComfyUIBackend, timeline: EventTimeline, interval_seconds: float = 1.0) -> None:
        self.backend = backend
        self.timeline = timeline
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self.query_wall_seconds = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hiveframe-c0-resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self.interval_seconds * 3))

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.perf_counter()
            sample = self._sample()
            self.query_wall_seconds += time.perf_counter() - started
            self.samples.append(sample)
            self._stop.wait(self.interval_seconds)

    def _sample(self) -> dict[str, Any]:
        sample: dict[str, Any] = {
            "timestamp": _utc_now(),
            "monotonic": time.monotonic(),
            **self.timeline.active_context(),
            "scope": {"vram": "system-wide sampled", "ram": "system-wide sampled", "rss": "process-tree sampled"},
        }
        try:
            stats = self.backend.client.json("GET", "/system_stats")
        except Exception as error:
            sample["system_stats_error"] = type(error).__name__
            stats = {}
        system = stats.get("system", {}) if isinstance(stats, Mapping) else {}
        devices = stats.get("devices", []) if isinstance(stats, Mapping) else []
        device = devices[0] if isinstance(devices, list) and devices and isinstance(devices[0], Mapping) else {}
        for target, total_name, free_name in (
            ("gpu_vram", "vram_total", "vram_free"),
            ("system_ram", "ram_total", "ram_free"),
        ):
            source = device if target == "gpu_vram" else system
            total = source.get(total_name)
            free = source.get(free_name)
            sample[f"{target}_total_bytes"] = total if isinstance(total, int) else None
            sample[f"{target}_free_bytes"] = free if isinstance(free, int) else None
            sample[f"{target}_used_bytes"] = total - free if isinstance(total, int) and isinstance(free, int) else None
        sample.update(self._nvidia_sample())
        sample.update(self._rss_sample())
        return sample

    @staticmethod
    def _nvidia_sample() -> dict[str, Any]:
        executable = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
        try:
            result = subprocess.run(
                [executable, "--query-gpu=memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
            return {
                "nvidia_vram_used_bytes": int(parts[0]) * 1024 * 1024,
                "nvidia_vram_free_bytes": int(parts[1]) * 1024 * 1024,
                "nvidia_gpu_utilization_percent": int(parts[2]),
            }
        except Exception as error:
            return {
                "nvidia_vram_used_bytes": None,
                "nvidia_vram_free_bytes": None,
                "nvidia_gpu_utilization_percent": None,
                "nvidia_sample_error": type(error).__name__,
            }

    def _rss_sample(self) -> dict[str, Any]:
        process = self.backend._process
        if process is None:
            return {"main_process_rss_bytes": None, "child_process_rss_bytes": None, "process_tree_rss_bytes": None}
        try:
            import psutil

            root = psutil.Process(process.pid)
            main = root.memory_info().rss
            children = sum(child.memory_info().rss for child in root.children(recursive=True) if child.is_running())
            return {
                "main_process_rss_bytes": main,
                "child_process_rss_bytes": children,
                "process_tree_rss_bytes": main + children,
            }
        except Exception as error:
            return {
                "main_process_rss_bytes": None,
                "child_process_rss_bytes": None,
                "process_tree_rss_bytes": None,
                "process_rss_error": type(error).__name__,
            }

    def summary(self) -> dict[str, Any]:
        def maximum(name: str) -> int | None:
            values = [sample.get(name) for sample in self.samples if isinstance(sample.get(name), int)]
            return max(values) if values else None

        return {
            "sample_interval_seconds": self.interval_seconds,
            "sample_count": len(self.samples),
            "sampling_query_wall_seconds_total": self.query_wall_seconds,
            "peak_comfyui_system_sampled_vram_bytes": maximum("gpu_vram_used_bytes"),
            "peak_nvidia_system_sampled_vram_bytes": maximum("nvidia_vram_used_bytes"),
            "peak_system_wide_used_ram_bytes": maximum("system_ram_used_bytes"),
            "peak_process_tree_rss_bytes": maximum("process_tree_rss_bytes"),
            "peak_gpu_utilization_percent": maximum("nvidia_gpu_utilization_percent"),
            "torch_allocator_peak": unsupported(
                "The runner is outside the ComfyUI process and cannot read its PyTorch allocator peak safely.",
                "separate-process observation",
                unit="bytes",
                scope="allocator-level",
            ),
            "measurement_note": "All peaks above are sampled, not exact allocator peaks.",
        }


def sanitize_public(value: Any) -> Any:
    if isinstance(value, Mapping):
        blocked_keys = {"private_path", "prompt", "command", "database", "asset_root", "comfyui_root", "output_root"}
        return {key: sanitize_public(item) for key, item in value.items() if key not in blocked_keys}
    if isinstance(value, list):
        return [sanitize_public(item) for item in value]
    if isinstance(value, str) and (re.search(r"[A-Za-z]:[\\/]", value) or re.search(r"/(home|Users)/[^/]+", value)):
        return "<private-path>"
    return value


def _safe_run_root(root: Path, run_id: str) -> Path:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run ID must be a safe lowercase identifier")
    resolved = root.resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("private C0 run root already contains artifacts")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _decode_video(path: Path) -> dict[str, Any]:
    try:
        import av
    except ImportError as error:
        raise RuntimeError("PyAV is required for the C0 decode gate") from error
    frames = 0
    width = height = None
    fps = None
    codec = None
    audio_streams = 0
    with av.open(str(path)) as container:
        video_streams = list(container.streams.video)
        audio_streams = len(list(container.streams.audio))
        if len(video_streams) != 1:
            raise RuntimeError("C0 output must contain exactly one video stream")
        stream = video_streams[0]
        codec = stream.codec_context.name
        fps = float(stream.average_rate) if stream.average_rate is not None else None
        for frame in container.decode(stream):
            frames += 1
            width = frame.width
            height = frame.height
    return {
        "decode_succeeded": frames > 0,
        "decoded_frame_count": frames,
        "width": width,
        "height": height,
        "fps": fps,
        "codec": codec,
        "audio_stream_count": audio_streams,
    }


def _history_video(backend: MiniMaxH3ComfyUIBackend, history: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    descriptor = backend._find_video_descriptor(history.get("outputs"))
    if descriptor is None:
        raise RuntimeError("ComfyUI history contains no video output")
    filename = descriptor.get("filename")
    subfolder = descriptor.get("subfolder", "")
    output_type = descriptor.get("type", "output")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise RuntimeError("ComfyUI returned an unsafe output filename")
    query = urlencode({"filename": filename, "subfolder": subfolder, "type": output_type})
    content = backend.client.bytes("/view?" + query)
    if not content:
        raise RuntimeError("ComfyUI returned an empty output")
    return dict(descriptor), content


async def _collect_websocket_run(
    backend: MiniMaxH3ComfyUIBackend,
    workflow: Mapping[str, Mapping[str, Any]],
    timeline: EventTimeline,
) -> tuple[str, Mapping[str, Any]]:
    try:
        import aiohttp
    except ImportError as error:
        raise RuntimeError("The installed ComfyUI runtime lacks aiohttp WebSocket support") from error
    base = urlparse(backend.config.base_url)
    client_id = "hiveframe-c0-" + uuid.uuid4().hex
    websocket_url = f"ws://{base.hostname}:{base.port}/ws?clientId={client_id}"
    timeout = aiohttp.ClientTimeout(total=backend.poll_timeout_seconds + 60.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(websocket_url, autoping=True, heartbeat=30.0) as websocket:
            timeline.submitted_monotonic = time.monotonic()
            response = backend.client.json("POST", "/prompt", {"prompt": workflow, "client_id": client_id})
            prompt_id = response.get("prompt_id") if isinstance(response, Mapping) else None
            if not isinstance(prompt_id, str) or not prompt_id:
                raise RuntimeError("ComfyUI did not return a prompt ID")
            timeline.prompt_id = prompt_id
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(message.data)
                    if isinstance(payload, Mapping) and timeline.ingest(payload, time.monotonic()):
                        break
                elif message.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                    raise RuntimeError("ComfyUI WebSocket closed before a terminal event")
    history = backend.get_history(prompt_id)
    if history is None:
        raise RuntimeError("ComfyUI history is unavailable after terminal event")
    return prompt_id, history


def run_probe(*, run_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    backend = MiniMaxH3ComfyUIBackend()
    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": C0_SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": "c0_standard_instrumented",
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "standard_full_compute": True,
        "full_compute_fallback": True,
    }
    timeline: EventTimeline | None = None
    sampler: ResourceSampler | None = None
    startup_seconds = result_collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        startup = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow_status = backend.inspect_workflow()
        receipt["preflight"] = {"runtime": runtime, "assets": assets, "workflow": workflow_status}
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C0 Local H3 preflight did not reach ready")
        if workflow_status.get("workflow_sha256") != "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6":
            raise RuntimeError("approved Standard workflow hash changed")
        generation_request = {"content": [{"type": "text", "text": prompt}]}
        workflow = backend.build_api_workflow(generation_request, output_prefix=f"hiveframe/c0-{prompt_hash[:16]}")
        sage_count = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        receipt["sage_node_count"] = sage_count
        if sage_count != 0:
            raise RuntimeError("C0 Standard workflow contains a Sage node")
        profile = workflow_status.get("execution_profile")
        receipt["execution_profile"] = profile
        expected_profile = {
            "width": 864,
            "height": 480,
            "frame_count": 124,
            "fps": 24,
            "steps": 20,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "denoise": 1.0,
            "seed": 101,
        }
        if not isinstance(profile, Mapping) or any(profile.get(key) != value for key, value in expected_profile.items()):
            raise RuntimeError("C0 Standard execution profile changed")
        timeline = EventTimeline(workflow)
        sampler = ResourceSampler(backend, timeline, interval_seconds=1.0)
        sampler.start()
        receipt["generation_attempt_count"] = 1
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        receipt["backend_prompt_id"] = prompt_id
        collection = time.monotonic()
        descriptor, content = _history_video(backend, history)
        output = root / "c0-standard-instrumented.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        result_collection_seconds = time.monotonic() - collection
        if (
            decode["decoded_frame_count"] != 124
            or (decode["width"], decode["height"]) != (864, 480)
            or decode["fps"] != 24.0
            or decode["audio_stream_count"] < 1
        ):
            raise RuntimeError("C0 output failed the fixed video integrity contract")
        receipt["result"] = {
            "logical_artifact_id": "C0_STANDARD_INSTRUMENTED_VIDEO",
            "private_path": str(output),
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "decode": decode,
        }
        exit_code = 0
    except Exception as error:
        receipt["runner_error"] = type(error).__name__
        receipt["runner_error_message"] = str(error)[:1000]
    finally:
        if sampler is not None:
            sampler.stop()
        shutdown = time.monotonic()
        try:
            receipt["runtime_stop"] = backend.stop_runtime()
        except Exception as error:
            receipt["runtime_stop"] = {"status": "failed", "error": type(error).__name__}
        shutdown_seconds = time.monotonic() - shutdown
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"),
            "result_collection_seconds": measured(result_collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "model_materialization_seconds": unsupported(
                "Lazy model materialization overlaps the sampler node and has no independent start/end event.",
                "WebSocket events plus installed-source inspection",
            ),
            "torch_gpu_kernel_seconds": unsupported(
                "No profiler run was authorized; WebSocket and sampled metrics do not measure GPU kernel duration.",
                "not collected",
                scope="GPU kernel",
            ),
        }
        if timeline is not None:
            receipt["websocket_event_types"] = sorted({event["type"] for event in timeline.events})
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["phase_attribution"] = timeline.phase_attribution(
                runner_total_seconds=runner_total,
                runtime_startup_seconds=startup_seconds,
                result_collection_seconds=result_collection_seconds,
                shutdown_seconds=shutdown_seconds,
            )
            receipt["instrumentation"] = {
                "websocket_parser_wall_seconds": timeline.parser_wall_seconds,
                "resource_sampler": sampler.summary() if sampler is not None else None,
            }
            (root / "websocket-events.jsonl").write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in timeline.events),
                encoding="utf-8",
            )
        if sampler is not None:
            (root / "resource-samples.json").write_text(
                json.dumps(sampler.samples, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        submit = receipt.get("phase_attribution", {}).get("submit_to_terminal_seconds")
        receipt["historical_comparison"] = {
            "historical_standard_submit_seconds": HISTORICAL_STANDARD_SUBMIT_SECONDS,
            "instrumented_submit_seconds": submit,
            "relative_change_percent": (
                (submit / HISTORICAL_STANDARD_SUBMIT_SECONDS - 1.0) * 100 if isinstance(submit, (int, float)) else None
            ),
            "single_run_only": True,
            "performance_baseline_eligible": bool(
                isinstance(submit, (int, float))
                and abs((submit / HISTORICAL_STANDARD_SUBMIT_SECONDS - 1.0) * 100) <= 5.0
            ),
        }
        receipt["exit_code"] = exit_code
        private_receipt = root / "c0-private-receipt.json"
        private_receipt.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        public = sanitize_public(receipt)
        (root / "c0-public-summary.json").write_text(
            json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    phase = receipt.get("phase_attribution") if isinstance(receipt.get("phase_attribution"), Mapping) else {}
    resources = receipt.get("instrumentation", {}).get("resource_sampler", {}) if isinstance(receipt.get("instrumentation"), Mapping) else {}
    return sanitize_public(
        {
            "schema_version": receipt.get("schema_version"),
            "run_id": receipt.get("run_id"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "sage_node_count": receipt.get("sage_node_count"),
            "prompt_sha256": receipt.get("prompt_sha256"),
            "backend_prompt_id": receipt.get("backend_prompt_id"),
            "phase_attribution": phase,
            "node_timeline": receipt.get("node_timeline"),
            "progress_timeline": receipt.get("progress_timeline"),
            "metrics": receipt.get("metrics"),
            "resources": resources,
            "historical_comparison": receipt.get("historical_comparison"),
            "result_sha256": result.get("sha256"),
            "result_size_bytes": result.get("size_bytes"),
            "decode": result.get("decode"),
            "runner_error": receipt.get("runner_error"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exactly one instrumented Standard Local H3 C0 generation.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = run_probe(run_id=args.run_id, p0_database=args.p0_database, private_run_root=args.private_run_root)
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
