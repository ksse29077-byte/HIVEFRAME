"""One-submit local LTX-Video 2B FP8 admission probe."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import argparse
import json
import os
import subprocess
import threading
import time
import uuid


REQUIRED_NODES = {
    "CheckpointLoaderSimple",
    "CLIPLoader",
    "CLIPTextEncode",
    "LoadImage",
    "LTXVImgToVideo",
    "LTXVConditioning",
    "LTXVScheduler",
    "KSamplerSelect",
    "SamplerCustom",
    "VAEDecode",
    "CreateVideo",
    "SaveVideo",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != "ltx.video.2b.fp8.admission.1":
        raise ValueError("unsupported LTX admission schema")
    profile = config["profile"]
    budget = config["execution_budget"]
    if profile["mode"] != "I2V" or (profile["width"], profile["height"]) != (768, 512):
        raise ValueError("the fixed I2V admission profile changed")
    if profile["frames"] != 33 or profile["fps"] != 24.0 or profile["steps"] != 8:
        raise ValueError("the fixed frame/FPS/step profile changed")
    if profile["guidance"] != 1.0 or profile["stg"] is not False:
        raise ValueError("distilled guidance contract changed")
    for key in ("maximum_product_or_test_jobs", "maximum_backend_submissions", "maximum_generations"):
        if budget[key] != 1:
            raise ValueError(f"unbounded admission budget: {key}")
    for key in ("retry_count", "fallback_count", "wan_downloads_or_runs"):
        if budget[key] != 0:
            raise ValueError(f"forbidden admission action: {key}")


def validate_private_prompt(config: Mapping[str, Any], prompt: str, negative_prompt: str) -> None:
    if sha256_bytes(prompt) != config["profile"]["prompt_sha256"]:
        raise ValueError("private prompt does not match the approved digest")
    if sha256_bytes(negative_prompt) != config["profile"]["negative_prompt_sha256"]:
        raise ValueError("private negative prompt does not match the approved digest")


def build_workflow(
    config: Mapping[str, Any], *, input_name: str, output_prefix: str, prompt: str, negative_prompt: str
) -> dict[str, Any]:
    validate_private_prompt(config, prompt, negative_prompt)
    profile = config["profile"]
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": config["model"]["filename"]}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": config["text_encoder"]["filename"], "type": "ltxv", "device": "default"},
        },
        "3": {"class_type": "LoadImage", "inputs": {"image": input_name}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["2", 0]}},
        "6": {
            "class_type": "LTXVImgToVideo",
            "inputs": {
                "positive": ["4", 0],
                "negative": ["5", 0],
                "vae": ["1", 2],
                "image": ["3", 0],
                "width": profile["width"],
                "height": profile["height"],
                "length": profile["frames"],
                "batch_size": profile["batch_size"],
                "strength": profile["image_strength"],
            },
        },
        "7": {
            "class_type": "LTXVConditioning",
            "inputs": {"positive": ["6", 0], "negative": ["6", 1], "frame_rate": profile["fps"]},
        },
        "8": {
            "class_type": "LTXVScheduler",
            "inputs": {
                "steps": profile["steps"],
                "max_shift": profile["max_shift"],
                "base_shift": profile["base_shift"],
                "stretch": profile["stretch"],
                "terminal": profile["terminal"],
                "latent": ["6", 2],
            },
        },
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": profile["sampler"]}},
        "10": {
            "class_type": "SamplerCustom",
            "inputs": {
                "model": ["1", 0],
                "add_noise": True,
                "noise_seed": profile["seed"],
                "cfg": profile["guidance"],
                "positive": ["7", 0],
                "negative": ["7", 1],
                "sampler": ["9", 0],
                "sigmas": ["8", 0],
                "latent_image": ["6", 2],
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": profile["fps"]}},
        "13": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["12", 0], "filename_prefix": output_prefix, "format": "mp4", "codec": "auto"},
        },
    }


class LoopbackClient:
    def __init__(self, base_url: str, timeout_seconds: float = 30.0) -> None:
        if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("LTX admission requires a loopback ComfyUI URL")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def json(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self.base_url + path, data=payload, method=method)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def bytes(self, path: str) -> tuple[int, bytes]:
        with urlopen(self.base_url + path, timeout=self.timeout_seconds) as response:
            return int(response.status), response.read()


def queue_counts(queue: Mapping[str, Any]) -> tuple[int, int]:
    return len(queue.get("queue_running") or []), len(queue.get("queue_pending") or [])


def prompt_in_queue(entries: Any, prompt_id: str) -> bool:
    return any(isinstance(row, list) and prompt_id in row for row in (entries or []))


def assert_idle_twice(client: LoopbackClient, delay_seconds: float = 0.5) -> list[dict[str, int]]:
    snapshots = []
    for index in range(2):
        running, pending = queue_counts(client.json("GET", "/queue"))
        snapshots.append({"running": running, "pending": pending})
        if running or pending:
            raise RuntimeError(f"shared ComfyUI is busy: running={running}, pending={pending}")
        if index == 0:
            time.sleep(delay_seconds)
    return snapshots


def verify_file(path: Path, expected_bytes: int, expected_sha256: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise ValueError(f"size mismatch for {path.name}: {actual_bytes} != {expected_bytes}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ValueError(f"SHA-256 mismatch for {path.name}")
    return {"filename": path.name, "bytes": actual_bytes, "sha256": actual_sha256}


def inspect_admission(client: LoopbackClient, config: Mapping[str, Any], input_name: str) -> dict[str, Any]:
    stats = client.json("GET", "/system_stats")
    objects = client.json("GET", "/object_info")
    missing_nodes = sorted(REQUIRED_NODES - objects.keys())
    checkpoint_names = objects.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
    clip_names = objects.get("CLIPLoader", {}).get("input", {}).get("required", {}).get("clip_name", [[]])[0]
    image_names = objects.get("LoadImage", {}).get("input", {}).get("required", {}).get("image", [[]])[0]
    blockers = []
    if missing_nodes:
        blockers.append("missing_nodes:" + ",".join(missing_nodes))
    if config["model"]["filename"] not in checkpoint_names:
        blockers.append("checkpoint_not_discoverable")
    if config["text_encoder"]["filename"] not in clip_names:
        blockers.append("text_encoder_not_discoverable")
    if input_name not in image_names:
        blockers.append("private_input_not_discoverable")
    return {"system_stats": stats, "missing_nodes": missing_nodes, "blockers": blockers}


@dataclass
class ResourceSampler:
    client: LoopbackClient
    interval_seconds: float = 0.5
    samples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ltx-resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            sample: dict[str, Any] = {"monotonic": time.perf_counter()}
            try:
                stats = self.client.json("GET", "/system_stats")
                system = stats.get("system") or {}
                device = (stats.get("devices") or [{}])[0]
                sample["system_ram_used_bytes"] = system.get("ram_total", 0) - system.get("ram_free", 0)
                sample["system_vram_used_bytes"] = device.get("vram_total", 0) - device.get("vram_free", 0)
            except Exception as error:
                self.errors.append(f"system_stats:{type(error).__name__}:{error}")
            try:
                output = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                    text=True,
                    timeout=5.0,
                ).strip()
                utilization, used_mib = [int(item.strip()) for item in output.split(",")]
                sample.update({"gpu_utilization_percent": utilization, "nvidia_used_vram_mib": used_mib})
            except Exception as error:
                self.errors.append(f"nvidia_smi:{type(error).__name__}:{error}")
            self.samples.append(sample)
            self._stop.wait(self.interval_seconds)

    def summary(self) -> dict[str, Any]:
        def peak(name: str) -> int | None:
            values = [row[name] for row in self.samples if isinstance(row.get(name), int)]
            return max(values) if values else None

        util = [row["gpu_utilization_percent"] for row in self.samples if isinstance(row.get("gpu_utilization_percent"), int)]
        return {
            "sample_count": len(self.samples),
            "peak_system_ram_used_bytes": peak("system_ram_used_bytes"),
            "peak_system_vram_used_bytes": peak("system_vram_used_bytes"),
            "peak_nvidia_used_vram_mib": peak("nvidia_used_vram_mib"),
            "peak_gpu_utilization_percent": max(util) if util else None,
            "mean_gpu_utilization_percent": (sum(util) / len(util)) if util else None,
            "errors": self.errors,
        }


def find_video_descriptor(outputs: Any) -> dict[str, Any] | None:
    if isinstance(outputs, Mapping):
        if isinstance(outputs.get("filename"), str) and outputs.get("type") in {"output", "temp"}:
            return dict(outputs)
        for value in outputs.values():
            found = find_video_descriptor(value)
            if found:
                return found
    elif isinstance(outputs, list):
        for value in outputs:
            found = find_video_descriptor(value)
            if found:
                return found
    return None


def analyze_video(path: Path, contact_sheet_path: Path) -> dict[str, Any]:
    import av
    import numpy as np
    from PIL import Image, ImageDraw

    container = av.open(str(path))
    video_streams = list(container.streams.video)
    audio_streams = list(container.streams.audio)
    if not video_streams:
        raise ValueError("video stream missing")
    stream = video_streams[0]
    width, height = stream.width, stream.height
    codec = stream.codec_context.name
    fps = float(stream.average_rate) if stream.average_rate else None
    frames, black, duplicates, previous, decode_errors = [], 0, 0, None, []
    try:
        for frame in container.decode(video=0):
            array = frame.to_ndarray(format="rgb24")
            if float(array.mean()) <= 2.0:
                black += 1
            if previous is not None and float(np.abs(array.astype(np.int16) - previous.astype(np.int16)).mean()) <= 0.5:
                duplicates += 1
            previous = array
            frames.append(array)
    except Exception as error:
        decode_errors.append(f"{type(error).__name__}:{error}")
    finally:
        container.close()

    selected = sorted({0, len(frames) // 4, len(frames) // 2, (3 * len(frames)) // 4, max(len(frames) - 1, 0)})
    selected = [index for index in selected if 0 <= index < len(frames)]
    if selected:
        thumbs = [Image.fromarray(frames[index]).resize((384, 256)) for index in selected]
        sheet = Image.new("RGB", (384 * len(thumbs), 286), "white")
        draw = ImageDraw.Draw(sheet)
        for column, (index, thumb) in enumerate(zip(selected, thumbs, strict=True)):
            sheet.paste(thumb, (column * 384, 0))
            draw.text((column * 384 + 8, 264), f"frame {index}", fill="black")
        sheet.save(contact_sheet_path)

    decoded = len(frames)
    return {
        "container": path.suffix.lstrip(".").lower(),
        "codec": codec,
        "width": width,
        "height": height,
        "decoded_frame_count": decoded,
        "fps": fps,
        "duration_seconds": (decoded / fps) if fps else None,
        "audio_stream_count": len(audio_streams),
        "black_frame_count": black,
        "corrupt_frame_count": len(decode_errors),
        "decode_errors": decode_errors,
        "adjacent_duplicate_frame_count": duplicates,
        "adjacent_duplicate_frame_ratio": duplicates / max(decoded - 1, 1),
        "file_bytes": path.stat().st_size,
        "contact_sheet_created": contact_sheet_path.is_file(),
    }


def integrity_passed(metrics: Mapping[str, Any], gate: Mapping[str, Any], http_status: int) -> bool:
    return bool(
        metrics.get("container") == gate["container"]
        and metrics.get("codec") in {gate["codec"], "libx264"}
        and metrics.get("width") == gate["width"]
        and metrics.get("height") == gate["height"]
        and metrics.get("decoded_frame_count") == gate["frames"]
        and abs(float(metrics.get("fps") or 0.0) - float(gate["fps"])) < 0.01
        and metrics.get("black_frame_count") <= gate["maximum_black_frames"]
        and metrics.get("corrupt_frame_count") <= gate["maximum_corrupt_frames"]
        and metrics.get("file_bytes", 0) > 0
        and http_status == 200
    )


def decide(receipt: Mapping[str, Any]) -> str:
    counters = receipt["counters"]
    submit_to_terminal = (receipt.get("timings") or {}).get("submit_to_terminal_seconds")
    if receipt.get("blocked_before_submit"):
        return "LTX_ADMISSION_BLOCKED"
    if (
        receipt.get("terminal_status") == "succeeded"
        and receipt.get("output_integrity_passed") is True
        and counters["backend_submission_count"] == 1
        and counters["gpu_execution_started_count"] == 1
        and counters["completed_count"] == 1
        and isinstance(submit_to_terminal, (int, float))
        and submit_to_terminal <= receipt["admission_stop_seconds"]
        and all(counters[key] == 0 for key in ("retry_count", "fallback_count", "external_api_call_count", "external_job_termination_count", "oom_count"))
    ):
        return "LTX_ADMISSION_READY_FOR_FORMAL_H3_COMPARISON"
    return "LTX_ADMISSION_FAILED"


def public_projection(value: Any) -> Any:
    private_keys = {
        "private_path",
        "private_run_root",
        "prompt",
        "negative_prompt",
        "input_path",
        "result_url",
        "workflow",
        "system_stats",
        "prompt_id",
    }
    if isinstance(value, Mapping):
        return {key: public_projection(item) for key, item in value.items() if key not in private_keys}
    if isinstance(value, list):
        return [public_projection(item) for item in value]
    return value


def run_admission(
    *,
    config: Mapping[str, Any],
    input_path: Path,
    model_path: Path,
    text_encoder_path: Path,
    private_run_root: Path,
    prompt: str,
    negative_prompt: str,
) -> dict[str, Any]:
    validate_private_prompt(config, prompt, negative_prompt)
    if private_run_root.exists() and any(private_run_root.iterdir()):
        raise ValueError("private LTX admission root already contains artifacts")
    private_run_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    receipt: dict[str, Any] = {
        "schema_version": "ltx.video.2b.fp8.admission.private.1",
        "started_at": utc_now(),
        "private_run_root": str(private_run_root),
        "input_path": str(input_path),
        "profile": {key: value for key, value in config["profile"].items() if "source" not in key},
        "counters": {
            "product_or_test_job_create_count": 1,
            "backend_submission_count": 0,
            "gpu_execution_started_count": 0,
            "completed_count": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "external_api_call_count": 0,
            "external_job_termination_count": 0,
            "oom_count": 0,
        },
        "lifecycle": [],
        "blocked_before_submit": False,
        "admission_stop_seconds": config["execution_budget"]["submit_to_terminal_stop_seconds"],
    }
    receipt_path = private_run_root / "private-receipt.json"
    client = LoopbackClient(config["runtime"]["base_url"])
    sampler: ResourceSampler | None = None
    submit_at = running_at = terminal_at = None
    try:
        receipt["file_verification"] = {
            "model": verify_file(model_path, config["model"]["bytes"], config["model"]["sha256"]),
            "text_encoder": verify_file(
                text_encoder_path, config["text_encoder"]["bytes"], config["text_encoder"]["sha256"]
            ),
            "input_sha256": sha256_file(input_path),
        }
        if receipt["file_verification"]["input_sha256"] != config["profile"]["input_sha256"]:
            raise ValueError("private input SHA-256 does not match the approved P1 evidence")
        receipt["idle_gate"] = assert_idle_twice(client)
        inspection = inspect_admission(client, config, input_path.name)
        receipt["runtime_inspection"] = inspection
        if inspection["blockers"]:
            receipt["blocked_before_submit"] = True
            raise RuntimeError(";".join(inspection["blockers"]))

        output_prefix = "hiveframe/ltx-admission-" + sha256(
            f"{config['profile']['seed']}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:16]
        workflow = build_workflow(
            config,
            input_name=input_path.name,
            output_prefix=output_prefix,
            prompt=prompt,
            negative_prompt=negative_prompt,
        )
        receipt["workflow"] = workflow
        receipt["workflow_sha256"] = sha256(json.dumps(workflow, sort_keys=True).encode("utf-8")).hexdigest()
        sampler = ResourceSampler(client)
        sampler.start()
        submit_at = time.perf_counter()
        response = client.json("POST", "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
        receipt["counters"]["backend_submission_count"] = 1
        prompt_id = response.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise RuntimeError(f"ComfyUI rejected the prompt: {response}")
        receipt["prompt_id"] = prompt_id
        receipt["node_errors"] = response.get("node_errors") or {}
        receipt["lifecycle"].append({"state": "queued", "at": utc_now(), "seconds_from_submit": 0.0})

        observation_deadline = submit_at + max(
            1800.0, float(config["execution_budget"]["submit_to_terminal_stop_seconds"])
        )
        history: dict[str, Any] | None = None
        while time.perf_counter() < observation_deadline:
            now = time.perf_counter()
            queue = client.json("GET", "/queue")
            if prompt_in_queue(queue.get("queue_running"), prompt_id) and running_at is None:
                running_at = now
                receipt["counters"]["gpu_execution_started_count"] = 1
                receipt["lifecycle"].append(
                    {"state": "running", "at": utc_now(), "seconds_from_submit": running_at - submit_at}
                )
            history_response = client.json("GET", "/history/" + prompt_id)
            entry = history_response.get(prompt_id)
            if isinstance(entry, Mapping):
                status = entry.get("status") or {}
                if status.get("completed") is True or status.get("status_str") in {"error", "failed"}:
                    history = dict(entry)
                    terminal_at = now
                    break
            time.sleep(0.25)
        if history is None:
            raise TimeoutError("terminal history was not observed; the probe did not interrupt the prompt")
        status = history.get("status") or {}
        terminal_status = (
            "succeeded" if status.get("completed") is True and status.get("status_str") == "success" else "failed"
        )
        receipt["terminal_status"] = terminal_status
        receipt["history_status"] = status
        receipt["lifecycle"].append(
            {"state": terminal_status, "at": utc_now(), "seconds_from_submit": terminal_at - submit_at}
        )
        if terminal_status != "succeeded":
            error_text = json.dumps(status, ensure_ascii=False)
            if "out of memory" in error_text.lower() or "cuda oom" in error_text.lower():
                receipt["counters"]["oom_count"] = 1
            raise RuntimeError("ComfyUI generation failed: " + error_text)

        receipt["counters"]["completed_count"] = 1
        descriptor = find_video_descriptor(history.get("outputs"))
        if descriptor is None:
            raise RuntimeError("ComfyUI succeeded without a video descriptor")
        query = urlencode(
            {"filename": descriptor["filename"], "subfolder": descriptor.get("subfolder", ""), "type": descriptor["type"]}
        )
        result_url = "/view?" + query
        http_status, content = client.bytes(result_url)
        output_path = private_run_root / Path(descriptor["filename"]).name
        output_path.write_bytes(content)
        contact_sheet_path = private_run_root / "contact-sheet.png"
        integrity = analyze_video(output_path, contact_sheet_path)
        receipt["result"] = {
            "private_path": str(output_path),
            "result_url": client.base_url + result_url,
            "local_result_http_status": http_status,
            "downloadable": http_status == 200 and len(content) > 0,
            "sha256": sha256(content).hexdigest(),
        }
        receipt["integrity"] = integrity
        receipt["output_integrity_passed"] = integrity_passed(integrity, config["integrity_gate"], http_status)
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
        if receipt["counters"]["backend_submission_count"] == 0:
            receipt["blocked_before_submit"] = True
        if "out of memory" in str(error).lower() or "cuda oom" in str(error).lower():
            receipt["counters"]["oom_count"] = 1
        receipt.setdefault(
            "terminal_status", "failed" if receipt["counters"]["backend_submission_count"] else "not_submitted"
        )
        receipt.setdefault("output_integrity_passed", False)
    finally:
        if sampler is not None:
            sampler.stop()
            receipt["resources"] = sampler.summary()
        finished = time.perf_counter()
        receipt["timings"] = {
            "model_loading_seconds": None,
            "model_loading_reason": "ComfyUI HTTP lifecycle does not expose loader-only wall time",
            "queue_wait_seconds": (running_at - submit_at) if submit_at is not None and running_at is not None else None,
            "submit_to_running_seconds": (running_at - submit_at) if submit_at is not None and running_at is not None else None,
            "running_to_terminal_seconds": (terminal_at - running_at) if terminal_at is not None and running_at is not None else None,
            "submit_to_terminal_seconds": (terminal_at - submit_at) if terminal_at is not None and submit_at is not None else None,
            "admission_e2e_seconds": finished - started,
            "output_file_creation_seconds": None,
            "output_file_creation_reason": "not separately exposed by ComfyUI",
            "video_encoding_seconds": None,
            "video_encoding_reason": "not separately exposed by ComfyUI",
            "temperature": "cold LTX model load; shared ComfyUI process already running",
        }
        receipt["decision"] = decide(receipt)
        receipt["finished_at"] = utc_now()
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--text-encoder", type=Path, required=True)
    parser.add_argument("--private-run-root", type=Path, required=True)
    args = parser.parse_args()
    prompt = os.environ.get("HIVEFRAME_LTX_PROMPT", "")
    negative_prompt = os.environ.get("HIVEFRAME_LTX_NEGATIVE_PROMPT", "")
    receipt = run_admission(
        config=load_config(args.config),
        input_path=args.input,
        model_path=args.model,
        text_encoder_path=args.text_encoder,
        private_run_root=args.private_run_root,
        prompt=prompt,
        negative_prompt=negative_prompt,
    )
    print(json.dumps(public_projection(receipt), ensure_ascii=False, indent=2))
    return 0 if receipt["decision"] == "LTX_ADMISSION_READY_FOR_FORMAL_H3_COMPARISON" else 2


if __name__ == "__main__":
    raise SystemExit(main())
