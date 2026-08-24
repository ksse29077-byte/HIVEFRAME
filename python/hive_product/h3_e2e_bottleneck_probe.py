"""Run the single admitted Standard H3 end-to-end bottleneck profile."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import asyncio
import copy
import json
import os
import shutil
import subprocess
import sys
import time

from .a3_g1_h3_conditional_probe import APPROVED_WORKFLOW_SHA256
from .c0_h3_phase_probe import (
    EventTimeline,
    ResourceSampler,
    _collect_websocket_run,
    sanitize_public,
)
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .comfyui_process_ownership import (
    build_post_shutdown_receipt,
    build_pre_launch_receipt,
    build_process_ownership_receipt,
    stop_verified_runtime_descendants,
    wait_for_console_helper_exit,
)
from .h3_e2e_bottleneck_profile import profile_mapping_gate
from .h3_observer_v4_control_probe import _p1_a2_profile_receipt
from .h3_row_region_safety_control_v2_probe import (
    _adjacent_duplicate_count,
    _download_video,
    _load_prompt,
    _nvidia_memory,
    _port_open,
    _utc_now,
    inspect_external_jobs,
)
from .h3_subblock_cost_surface import (
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    inspect_installed_source,
)
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video


SCHEMA_VERSION = "h3.e2e-bottleneck-profile.runner.1"
NODE_CLASS = "HIVEFRAMEH3EndToEndProfileSampler"
RECEIPT_ENV = "HIVEFRAME_H3_E2E_PROFILE_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_E2E_PROFILE_ADMISSION"
RUN_KIND = "STANDARD_H3_AGGREGATE_PROFILE"
READY = "H3_HIGH_IMPACT_PROFILE_COMPLETE_READY_FOR_IMPLEMENTATION"
BLOCKED = "H3_HIGH_IMPACT_PROFILE_ADMISSION_BLOCKED"
FAILED = "H3_HIGH_IMPACT_PROFILE_FAILED"
ARCHITECTURE_INSUFFICIENT = "H3_STANDARD_ARCHITECTURE_INSUFFICIENT_FOR_TARGET"
INPUT_SHA256 = "493ea036b4d5008c6ae7eaec772163527db1aed9457021a93ab922ee87dfb411"


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def settings_digest() -> str:
    payload = {
        "run_kind": RUN_KIND,
        "model_source_sha256": MODEL_SOURCE_SHA256,
        "workflow_sha256": APPROVED_WORKFLOW_SHA256,
        "profile": {
            "mode": "image_to_video_with_native_audio",
            "seed": 101,
            "width": 864,
            "height": 480,
            "frames": 124,
            "fps": 24,
            "steps": 20,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "denoise": 1.0,
            "sage": False,
            "attention": "attention_pytorch",
        },
        "full_compute_only": True,
        "v4_observer_enabled": False,
        "v4_evidence_transfer_bytes": 0,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    first_frame_name: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("H3 profile requires Standard SamplerCustomAdvanced at node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("H3 profile sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update(
        {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest(),
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    workflow["16"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
    workflow["8"]["inputs"]["first_frame"] = ["16", 0]
    return workflow


def _phase_ledger(
    *,
    timeline: EventTimeline,
    callback: Mapping[str, Any],
    submit_to_terminal_seconds: float,
    result_collection_seconds: float,
) -> dict[str, Any]:
    timing = callback["timing"]
    nodes = {str(item["node_id"]): item for item in timeline.node_timeline()}

    def node_seconds(node_id: str) -> float:
        value = nodes.get(node_id, {}).get("observed_wall_seconds")
        return float(value) if isinstance(value, (int, float)) else 0.0

    sampler_seconds = node_seconds("10")
    non_sampler = max(0.0, submit_to_terminal_seconds - sampler_seconds)
    phases = {
        "model_and_encoder_loading": sum(node_seconds(node) for node in ("1", "2", "3", "4")),
        "input_prompt_conditioning": sum(node_seconds(node) for node in ("5", "6", "7", "8", "9", "16")),
        "sampler": sampler_seconds,
        "vae_video_decode": node_seconds("11"),
        "vae_audio_decode": node_seconds("12"),
        "frame_video_encode_mux_save": node_seconds("13") + node_seconds("14"),
        "result_retrieval_decode_receipt": result_collection_seconds,
    }
    measured_pre_terminal_non_sampler = sum(
        value
        for key, value in phases.items()
        if key not in {"sampler", "result_retrieval_decode_receipt"}
    )
    phases["queue_and_unattributed_outside_sampler"] = max(
        0.0, non_sampler - measured_pre_terminal_non_sampler
    )
    accounted = sum(phases.values())
    submit_to_output_seconds = submit_to_terminal_seconds + result_collection_seconds
    sampler_gpu_seconds = float(timing["sampler_cuda_event_span_ms"]) / 1000.0
    return {
        "scope": "submission through verified local output and receipt",
        "submit_to_terminal_seconds": submit_to_terminal_seconds,
        "submit_to_output_seconds": submit_to_output_seconds,
        "non_overlapping_phases_seconds": phases,
        "accounted_seconds": accounted,
        "accounting_ratio": accounted / submit_to_output_seconds if submit_to_output_seconds else None,
        "sampler_wall_seconds": sampler_seconds,
        "sampler_gpu_event_span_seconds": sampler_gpu_seconds,
        "sampler_cpu_dispatch_wait_residual_seconds": max(0.0, sampler_seconds - sampler_gpu_seconds),
        "transformer_nested_gpu": {
            "model_forward": timing["model_forward"],
            "leaf_categories": timing["leaf_categories"],
            "model_other_prepost_offload_ms": timing["model_other_prepost_offload_ms"],
            "sampler_non_model_dispatch_wait_ms": timing["sampler_non_model_dispatch_wait_ms"],
            "accounting_ratio": timing["sampler_accounting_ratio"],
        },
        "overlap_rules": {
            "submit_phases": "mutually exclusive WebSocket node spans plus residual",
            "transformer_gpu": "nested inside sampler and excluded from submit-phase sum",
            "resource_samples": "concurrent observations; excluded from all duration sums",
            "cuda_leaf_spans": "mutually exclusive inside model-forward parent spans",
        },
        "memory_transfer_attribution": {
            "exact_model_offload_h2d_seconds": None,
            "exact_model_offload_d2h_seconds": None,
            "activation_transfer_seconds": None,
            "support_status": "not_collected",
            "reason": "Exact transfer-stream attribution requires a profiler trace or synchronization that this bounded profile forbids; transfer and prefetch effects remain in model_other_prepost_offload_ms.",
        },
    }


def _resource_gpu_ledger(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sampler_samples = [sample for sample in samples if str(sample.get("node_id")) == "10"]
    utilization = [
        int(sample["nvidia_gpu_utilization_percent"])
        for sample in sampler_samples
        if isinstance(sample.get("nvidia_gpu_utilization_percent"), int)
    ]
    return {
        "measurement_method": "one-second nvidia-smi samples observed concurrently; not added to CUDA event durations",
        "sampler_sample_count": len(sampler_samples),
        "sampler_utilization_sample_count": len(utilization),
        "sampler_mean_gpu_utilization_percent": sum(utilization) / len(utilization) if utilization else None,
        "sampler_peak_gpu_utilization_percent": max(utilization) if utilization else None,
        "sampler_idle_sample_count": sum(value == 0 for value in utilization),
        "sampler_active_sample_count": sum(value > 0 for value in utilization),
        "sampler_idle_sample_ratio": (
            sum(value == 0 for value in utilization) / len(utilization) if utilization else None
        ),
    }


def _candidate_ranking(ledger: Mapping[str, Any]) -> dict[str, Any]:
    total = float(ledger["accounted_seconds"])
    phases = ledger["non_overlapping_phases_seconds"]
    leaves = ledger["transformer_nested_gpu"]["leaf_categories"]

    def leaf_seconds(name: str) -> float:
        value = leaves.get(name, {}).get("total_ms")
        return float(value) / 1000.0 if isinstance(value, (int, float)) else 0.0

    attention_family = sum(
        leaf_seconds(name)
        for name in (
            "attention_qkv_projection",
            "attention_qk_norm_rope",
            "attention_kernel",
            "attention_output_projection",
        )
    )
    mlp_family = leaf_seconds("mlp_fc1_projection") + leaf_seconds("mlp_activation_fc2_projection")
    vae_encode = float(phases["vae_video_decode"]) + float(phases["vae_audio_decode"]) + float(
        phases["frame_video_encode_mux_save"]
    )
    model_other = float(ledger["transformer_nested_gpu"]["model_other_prepost_offload_ms"]) / 1000.0
    candidates = [
        {
            "candidate": "attention_backend_qkv_rope_out_fusion_ab",
            "surface_seconds": attention_family,
            "surface_share_of_e2e": attention_family / total if total else 0.0,
            "assumed_fraction_removed": 0.20,
            "quality_risk": "low with exact-math backend parity gate; A/B required",
            "rtx3060_12gb": "feasible with Full Compute fallback and no persistent cache",
        },
        {
            "candidate": "model_offload_overlap_and_residency_rearrangement",
            "surface_seconds": model_other,
            "surface_share_of_e2e": model_other / total if total else 0.0,
            "assumed_fraction_removed": 0.50,
            "quality_risk": "none if execution order and tensor values remain exact",
            "rtx3060_12gb": "conditional on measured allocator reserve",
        },
        {
            "candidate": "mlp_projection_activation_fusion",
            "surface_seconds": mlp_family,
            "surface_share_of_e2e": mlp_family / total if total else 0.0,
            "assumed_fraction_removed": 0.20,
            "quality_risk": "low with exact output parity gate",
            "rtx3060_12gb": "feasible",
        },
        {
            "candidate": "vae_decode_encode_mux_pipeline",
            "surface_seconds": vae_encode,
            "surface_share_of_e2e": vae_encode / total if total else 0.0,
            "assumed_fraction_removed": 0.30,
            "quality_risk": "none for overlap; codec changes excluded",
            "rtx3060_12gb": "feasible with bounded staging",
        },
    ]
    for candidate in candidates:
        expected = candidate["surface_share_of_e2e"] * candidate["assumed_fraction_removed"]
        candidate["expected_e2e_reduction"] = expected
        candidate["amdahl_speedup"] = 1.0 / (1.0 - expected) if expected < 1.0 else None
        candidate["tier"] = (
            "TIER_A"
            if expected >= 0.20
            else "TIER_B"
            if expected >= 0.10
            else "TIER_C"
            if expected >= 0.03
            else "AUXILIARY"
            if expected > 0.0
            else "NOT_VIABLE"
        )
    candidates.sort(key=lambda item: (-float(item["expected_e2e_reduction"]), str(item["candidate"])))
    selected = next((item for item in candidates if item["expected_e2e_reduction"] >= 0.10), None)
    return {
        "method": "single-factor Amdahl estimate using measured non-overlapping surface and predeclared conservative removable fraction",
        "candidates": candidates,
        "selected_next_task": selected,
        "standard_architecture_sufficient_for_next_10_percent_candidate": selected is not None,
        "v4_classification": "AUXILIARY",
        "v4_state": "EXPERIMENTAL_AUXILIARY_FROZEN",
        "v4_product_default_enabled": False,
        "v4_executable_plan": None,
        "v4_product_performance_contribution_seconds": 0.0,
    }


def _shutdown_owned_runtime(
    *,
    backend: MiniMaxH3ComfyUIBackend,
    ownership: Mapping[str, Any],
    runtime_pid: int,
    comfyui_root: Path,
    runtime_output: Path,
    base_url: str,
    run_id: str,
    baseline_gpu_bytes: int | None,
) -> dict[str, Any]:
    port = int(base_url.rsplit(":", 1)[1])
    current = build_process_ownership_receipt(
        backend_process=backend._process,
        runtime_pid=runtime_pid,
        comfyui_root=comfyui_root,
        runtime_output=runtime_output,
        host="127.0.0.1",
        port=port,
        run_id=run_id,
        phase="PRE_SHUTDOWN",
    )
    continuity = {
        name: current.get(name) == ownership.get(name)
        for name in (
            "runtime_run_id",
            "launcher_pid",
            "runtime_pid",
            "listener_pid",
            "console_helper_pid",
            "launcher_create_time",
            "console_helper_create_time",
        )
    }
    continuity["tree_identity"] = current.get("process_tree", {}).get(
        "identity_digest"
    ) == ownership.get("process_tree", {}).get("identity_digest")
    if current.get("passed") is not True or not all(continuity.values()):
        return {"passed": False, "pre_shutdown": current, "continuity": continuity}
    descendants = stop_verified_runtime_descendants(current)
    stop = backend.stop_runtime()
    helper = wait_for_console_helper_exit(current.get("console_helper_process"))
    post = build_post_shutdown_receipt(
        run_id=run_id,
        owned_processes=current.get("owned_processes", []),
        host="127.0.0.1",
        port=port,
        baseline_gpu_bytes=baseline_gpu_bytes,
        current_gpu_bytes=_nvidia_memory().get("used_bytes"),
        console_helper_process=current.get("console_helper_process"),
    )
    return {
        "passed": stop.get("stopped") is True and helper.get("passed") is True and post.get("passed") is True,
        "pre_shutdown": current,
        "continuity": continuity,
        "descendant_stop": descendants,
        "stop": stop,
        "console_helper_natural_exit": helper,
        "post_shutdown": post,
        "external_process_termination_count": 0,
    }


def run_probe(
    *,
    run_id: str,
    expected_head: str,
    branch: str,
    p0_database: Path,
    p1_a2_receipt: Path,
    external_product_databases: Sequence[Path],
    input_image: Path,
    private_run_root: Path,
    asset_root: Path,
    comfyui_root: Path,
    workflow_path: Path,
    base_url: str,
) -> dict[str, Any]:
    root = private_run_root.resolve() / run_id
    if root.exists():
        raise ValueError("H3 profile run directory already exists")
    root.mkdir(parents=True)
    callback_path = root / "callback-private.json"
    node_admission_path = root / "node-admission-private.json"
    repository = Path(__file__).resolve().parents[2]
    runtime_output = root / "comfy-output"
    input_digest = sha256(input_image.read_bytes()).hexdigest()
    prompt, prompt_digest = _load_prompt(p0_database)
    run_digest = sha256(run_id.encode()).hexdigest()
    custom_nodes_root = repository / "python" / "hive_product" / "comfyui_nodes"
    config = ComfyUIH3Config(
        asset_root=asset_root.resolve(),
        comfyui_root=comfyui_root.resolve(),
        base_url=base_url.rstrip("/"),
        workflow=workflow_path.resolve(),
        output_root=runtime_output,
        custom_nodes_root=custom_nodes_root,
        poll_interval_seconds=0.5,
        timeout_seconds=3_600.0,
    )
    backend = MiniMaxH3ComfyUIBackend(config=config)
    prior_environment = {
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        RECEIPT_ENV: os.environ.get(RECEIPT_ENV),
        ADMISSION_ENV: os.environ.get(ADMISSION_ENV),
    }
    entries = [str(repository / "python")]
    if prior_environment["PYTHONPATH"]:
        entries.append(str(prior_environment["PYTHONPATH"]))
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)
    os.environ[RECEIPT_ENV] = str(callback_path)
    os.environ[ADMISSION_ENV] = str(node_admission_path)
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": RUN_KIND,
        "started_at": _utc_now(),
        "decision": BLOCKED,
        "input_sha256": input_digest,
        "prompt_sha256": prompt_digest,
        "settings_digest": settings_digest(),
        "submission_count": 0,
        "gpu_start_count": 0,
        "completion_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "attention_omission_count": 0,
        "v4_observer_enabled": False,
        "v4_evidence_transfer_bytes": 0,
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    ownership: Mapping[str, Any] | None = None
    runtime_started = False
    runtime_pid = -1
    baseline_gpu: Mapping[str, Any] | None = None
    submitted = False
    exit_code = 1
    runner_started = time.monotonic()
    runtime_startup_seconds = 0.0
    result_collection_seconds = 0.0
    try:
        source_gate = inspect_installed_source(comfyui_root / MODEL_SOURCE_RELATIVE)
        p1_reference = _p1_a2_profile_receipt(p1_a2_receipt)
        external_jobs = inspect_external_jobs(external_product_databases)
        port = int(base_url.rsplit(":", 1)[1])
        pre_ownership = build_pre_launch_receipt(run_id=run_id, host="127.0.0.1", port=port)
        baseline_gpu = _nvidia_memory()
        start_checks = {
            "head_exact": _git(repository, "rev-parse", "HEAD") == expected_head,
            "remote_head_exact": _git(repository, "rev-parse", f"origin/{branch}") == expected_head,
            "branch_exact": _git(repository, "branch", "--show-current") == branch,
            "worktree_clean": not _git(repository, "status", "--porcelain"),
            "source_exact": source_gate.get("admitted") is True,
            "workflow_exact": sha256(workflow_path.read_bytes()).hexdigest() == APPROVED_WORKFLOW_SHA256,
            "p1_a2_exact": p1_reference.get("passed") is True,
            "input_exact": input_digest == INPUT_SHA256 == p1_reference.get("reference_sha256"),
            "external_jobs_zero": external_jobs.get("active_job_count") == 0,
            "pre_launch_ownership": pre_ownership.get("passed") is True,
            "port_free": not _port_open(base_url),
        }
        receipt["pre_start_admission"] = {
            "checks": start_checks,
            "passed": all(start_checks.values()),
            "source": source_gate,
            "p1_a2": p1_reference,
            "external_jobs": external_jobs,
            "process_ownership": pre_ownership,
            "baseline_gpu": baseline_gpu,
        }
        if not all(start_checks.values()):
            raise RuntimeError("H3 profile pre-start Admission Gate failed")
        runtime_start_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        runtime_startup_seconds = time.monotonic() - runtime_start_started
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("H3 profile requires a fresh owned runtime")
        runtime_started = True
        objects = backend.client.json("GET", "/object_info")
        queue = backend.client.json("GET", "/queue")
        if not node_admission_path.is_file():
            raise RuntimeError("H3 profile node admission receipt is missing")
        node_admission = json.loads(node_admission_path.read_text(encoding="utf-8"))
        runtime_pid = int(node_admission.get("process_id", -1))
        ownership = build_process_ownership_receipt(
            backend_process=backend._process,
            runtime_pid=runtime_pid,
            comfyui_root=comfyui_root,
            runtime_output=runtime_output,
            host="127.0.0.1",
            port=port,
            run_id=run_id,
            phase="POST_LAUNCH",
        )
        post_checks = {
            "node_loaded": isinstance(objects, Mapping) and NODE_CLASS in objects,
            "queue_running_zero": len(queue.get("queue_running", [])) == 0,
            "queue_pending_zero": len(queue.get("queue_pending", [])) == 0,
            "node_admission_pass": node_admission.get("status") == "PASS",
            "v4_observer_disabled": node_admission.get("v4_observer_enabled") is False,
            "v4_transfer_zero": node_admission.get("v4_evidence_transfer_bytes") == 0,
            "ownership_pass": ownership.get("passed") is True,
        }
        receipt["post_start_admission"] = {
            "checks": post_checks,
            "passed": all(post_checks.values()),
            "node": node_admission,
            "process_ownership": ownership,
        }
        if not all(post_checks.values()):
            raise RuntimeError("H3 profile post-start Admission Gate failed")
        input_name = f"hiveframe-profile-{input_digest[:16]}{input_image.suffix.lower()}"
        input_target = runtime_output / "input" / input_name
        shutil.copyfile(input_image, input_target)
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/profile-{input_digest[:12]}",
        )
        workflow = build_workflow(standard, run_digest=run_digest, first_frame_name=input_name)
        if any(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values()):
            raise RuntimeError("H3 profile workflow contains Sage")
        if sum(node.get("class_type") == NODE_CLASS for node in workflow.values()) != 1:
            raise RuntimeError("H3 profile sampler cardinality changed")
        timeline = EventTimeline(workflow)
        resource_sampler = ResourceSampler(backend, timeline)
        resource_sampler.start()
        receipt["submission_count"] = 1
        submitted = True
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        receipt["backend_prompt_id"] = prompt_id
        receipt["gpu_start_count"] = int(bool(timeline.progress_summary().get("records", [])))
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"H3 profile terminal event was {timeline.terminal_event}")
        receipt["completion_count"] = 1
        resource_sampler.stop()
        collection_started = time.monotonic()
        descriptor, content, status = _download_video(backend, history)
        output = root / "standard-h3-profile.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        integrity = bool(
            decode["decoded_frame_count"] == 124
            and (decode["width"], decode["height"]) == (864, 480)
            and decode["fps"] == 24.0
            and decode["codec"] == "h264"
            and decode["audio_stream_count"] >= 1
            and decode["black_frame_count"] == 0
            and decode["corrupted_frame_count"] == 0
            and status == 200
        )
        receipt["output"] = {
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "http_status": status,
            "decode": decode,
            "adjacent_exact_duplicate_frames": _adjacent_duplicate_count(output),
            "integrity_passed": integrity,
            "private_path": str(output),
        }
        if not integrity or not callback_path.is_file():
            raise RuntimeError("H3 profile output or callback integrity failed")
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        result_collection_seconds = time.monotonic() - collection_started
        receipt["callback"] = callback
        receipt["mapping_gate"] = profile_mapping_gate(callback)
        if not receipt["mapping_gate"]["passed"]:
            raise RuntimeError("H3 profile mapping Gate failed")
        submit_seconds = float(timeline.terminal_monotonic - timeline.submitted_monotonic)
        receipt["time_ledger"] = _phase_ledger(
            timeline=timeline,
            callback=callback,
            submit_to_terminal_seconds=submit_seconds,
            result_collection_seconds=result_collection_seconds,
        )
        receipt["candidate_ranking"] = _candidate_ranking(receipt["time_ledger"])
        if receipt["time_ledger"]["accounting_ratio"] < 0.95:
            raise RuntimeError("H3 profile E2E accounting is below 95 percent")
        if receipt["candidate_ranking"]["selected_next_task"] is None:
            receipt["decision"] = ARCHITECTURE_INSUFFICIENT
        else:
            receipt["decision"] = READY
        exit_code = 0
    except Exception as error:
        if submitted:
            receipt["decision"] = FAILED
        receipt["error_type"] = type(error).__name__
        receipt["error_message"] = str(error)[:1000]
    finally:
        if resource_sampler is not None:
            resource_sampler.stop()
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
        if resource_sampler is not None:
            receipt["resource_summary"] = resource_sampler.summary()
            receipt["gpu_active_idle"] = _resource_gpu_ledger(resource_sampler.samples)
            (root / "resource-samples.json").write_text(
                json.dumps(resource_sampler.samples, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if runtime_started and ownership is not None:
            receipt["runtime_shutdown"] = _shutdown_owned_runtime(
                backend=backend,
                ownership=ownership,
                runtime_pid=runtime_pid,
                comfyui_root=comfyui_root,
                runtime_output=runtime_output,
                base_url=base_url,
                run_id=run_id,
                baseline_gpu_bytes=baseline_gpu.get("used_bytes") if baseline_gpu else None,
            )
            if receipt["runtime_shutdown"].get("passed") is not True:
                receipt["decision"] = FAILED if submitted else BLOCKED
                exit_code = 1
        elif runtime_started:
            receipt["runtime_shutdown"] = {"passed": False, "reason": "ownership_not_admitted"}
            exit_code = 1
        for name, value in prior_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        receipt["finished_at"] = _utc_now()
        receipt["runner_metrics"] = {
            "runtime_startup_seconds": runtime_startup_seconds,
            "result_collection_seconds": result_collection_seconds,
            "runner_wall_seconds": time.monotonic() - runner_started,
        }
        receipt["exit_code"] = exit_code
        private_receipt = root / "h3-e2e-profile-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        public_summary = root / "h3-e2e-profile-public-summary.json"
        public_summary.write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
        receipt["public_summary_path"] = str(public_summary)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    ranking = receipt.get("candidate_ranking") if isinstance(receipt.get("candidate_ranking"), Mapping) else {}
    ledger = receipt.get("time_ledger") if isinstance(receipt.get("time_ledger"), Mapping) else {}
    return sanitize_public(
        {
            "run_id": receipt.get("run_id"),
            "decision": receipt.get("decision"),
            "exit_code": receipt.get("exit_code"),
            "submission_count": receipt.get("submission_count"),
            "gpu_start_count": receipt.get("gpu_start_count"),
            "completion_count": receipt.get("completion_count"),
            "retry_count": receipt.get("retry_count"),
            "fallback_count": receipt.get("fallback_count"),
            "accounting_ratio": ledger.get("accounting_ratio"),
            "sampler_wall_seconds": ledger.get("sampler_wall_seconds"),
            "selected_next_task": ranking.get("selected_next_task"),
            "output": receipt.get("output"),
            "error": receipt.get("error_message"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Standard H3 aggregate bottleneck profile.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--p1-a2-receipt", required=True, type=Path)
    parser.add_argument("--external-product-database", action="append", default=[], type=Path)
    parser.add_argument("--input-image", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--comfyui-root", required=True, type=Path)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    args = parser.parse_args(argv)
    receipt = run_probe(
        run_id=args.run_id,
        expected_head=args.expected_head,
        branch=args.branch,
        p0_database=args.p0_database,
        p1_a2_receipt=args.p1_a2_receipt,
        external_product_databases=args.external_product_database,
        input_image=args.input_image,
        private_run_root=args.private_run_root,
        asset_root=args.asset_root,
        comfyui_root=args.comfyui_root,
        workflow_path=args.workflow,
        base_url=args.base_url,
    )
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
