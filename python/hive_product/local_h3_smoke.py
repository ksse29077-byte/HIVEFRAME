"""Run exactly one P0 Local H3 ComfyUI product smoke from environment input.

The prompt and all local paths remain environment-only. The public repository
contains the runner contract, never a user prompt or machine-specific path.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import sys
import threading
import time

from .comfyui_backend import MiniMaxH3ComfyUIBackend
from .server import create_server
from .service import ProductService


def _decode_video(path: Path) -> dict:
    """Decode every video frame using the runtime's local PyAV installation."""
    try:
        import av
    except ImportError as error:
        raise RuntimeError("PyAV is required for the P0 output decode gate") from error
    decoded = 0
    first_width = None
    first_height = None
    with av.open(str(path)) as container:
        streams = list(container.streams.video)
        if not streams:
            raise RuntimeError("generated artifact has no video stream")
        stream = streams[0]
        codec = stream.codec_context.name
        average_rate = float(stream.average_rate) if stream.average_rate is not None else None
        for frame in container.decode(stream):
            decoded += 1
            first_width = first_width or frame.width
            first_height = first_height or frame.height
    if decoded == 0:
        raise RuntimeError("generated video stream decoded zero frames")
    return {
        "decode_succeeded": True,
        "decoded_frame_count": decoded,
        "width": first_width,
        "height": first_height,
        "fps": average_rate,
        "codec": codec,
    }


def _json_request(base_url: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=30) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("product API did not return an object")
    return value


def main() -> int:
    prompt = os.environ.get("HIVEFRAME_H3_SMOKE_PROMPT", "").strip()
    if not prompt:
        raise SystemExit("HIVEFRAME_H3_SMOKE_PROMPT is required")
    backend = MiniMaxH3ComfyUIBackend()
    server = None
    server_thread = None
    summary: dict = {
        "run_kind": "p0_local_h3_comfyui_smoke",
        "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
        "external_api_call_count": 0,
        "model_download_count": 0,
        "workflow_submission_count": 0,
        "feedback_created": False,
    }
    exit_code = 1
    try:
        summary["runtime_start"] = backend.start_runtime()
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow = backend.inspect_workflow()
        summary["preflight"] = {"runtime": runtime, "assets": assets, "workflow": workflow}
        if any(value.get("state") != "ready" for value in (runtime, assets, workflow)):
            raise RuntimeError("Local H3 ComfyUI preflight did not reach ready")

        service = ProductService(comfyui_backend=backend)
        server = create_server(service, port=0)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        job = _json_request(
            base_url,
            "/api/jobs",
            {
                "backend": "minimax_h3_comfyui_local",
                "prompt": prompt,
                "resolution": "768P",
                "duration_seconds": 4,
                "ratio": "16:9",
                "profile": "standard",
                "generation_consent": True,
            },
        )
        summary["product_job_create_count"] = 1
        summary["job_id"] = job["job_id"]
        observed = [job["status"]]
        deadline = time.monotonic() + backend.poll_timeout_seconds + 30.0
        while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.5)
            job = _json_request(base_url, f"/api/jobs/{job['job_id']}")
            if job.get("backend_job_id"):
                summary["workflow_submission_count"] = 1
            if observed[-1] != job["status"]:
                observed.append(job["status"])
        summary["observed_product_states"] = observed
        summary["terminal_status"] = job["status"]
        summary["backend_prompt_id"] = job.get("backend_job_id")
        summary["error_code"] = job.get("error_code")
        summary["error_message"] = job.get("error_message")
        if job["status"] != "succeeded":
            raise RuntimeError("Local H3 product smoke did not succeed")

        metadata, result_path = service.result_asset(job["job_id"])
        receipt_metadata, receipt_path = service.store.get_asset(job["receipt_id"])
        result_bytes = result_path.read_bytes()
        if not result_bytes:
            raise RuntimeError("Local H3 product result is empty")
        decode = _decode_video(result_path)
        summary.update(
            {
                "result": {
                    "asset_id": metadata["asset_id"],
                    "filename": metadata["filename"],
                    "media_type": metadata["media_type"],
                    "size_bytes": metadata["size_bytes"],
                    "sha256": metadata["sha256"],
                    "private_path": str(result_path),
                },
                "receipt": {
                    "asset_id": receipt_metadata["asset_id"],
                    "sha256": receipt_metadata["sha256"],
                    "private_path": str(receipt_path),
                },
                "result_download_verified": True,
                "decode": decode,
            }
        )
        exit_code = 0
    except Exception as error:  # preserve a private partial receipt for every failure
        summary["runner_error"] = type(error).__name__
        summary["runner_error_message"] = str(error)[:1_000]
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if server_thread is not None:
            server_thread.join(timeout=5)
        try:
            summary["runtime_stop"] = backend.stop_runtime()
        except Exception as error:
            summary["runtime_stop"] = {"status": "failed", "error": type(error).__name__}
        output_root = backend.config.output_root
        if output_root is not None:
            runtime_root = output_root / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            summary_path = runtime_root / "hiveframe-p0-h3-smoke-summary.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        public = {
            "run_kind": summary["run_kind"],
            "terminal_status": summary.get("terminal_status", "failed"),
            "observed_product_states": summary.get("observed_product_states", []),
            "workflow_submission_count": summary["workflow_submission_count"],
            "result_sha256": summary.get("result", {}).get("sha256"),
            "result_size_bytes": summary.get("result", {}).get("size_bytes"),
            "decode_succeeded": summary.get("decode", {}).get("decode_succeeded", False),
            "decoded_frame_count": summary.get("decode", {}).get("decoded_frame_count"),
            "runner_error": summary.get("runner_error"),
        }
        print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
