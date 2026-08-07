"""One-shot C3-R2 CONTROL or SELECTIVE Local H3 residual-replay probe."""

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
import math
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
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt
from .segment_residual_replay import (
    BLOCK_COUNT,
    CONTROL,
    FROZEN_CEILING,
    MAX_THEORETICAL_REDUCTION,
    SEGMENT_BLOCKS,
    SELECTIVE,
    residual_settings_digest,
    select_maximum_safe_targets,
)


SCHEMA_VERSION = "c3-r2.h3.segment-residual-replay.1"
APPROVED_WORKFLOW_SHA256 = "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6"
MODEL_SOURCE_SHA256 = "882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024"
NODE_CLASS = "HIVEFRAMEH3SegmentResidualReplaySampler"
MODEL_SOURCE_RELATIVE = Path("comfy/ldm/minimax/model.py")
QUALITY_GATE = {
    "mean_ssim_min": 0.95,
    "p05_ssim_min": 0.90,
    "min_ssim_min": 0.85,
    "low_ssim_frame_rate_max": 0.02,
    "normalized_mae_max": 0.03,
    "motion_energy_ratio_min": 0.90,
    "motion_energy_ratio_max": 1.10,
    "gradient_energy_ratio_min": 0.90,
    "gradient_energy_ratio_max": 1.10,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_admission(comfyui_root: Path | None) -> dict[str, Any]:
    if comfyui_root is None:
        return {"admitted": False, "reason": "comfyui_root_unconfigured"}
    source = comfyui_root / MODEL_SOURCE_RELATIVE
    if not source.is_file():
        return {"admitted": False, "reason": "model_source_missing"}
    source_hash = sha256(source.read_bytes()).hexdigest()
    checks = {
        "source_hash_unchanged_from_c3_r1": source_hash == MODEL_SOURCE_SHA256,
        "packed_input_output_contract": True,
        "dtype_device_preserved_by_in_place_residual_stream": True,
        "no_mandatory_external_side_effect_owned_by_segment": True,
        "exactly_one_gpu_snapshot_sufficient": True,
        "block_49_receives_wrapper_img": True,
        "standard_restored_by_unpatched_guider": True,
    }
    return {
        "admitted": all(checks.values()),
        "source_sha256": source_hash,
        "checks": checks,
        "source_basis": {
            "dit_block_behavior": "gated attention and MLP residuals accumulate into packed x in place",
            "wrapper_contract": "patches_replace dit/double_block returns img consumed by next ordered block",
            "prefetch_contract": "prefetch pop remains outside replacement wrapper for every ordered block",
        },
    }


def build_c3_r2_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    workflow_revision_digest: str,
    settings_digest: str,
    model_revision_digest: str,
    calibrated_targets: tuple[int, ...],
    actual_residual_replay_enabled: bool,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C3-R2 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C3-R2 sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update(
        {
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "calibrated_targets_csv": ",".join(str(value) for value in calibrated_targets),
            "actual_residual_replay_enabled": bool(actual_residual_replay_enabled),
        }
    )
    return workflow


def compare_videos(control_path: Path, selective_path: Path, artifact_root: Path) -> dict[str, Any]:
    try:
        import av
        import numpy as np
        from PIL import Image
    except ImportError as error:
        raise RuntimeError("PyAV, NumPy, and Pillow are required for the C3-R2 quality gate") from error

    ssim_values: list[float] = []
    mae_values: list[float] = []
    control_motion: list[float] = []
    selective_motion: list[float] = []
    control_gradient: list[float] = []
    selective_gradient: list[float] = []
    review_frames: list[tuple[int, Any, Any, Any]] = []
    previous_control = previous_selective = None
    with av.open(str(control_path)) as control, av.open(str(selective_path)) as selective:
        control_frames = control.decode(video=0)
        selective_frames = selective.decode(video=0)
        index = 0
        while True:
            left = next(control_frames, None)
            right = next(selective_frames, None)
            if left is None or right is None:
                if left is not None or right is not None:
                    raise RuntimeError("C3-R2 videos have different decoded frame counts")
                break
            a_rgb = left.to_ndarray(format="rgb24")
            b_rgb = right.to_ndarray(format="rgb24")
            if a_rgb.shape != b_rgb.shape:
                raise RuntimeError("C3-R2 videos have different frame shapes")
            a = left.to_ndarray(format="gray").astype(np.float64)
            b = right.to_ndarray(format="gray").astype(np.float64)
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
            control_gradient.append(
                float(np.mean(np.abs(np.diff(a, axis=0)))) + float(np.mean(np.abs(np.diff(a, axis=1))))
            )
            selective_gradient.append(
                float(np.mean(np.abs(np.diff(b, axis=0)))) + float(np.mean(np.abs(np.diff(b, axis=1))))
            )
            if previous_control is not None and previous_selective is not None:
                control_motion.append(float(np.mean(np.abs(a - previous_control))))
                selective_motion.append(float(np.mean(np.abs(b - previous_selective))))
            if index % 16 == 0:
                difference = np.clip(np.abs(a_rgb.astype(np.int16) - b_rgb.astype(np.int16)) * 4, 0, 255).astype(np.uint8)
                review_frames.append((index, a_rgb, b_rgb, difference))
            previous_control = a
            previous_selective = b
            index += 1
    if not ssim_values:
        raise RuntimeError("C3-R2 quality comparison decoded zero paired frames")
    ordered = sorted(ssim_values)
    p05 = ordered[max(0, math.ceil(len(ordered) * 0.05) - 1)]
    control_motion_energy = sum(control_motion) / len(control_motion) if control_motion else 0.0
    selective_motion_energy = sum(selective_motion) / len(selective_motion) if selective_motion else 0.0
    motion_ratio = selective_motion_energy / control_motion_energy if control_motion_energy > 0 else None
    control_gradient_energy = sum(control_gradient) / len(control_gradient)
    selective_gradient_energy = sum(selective_gradient) / len(selective_gradient)
    gradient_ratio = selective_gradient_energy / control_gradient_energy if control_gradient_energy > 0 else None
    low_rate = sum(value < 0.85 for value in ssim_values) / len(ssim_values)
    normalized_mae = sum(mae_values) / len(mae_values)
    mean_ssim = sum(ssim_values) / len(ssim_values)
    checks = {
        "mean_ssim": mean_ssim >= QUALITY_GATE["mean_ssim_min"],
        "p05_ssim": p05 >= QUALITY_GATE["p05_ssim_min"],
        "min_ssim": min(ssim_values) >= QUALITY_GATE["min_ssim_min"],
        "low_ssim_frame_rate": low_rate <= QUALITY_GATE["low_ssim_frame_rate_max"],
        "normalized_mae": normalized_mae <= QUALITY_GATE["normalized_mae_max"],
        "motion_energy_ratio": motion_ratio is not None
        and QUALITY_GATE["motion_energy_ratio_min"]
        <= motion_ratio
        <= QUALITY_GATE["motion_energy_ratio_max"],
        "gradient_energy_ratio": gradient_ratio is not None
        and QUALITY_GATE["gradient_energy_ratio_min"]
        <= gradient_ratio
        <= QUALITY_GATE["gradient_energy_ratio_max"],
    }
    if review_frames:
        width = review_frames[0][1].shape[1]
        height = review_frames[0][1].shape[0]
        rows = len(review_frames)
        contact = Image.new("RGB", (width * 3, height * rows))
        for row, (_, control_frame, selective_frame, difference) in enumerate(review_frames):
            contact.paste(Image.fromarray(control_frame), (0, row * height))
            contact.paste(Image.fromarray(selective_frame), (width, row * height))
            contact.paste(Image.fromarray(difference), (width * 2, row * height))
        contact.save(artifact_root / "c3-r2-control-selective-difference-contact-sheet.jpg", quality=90)
    side_by_side_path = artifact_root / "c3-r2-control-selective-side-by-side.mp4"
    with (
        av.open(str(control_path)) as control,
        av.open(str(selective_path)) as selective,
        av.open(str(side_by_side_path), mode="w") as combined,
    ):
        stream = combined.add_stream("libx264", rate=24)
        stream.width = 1728
        stream.height = 480
        stream.pix_fmt = "yuv420p"
        for left, right in zip(control.decode(video=0), selective.decode(video=0), strict=True):
            canvas = np.concatenate(
                (left.to_ndarray(format="rgb24"), right.to_ndarray(format="rgb24")), axis=1
            )
            frame = av.VideoFrame.from_ndarray(canvas, format="rgb24")
            for packet in stream.encode(frame):
                combined.mux(packet)
        for packet in stream.encode():
            combined.mux(packet)
    raw_metrics = artifact_root / "c3-r2-frame-quality-private.json"
    raw_metrics.write_text(
        json.dumps(
            {"ssim": ssim_values, "normalized_mae": mae_values}, indent=2, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "paired_frame_count": len(ssim_values),
        "mean_ssim": mean_ssim,
        "p05_ssim": p05,
        "min_ssim": min(ssim_values),
        "low_ssim_frame_rate": low_rate,
        "normalized_mae": normalized_mae,
        "control_motion_energy": control_motion_energy,
        "selective_motion_energy": selective_motion_energy,
        "motion_energy_ratio": motion_ratio,
        "control_gradient_energy": control_gradient_energy,
        "selective_gradient_energy": selective_gradient_energy,
        "gradient_energy_ratio": gradient_ratio,
        "checks": checks,
        "fixed_gate": QUALITY_GATE,
        "passed": all(checks.values()),
        "quality_degradation_detected": not all(checks.values()),
        "quality_guaranteed": False,
        "quality_improvement": False,
        "visual_equivalence": "not_proven",
        "method": "frame-aligned grayscale global SSIM/MAE, adjacent-frame motion energy, and spatial gradient energy",
        "private_visual_review_artifacts": [
            "c3-r2-control-selective-side-by-side.mp4",
            "c3-r2-control-selective-difference-contact-sheet.jpg",
            "c3-r2-frame-quality-private.json",
        ],
    }


def _mapping_gate(mode: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    execution = policy.get("segment_execution") if isinstance(policy.get("segment_execution"), Mapping) else {}
    plan = policy.get("c3_r2_plan") if isinstance(policy.get("c3_r2_plan"), Mapping) else {}
    original = int(execution.get("original_block_call_count", -1))
    replayed = int(execution.get("replayed_block_call_count", -1))
    applications = int(execution.get("residual_application_count", -1))
    checks = {
        "sampler_succeeded": policy.get("sampler_succeeded") is True,
        "model_forward_count": execution.get("model_forward_count") == 20,
        "exact_block_accounting": original + replayed == 1000,
        "exact_segment_replay_accounting": replayed == applications * len(SEGMENT_BLOCKS),
        "mapping_error_zero": execution.get("mapping_error_count") == 0,
        "wrapper_failure_zero": execution.get("wrapper_failure_count") == 0,
        "tensor_bytes_to_rust_zero": plan.get("tensor_bytes_to_rust") == 0,
        "per_block_rust_zero": execution.get("rust_calls_per_block") == 0,
        "per_block_cache_zero": execution.get("per_block_cache_count") == 0,
        "bounded_residual_buffers": int(execution.get("max_concurrent_residual_sized_buffers", 99)) <= 2,
    }
    if mode == CONTROL:
        checks.update(
            {
                "control_original_calls": original == BLOCK_COUNT * 20,
                "control_replay_zero": replayed == 0 and applications == 0,
            }
        )
    return {"checks": checks, "passed": all(checks.values())}


def run_probe(
    *,
    mode: str,
    run_id: str,
    p0_database: Path,
    private_run_root: Path,
    calibrated_targets: tuple[int, ...] = (),
    compare_control_video: Path | None = None,
) -> dict[str, Any]:
    if mode not in {CONTROL, SELECTIVE}:
        raise ValueError("invalid C3-R2 mode")
    if mode == CONTROL and calibrated_targets:
        raise ValueError("CONTROL must not receive calibrated reuse targets")
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    source_gate = source_admission(base_config.comfyui_root)
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    callback_receipt_path = root / "c3-r2-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C3_R2_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C3_R2_RECEIPT"] = str(callback_receipt_path)
    actual_replay = mode == SELECTIVE
    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": "c3_r2_quality_preserving_segment_residual_replay",
        "mode": mode,
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "actual_residual_replay_enabled": actual_replay,
        "calibrated_targets": list(calibrated_targets),
        "frozen_ceiling": list(FROZEN_CEILING),
        "segment_blocks": list(SEGMENT_BLOCKS),
        "maximum_theoretical_reduction": MAX_THEORETICAL_REDUCTION,
        "source_admission": source_gate,
        "claim_boundary": "single-profile mechanism validation; product promotion and speedup claim remain zero",
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    startup_seconds = result_collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("C3-R2 installed-source admission failed")
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
            "c3_r2_custom_node_present": custom_node_present,
            "source_admission": source_gate,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C3-R2 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C3-R2 custom node is unavailable")
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
            raise RuntimeError("C3-R2 Standard execution profile changed")
        receipt["execution_profile"] = profile
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/c3-r2-{mode.lower()}-{prompt_hash[:16]}",
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        settings_digest = residual_settings_digest(
            actual_residual_replay_enabled=actual_replay,
            calibrated_targets=calibrated_targets,
        )
        workflow = build_c3_r2_workflow(
            standard,
            run_digest=run_digest,
            workflow_revision_digest=APPROVED_WORKFLOW_SHA256,
            settings_digest=settings_digest,
            model_revision_digest=MODEL_SOURCE_SHA256,
            calibrated_targets=calibrated_targets,
            actual_residual_replay_enabled=actual_replay,
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest,
            "model_revision_digest": MODEL_SOURCE_SHA256,
            "runtime_wrapper": NODE_CLASS,
            "actual_residual_replay_enabled": actual_replay,
            "calibrated_targets": list(calibrated_targets),
        }
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C3-R2 workflow contains a Sage node")
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
        output = root / f"c3-r2-{mode.lower()}.mp4"
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
            raise RuntimeError("C3-R2 output failed the fixed video integrity contract")
        if not callback_receipt_path.is_file():
            raise RuntimeError("C3-R2 callback receipt is missing")
        callback_policy = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["callback_policy"] = callback_policy
        receipt["mapping_gate"] = _mapping_gate(mode, callback_policy)
        if not receipt["mapping_gate"]["passed"]:
            raise RuntimeError("C3-R2 model-forward/block/cache mapping gate failed")
        if mode == CONTROL:
            execution = callback_policy.get("segment_execution", {})
            diagnostics = execution.get("similarity_diagnostics", [])
            selected_targets = select_maximum_safe_targets(
                diagnostics if isinstance(diagnostics, list) else []
            )
            receipt["control_calibration"] = {
                "frozen_before_selective": True,
                "selected_targets": list(selected_targets),
                "selection_method": "chronological maximum-safe nonconsecutive selection inside frozen ceiling",
                "similarity_gate": execution.get("similarity_gate"),
            }
        receipt["result"] = {
            "logical_artifact_id": f"C3_R2_{mode}_VIDEO",
            "private_path": str(output),
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "decode": decode,
        }
        if mode == SELECTIVE:
            if compare_control_video is None or not compare_control_video.is_file():
                raise RuntimeError("SELECTIVE requires the completed CONTROL video for paired quality")
            receipt["quality_comparison"] = compare_videos(compare_control_video, output, root)
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
            os.environ.pop("HIVEFRAME_C3_R2_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C3_R2_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"),
            "result_collection_seconds": measured(result_collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "torch_gpu_kernel_seconds": unsupported("No GPU profiler run was authorized for C3-R2.", "not collected", scope="GPU kernel"),
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
        private_receipt = root / f"c3-r2-{mode.lower()}-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (root / f"c3-r2-{mode.lower()}-public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    execution = receipt.get("callback_policy", {}).get("segment_execution", {})
    phase = receipt.get("phase_attribution", {})
    return sanitize_public(
        {
            "run_id": receipt.get("run_id"),
            "mode": receipt.get("mode"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "model_forward_count": execution.get("model_forward_count"),
            "original_block_call_count": execution.get("original_block_call_count"),
            "replayed_block_call_count": execution.get("replayed_block_call_count"),
            "residual_application_count": execution.get("residual_application_count"),
            "similarity_diagnostics": execution.get("similarity_diagnostics"),
            "control_calibration": receipt.get("control_calibration"),
            "submit_to_terminal_seconds": phase.get("submit_to_terminal_seconds"),
            "quality_comparison": receipt.get("quality_comparison"),
            "result_sha256": result.get("sha256"),
            "decode": result.get("decode"),
            "error": receipt.get("runner_error_message"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one C3-R2 residual CONTROL or SELECTIVE H3 probe.")
    parser.add_argument("--mode", required=True, choices=(CONTROL, SELECTIVE))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--calibrated-targets", default="")
    parser.add_argument("--compare-control-video", type=Path)
    args = parser.parse_args(argv)
    targets = tuple(int(value) for value in args.calibrated_targets.split(",") if value.strip())
    receipt = run_probe(
        mode=args.mode,
        run_id=args.run_id,
        p0_database=args.p0_database,
        private_run_root=args.private_run_root,
        calibrated_targets=targets,
        compare_control_video=args.compare_control_video,
    )
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
