"""One-shot CONTROL or SELECTIVE C3-R1 frozen-replay Local H3 probe."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import asyncio
import copy
import json
import os
import sys
import time

from .c0_h3_phase_probe import (
    EventTimeline,
    ResourceSampler,
    _collect_websocket_run,
    _history_video,
    _safe_run_root,
    measured,
    sanitize_public,
    unsupported,
)
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .frozen_block_selective import (
    BLOCK_COUNT,
    CANDIDATE_BLOCKS,
    CONTROL,
    FROZEN_SCHEDULE,
    SELECTIVE,
    THEORETICAL_OPPORTUNITY,
    frozen_settings_digest,
)
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "c3-r1.h3.frozen-block-bypass.1"
APPROVED_WORKFLOW_SHA256 = "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6"
MODEL_REVISION_DIGEST = "882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024"
NODE_CLASS = "HIVEFRAMEH3FrozenBlockSelectiveSampler"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_c3_r1_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    workflow_revision_digest: str,
    settings_digest: str,
    model_revision_digest: str,
    actual_block_bypass_enabled: bool,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C3-R1 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C3-R1 sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update(
        {
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "actual_block_bypass_enabled": bool(actual_block_bypass_enabled),
        }
    )
    return workflow


def compare_videos(control_path: Path, selective_path: Path) -> dict[str, Any]:
    try:
        import av
        import numpy as np
    except ImportError as error:
        raise RuntimeError("PyAV and NumPy are required for the C3-R1 quality gate") from error

    ssim_values: list[float] = []
    mae_values: list[float] = []
    control_motion: list[float] = []
    selective_motion: list[float] = []
    previous_control = previous_selective = None
    with av.open(str(control_path)) as control, av.open(str(selective_path)) as selective:
        control_stream = list(control.streams.video)
        selective_stream = list(selective.streams.video)
        if len(control_stream) != 1 or len(selective_stream) != 1:
            raise RuntimeError("C3-R1 quality comparison requires one video stream per artifact")
        control_frames = control.decode(control_stream[0])
        selective_frames = selective.decode(selective_stream[0])
        while True:
            left = next(control_frames, None)
            right = next(selective_frames, None)
            if left is None or right is None:
                if left is not None or right is not None:
                    raise RuntimeError("C3-R1 videos have different decoded frame counts")
                break
            a = left.to_ndarray(format="gray").astype(np.float64)
            b = right.to_ndarray(format="gray").astype(np.float64)
            if a.shape != b.shape:
                raise RuntimeError("C3-R1 videos have different frame shapes")
            mean_a = float(np.mean(a))
            mean_b = float(np.mean(b))
            centered_a = a - mean_a
            centered_b = b - mean_b
            var_a = float(np.mean(centered_a * centered_a))
            var_b = float(np.mean(centered_b * centered_b))
            covariance = float(np.mean(centered_a * centered_b))
            c1 = (0.01 * 255.0) ** 2
            c2 = (0.03 * 255.0) ** 2
            denominator = (mean_a * mean_a + mean_b * mean_b + c1) * (var_a + var_b + c2)
            ssim_values.append(
                ((2 * mean_a * mean_b + c1) * (2 * covariance + c2) / denominator)
                if denominator
                else 1.0
            )
            mae_values.append(float(np.mean(np.abs(a - b))) / 255.0)
            if previous_control is not None and previous_selective is not None:
                control_motion.append(float(np.mean(np.abs(a - previous_control))))
                selective_motion.append(float(np.mean(np.abs(b - previous_selective))))
            previous_control = a
            previous_selective = b
    if not ssim_values:
        raise RuntimeError("C3-R1 quality comparison decoded zero paired frames")
    ordered = sorted(ssim_values)
    p05 = ordered[max(0, int(len(ordered) * 0.05) - 1)]
    control_energy = sum(control_motion) / len(control_motion) if control_motion else 0.0
    selective_energy = sum(selective_motion) / len(selective_motion) if selective_motion else 0.0
    motion_ratio = selective_energy / control_energy if control_energy > 0 else None
    low_rate = sum(value < 0.75 for value in ssim_values) / len(ssim_values)
    checks = {
        "mean_ssim": sum(ssim_values) / len(ssim_values) >= 0.90,
        "p05_ssim": p05 >= 0.80,
        "low_ssim_frame_rate": low_rate <= 0.05,
        "motion_energy_ratio": motion_ratio is not None and 0.75 <= motion_ratio <= 1.25,
    }
    return {
        "paired_frame_count": len(ssim_values),
        "mean_ssim": sum(ssim_values) / len(ssim_values),
        "p05_ssim": p05,
        "min_ssim": min(ssim_values),
        "low_ssim_frame_rate": low_rate,
        "normalized_mae": sum(mae_values) / len(mae_values),
        "control_motion_energy": control_energy,
        "selective_motion_energy": selective_energy,
        "motion_energy_ratio": motion_ratio,
        "checks": checks,
        "passed": all(checks.values()),
        "visual_equivalence": "not_proven",
        "method": "frame-aligned decoded grayscale global SSIM, normalized MAE, and adjacent-frame motion energy",
    }


def _mapping_gate(mode: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    block = policy.get("block_execution") if isinstance(policy.get("block_execution"), Mapping) else {}
    plan = policy.get("c3_plan") if isinstance(policy.get("c3_plan"), Mapping) else {}
    expected_original = BLOCK_COUNT * 20
    checks = {
        "sampler_succeeded": policy.get("sampler_succeeded") is True,
        "model_forward_count": block.get("model_forward_count") == 20,
        "observed_block_calls": block.get("observed_block_call_count") == expected_original,
        "mapping_error_zero": block.get("mapping_error_count") == 0,
        "wrapper_failure_zero": block.get("wrapper_failure_count") == 0,
        "c3_tensor_bytes_zero": plan.get("tensor_bytes_to_rust") == 0,
        "per_block_rust_zero": block.get("rust_calls_per_block") == 0,
    }
    if mode == CONTROL:
        checks.update(
            {
                "control_original_calls": block.get("original_block_call_count") == expected_original,
                "control_bypass_zero": block.get("bypass_block_call_count") == 0,
            }
        )
    return {"checks": checks, "passed": all(checks.values())}


def run_probe(
    *,
    mode: str,
    run_id: str,
    p0_database: Path,
    private_run_root: Path,
    compare_control_video: Path | None = None,
) -> dict[str, Any]:
    if mode not in {CONTROL, SELECTIVE}:
        raise ValueError("mode must be CONTROL or SELECTIVE")
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    callback_receipt_path = root / "c3-r1-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C3_R1_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C3_R1_RECEIPT"] = str(callback_receipt_path)
    actual_bypass = mode == SELECTIVE
    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": "c3_r1_frozen_replay_mechanism_validation",
        "mode": mode,
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "actual_block_bypass_enabled": actual_bypass,
        "frozen_schedule": list(FROZEN_SCHEDULE),
        "candidate_blocks": list(CANDIDATE_BLOCKS),
        "theoretical_opportunity": THEORETICAL_OPPORTUNITY,
        "claim_boundary": "frozen replay mechanism validation; not a live product policy or Fast Mode",
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    startup_seconds = result_collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        startup_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup_started
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow_status = backend.inspect_workflow()
        objects = backend.client.json("GET", "/object_info")
        custom_node_present = isinstance(objects, Mapping) and NODE_CLASS in objects
        receipt["preflight"] = {
            "runtime": runtime,
            "assets": assets,
            "workflow": workflow_status,
            "c3_r1_custom_node_present": custom_node_present,
            "source_admission_reused_from_c3": True,
            "model_source_sha256": MODEL_REVISION_DIGEST,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C3-R1 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C3-R1 custom node is unavailable")
        if workflow_status.get("workflow_sha256") != APPROVED_WORKFLOW_SHA256:
            raise RuntimeError("approved Standard workflow hash changed")
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
        profile = workflow_status.get("execution_profile")
        if not isinstance(profile, Mapping) or any(profile.get(key) != value for key, value in expected_profile.items()):
            raise RuntimeError("C3-R1 Standard execution profile changed")
        receipt["execution_profile"] = profile
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/c3-r1-{mode.lower()}-{prompt_hash[:16]}",
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        settings_digest = frozen_settings_digest(actual_block_bypass_enabled=actual_bypass)
        workflow = build_c3_r1_workflow(
            standard,
            run_digest=run_digest,
            workflow_revision_digest=APPROVED_WORKFLOW_SHA256,
            settings_digest=settings_digest,
            model_revision_digest=MODEL_REVISION_DIGEST,
            actual_block_bypass_enabled=actual_bypass,
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest,
            "model_revision_digest": MODEL_REVISION_DIGEST,
            "runtime_wrapper": NODE_CLASS,
            "actual_block_bypass_enabled": actual_bypass,
        }
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C3-R1 workflow contains a Sage node")
        timeline = EventTimeline(workflow)
        resource_sampler = ResourceSampler(backend, timeline, interval_seconds=1.0)
        resource_sampler.start()
        receipt["generation_attempt_count"] = 1
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        receipt["backend_prompt_id"] = prompt_id
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        collection_started = time.monotonic()
        descriptor, content = _history_video(backend, history)
        output = root / f"c3-r1-{mode.lower()}.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        result_collection_seconds = time.monotonic() - collection_started
        if (
            decode["decoded_frame_count"] != 124
            or (decode["width"], decode["height"]) != (864, 480)
            or decode["fps"] != 24.0
            or decode["codec"] != "h264"
            or decode["audio_stream_count"] < 1
            or decode["black_frame_count"] != 0
            or decode["corrupted_frame_count"] != 0
        ):
            raise RuntimeError("C3-R1 output failed the fixed video integrity contract")
        if not callback_receipt_path.is_file():
            raise RuntimeError("C3-R1 callback receipt is missing")
        callback_policy = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["callback_policy"] = callback_policy
        receipt["mapping_gate"] = _mapping_gate(mode, callback_policy)
        if not receipt["mapping_gate"]["passed"]:
            raise RuntimeError("C3-R1 model-forward/block mapping gate failed")
        receipt["result"] = {
            "logical_artifact_id": f"C3_R1_{mode}_VIDEO",
            "private_path": str(output),
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "decode": decode,
        }
        if mode == SELECTIVE:
            if compare_control_video is None or not compare_control_video.is_file():
                raise RuntimeError("SELECTIVE requires the completed CONTROL video for paired quality")
            receipt["quality_comparison"] = compare_videos(compare_control_video, output)
        exit_code = 0
    except Exception as error:
        receipt["runner_error"] = type(error).__name__
        receipt["runner_error_message"] = str(error)[:1000]
    finally:
        if resource_sampler is not None:
            resource_sampler.stop()
        shutdown_started = time.monotonic()
        try:
            receipt["runtime_stop"] = backend.stop_runtime()
        except Exception as error:
            receipt["runtime_stop"] = {"status": "failed", "error": type(error).__name__}
        shutdown_seconds = time.monotonic() - shutdown_started
        if prior_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = prior_pythonpath
        if prior_receipt is None:
            os.environ.pop("HIVEFRAME_C3_R1_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C3_R1_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"),
            "result_collection_seconds": measured(result_collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "torch_gpu_kernel_seconds": unsupported("No GPU profiler run was authorized for C3-R1.", "not collected", scope="GPU kernel"),
        }
        if timeline is not None:
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
                "resource_sampler": resource_sampler.summary() if resource_sampler is not None else None,
            }
            (root / "websocket-events.jsonl").write_text(
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline.events),
                encoding="utf-8",
            )
        if resource_sampler is not None:
            (root / "resource-samples.json").write_text(
                json.dumps(resource_sampler.samples, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if "callback_policy" not in receipt and callback_receipt_path.is_file():
            receipt["callback_policy"] = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["exit_code"] = exit_code
        private_receipt = root / f"c3-r1-{mode.lower()}-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (root / f"c3-r1-{mode.lower()}-public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    block = receipt.get("callback_policy", {}).get("block_execution", {})
    phase = receipt.get("phase_attribution", {})
    return sanitize_public(
        {
            "run_id": receipt.get("run_id"),
            "mode": receipt.get("mode"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "model_forward_count": block.get("model_forward_count"),
            "original_block_call_count": block.get("original_block_call_count"),
            "bypass_block_call_count": block.get("bypass_block_call_count"),
            "submit_to_terminal_seconds": phase.get("submit_to_terminal_seconds"),
            "quality_comparison": receipt.get("quality_comparison"),
            "result_sha256": result.get("sha256"),
            "decode": result.get("decode"),
            "error": receipt.get("runner_error_message"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one C3-R1 frozen-replay CONTROL or SELECTIVE H3 probe.")
    parser.add_argument("--mode", required=True, choices=(CONTROL, SELECTIVE))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--compare-control-video", type=Path)
    args = parser.parse_args(argv)
    receipt = run_probe(
        mode=args.mode,
        run_id=args.run_id,
        p0_database=args.p0_database,
        private_run_root=args.private_run_root,
        compare_control_video=args.compare_control_video,
    )
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
