"""Run the bounded C4-S1 CONTROL/SELECTIVE Local H3 experiment."""

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
from .c3_r2_h3_residual_probe import APPROVED_WORKFLOW_SHA256
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .ff_token_selective import (
    BLOCK_COUNT,
    HIDDEN_WIDTH,
    MODEL_SOURCE_SHA256,
    POLICIES,
    POLICY_BY_ID,
    STEP_COUNT,
    VIDEO_TOKEN_COUNT,
    fixed_contract,
    inspect_installed_ff_source,
)
from .h3_subblock_cost_surface import MODEL_SOURCE_RELATIVE
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "c4-s1.h3.ff-token-selective.1"
NODE_CLASS = "HIVEFRAMEH3FFTokenSelectiveSampler"
CONTROL_MODE = "CONTROL_FF_TOKEN_SHADOW"
SELECTIVE_MODE = "SELECTIVE_FF_TOKEN"
REFERENCE_SAMPLER_SECONDS = 488.847320
COMPARABILITY_RELATIVE_LIMIT = 0.05
QUALITY_GATE = {
    "mean_ssim": (">=", 0.95),
    "p05_ssim": (">=", 0.90),
    "min_ssim": (">=", 0.85),
    "ssim_below_0_85_rate": ("<=", 0.02),
    "normalized_mae": ("<=", 0.03),
    "motion_energy_ratio": ("range", (0.90, 1.10)),
    "gradient_energy_ratio": ("range", (0.90, 1.10)),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def settings_digest(*, mode: str, selected_policy: str | None) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "selected_policy": selected_policy,
        "model_source_sha256": MODEL_SOURCE_SHA256,
        "workflow_sha256": APPROVED_WORKFLOW_SHA256,
        "contract": fixed_contract(),
        "reference_sampler_seconds": REFERENCE_SAMPLER_SECONDS,
        "comparability_relative_limit": COMPARABILITY_RELATIVE_LIMIT,
        "profile": {
            "seed": 101,
            "width": 864,
            "height": 480,
            "frames": 124,
            "fps": 24,
            "steps": 20,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "denoise": 1.0,
            "native_audio": True,
            "sage": False,
        },
        "quality_gate": QUALITY_GATE,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    mode: str,
    selected_policy: str | None,
    run_digest: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C4-S1 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C4-S1 sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update(
        {
            "mode": mode,
            "selected_policy": selected_policy or "",
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest(mode=mode, selected_policy=selected_policy),
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    return workflow


def instrumentation_gate(callback: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    data = callback.get("instrumentation") if isinstance(callback.get("instrumentation"), Mapping) else {}
    memory = data.get("memory_contract") if isinstance(data.get("memory_contract"), Mapping) else {}
    checks = {
        "sampler_succeeded": callback.get("sampler_succeeded") is True,
        "mode_exact": callback.get("mode") == mode,
        "attention_full_compute": callback.get("attention_execution") == "ALWAYS_FULL_COMPUTE",
        "model_forward_count": data.get("model_forward_count") == STEP_COUNT,
        "block_call_count": data.get("block_call_count") == STEP_COUNT * BLOCK_COUNT,
        "mapping_error_zero": data.get("mapping_error_count") == 0,
        "wrapper_failure_zero": data.get("wrapper_failure_count") == 0,
        "video_token_count": data.get("observed_video_token_count") == VIDEO_TOKEN_COUNT,
        "hidden_width": data.get("observed_hidden_width") == HIDDEN_WIDTH,
        "attention_omission_zero": data.get("attention_omission_count") == 0,
        "non_video_omission_zero": data.get("non_video_omission_count") == 0,
        "one_mlp_call_per_block": data.get("mlp_call_count") == STEP_COUNT * BLOCK_COUNT,
        "memory_budget": memory.get("budget_passed") is True,
        "full_tensor_cache_zero": memory.get("full_tensor_cache_count") == 0,
        "host_full_tensor_copy_zero": memory.get("host_full_tensor_copy_bytes") == 0,
        "tensor_to_rust_zero": memory.get("tensor_bytes_to_rust") == 0,
        "single_explicit_synchronization": data.get("synchronization_count") == 1,
        "profiler_disabled": data.get("profiler_enabled") is False,
    }
    if mode == CONTROL_MODE:
        checks.update(
            {
                "control_omission_zero": data.get("omitted_video_row_count") == 0,
                "control_full_rows": data.get("actual_mlp_row_count") == data.get("full_mlp_row_count"),
            }
        )
    return {"checks": checks, "passed": all(checks.values())}


def instrumentation_comparability(measured_sampler_seconds: float) -> dict[str, Any]:
    delta = measured_sampler_seconds - REFERENCE_SAMPLER_SECONDS
    relative = delta / REFERENCE_SAMPLER_SECONDS
    return {
        "reference_sampler_seconds": REFERENCE_SAMPLER_SECONDS,
        "measured_sampler_seconds": measured_sampler_seconds,
        "delta_seconds": delta,
        "relative_delta": relative,
        "relative_limit": COMPARABILITY_RELATIVE_LIMIT,
        "passed": abs(relative) <= COMPARABILITY_RELATIVE_LIMIT,
    }


def policy_admission(callback: Mapping[str, Any]) -> dict[str, Any]:
    data = callback.get("instrumentation") if isinstance(callback.get("instrumentation"), Mapping) else {}
    shadows = data.get("policy_shadow") if isinstance(data.get("policy_shadow"), Mapping) else {}
    results: dict[str, Any] = {}
    for policy in POLICIES:
        evidence = shadows.get(policy.policy_id) if isinstance(shadows.get(policy.policy_id), Mapping) else {}
        impact = evidence.get("actual_impact") if isinstance(evidence.get("actual_impact"), Mapping) else {}
        checks = {
            "all_token_mlp_row_reduction": float(evidence.get("all_token_mlp_row_reduction", 0.0)) >= 0.10,
            "video_token_skip_ratio": float(evidence.get("video_token_skip_ratio", 0.0)) >= 0.20,
            "affected_non_anchor_steps": int(evidence.get("affected_step_count", 0)) >= 3,
            "affected_blocks": int(evidence.get("affected_block_count", 0)) >= 10,
            "actual_impact_mean": impact.get("mean") is not None and float(impact["mean"]) <= 0.003,
            "actual_impact_p99": impact.get("p99") is not None and float(impact["p99"]) <= 0.010,
            "actual_impact_over_rate": impact.get("over_0_010_rate") is not None and float(impact["over_0_010_rate"]) <= 0.005,
            "actual_impact_max": impact.get("max") is not None and float(impact["max"]) <= 0.025,
            "nonfinite_zero": impact.get("nonfinite_count") == 0,
        }
        results[policy.policy_id] = {"checks": checks, "passed": all(checks.values()), "evidence": evidence}
    passing = [policy for policy in POLICIES if results[policy.policy_id]["passed"]]
    selected = None
    if passing:
        selected = max(
            passing,
            key=lambda policy: (
                float(results[policy.policy_id]["evidence"]["all_token_mlp_row_reduction"]),
                float(results[policy.policy_id]["evidence"]["video_token_skip_ratio"]),
                -int(policy.policy_id[1:]),
            ),
        ).policy_id
    return {"policies": results, "selected_policy": selected, "passed": selected is not None}


def compare_videos(control_path: Path, selective_path: Path) -> dict[str, Any]:
    try:
        import av
        import numpy as np
    except ImportError as error:
        raise RuntimeError("PyAV and NumPy are required for the C4-S1 quality gate") from error
    ssim_values: list[float] = []
    mae_values: list[float] = []
    control_motion: list[float] = []
    selective_motion: list[float] = []
    control_gradient: list[float] = []
    selective_gradient: list[float] = []
    previous_control = previous_selective = None
    with av.open(str(control_path)) as control, av.open(str(selective_path)) as selective:
        cstream = list(control.streams.video)
        sstream = list(selective.streams.video)
        if len(cstream) != 1 or len(sstream) != 1:
            raise RuntimeError("C4-S1 comparison requires one video stream per artifact")
        cframes = control.decode(cstream[0])
        sframes = selective.decode(sstream[0])
        while True:
            left, right = next(cframes, None), next(sframes, None)
            if left is None or right is None:
                if left is not None or right is not None:
                    raise RuntimeError("C4-S1 videos have different decoded frame counts")
                break
            a = left.to_ndarray(format="gray").astype(np.float64)
            b = right.to_ndarray(format="gray").astype(np.float64)
            if a.shape != b.shape:
                raise RuntimeError("C4-S1 videos have different frame shapes")
            ma, mb = float(np.mean(a)), float(np.mean(b))
            ca, cb = a - ma, b - mb
            va, vb = float(np.mean(ca * ca)), float(np.mean(cb * cb))
            cov = float(np.mean(ca * cb))
            c1, c2 = (0.01 * 255.0) ** 2, (0.03 * 255.0) ** 2
            denominator = (ma * ma + mb * mb + c1) * (va + vb + c2)
            ssim_values.append(((2 * ma * mb + c1) * (2 * cov + c2) / denominator) if denominator else 1.0)
            mae_values.append(float(np.mean(np.abs(a - b))) / 255.0)
            control_gradient.append(float(np.mean(np.abs(np.diff(a, axis=0))) + np.mean(np.abs(np.diff(a, axis=1)))))
            selective_gradient.append(float(np.mean(np.abs(np.diff(b, axis=0))) + np.mean(np.abs(np.diff(b, axis=1)))))
            if previous_control is not None:
                control_motion.append(float(np.mean(np.abs(a - previous_control))))
                selective_motion.append(float(np.mean(np.abs(b - previous_selective))))
            previous_control, previous_selective = a, b
    if not ssim_values:
        raise RuntimeError("C4-S1 quality comparison decoded zero paired frames")
    ordered = sorted(ssim_values)
    p05 = ordered[max(0, math.ceil(len(ordered) * 0.05) - 1)]
    control_motion_energy = sum(control_motion) / len(control_motion) if control_motion else 0.0
    selective_motion_energy = sum(selective_motion) / len(selective_motion) if selective_motion else 0.0
    control_gradient_energy = sum(control_gradient) / len(control_gradient)
    selective_gradient_energy = sum(selective_gradient) / len(selective_gradient)
    motion_ratio = selective_motion_energy / control_motion_energy if control_motion_energy else None
    gradient_ratio = selective_gradient_energy / control_gradient_energy if control_gradient_energy else None
    metrics = {
        "paired_frame_count": len(ssim_values),
        "mean_ssim": sum(ssim_values) / len(ssim_values),
        "p05_ssim": p05,
        "min_ssim": min(ssim_values),
        "ssim_below_0_85_rate": sum(value < 0.85 for value in ssim_values) / len(ssim_values),
        "normalized_mae": sum(mae_values) / len(mae_values),
        "control_motion_energy": control_motion_energy,
        "selective_motion_energy": selective_motion_energy,
        "motion_energy_ratio": motion_ratio,
        "control_gradient_energy": control_gradient_energy,
        "selective_gradient_energy": selective_gradient_energy,
        "gradient_energy_ratio": gradient_ratio,
        "visual_equivalence": "not_proven",
        "human_visual_review": "required",
    }
    checks = {
        "mean_ssim": metrics["mean_ssim"] >= 0.95,
        "p05_ssim": metrics["p05_ssim"] >= 0.90,
        "min_ssim": metrics["min_ssim"] >= 0.85,
        "ssim_below_0_85_rate": metrics["ssim_below_0_85_rate"] <= 0.02,
        "normalized_mae": metrics["normalized_mae"] <= 0.03,
        "motion_energy_ratio": motion_ratio is not None and 0.90 <= motion_ratio <= 1.10,
        "gradient_energy_ratio": gradient_ratio is not None and 0.90 <= gradient_ratio <= 1.10,
    }
    metrics["checks"] = checks
    metrics["passed"] = all(checks.values())
    metrics["method"] = "frame-aligned decoded grayscale global SSIM, normalized MAE, motion energy, and spatial gradient energy"
    return metrics


def _run_generation(
    *,
    run_id: str,
    mode: str,
    selected_policy: str | None,
    prompt: str,
    prompt_hash: str,
    root: Path,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    source = base_config.comfyui_root / MODEL_SOURCE_RELATIVE if base_config.comfyui_root else Path("<missing>")
    source_gate = inspect_installed_ff_source(source)
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    callback_path = root / "callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C4_S1_RECEIPT")
    python_entries = [str(repository_root / "python")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C4_S1_RECEIPT"] = str(callback_path)
    runner_started = time.monotonic()
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    timeline: EventTimeline | None = None
    resources: ResourceSampler | None = None
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": mode,
        "selected_policy": selected_policy,
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "settings_digest": settings_digest(mode=mode, selected_policy=selected_policy),
        "source_admission": source_gate,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
    }
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("C4-S1 installed-source admission failed")
        startup_started = time.monotonic()
        runtime_start = backend.start_runtime()
        receipt["runtime_start"] = runtime_start
        startup_seconds = time.monotonic() - startup_started
        if runtime_start.get("started_here") is not True:
            raise RuntimeError("C4-S1 requires one fresh owned ComfyUI process")
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow_status = backend.inspect_workflow()
        objects = backend.client.json("GET", "/object_info")
        node_present = isinstance(objects, Mapping) and NODE_CLASS in objects
        receipt["preflight"] = {
            "runtime": runtime,
            "assets": assets,
            "workflow": workflow_status,
            "custom_node_present": node_present,
            "source_admission": source_gate,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C4-S1 Local H3 preflight did not reach ready")
        if not node_present:
            raise RuntimeError("repository-owned C4-S1 custom node is unavailable")
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
            raise RuntimeError("C4-S1 Standard execution profile changed")
        receipt["execution_profile"] = profile
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/c4-s1-{mode.lower()}-{prompt_hash[:12]}",
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        workflow = build_workflow(standard, mode=mode, selected_policy=selected_policy, run_digest=run_digest)
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C4-S1 workflow contains a Sage node")
        timeline = EventTimeline(workflow)
        resources = ResourceSampler(backend, timeline, interval_seconds=1.0)
        resources.start()
        receipt["generation_attempt_count"] = 1
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        receipt["backend_prompt_id"] = prompt_id
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        collection_started = time.monotonic()
        descriptor, content = _history_video(backend, history)
        output = root / ("control.mp4" if mode == CONTROL_MODE else "selective.mp4")
        output.write_bytes(content)
        decode = _decode_video(output)
        collection_seconds = time.monotonic() - collection_started
        required_decode = (
            decode["decoded_frame_count"] == 124
            and (decode["width"], decode["height"]) == (864, 480)
            and decode["fps"] == 24.0
            and decode["codec"] == "h264"
            and decode["audio_stream_count"] >= 1
            and decode["black_frame_count"] == 0
            and decode["corrupted_frame_count"] == 0
        )
        if not required_decode:
            raise RuntimeError("C4-S1 output failed fixed video integrity contract")
        if not callback_path.is_file():
            raise RuntimeError("C4-S1 callback receipt is missing")
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        receipt["callback_instrumentation"] = callback
        receipt["instrumentation_gate"] = instrumentation_gate(callback, mode=mode)
        if not receipt["instrumentation_gate"]["passed"]:
            raise RuntimeError("C4-S1 instrumentation Gate failed")
        receipt["result"] = {
            "logical_artifact_id": f"C4_S1_{mode}_VIDEO",
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
        if resources is not None:
            resources.stop()
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
            os.environ.pop("HIVEFRAME_C4_S1_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C4_S1_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"),
            "result_collection_seconds": measured(collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "gpu_kernel_seconds": unsupported("PyTorch profiler, CUPTI, and Nsight were disabled for C4-S1.", "not collected", scope="GPU kernel-duration sum"),
        }
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["phase_attribution"] = timeline.phase_attribution(
                runner_total_seconds=runner_total,
                runtime_startup_seconds=startup_seconds,
                result_collection_seconds=collection_seconds,
                shutdown_seconds=shutdown_seconds,
            )
            receipt["instrumentation"] = {
                "websocket_parser_wall_seconds": timeline.parser_wall_seconds,
                "resource_sampler": resources.summary() if resources else None,
            }
            (root / "websocket-events.jsonl").write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline.events), encoding="utf-8")
        if resources is not None:
            (root / "resource-samples.json").write_text(json.dumps(resources.samples, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if "callback_instrumentation" not in receipt and callback_path.is_file():
            receipt["callback_instrumentation"] = json.loads(callback_path.read_text(encoding="utf-8"))
        receipt["exit_code"] = exit_code
        (root / "private-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (root / "public-summary.json").write_text(json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        receipt["private_receipt_path"] = str(root / "private-receipt.json")
        receipt["public_summary_path"] = str(root / "public-summary.json")
    return receipt


def _sampler_seconds(receipt: Mapping[str, Any]) -> float:
    phase = receipt.get("phase_attribution") if isinstance(receipt.get("phase_attribution"), Mapping) else {}
    phases = phase.get("phases") if isinstance(phase.get("phases"), Mapping) else {}
    denoising = phases.get("denoising") if isinstance(phases.get("denoising"), Mapping) else {}
    return float(denoising["seconds"])


def _submit_seconds(receipt: Mapping[str, Any]) -> float:
    phase = receipt.get("phase_attribution") if isinstance(receipt.get("phase_attribution"), Mapping) else {}
    return float(phase["submit_to_terminal_seconds"])


def _visual_review_package(control: Path, selective: Path, root: Path) -> dict[str, Any]:
    import av
    import numpy as np
    from PIL import Image
    review = root / "visual-review"
    review.mkdir(exist_ok=False)
    frames = {0, 31, 62, 93, 123}

    def load(path: Path) -> dict[int, Any]:
        output = {}
        with av.open(str(path)) as container:
            stream = list(container.streams.video)[0]
            for index, frame in enumerate(container.decode(stream)):
                if index in frames:
                    output[index] = frame.to_ndarray(format="rgb24")
        return output

    left, right = load(control), load(selective)
    hashes = []
    for index in sorted(frames):
        a, b = left[index], right[index]
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.uint8)
        canvas = np.concatenate((a, b, diff), axis=1)
        target = review / f"frame-{index:03d}-control-selective-diff.png"
        Image.fromarray(canvas).save(target)
        hashes.append({"frame": index, "sha256": sha256(target.read_bytes()).hexdigest()})
    manifest = {"status": "review_pending", "frames": hashes, "layout": "CONTROL | SELECTIVE | absolute RGB difference"}
    (review / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"logical_artifact_id": "C4_S1_PRIVATE_VISUAL_REVIEW", "status": "review_pending", "manifest_sha256": sha256((review / "manifest.json").read_bytes()).hexdigest()}


def run_experiment(*, experiment_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, experiment_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "started_at": _utc_now(),
        "generation_budget": 2,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "selector_contract": fixed_contract(),
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
        "visual_equivalence": "not_proven",
    }
    control = _run_generation(
        run_id=f"{experiment_id}-control",
        mode=CONTROL_MODE,
        selected_policy=None,
        prompt=prompt,
        prompt_hash=prompt_hash,
        root=root / "control",
    )
    summary["generation_attempt_count"] += int(control.get("generation_attempt_count", 0))
    summary["control"] = control
    if control.get("exit_code") != 0:
        summary["technical_decision"] = "C4_S1_CONTROL_FAILED"
        summary["disposition"] = "REVISE_ONCE"
    else:
        comparability = instrumentation_comparability(_sampler_seconds(control))
        summary["control_comparability"] = comparability
        if not comparability["passed"]:
            summary["technical_decision"] = "C4_S1_INSTRUMENTATION_OVERHEAD_TOO_HIGH"
            summary["disposition"] = "REVISE_ONCE"
        else:
            admission = policy_admission(control["callback_instrumentation"])
            summary["control_policy_admission"] = admission
            selected = admission["selected_policy"]
            if selected is None:
                summary["technical_decision"] = "C4_S1_CAUSAL_FF_ADMISSION_TOO_LOW"
                summary["disposition"] = "REVISE_ONCE"
            else:
                selective = _run_generation(
                    run_id=f"{experiment_id}-selective-{selected.lower()}",
                    mode=SELECTIVE_MODE,
                    selected_policy=selected,
                    prompt=prompt,
                    prompt_hash=prompt_hash,
                    root=root / "selective",
                )
                summary["generation_attempt_count"] += int(selective.get("generation_attempt_count", 0))
                summary["selective"] = selective
                if selective.get("exit_code") != 0:
                    summary["technical_decision"] = "C4_S1_SELECTIVE_EXECUTION_FAILED"
                    summary["disposition"] = "REVISE_ONCE"
                else:
                    control_path = Path(control["result"]["private_path"])
                    selective_path = Path(selective["result"]["private_path"])
                    quality = compare_videos(control_path, selective_path)
                    summary["quality"] = quality
                    data = selective["callback_instrumentation"]["instrumentation"]
                    reduction = float(data["actual_all_token_mlp_row_reduction"])
                    summary["runtime_comparison"] = {
                        "control_sampler_seconds": _sampler_seconds(control),
                        "selective_sampler_seconds": _sampler_seconds(selective),
                        "sampler_ratio": _sampler_seconds(control) / _sampler_seconds(selective),
                        "control_submit_to_terminal_seconds": _submit_seconds(control),
                        "selective_submit_to_terminal_seconds": _submit_seconds(selective),
                        "submit_to_terminal_ratio": _submit_seconds(control) / _submit_seconds(selective),
                        "selective_e2e_regression": _submit_seconds(selective) / _submit_seconds(control) - 1.0,
                    }
                    if reduction < 0.05:
                        summary["technical_decision"] = "C4_S1_LIVE_OPPORTUNITY_TOO_LOW"
                        summary["disposition"] = "REVISE_ONCE"
                    elif not quality["passed"]:
                        summary["technical_decision"] = "C4_S1_FF_ZERO_UPDATE_QUALITY_REJECTED"
                        summary["disposition"] = "REVISE_ONCE"
                    elif summary["runtime_comparison"]["selective_e2e_regression"] > 0.02:
                        summary["technical_decision"] = "C4_S1_FF_WORK_REDUCTION_VERIFIED_RUNTIME_REGRESSED"
                        summary["disposition"] = "REVISE_ONCE"
                    elif (
                        summary["runtime_comparison"]["sampler_ratio"] > 1.0
                        and summary["runtime_comparison"]["submit_to_terminal_ratio"] > 1.0
                    ):
                        summary["technical_decision"] = "C4_S1_FF_SELECTIVE_COMPONENT_READY_FOR_VISUAL_REVIEW"
                        summary["disposition"] = "KEEP_AS_OPTIONAL"
                        summary["visual_review"] = _visual_review_package(control_path, selective_path, root)
                    else:
                        summary["technical_decision"] = "C4_S1_FF_SELECTIVE_COMPONENT_VERIFIED"
                        summary["disposition"] = "KEEP_AS_OPTIONAL"
                        summary["visual_review"] = _visual_review_package(control_path, selective_path, root)
    summary["finished_at"] = _utc_now()
    summary["retry_count"] = 0
    summary["external_api_call_count"] = 0
    summary["model_download_count"] = 0
    summary["rust_abi_change_count"] = 0
    (root / "experiment-private-receipt.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "experiment-public-summary.json").write_text(json.dumps(sanitize_public(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary["private_receipt_path"] = str(root / "experiment-private-receipt.json")
    summary["public_summary_path"] = str(root / "experiment-public-summary.json")
    return summary


def public_result(summary: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_public(
        {
            "experiment_id": summary.get("experiment_id"),
            "technical_decision": summary.get("technical_decision"),
            "disposition": summary.get("disposition"),
            "generation_attempt_count": summary.get("generation_attempt_count"),
            "retry_count": summary.get("retry_count"),
            "control_comparability": summary.get("control_comparability"),
            "control_policy_admission": summary.get("control_policy_admission"),
            "runtime_comparison": summary.get("runtime_comparison"),
            "quality": summary.get("quality"),
            "visual_review": summary.get("visual_review"),
            "speedup_claim": summary.get("speedup_claim"),
            "product_promotion": summary.get("product_promotion"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded C4-S1 H3 FF token-selective experiment.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_experiment(experiment_id=args.experiment_id, p0_database=args.p0_database, private_run_root=args.private_run_root)
    print(json.dumps(public_result(result), ensure_ascii=False, sort_keys=True))
    return 0 if result.get("technical_decision") not in {"C4_S1_CONTROL_FAILED", "C4_S1_SELECTIVE_EXECUTION_FAILED"} else 1


if __name__ == "__main__":
    sys.exit(main())
