"""Bounded F0 SageAttention KJ probe for the existing Local H3 backend.

The public module contains only the workflow mutation and runner contract.
Prompts, machine paths, full receipts, logs, and generated media stay in a
repository-external run root supplied at execution time.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import json
import re
import sqlite3
import sys
import time

from .comfyui_backend import BackendFailure, MiniMaxH3ComfyUIBackend
from .service import ProductService


SAGE_NODE_CLASS = "PathchSageAttentionKJ"
SAGE_NODE_ID = "15"
STANDARD_MODEL_NODE_ID = "1"
MODEL_CONSUMERS = ("6", "9")
SAFE_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


def _unsupported(reason: str, method: str = "ComfyUI history and logs") -> dict[str, Any]:
    return {
        "value": None,
        "unit": "seconds",
        "support_status": "not_collected",
        "reason": reason,
        "measurement_method": method,
    }


def apply_sageattention_auto(standard_workflow: Mapping[str, Any]) -> dict[str, Any]:
    """Return a Sage copy with one patch node on the shared MODEL edge."""
    workflow = deepcopy(dict(standard_workflow))
    if SAGE_NODE_ID in workflow:
        raise ValueError(f"workflow node {SAGE_NODE_ID} is already occupied")
    if any(
        isinstance(node, Mapping) and node.get("class_type") == SAGE_NODE_CLASS
        for node in workflow.values()
    ):
        raise ValueError("workflow already contains a SageAttention KJ node")
    expected_edge = [STANDARD_MODEL_NODE_ID, 0]
    for consumer_id in MODEL_CONSUMERS:
        consumer = workflow.get(consumer_id)
        if not isinstance(consumer, dict) or consumer.get("inputs", {}).get("model") != expected_edge:
            raise ValueError(f"unexpected MODEL edge at node {consumer_id}")
    workflow[SAGE_NODE_ID] = {
        "class_type": SAGE_NODE_CLASS,
        "inputs": {
            "model": expected_edge,
            "sage_attention": "auto",
            "allow_compile": False,
        },
    }
    for consumer_id in MODEL_CONSUMERS:
        workflow[consumer_id]["inputs"]["model"] = [SAGE_NODE_ID, 0]
    return workflow


def workflow_patch_summary(standard: Mapping[str, Any], sage: Mapping[str, Any]) -> dict[str, Any]:
    """Describe and validate the only permitted F0 workflow difference."""
    expected = apply_sageattention_auto(standard)
    if dict(sage) != expected:
        raise ValueError("Sage workflow differs from the declared one-node patch")
    standard_sage_nodes = sum(
        isinstance(node, Mapping) and node.get("class_type") == SAGE_NODE_CLASS
        for node in standard.values()
    )
    sage_sage_nodes = sum(
        isinstance(node, Mapping) and node.get("class_type") == SAGE_NODE_CLASS
        for node in sage.values()
    )
    return {
        "standard_sage_node_count": standard_sage_nodes,
        "sage_sage_node_count": sage_sage_nodes,
        "patch_node_id": SAGE_NODE_ID,
        "patch_node_class": SAGE_NODE_CLASS,
        "patch_mode": "auto",
        "allow_compile": False,
        "input_model_edge": [STANDARD_MODEL_NODE_ID, 0],
        "rewired_model_consumers": list(MODEL_CONSUMERS),
    }


class SageAttentionAutoComfyUIBackend(MiniMaxH3ComfyUIBackend):
    """F0-only adapter variant; the Standard backend remains unchanged."""

    def inspect_runtime(self) -> dict[str, Any]:
        status = super().inspect_runtime()
        if status.get("state") != "ready":
            return status
        try:
            objects = self.client.json("GET", "/object_info")
        except BackendFailure:
            return {**status, "state": "runtime_incompatible", "reason": "sage_node_query_failed"}
        node = objects.get(SAGE_NODE_CLASS) if isinstance(objects, dict) else None
        choices = node.get("input", {}).get("required", {}).get("sage_attention") if isinstance(node, dict) else None
        options = choices[0] if isinstance(choices, list) and choices else []
        if not isinstance(node, dict) or not isinstance(options, list) or "auto" not in options:
            return {**status, "state": "runtime_incompatible", "reason": "sage_auto_unavailable"}
        return {**status, "sage_node_class": SAGE_NODE_CLASS, "sage_auto_available": True}

    def build_api_workflow(self, generation_request: Mapping[str, Any], *, output_prefix: str) -> dict[str, Any]:
        standard = super().build_api_workflow(generation_request, output_prefix=output_prefix)
        return apply_sageattention_auto(standard)

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        receipt = super().build_receipt(**fields)
        receipt["external_acceleration"] = {
            "provider": "SageAttention KJ",
            "mode": "auto",
            "node_class": SAGE_NODE_CLASS,
            "candidate_only": True,
            "promoted": False,
            "standard_fallback_available": True,
        }
        return receipt


def _load_private_prompt(database: Path) -> tuple[str, str]:
    if not database.is_file():
        raise ValueError("private P0 database is unavailable")
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT prompt FROM jobs WHERE backend = ? AND status = ? ORDER BY created_at",
            ("minimax_h3_comfyui_local", "succeeded"),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0].strip():
        raise ValueError("private P0 database must contain exactly one successful Local H3 prompt")
    prompt = rows[0][0].strip()
    return prompt, sha256(prompt.encode("utf-8")).hexdigest()


def _decode_video(path: Path) -> dict[str, Any]:
    try:
        import av
        import numpy as np
    except ImportError as error:
        raise RuntimeError("PyAV and NumPy are required for the F0 integrity gate") from error
    frame_count = 0
    black_frames = 0
    width = height = None
    fps = None
    codec = None
    audio_streams = 0
    with av.open(str(path)) as container:
        video_streams = list(container.streams.video)
        audio_streams = len(list(container.streams.audio))
        if len(video_streams) != 1:
            raise RuntimeError("F0 output must contain exactly one video stream")
        stream = video_streams[0]
        codec = stream.codec_context.name
        fps = float(stream.average_rate) if stream.average_rate is not None else None
        for frame in container.decode(stream):
            pixels = frame.to_ndarray(format="gray")
            frame_count += 1
            width = frame.width
            height = frame.height
            black_frames += int(float(np.mean(pixels)) <= 1.0)
    if frame_count == 0:
        raise RuntimeError("F0 output decoded zero frames")
    return {
        "decode_succeeded": True,
        "decoded_frame_count": frame_count,
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": frame_count / fps if fps else None,
        "codec": codec,
        "audio_stream_count": audio_streams,
        "black_frame_count": black_frames,
        "black_output_detected": black_frames == frame_count,
        "corrupted_frame_count": 0,
        "serious_flicker_indicator": {
            "value": None,
            "support_status": "not_collected",
            "reason": "No new perceptual flicker evaluator is admitted for the bounded F0 probe.",
        },
    }


def _safe_run_root(root: Path, run_id: str) -> Path:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run ID must be a safe lowercase identifier")
    resolved = root.resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise ValueError("private run root already contains artifacts")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _read_receipt(service: ProductService, receipt_id: str) -> tuple[dict[str, Any], Path]:
    _, path = service.store.get_asset(receipt_id)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("stored receipt is not a JSON object")
    return value, path


def run_probe(*, mode: str, run_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    backend: MiniMaxH3ComfyUIBackend
    backend = SageAttentionAutoComfyUIBackend() if mode == "sage-auto" else MiniMaxH3ComfyUIBackend()
    started_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    summary: dict[str, Any] = {
        "schema_version": "f0.sage.probe.1",
        "run_id": run_id,
        "mode": mode,
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 1,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "started_at": started_at,
        "phase_metrics": {
            "model_load_seconds": _unsupported("ComfyUI does not isolate model loading from this workflow."),
            "denoising_seconds": _unsupported("ComfyUI history does not expose a denoising-only span."),
            "average_step_seconds": _unsupported("Per-step timestamps are not exposed by the runtime history."),
            "median_step_seconds": _unsupported("Per-step timestamps are not exposed by the runtime history."),
            "vae_video_decode_seconds": _unsupported("ComfyUI history does not expose a VAE-video-decode span."),
            "vae_audio_decode_seconds": _unsupported("ComfyUI history does not expose a VAE-audio-decode span."),
            "encoding_seconds": _unsupported("ComfyUI history does not expose an encode-only span."),
        },
    }
    service: ProductService | None = None
    try:
        startup = time.perf_counter()
        summary["runtime_start"] = backend.start_runtime()
        summary["phase_metrics"]["runtime_startup_seconds"] = {
            "value": time.perf_counter() - startup,
            "unit": "seconds",
            "support_status": "collected",
            "measurement_method": "runner monotonic span",
        }
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow = backend.inspect_workflow()
        summary["preflight"] = {"runtime": runtime, "assets": assets, "workflow": workflow}
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow)):
            raise RuntimeError("F0 Local H3 preflight did not reach ready")
        service = ProductService(artifact_root=root / "product-artifacts", comfyui_backend=backend)
        job = service.create_job(
            {
                "backend": "minimax_h3_comfyui_local",
                "prompt": prompt,
                "resolution": "768P",
                "duration_seconds": 4,
                "ratio": "16:9",
                "profile": "standard",
                "generation_consent": True,
            }
        )
        summary["product_job_id"] = job["job_id"]
        job = service.execute_job(job["job_id"])
        summary["terminal_status"] = job["status"]
        summary["backend_prompt_id"] = job.get("backend_job_id")
        summary["error_code"] = job.get("error_code")
        if job["status"] != "succeeded":
            if job.get("receipt_id"):
                summary["partial_receipt_id"] = job["receipt_id"]
            raise RuntimeError("F0 Local H3 generation did not succeed")
        metadata, result_path = service.result_asset(job["job_id"])
        receipt, receipt_path = _read_receipt(service, job["receipt_id"])
        integrity = _decode_video(result_path)
        if integrity["decoded_frame_count"] != 124 or (integrity["width"], integrity["height"]) != (864, 480):
            raise RuntimeError("F0 output does not match the fixed frame and resolution contract")
        if integrity["black_output_detected"] or integrity["audio_stream_count"] < 1:
            raise RuntimeError("F0 output failed the black-output or native-audio integrity gate")
        summary.update(
            {
                "receipt": receipt,
                "receipt_private_path": str(receipt_path),
                "result": {
                    "private_path": str(result_path),
                    "logical_artifact_id": f"F0_{mode.upper().replace('-', '_')}_VIDEO",
                    "sha256": metadata["sha256"],
                    "size_bytes": metadata["size_bytes"],
                    "media_type": metadata["media_type"],
                },
                "integrity": integrity,
            }
        )
    except Exception as error:
        summary["runner_error"] = type(error).__name__
        summary["runner_error_message"] = str(error)[:1000]
    finally:
        collection_done = time.perf_counter()
        try:
            summary["runtime_stop"] = backend.stop_runtime()
        except Exception as error:
            summary["runtime_stop"] = {"status": "failed", "error": type(error).__name__}
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["phase_metrics"]["runner_total_seconds"] = {
            "value": time.perf_counter() - started_perf,
            "unit": "seconds",
            "support_status": "collected",
            "measurement_method": "runner entry through owned-runtime stop",
        }
        summary["phase_metrics"]["setup_execution_collection_seconds"] = {
            "value": collection_done - started_perf,
            "unit": "seconds",
            "support_status": "collected",
            "measurement_method": "runner entry through result collection",
        }
        path = root / "f0-private-run-summary.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        summary["private_summary_path"] = str(path)
    return summary


def _public_result(summary: Mapping[str, Any]) -> dict[str, Any]:
    receipt = summary.get("receipt") if isinstance(summary.get("receipt"), Mapping) else {}
    metrics = receipt.get("metrics") if isinstance(receipt, Mapping) else {}
    result = summary.get("result") if isinstance(summary.get("result"), Mapping) else {}
    return {
        "run_id": summary.get("run_id"),
        "mode": summary.get("mode"),
        "terminal_status": summary.get("terminal_status", "failed"),
        "prompt_sha256": summary.get("prompt_sha256"),
        "backend_prompt_id": summary.get("backend_prompt_id"),
        "metrics": metrics,
        "integrity": summary.get("integrity"),
        "result_sha256": result.get("sha256"),
        "result_size_bytes": result.get("size_bytes"),
        "runner_error": summary.get("runner_error"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Local H3 Standard or SageAttention F0 probe.")
    parser.add_argument("--mode", required=True, choices=("standard", "sage-auto"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = run_probe(
        mode=args.mode,
        run_id=args.run_id,
        p0_database=args.p0_database,
        private_run_root=args.private_run_root,
    )
    print(json.dumps(_public_result(summary), ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("terminal_status") == "succeeded" and not summary.get("runner_error") else 1


if __name__ == "__main__":
    sys.exit(main())
