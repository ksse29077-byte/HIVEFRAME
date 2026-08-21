"""One-shot H3 V4 observer Formal CONTROL runner."""

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
import time

import psutil

from .a3_g1_conditional_reuse import (
    CONTROL_MODE,
    IMMUTABLE_STANDARD_SAMPLER_SECONDS,
    IMMUTABLE_STANDARD_SUBMIT_SECONDS,
)
from .a3_g1_h3_conditional_probe import APPROVED_WORKFLOW_SHA256
from .active_query_attention import (
    BLOCK_COUNT,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    inspect_installed_attention_source,
)
from .c0_h3_phase_probe import (
    EventTimeline,
    ResourceSampler,
    _collect_websocket_run,
    measured,
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
from .h3_bounded_host_source_oracle_v4 import (
    CANDIDATE_H2D_HARD_CAP_BYTES,
    FROZEN_EVENTS,
    GPU_STAGING_BUDGET_BYTES,
    HOST_SOURCE_RESIDENT_BYTES,
    MINIMUM_EXACT_RECORDS,
    MINIMUM_PLANNED_Q_RATIO,
    RAM_RESERVE_MIN_BYTES,
    SOURCE_CAPTURE_D2H_BYTES,
    TOTAL_TENSOR_TRANSFER_BYTES,
    TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
    build_memory_admission,
    build_transfer_ledger,
    frozen_inventory_digest,
    model_free_preflight_receipt,
)
from .h3_bounded_host_source_oracle_v4_cuda import run_bounded_cuda_preflight
from .h3_observer_v4 import PROFILE_DIGEST, PROFILE_ID, SOURCE_CAPTURE_COUNT
from .h3_row_region_safety import (
    CACHE_HARD_CAP_BYTES,
    FULL_Q_ROWS,
    generation_candidates,
    generation_identity,
)
from .h3_row_region_safety_control_v2_probe import (
    _adjacent_duplicate_count,
    _download_video,
    _gpu_process_memory,
    _json_safe,
    _load_prompt,
    _nvidia_memory,
    _port_open,
    _replay_signature,
    _utc_now,
    inspect_external_jobs,
)
from .rust_cache_plan_v2 import PLAN_READY, RustCachePlanV2Bridge
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video


SCHEMA_VERSION = "h3.observer-v4.formal-control.runner.1"
NODE_CLASS = "HIVEFRAMEH3ObserverV4ControlSampler"
RECEIPT_ENV = "HIVEFRAME_H3_OBSERVER_V4_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_OBSERVER_V4_ADMISSION"
VALIDATED = "H3_V4_OBSERVER_RUNTIME_AND_FORMAL_CONTROL_VALIDATED"
NOT_VIABLE = "H3_COMPOUND_EYE_PATH_NOT_YET_PRODUCT_VIABLE"
FAILED = "H3_V4_FORMAL_CONTROL_FAILED"
ADMISSION_BLOCKED = "H3_V4_FORMAL_CONTROL_ADMISSION_BLOCKED"
PHYSICAL_VRAM_BYTES = 12_884_377_600
PROJECTED_BASELINE_PEAK_BYTES = 12_514_625_897
EXPECTED_ATTENTION_CALLS = BLOCK_COUNT * 20


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _profile_candidate(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        expected = {"width", "height", "fps", "steps", "seed"}
        if expected.issubset(value) and ("frames" in value or "frame_count" in value):
            return value
        for child in value.values():
            candidate = _profile_candidate(child)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for child in value:
            candidate = _profile_candidate(child)
            if candidate is not None:
                return candidate
    return None


def _p1_a2_profile_receipt(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    profile = _profile_candidate(payload)
    checks = {
        "status_succeeded": payload.get("status") == "succeeded",
        "backend_exact": payload.get("backend") == "minimax_h3_comfyui_local",
        "model_exact": payload.get("model_contract") == "MiniMax-H3",
        "workflow_exact": payload.get("workflow_sha256")
        == APPROVED_WORKFLOW_SHA256,
        "receipt_retry_zero": payload.get("metrics", {}).get("retry_count") == 0,
        "profile_found": profile is not None,
        "width_864": profile is not None and profile.get("width") == 864,
        "height_480": profile is not None and profile.get("height") == 480,
        "frames_124": profile is not None
        and profile.get("frames", profile.get("frame_count")) == 124,
        "fps_24": profile is not None and float(profile.get("fps", -1)) == 24.0,
        "steps_20": profile is not None and profile.get("steps") == 20,
        "seed_101": profile is not None and profile.get("seed") == 101,
        "sampler_fixed": profile is not None
        and profile.get("sampler") == "res_multistep",
        "scheduler_fixed": profile is not None and profile.get("scheduler") == "simple",
        "sage_disabled": profile is not None
        and profile.get("sage_enabled", profile.get("sage_attention")) is False,
    }
    return {
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "reference_sha256": payload.get("reference_sha256"),
        "profile": dict(profile) if profile is not None else None,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    first_frame_name: str,
) -> dict[str, Any]:
    """Replace only the Standard sampler with the CONTROL-only V4 observer."""

    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("V4 CONTROL requires the Standard sampler at node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("V4 CONTROL sampler inputs are malformed")
    inputs.update(
        {
            "mode": CONTROL_MODE,
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": PROFILE_DIGEST,
            "model_revision_digest": MODEL_SOURCE_SHA256,
            "observer_profile_digest": PROFILE_DIGEST,
        }
    )
    sampler["class_type"] = NODE_CLASS
    workflow["16"] = {
        "class_type": "LoadImage",
        "inputs": {"image": first_frame_name},
    }
    workflow["8"]["inputs"]["first_frame"] = ["16", 0]
    return workflow


def _node_seconds(timeline: EventTimeline, node_id: str) -> float | None:
    for item in timeline.node_timeline():
        if item.get("node_id") == node_id:
            value = item.get("observed_wall_seconds")
            return float(value) if isinstance(value, (int, float)) else None
    return None


def _performance_receipt(
    *, callback: Mapping[str, Any], sampler_seconds: float, submit_seconds: float
) -> dict[str, Any]:
    timing = callback["attention_execution"]["v4_oracle"]["timing_ms"]
    full_attention_ms = float(timing.get("full_attention", 0.0))
    observer_ms = float(timing.get("observer", 0.0))
    exact_oracle_ms = float(timing.get("exact_gpu_oracle", 0.0))
    source_d2h_ms = float(timing.get("source_d2h", 0.0))
    candidate_h2d_ms = float(timing.get("candidate_h2d", 0.0))
    projected_saving_upper_ms = full_attention_ms * MINIMUM_PLANNED_Q_RATIO
    production_observer_ms = max(0.0, observer_ms - exact_oracle_ms) + source_d2h_ms
    projected_net_ms = projected_saving_upper_ms - production_observer_ms
    return {
        "historical_standard_sampler_seconds": IMMUTABLE_STANDARD_SAMPLER_SECONDS,
        "historical_standard_submit_to_terminal_seconds": IMMUTABLE_STANDARD_SUBMIT_SECONDS,
        "control_sampler_seconds": sampler_seconds,
        "control_submit_to_terminal_seconds": submit_seconds,
        "actual_sampler_delta_seconds": sampler_seconds
        - IMMUTABLE_STANDARD_SAMPLER_SECONDS,
        "actual_submit_delta_seconds": submit_seconds - IMMUTABLE_STANDARD_SUBMIT_SECONDS,
        "full_attention_gpu_ms": full_attention_ms,
        "observer_gpu_ms": observer_ms,
        "source_d2h_gpu_ms": source_d2h_ms,
        "candidate_h2d_gpu_ms": candidate_h2d_ms,
        "exact_oracle_gpu_ms_control_only": exact_oracle_ms,
        "projected_q_saving_upper_ms": projected_saving_upper_ms,
        "projected_production_observer_cost_ms": production_observer_ms,
        "projected_production_net_ms": projected_net_ms,
        "projected_production_net_positive": projected_net_ms > 0.0,
        "projection_note": (
            "Exact holdout oracle is CONTROL-only and excluded from projected "
            "production observer cost; no SELECTIVE speedup is claimed."
        ),
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
        return {
            "passed": False,
            "pre_shutdown": current,
            "continuity": continuity,
            "stop": {"status": "blocked_unverified_ownership", "stopped": False},
        }
    descendants = stop_verified_runtime_descendants(current)
    stop = backend.stop_runtime()
    helper = wait_for_console_helper_exit(current.get("console_helper_process"))
    post_gpu = _nvidia_memory()
    post = build_post_shutdown_receipt(
        run_id=run_id,
        owned_processes=current.get("owned_processes", []),
        host="127.0.0.1",
        port=port,
        baseline_gpu_bytes=baseline_gpu_bytes,
        current_gpu_bytes=post_gpu.get("used_bytes"),
        console_helper_process=current.get("console_helper_process"),
    )
    return {
        "pre_shutdown": current,
        "continuity": continuity,
        "descendant_stop": descendants,
        "stop": stop,
        "console_helper_natural_exit": helper,
        "post_shutdown": post,
        "external_process_termination_count": 0,
        "passed": bool(
            stop.get("stopped") is True
            and helper.get("passed") is True
            and post.get("passed") is True
        ),
    }


def run_control(
    *,
    run_id: str,
    expected_head: str,
    branch: str,
    p0_database: Path,
    p1_a2_receipt: Path,
    external_product_databases: Sequence[Path],
    input_image: Path,
    input_image_sha256: str,
    private_run_root: Path,
    asset_root: Path,
    comfyui_root: Path,
    workflow_path: Path,
    base_url: str,
    rust_extension_root: Path,
) -> dict[str, Any]:
    root = private_run_root.resolve() / run_id
    if root.exists():
        raise ValueError("V4 Formal CONTROL run directory already exists")
    root.mkdir(parents=True)
    callback_path = root / "callback-private.json"
    node_admission_path = root / "node-admission-private.json"
    repository = Path(__file__).resolve().parents[2]
    runtime_output = root / "comfy-output"
    image_digest = sha256(input_image.read_bytes()).hexdigest()
    prompt, prompt_digest = _load_prompt(p0_database)
    run_digest = sha256(run_id.encode("utf-8")).hexdigest()
    config = ComfyUIH3Config(
        asset_root=asset_root.resolve(),
        comfyui_root=comfyui_root.resolve(),
        base_url=base_url.rstrip("/"),
        workflow=workflow_path.resolve(),
        output_root=runtime_output,
        custom_nodes_root=repository / "python" / "hive_product" / "comfyui_v4_nodes",
        poll_interval_seconds=0.5,
        timeout_seconds=3_600.0,
    )
    backend = MiniMaxH3ComfyUIBackend(config=config)
    source_gate = inspect_installed_attention_source(
        comfyui_root / MODEL_SOURCE_RELATIVE,
        comfyui_root / "comfy/ldm/modules/attention.py",
    )
    prior_environment = {
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        RECEIPT_ENV: os.environ.get(RECEIPT_ENV),
        ADMISSION_ENV: os.environ.get(ADMISSION_ENV),
    }
    python_entries = [str(repository / "python"), str(rust_extension_root.resolve())]
    if prior_environment["PYTHONPATH"]:
        python_entries.append(str(prior_environment["PYTHONPATH"]))
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ[RECEIPT_ENV] = str(callback_path)
    os.environ[ADMISSION_ENV] = str(node_admission_path)

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": _utc_now(),
        "decision": ADMISSION_BLOCKED,
        "starting_head": expected_head,
        "profile": {
            "engine": "H3",
            "mode": "I2V",
            "width": 864,
            "height": 480,
            "frames": 124,
            "fps": 24,
            "steps": 20,
            "seed": 101,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "sage_enabled": False,
            "full_compute": True,
        },
        "profile_id": PROFILE_ID,
        "profile_digest": PROFILE_DIGEST,
        "inventory_digest": frozen_inventory_digest(),
        "input_identity_digest": image_digest,
        "prompt_identity_digest": prompt_digest,
        "submission_count": 0,
        "gpu_start_count": 0,
        "completion_count": 0,
        "retry_count": 0,
        "fallback_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "attention_omission_count": 0,
        "rust_live_compile_count": 0,
        "rust_offline_replay_count": 0,
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    ownership: Mapping[str, Any] | None = None
    runtime_started = False
    runtime_pid = -1
    submitted = False
    baseline_gpu: dict[str, int] | None = None
    started = time.monotonic()
    exit_code = 1
    try:
        head = _git(repository, "rev-parse", "HEAD")
        remote_head = _git(repository, "rev-parse", f"origin/{branch}")
        worktree_clean = not _git(repository, "status", "--porcelain")
        p1_reference = _p1_a2_profile_receipt(p1_a2_receipt)
        external_jobs = inspect_external_jobs(external_product_databases)
        pre_ownership = build_pre_launch_receipt(
            run_id=run_id,
            host="127.0.0.1",
            port=int(base_url.rsplit(":", 1)[1]),
        )
        baseline_gpu = _nvidia_memory()
        baseline_gpu_processes = _gpu_process_memory()
        memory = build_memory_admission(
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
            projected_baseline_peak_bytes=PROJECTED_BASELINE_PEAK_BYTES,
            available_ram_bytes=int(psutil.virtual_memory().available),
        )
        model_free = model_free_preflight_receipt()
        transfer = build_transfer_ledger()
        import torch

        cuda_preflight = run_bounded_cuda_preflight(torch)
        bridge_probe = RustCachePlanV2Bridge()
        checks = {
            "head_exact": head == expected_head,
            "remote_head_exact": remote_head == expected_head,
            "branch_exact": _git(repository, "branch", "--show-current") == branch,
            "worktree_clean": worktree_clean,
            "input_identity_exact": image_digest == input_image_sha256,
            "p1_a2_profile_exact": p1_reference["passed"] is True,
            "p1_a2_input_exact": p1_reference["reference_sha256"] == image_digest,
            "workflow_digest_exact": sha256(workflow_path.read_bytes()).hexdigest()
            == APPROVED_WORKFLOW_SHA256,
            "source_gate": source_gate.get("admitted") is True,
            "external_jobs_zero": external_jobs["active_job_count"] == 0,
            "pre_launch_ownership": pre_ownership.get("passed") is True,
            "foreign_runtime_zero": not pre_ownership.get("candidate_summaries"),
            "port_free": not _port_open(base_url),
            "gpu_idle_within_headroom": baseline_gpu["used_bytes"]
            <= int(memory["physical_vram_headroom_bytes"]),
            "memory_admitted": memory["passed"] is True,
            "model_free_admitted": model_free["passed"] is True,
            "cuda_preflight_admitted": cuda_preflight["passed"] is True,
            "transfer_admitted": transfer["passed"] is True,
            "release_pyo3_loaded": bridge_probe.extension is not None,
            "inventory_exact": len(FROZEN_EVENTS) == MINIMUM_EXACT_RECORDS,
            "source_capture_exact": SOURCE_CAPTURE_COUNT == 208,
        }
        receipt["pre_start_admission"] = {
            "head": head,
            "remote_head": remote_head,
            "p1_a2_reference": p1_reference,
            "external_jobs": external_jobs,
            "process_ownership": pre_ownership,
            "baseline_gpu": baseline_gpu,
            "baseline_gpu_processes": baseline_gpu_processes,
            "memory": memory,
            "model_free": model_free,
            "cuda_preflight": cuda_preflight,
            "transfer": transfer,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if not all(checks.values()):
            raise RuntimeError("V4 pre-start Admission Gate failed")

        receipt["runtime_start"] = backend.start_runtime()
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("V4 CONTROL requires a fresh owned runtime")
        runtime_started = True
        objects = backend.client.json("GET", "/object_info")
        queue = backend.client.json("GET", "/queue")
        if not node_admission_path.is_file():
            raise RuntimeError("V4 node admission receipt is missing")
        node_admission = json.loads(node_admission_path.read_text(encoding="utf-8"))
        runtime_pid = int(node_admission.get("process_id", -1))
        ownership = build_process_ownership_receipt(
            backend_process=backend._process,
            runtime_pid=runtime_pid,
            comfyui_root=comfyui_root,
            runtime_output=runtime_output,
            host="127.0.0.1",
            port=int(base_url.rsplit(":", 1)[1]),
            run_id=run_id,
            phase="POST_LAUNCH",
        )
        post_checks = {
            "node_loaded": isinstance(objects, Mapping) and NODE_CLASS in objects,
            "legacy_v2_node_not_loaded": isinstance(objects, Mapping)
            and "HIVEFRAMEH3RowRegionSafetyControlV2Sampler" not in objects,
            "queue_running_zero": len(queue.get("queue_running", [])) == 0,
            "queue_pending_zero": len(queue.get("queue_pending", [])) == 0,
            "node_admission_pass": node_admission.get("status") == "PASS",
            "source_slots_13": node_admission.get("source_slot_count") == 13,
            "source_page_locked": node_admission.get("source_slots_page_locked") is True,
            "metric_page_locked": node_admission.get("metric_buffer_page_locked") is True,
            "pinned_source_exact": node_admission.get("pinned_source_bytes")
            == HOST_SOURCE_RESIDENT_BYTES,
            "shared_staging_exact": node_admission.get("shared_gpu_staging_budget_bytes")
            == GPU_STAGING_BUDGET_BYTES,
            "ram_reserve": int(node_admission.get("available_ram_after_pinned_bytes", 0))
            >= RAM_RESERVE_MIN_BYTES,
            "ownership_pass": ownership.get("passed") is True,
        }
        receipt["post_start_admission"] = {
            "node": node_admission,
            "process_ownership": ownership,
            "checks": post_checks,
            "passed": all(post_checks.values()),
        }
        if not all(post_checks.values()):
            raise RuntimeError("V4 post-start Admission Gate failed")

        input_name = f"hiveframe-v4-{image_digest[:16]}{input_image.suffix.lower()}"
        target = runtime_output / "input" / input_name
        shutil.copyfile(input_image, target)
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/v4-control-{image_digest[:12]}",
        )
        workflow = build_workflow(
            standard, run_digest=run_digest, first_frame_name=input_name
        )
        if any(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values()):
            raise RuntimeError("V4 CONTROL workflow contains Sage")
        if sum(node.get("class_type") == NODE_CLASS for node in workflow.values()) != 1:
            raise RuntimeError("V4 observer sampler cardinality changed")
        timeline = EventTimeline(workflow)
        resource_sampler = ResourceSampler(backend, timeline)
        resource_sampler.start()
        receipt["submission_count"] = 1
        submitted = True
        prompt_id, history = asyncio.run(
            _collect_websocket_run(backend, workflow, timeline)
        )
        receipt["backend_prompt_id"] = prompt_id
        receipt["gpu_start_count"] = int(
            bool(timeline.progress_summary().get("records", []))
        )
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"V4 terminal event was {timeline.terminal_event}")
        receipt["completion_count"] = 1
        resource_sampler.stop()

        descriptor, content, http_status = _download_video(backend, history)
        output = root / "control-v4.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        duplicates = _adjacent_duplicate_count(output)
        output_pass = bool(
            decode["decoded_frame_count"] == 124
            and (decode["width"], decode["height"]) == (864, 480)
            and decode["fps"] == 24.0
            and decode["codec"] == "h264"
            and decode["black_frame_count"] == 0
            and decode["corrupted_frame_count"] == 0
            and http_status == 200
        )
        receipt["output"] = {
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "http_status": http_status,
            "adjacent_exact_duplicate_frames": duplicates,
            "decode": decode,
            "integrity_passed": output_pass,
            "private_path": str(output),
        }
        if not output_pass or not callback_path.is_file():
            raise RuntimeError("V4 output or callback integrity failed")

        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        execution = callback.get("attention_execution", {})
        safety = execution.get("safety_evidence", {})
        oracle = execution.get("v4_oracle", {})
        confusion = safety.get("confusion_matrix", {})
        execution_checks = {
            "sampler_succeeded": callback.get("sampler_succeeded") is True,
            "lifecycle_complete": execution.get("generation_lifecycle")
            == ["created", "admitted", "observing", "finalizing", "complete"],
            "model_forward_20": execution.get("model_forward_count") == 20,
            "block_calls_exact": execution.get("block_call_count")
            == EXPECTED_ATTENTION_CALLS,
            "full_attention_exact": execution.get("full_attention_calls")
            == EXPECTED_ATTENTION_CALLS,
            "partial_zero": execution.get("partial_attention_calls") == 0,
            "selective_zero": execution.get("selective_execution_count") == 0,
            "omission_zero": execution.get("attention_omission_count") == 0,
            "output_mutation_zero": execution.get("output_mutation_count") == 0,
            "records_199": safety.get("record_count") == MINIMUM_EXACT_RECORDS,
            "complete_untruncated": safety.get("complete") is True
            and safety.get("overflow") is False
            and safety.get("truncated") is False,
            "false_safe_zero": confusion.get("false_safe") == 0,
            "planned_q_at_least_three_percent": float(
                safety.get("planned_q_reduction_ratio", 0.0)
            )
            >= 0.03,
            "source_capture_208": oracle.get("source_capture_count")
            == SOURCE_CAPTURE_COUNT,
            "source_d2h_exact": oracle.get("source_capture_d2h_bytes")
            == SOURCE_CAPTURE_D2H_BYTES,
            "candidate_h2d_within_12gib": int(
                oracle.get("candidate_source_h2d_bytes", CANDIDATE_H2D_HARD_CAP_BYTES + 1)
            )
            <= CANDIDATE_H2D_HARD_CAP_BYTES,
            "total_transfer_exact": oracle.get("total_tensor_transfer_bytes")
            == TOTAL_TENSOR_TRANSFER_BYTES,
            "total_transfer_within_32gib": int(
                oracle.get("total_tensor_transfer_bytes", TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES + 1)
            )
            <= TOTAL_TENSOR_TRANSFER_HARD_CAP_BYTES,
            "metadata_bounded": int(oracle.get("metadata_d2h_bytes", 1024**2 + 1))
            <= 1024**2,
            "oracle_integrity": oracle.get("passed") is True,
            "rust_tensor_zero": safety.get("rust_tensor_transfer_bytes") == 0,
        }
        receipt["callback_instrumentation"] = callback
        receipt["execution_gate"] = {
            "checks": execution_checks,
            "passed": all(execution_checks.values()),
        }
        if not all(execution_checks.values()):
            raise RuntimeError("V4 execution evidence Gate failed")

        identity = generation_identity(
            run_digest_hex=run_digest,
            workflow_digest_hex=APPROVED_WORKFLOW_SHA256,
            model_digest_hex=MODEL_SOURCE_SHA256,
            settings_digest_hex=PROFILE_DIGEST,
            input_identity_digest_hex=image_digest,
        )
        candidates = generation_candidates(identity, safety["records"])
        live_bridge = RustCachePlanV2Bridge()
        receipt["rust_live_compile_count"] = 1
        live_started = time.perf_counter()
        live_plan = live_bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        live_seconds = time.perf_counter() - live_started
        replay_bridge = RustCachePlanV2Bridge()
        receipt["rust_offline_replay_count"] = 1
        replay_started = time.perf_counter()
        replay_plan = replay_bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        replay_seconds = time.perf_counter() - replay_started
        rust_checks = {
            "candidate_count_199": len(candidates) == MINIMUM_EXACT_RECORDS,
            "live_call_once": live_bridge.rust_call_count == 1,
            "replay_call_once": replay_bridge.rust_call_count == 1,
            "plan_ready": live_plan.get("decision_code") == PLAN_READY
            and live_plan.get("fallback_required") is False,
            "planned_q_three_percent": int(live_plan.get("planned_reduction_ppm", 0))
            >= 30_000,
            "cache_within_2gib": int(
                live_plan.get("total_selected_bytes", CACHE_HARD_CAP_BYTES + 1)
            )
            <= CACHE_HARD_CAP_BYTES,
            "deterministic_replay": _replay_signature(live_plan)
            == _replay_signature(replay_plan),
            "rust_tensor_zero": live_plan.get("performance_receipt", {})
            .get("rust_transfer_bytes", {})
            .get("value")
            == 0,
        }
        receipt["generation_evidence_batch"] = {
            "record_count": len(candidates),
            "complete": len(candidates) == MINIMUM_EXACT_RECORDS,
            "overflow": False,
            "tensor_bytes": 0,
        }
        receipt["rust_plan"] = _json_safe(live_plan)
        receipt["rust_replay"] = {
            "checks": rust_checks,
            "passed": all(rust_checks.values()),
            "live_compile_seconds": live_seconds,
            "offline_replay_seconds": replay_seconds,
        }
        if not all(rust_checks.values()):
            raise RuntimeError("V4 Rust live/replay Gate failed")

        sampler_seconds = _node_seconds(timeline, "10")
        submit_seconds = (
            timeline.terminal_monotonic - timeline.submitted_monotonic
            if timeline.terminal_monotonic is not None
            and timeline.submitted_monotonic is not None
            else None
        )
        if sampler_seconds is None or submit_seconds is None:
            raise RuntimeError("V4 runtime timing is incomplete")
        performance = _performance_receipt(
            callback=callback,
            sampler_seconds=sampler_seconds,
            submit_seconds=submit_seconds,
        )
        receipt["performance"] = performance
        receipt["decision"] = (
            VALIDATED
            if performance["projected_production_net_positive"] is True
            else NOT_VIABLE
        )
        exit_code = 0
    except BaseException as error:
        receipt["runner_error"] = type(error).__name__
        receipt["runner_error_message"] = str(error)[:1000]
        receipt["decision"] = FAILED if submitted else ADMISSION_BLOCKED
    finally:
        if resource_sampler is not None:
            resource_sampler.stop()
            receipt["resource_sampling"] = resource_sampler.summary()
        shutdown = {"passed": not runtime_started, "status": "not_started"}
        if runtime_started and ownership is not None:
            try:
                shutdown = _shutdown_owned_runtime(
                    backend=backend,
                    ownership=ownership,
                    runtime_pid=runtime_pid,
                    comfyui_root=comfyui_root,
                    runtime_output=runtime_output,
                    base_url=base_url,
                    run_id=run_id,
                    baseline_gpu_bytes=(baseline_gpu or {}).get("used_bytes"),
                )
            except BaseException as error:
                shutdown = {
                    "passed": False,
                    "error_type": type(error).__name__,
                    "error_message": str(error)[:1000],
                }
        receipt["runtime_shutdown"] = shutdown
        if runtime_started and shutdown.get("passed") is not True:
            receipt["decision"] = FAILED if submitted else ADMISSION_BLOCKED
            exit_code = 1
        for name, value in prior_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        receipt["finished_at"] = _utc_now()
        receipt["exit_code"] = exit_code
        receipt["runner_wall_seconds"] = measured(
            time.monotonic() - started,
            "seconds",
            "runner monotonic span",
            scope="runner entry through owned runtime stop",
        )
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["websocket_terminal_event"] = timeline.terminal_event
            receipt["gpu_start_count"] = int(
                bool(receipt["progress_timeline"].get("records", []))
            )
        if callback_path.is_file() and "callback_instrumentation" not in receipt:
            receipt["callback_instrumentation"] = json.loads(
                callback_path.read_text(encoding="utf-8")
            )
        receipt["final_submission_cardinality"] = {
            "submission": receipt["submission_count"],
            "gpu_start": receipt["gpu_start_count"],
            "completion": receipt["completion_count"],
            "retry": receipt["retry_count"],
            "fallback": receipt["fallback_count"],
        }
        (root / "private-receipt.json").write_text(
            json.dumps(_json_safe(receipt), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (root / "public-summary.json").write_text(
            json.dumps(sanitize_public(_json_safe(receipt)), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exactly one H3 V4 Formal CONTROL.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--p1-a2-receipt", required=True, type=Path)
    parser.add_argument("--external-product-database", action="append", default=[], type=Path)
    parser.add_argument("--input-image", required=True, type=Path)
    parser.add_argument("--input-image-sha256", required=True)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--comfyui-root", required=True, type=Path)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--rust-extension-root", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_control(
        run_id=args.run_id,
        expected_head=args.expected_head,
        branch=args.branch,
        p0_database=args.p0_database,
        p1_a2_receipt=args.p1_a2_receipt,
        external_product_databases=args.external_product_database,
        input_image=args.input_image,
        input_image_sha256=args.input_image_sha256,
        private_run_root=args.private_run_root,
        asset_root=args.asset_root,
        comfyui_root=args.comfyui_root,
        workflow_path=args.workflow,
        base_url=args.base_url,
        rust_extension_root=args.rust_extension_root,
    )
    print(json.dumps(sanitize_public(_json_safe(result)), sort_keys=True))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
