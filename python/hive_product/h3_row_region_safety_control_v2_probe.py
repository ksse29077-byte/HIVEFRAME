"""One-shot H3 Full Compute CONTROL V2 runner with fail-closed admission."""

from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode
import argparse
import asyncio
import copy
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import psutil

from .a3_g1_conditional_reuse import CONTROL_MODE
from .a3_g1_h3_conditional_probe import APPROVED_WORKFLOW_SHA256
from .active_query_attention import (
    BLOCK_COUNT,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    inspect_installed_attention_source,
)
from .c0_h3_phase_probe import EventTimeline, ResourceSampler, _collect_websocket_run, measured, sanitize_public
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .comfyui_process_ownership import (
    build_post_shutdown_receipt,
    build_pre_launch_receipt,
    build_process_ownership_receipt,
    collect_comfy_runtime_processes,
    stop_verified_runtime_descendants,
    wait_for_console_helper_exit,
)
from .h3_hybrid_cache_staging import (
    CONTROL_ORACLE_D2H_BYTES,
    CONTROL_TRANSFER_LIMIT_BYTES,
    HOST_OS_COMFY_RESERVE_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PHYSICAL_VRAM_BYTES,
    CANDIDATE_SLOT_BYTES,
    PINNED_RING_DEPTH,
    PINNED_HOST_TOTAL_BYTES,
    TRACE_MEASURED_MAX_IN_FLIGHT,
    build_runtime_admission,
)
from .h3_row_region_safety import CACHE_HARD_CAP_BYTES, FULL_Q_ROWS, MAX_EVIDENCE_RECORDS, generation_candidates, generation_identity
from .h3_row_region_safety_v2 import (
    CANDIDATE_BLOCKS,
    EXPECTED_ENQUEUE_COUNT,
    EXPECTED_RECORD_COUNT,
    HOLDOUT_LABEL,
    evidence_design_receipt,
    settings_digest,
)
from .h3_row_region_safety_v2_preflight import READY as ORACLE_PREFLIGHT_READY
from .rust_cache_plan_v2 import PLAN_READY, RustCachePlanV2Bridge
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video


SCHEMA_VERSION = "h3.row-region-safety-control-v2.runner.1"
NODE_CLASS = "HIVEFRAMEH3RowRegionSafetyControlV2Sampler"
RECEIPT_ENV = "HIVEFRAME_H3_ROW_REGION_V2_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_ROW_REGION_V2_ADMISSION"
LINEAGE_CAPSULE_ENV = "HIVEFRAME_H3_LINEAGE_DIAGNOSTIC_CAPSULE"
READY = "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_READY_FOR_EXECUTOR_INTEGRATION"
FAILED = "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_FAILED"
ADMISSION_BLOCKED = "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED"
PROJECTED_CUDA_PEAK_BYTES = 12_514_625_897
MINIMUM_VRAM_HEADROOM_BYTES = 256 * 1024**2
PREFLIGHT_AVAILABLE_RAM_BYTES = 47_136_583_680
RTX_3060_LUID_FRAGMENT = "luid_0x00000000_0x000114d9"
FROZEN_PLAN_SETTINGS_SHA256 = "7b9852657c88d433ba03a2ed4e91ad0817ae44cc8df686dff9528da728983757"


def _cardinality_receipt(
    writes: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    enqueue_by_step = Counter(int(item["step"]) for item in writes)
    enqueue_by_block = Counter(int(item["block"]) for item in writes)
    evidence_by_step = Counter(int(item["step"]) for item in records)
    evidence_by_block = Counter(int(item["block"]) for item in records)
    evidence_by_region = Counter(int(item["region"]) for item in records)
    expected_enqueue_by_step = {step: len(CANDIDATE_BLOCKS) for step in range(20)}
    expected_enqueue_by_block = {block: 20 for block in CANDIDATE_BLOCKS}
    expected_evidence_by_step = {step: len(CANDIDATE_BLOCKS) for step in range(2, 18)}
    expected_evidence_by_block = {block: 16 for block in CANDIDATE_BLOCKS}
    expected_evidence_by_region = {0: EXPECTED_RECORD_COUNT}

    def plain(counter: Counter[int]) -> dict[int, int]:
        return dict(sorted(counter.items()))

    actual = {
        "enqueue_by_step": plain(enqueue_by_step),
        "enqueue_by_block": plain(enqueue_by_block),
        "evidence_by_step": plain(evidence_by_step),
        "evidence_by_block": plain(evidence_by_block),
        "evidence_by_region": plain(evidence_by_region),
    }
    expected = {
        "enqueue_by_step": expected_enqueue_by_step,
        "enqueue_by_block": expected_enqueue_by_block,
        "evidence_by_step": expected_evidence_by_step,
        "evidence_by_block": expected_evidence_by_block,
        "evidence_by_region": expected_evidence_by_region,
    }
    checks = {name + "_exact": actual[name] == expected[name] for name in expected}
    return {"expected": expected, "actual": actual, "checks": checks, "passed": all(checks.values())}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _load_prompt(database: Path) -> tuple[str, str]:
    if not database.is_file():
        raise ValueError("private P1-A2 database is unavailable")
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            """
            SELECT prompt FROM jobs
            WHERE backend = ? AND status = ? AND profile = ?
              AND generation_mode = ? AND reference_asset_id IS NOT NULL
            ORDER BY created_at
            """,
            ("minimax_h3_comfyui_local", "succeeded", "standard", "image_to_video"),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0].strip():
        raise ValueError("private database must identify exactly one P1-A2 Standard I2V prompt")
    prompt = rows[0][0].strip()
    return prompt, sha256(prompt.encode()).hexdigest()


def inspect_external_jobs(databases: Sequence[Path]) -> dict[str, Any]:
    states: dict[str, int] = {}
    checked = 0
    for database in databases:
        if not database.is_file():
            raise ValueError("an external product database is unavailable")
        connection = sqlite3.connect(database)
        try:
            for state, count in connection.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
                states[str(state)] = states.get(str(state), 0) + int(count)
            checked += 1
        finally:
            connection.close()
    active = sum(states.get(name, 0) for name in ("queued", "running", "pending"))
    return {"database_count": checked, "states": states, "active_job_count": active}


def inspect_comfy_processes() -> list[dict[str, Any]]:
    return list(collect_comfy_runtime_processes()["candidate_summaries"])


def _port_open(base_url: str) -> bool:
    port = int(base_url.rsplit(":", 1)[1])
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _nvidia_memory() -> dict[str, int]:
    executable = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    result = subprocess.run(
        [executable, "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    total_mib, used_mib = [int(value.strip()) for value in result.stdout.splitlines()[0].split(",")]
    return {"total_bytes": total_mib * 1024**2, "used_bytes": used_mib * 1024**2}


def _gpu_process_memory() -> list[dict[str, int]]:
    powershell = shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    script = (
        "Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage' "
        "-ErrorAction Stop | Select-Object -ExpandProperty CounterSamples | "
        "Select-Object InstanceName,CookedValue | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    decoded = json.loads(result.stdout or "[]")
    samples = decoded if isinstance(decoded, list) else [decoded]
    by_pid: dict[int, int] = {}
    for sample in samples:
        instance = str(sample.get("InstanceName", ""))
        if RTX_3060_LUID_FRAGMENT not in instance.lower():
            continue
        match = re.search(r"pid_(\d+)", instance, re.IGNORECASE)
        if match is None:
            continue
        pid = int(match.group(1))
        by_pid[pid] = by_pid.get(pid, 0) + max(0, round(float(sample["CookedValue"])))
    return [
        {"pid": pid, "dedicated_bytes": dedicated}
        for pid, dedicated in sorted(by_pid.items())
    ]


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]], *, run_digest: str, first_frame_name: str
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("CONTROL V2 requires the Standard sampler at node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("CONTROL V2 sampler inputs are malformed")
    inputs.update(
        {
            "mode": CONTROL_MODE,
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest(),
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    sampler["class_type"] = NODE_CLASS
    workflow["16"] = {"class_type": "LoadImage", "inputs": {"image": first_frame_name}}
    workflow["8"]["inputs"]["first_frame"] = ["16", 0]
    return workflow


def _download_video(backend: MiniMaxH3ComfyUIBackend, history: Mapping[str, Any]) -> tuple[dict[str, Any], bytes, int]:
    descriptor = backend._find_video_descriptor(history.get("outputs"))
    if descriptor is None:
        raise RuntimeError("ComfyUI history contains no video output")
    filename = descriptor.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise RuntimeError("ComfyUI returned an unsafe output filename")
    query = urlencode(
        {
            "filename": filename,
            "subfolder": descriptor.get("subfolder", ""),
            "type": descriptor.get("type", "output"),
        }
    )
    content = backend.client.bytes("/view?" + query)
    if not content:
        raise RuntimeError("ComfyUI returned an empty output")
    return dict(descriptor), content, 200


def _adjacent_duplicate_count(path: Path) -> int:
    import av

    previous: bytes | None = None
    duplicates = 0
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            current = frame.to_ndarray(format="rgb24").tobytes()
            duplicates += int(previous == current)
            previous = current
    return duplicates


def _replay_signature(plan: Mapping[str, Any]) -> dict[str, Any]:
    return _json_safe(
        {
            key: plan.get(key)
            for key in (
                "selected",
                "rejected",
                "eviction_order",
                "total_selected_bytes",
                "total_planned_q_rows",
                "total_full_q_rows",
                "planned_reduction_ppm",
                "total_planned_d2h_bytes",
                "total_planned_h2d_bytes",
                "plan_digest",
                "lineage_digest",
            )
        }
    )


def run_control(
    *,
    run_id: str,
    p0_database: Path,
    external_product_databases: Sequence[Path],
    input_image: Path,
    input_image_sha256: str,
    private_run_root: Path,
    asset_root: Path,
    comfyui_root: Path,
    workflow_path: Path,
    base_url: str,
    rust_extension_root: Path,
    synthetic_receipt: Path,
    verification_receipt: Path,
    lineage_diagnostic: bool = False,
) -> dict[str, Any]:
    root = private_run_root.resolve() / run_id
    if root.exists():
        raise ValueError("private CONTROL V2 run directory already exists")
    root.mkdir(parents=True)
    callback_path = root / "callback-private.json"
    node_admission_path = root / "node-admission-private.json"
    lineage_capsule_path = root / "lineage-diagnostic-capsule.json"
    image_digest = sha256(input_image.read_bytes()).hexdigest()
    if image_digest != input_image_sha256:
        raise RuntimeError("P1-A2 input image identity changed")
    prompt, prompt_digest = _load_prompt(p0_database)
    synthetic = json.loads(synthetic_receipt.read_text(encoding="utf-8"))
    verification = json.loads(verification_receipt.read_text(encoding="utf-8-sig"))
    repository_root = Path(__file__).resolve().parents[2]
    runtime_output = root / "comfy-output"
    config = ComfyUIH3Config(
        asset_root=asset_root.resolve(),
        comfyui_root=comfyui_root.resolve(),
        base_url=base_url.rstrip("/"),
        workflow=workflow_path.resolve(),
        output_root=runtime_output,
        custom_nodes_root=repository_root / "python" / "hive_product" / "comfyui_nodes",
        poll_interval_seconds=0.5,
        timeout_seconds=3_600.0,
    )
    backend = MiniMaxH3ComfyUIBackend(config=config)
    run_digest = sha256(run_id.encode()).hexdigest()
    model_source = comfyui_root / MODEL_SOURCE_RELATIVE
    source_gate = inspect_installed_attention_source(
        model_source, comfyui_root / "comfy/ldm/modules/attention.py"
    )
    prior_environment = {
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        RECEIPT_ENV: os.environ.get(RECEIPT_ENV),
        ADMISSION_ENV: os.environ.get(ADMISSION_ENV),
        LINEAGE_CAPSULE_ENV: os.environ.get(LINEAGE_CAPSULE_ENV),
    }
    python_entries = [str(repository_root / "python"), str(rust_extension_root.resolve())]
    if prior_environment["PYTHONPATH"]:
        python_entries.append(str(prior_environment["PYTHONPATH"]))
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ[RECEIPT_ENV] = str(callback_path)
    os.environ[ADMISSION_ENV] = str(node_admission_path)
    if lineage_diagnostic:
        os.environ[LINEAGE_CAPSULE_ENV] = str(lineage_capsule_path)
    else:
        os.environ.pop(LINEAGE_CAPSULE_ENV, None)

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": _utc_now(),
        "decision": ADMISSION_BLOCKED,
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
        "input_identity_digest": image_digest,
        "prompt_identity_digest": prompt_digest,
        "source_admission": source_gate,
        "evidence_design": evidence_design_receipt(),
        "submission_count": 0,
        "gpu_start_count": 0,
        "completion_count": 0,
        "retry_count": 0,
        "fallback_generation_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "attention_omission_count": 0,
        "rust_live_compile_count": 0,
        "rust_offline_replay_count": 0,
        "lineage_diagnostic_only": lineage_diagnostic,
        "diagnostic_h3_submission_count": 0,
        "diagnostic_gpu_start_count": 0,
        "valid_control_result_count": 0 if lineage_diagnostic else None,
    }
    timeline: EventTimeline | None = None
    sampler: ResourceSampler | None = None
    submitted = False
    runtime_started = False
    owned_runtime_pid = -1
    baseline_gpu: dict[str, int] | None = None
    baseline_gpu_processes: list[dict[str, int]] = []
    post_launch_ownership: dict[str, Any] | None = None
    runner_started = time.monotonic()
    exit_code = 1
    try:
        external_jobs = inspect_external_jobs(external_product_databases)
        pre_launch_ownership = build_pre_launch_receipt(
            run_id=run_id,
            host="127.0.0.1",
            port=int(base_url.rsplit(":", 1)[1]),
        )
        foreign_comfy = pre_launch_ownership["candidate_summaries"]
        baseline_gpu = _nvidia_memory()
        baseline_gpu_processes = _gpu_process_memory()
        projected_headroom = PHYSICAL_VRAM_BYTES - PROJECTED_CUDA_PEAK_BYTES
        admission_projection = build_runtime_admission(
            physical_ram_bytes=int(psutil.virtual_memory().total),
            current_available_ram_bytes=int(psutil.virtual_memory().available),
            physical_vram_bytes=PHYSICAL_VRAM_BYTES,
        )
        synthetic_checks = {
            "passed": synthetic.get("decision") == ORACLE_PREFLIGHT_READY,
            "bf16_bit_preserved": synthetic.get("bf16_bit_preserved") is True,
            "metric_error_at_most_1e_6": float(
                synthetic.get("cpu_gpu_metric_max_abs_error", 1.0)
            ) <= 1e-6,
            "real_row_map": synthetic.get("representative_row_count") == 1036
            and synthetic.get("omitted_row_count") == 2331,
            "hot_sync_zero": synthetic.get("hot_path_forced_sync_zero") is True,
        }
        verification_checks = {
            "release_pyo3_loaded": verification.get("release_pyo3_loaded") is True,
            "pyo3_tests_15": verification.get("pyo3_tests_passed") == 15,
            "pyo3_skips_zero": verification.get("pyo3_tests_skipped") == 0,
            "rust_cache_plan_tests_12": verification.get("rust_cache_plan_tests_passed") == 12,
            "rust_tensor_bytes_zero": verification.get("rust_tensor_bytes") == 0,
            "rust_calls_per_generation_max_one": verification.get("rust_calls_per_generation_max") == 1,
            "rust_hot_path_calls_zero": all(
                verification.get(name) == 0
                for name in ("rust_calls_per_block", "rust_calls_per_region", "rust_calls_per_row")
            ),
        }
        worktree_clean = not subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        inventory_checks = {
            "candidate_blocks_exact": tuple(CANDIDATE_BLOCKS) == tuple(range(30)),
            "expected_enqueue_exact": EXPECTED_ENQUEUE_COUNT == 600,
            "expected_evidence_exact": EXPECTED_RECORD_COUNT == 480,
            "ring_slots_exact": PINNED_RING_DEPTH == 4,
            "slot_bytes_exact": CANDIDATE_SLOT_BYTES == 48_269_312,
            "pinned_ring_bytes_exact": PINNED_HOST_TOTAL_BYTES == 193_077_248,
            "plan_settings_digest_exact": settings_digest()
            == FROZEN_PLAN_SETTINGS_SHA256,
        }
        pre_start_checks = {
            "worktree_clean": worktree_clean,
            "external_jobs_zero": external_jobs["active_job_count"] == 0,
            "foreign_comfy_process_zero": len(foreign_comfy) == 0,
            "dedicated_port_free": not _port_open(base_url),
            "source_gate": source_gate.get("admitted") is True,
            "workflow_digest": sha256(workflow_path.read_bytes()).hexdigest() == APPROVED_WORKFLOW_SHA256,
            "projected_peak_below_physical": PROJECTED_CUDA_PEAK_BYTES < PHYSICAL_VRAM_BYTES,
            "headroom_at_least_256_mib": projected_headroom >= MINIMUM_VRAM_HEADROOM_BYTES,
            "fragmentation_guard": baseline_gpu["used_bytes"] <= projected_headroom,
            "gpu_process_counter_available": bool(baseline_gpu_processes),
            "balanced_projection_pass": admission_projection["control_submission_allowed"] is True,
            "synthetic_oracle_pass": all(synthetic_checks.values()),
            "release_pyo3_and_rust_pass": all(verification_checks.values()),
            "pre_launch_ownership_pass": pre_launch_ownership["passed"] is True,
            "candidate_inventory_and_plan_pass": all(inventory_checks.values()),
        }
        receipt["pre_start_admission"] = {
            "external_jobs": external_jobs,
            "foreign_comfy_processes": foreign_comfy,
            "baseline_gpu": baseline_gpu,
            "baseline_gpu_processes": baseline_gpu_processes,
            "physical_vram_bytes": PHYSICAL_VRAM_BYTES,
            "projected_cuda_peak_bytes": PROJECTED_CUDA_PEAK_BYTES,
            "projected_headroom_bytes": projected_headroom,
            "two_gib_reserve_satisfied": False,
            "projection": admission_projection,
            "synthetic": synthetic_checks,
            "release_verification": verification_checks,
            "process_ownership": pre_launch_ownership,
            "candidate_inventory_and_plan": inventory_checks,
            "checks": pre_start_checks,
            "passed": all(pre_start_checks.values()),
        }
        if not all(pre_start_checks.values()):
            raise RuntimeError("pre-start runtime admission failed")

        receipt["runtime_start"] = backend.start_runtime()
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("CONTROL V2 requires a fresh owned runtime")
        runtime_started = True
        objects = backend.client.json("GET", "/object_info")
        queue = backend.client.json("GET", "/queue")
        if not node_admission_path.is_file():
            raise RuntimeError("pinned-host admission receipt is missing")
        node_admission = json.loads(node_admission_path.read_text(encoding="utf-8"))
        host_available = int(node_admission.get("available_ram_after_pinned_bytes", 0))
        owned_runtime_pid = int(node_admission.get("process_id", -1))
        ownership = build_process_ownership_receipt(
            backend_process=backend._process,
            runtime_pid=owned_runtime_pid,
            comfyui_root=comfyui_root,
            runtime_output=runtime_output,
            host="127.0.0.1",
            port=int(base_url.rsplit(":", 1)[1]),
            run_id=run_id,
            phase="POST_LAUNCH",
        )
        post_launch_ownership = ownership
        post_launch_gpu_processes = _gpu_process_memory()
        baseline_external_gpu_bytes = sum(
            item["dedicated_bytes"] for item in baseline_gpu_processes
        )
        post_launch_external_gpu_bytes = sum(
            item["dedicated_bytes"]
            for item in post_launch_gpu_processes
            if item["pid"] != owned_runtime_pid
        )
        post_start_checks = {
            "node_loaded": isinstance(objects, Mapping) and NODE_CLASS in objects,
            "queue_running_zero": isinstance(queue, Mapping) and len(queue.get("queue_running", [])) == 0,
            "queue_pending_zero": isinstance(queue, Mapping) and len(queue.get("queue_pending", [])) == 0,
            "pinned_allocation_pass": node_admission.get("status") == "PASS",
            "page_locked": node_admission.get("page_locked") is True,
            "pinned_bytes_exact": node_admission.get("pinned_host_bytes") == PINNED_HOST_TOTAL_BYTES,
            "ring_slots_exact": node_admission.get("ring_capacity", {}).get("required_slots")
            == PINNED_RING_DEPTH,
            "slot_bytes_exact": node_admission.get("slot_bytes") == CANDIDATE_SLOT_BYTES,
            "initial_slot_states_all_free": node_admission.get("slot_states")
            == ["FREE"] * PINNED_RING_DEPTH,
            "host_reserve_after_future_source_cache": host_available - HOST_SOURCE_CACHE_BYTES >= HOST_OS_COMFY_RESERVE_BYTES,
            "external_gpu_usage_not_increased": post_launch_external_gpu_bytes
            <= baseline_external_gpu_bytes,
            "persistent_full_source_cuda_zero": admission_projection["balanced_12gb"][
                "persistent_full_source_cuda_bytes"
            ]
            == 0,
            "allocator_admission_pass": admission_projection["control_submission_allowed"] is True,
            "owned_runtime_receipt_pass": ownership["passed"] is True,
        }
        receipt["post_start_admission"] = {
            "node": node_admission,
            "owned_runtime_pid": owned_runtime_pid,
            "process_ownership": ownership,
            "available_after_future_source_cache_bytes": host_available - HOST_SOURCE_CACHE_BYTES,
            "host_available_change_from_preflight_bytes": host_available
            - PREFLIGHT_AVAILABLE_RAM_BYTES,
            "post_launch_gpu_processes": post_launch_gpu_processes,
            "baseline_external_gpu_bytes": baseline_external_gpu_bytes,
            "post_launch_external_gpu_bytes": post_launch_external_gpu_bytes,
            "checks": post_start_checks,
            "passed": all(post_start_checks.values()),
        }
        if not all(post_start_checks.values()):
            raise RuntimeError("post-start runtime admission failed")

        input_name = f"hiveframe-reference-{image_digest[:16]}{input_image.suffix.lower()}"
        target = runtime_output / "input" / input_name
        shutil.copyfile(input_image, target)
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/control-v2-{image_digest[:12]}",
        )
        workflow = build_workflow(standard, run_digest=run_digest, first_frame_name=input_name)
        if sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values()) != 0:
            raise RuntimeError("CONTROL V2 workflow contains Sage")
        timeline = EventTimeline(workflow)
        sampler = ResourceSampler(backend, timeline)
        sampler.start()
        receipt["submission_count"] = 1
        receipt["diagnostic_h3_submission_count"] = int(lineage_diagnostic)
        submitted = True
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        receipt["backend_prompt_id"] = prompt_id
        receipt["gpu_start_count"] = int(bool(timeline.progress_summary().get("records", [])))
        receipt["diagnostic_gpu_start_count"] = (
            receipt["gpu_start_count"] if lineage_diagnostic else 0
        )
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        if lineage_diagnostic:
            raise RuntimeError(
                "diagnostic node returned success instead of a fail-closed terminal"
            )
        receipt["completion_count"] = 1
        sampler.stop()

        descriptor, content, http_status = _download_video(backend, history)
        output = root / "control-v2.mp4"
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
            "download_passed": bool(content),
            "adjacent_exact_duplicate_frames": duplicates,
            "decode": decode,
            "integrity_passed": output_pass,
            "private_path": str(output),
        }
        if not output_pass or not callback_path.is_file():
            raise RuntimeError("CONTROL V2 output or callback integrity failed")

        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        execution = callback.get("attention_execution", {})
        safety = execution.get("safety_evidence", {})
        oracle = execution.get("hybrid_oracle", {})
        confusion = safety.get("confusion_matrix", {})
        cardinality = _cardinality_receipt(
            oracle.get("ring_write_sequence", []), safety.get("records", [])
        )
        final_slot_states = oracle.get("final_slot_states")
        execution_checks = {
            "sampler_succeeded": callback.get("sampler_succeeded") is True,
            "model_forward_count": execution.get("model_forward_count") == 20,
            "block_call_count": execution.get("block_call_count") == BLOCK_COUNT * 20,
            "full_attention_calls": execution.get("full_attention_calls") == BLOCK_COUNT * 20,
            "partial_attention_zero": execution.get("partial_attention_calls") == 0,
            "enqueue_count_exact": oracle.get("enqueue_count") == EXPECTED_ENQUEUE_COUNT,
            "records_complete": safety.get("record_count") == EXPECTED_RECORD_COUNT,
            "records_bounded": int(safety.get("record_count", MAX_EVIDENCE_RECORDS + 1)) <= MAX_EVIDENCE_RECORDS,
            "false_safe_zero": confusion.get("false_safe") == 0,
            "false_unsafe_collected": safety.get("false_unsafe_status") == "COLLECTED",
            "nonfinite_zero": oracle.get("nonfinite_count") == 0,
            "truncated_evidence_zero": safety.get("overflow") is False,
            "incomplete_evidence_zero": oracle.get("incomplete_record_count") == 0,
            "d2h_exact": oracle.get("d2h_bytes") == CONTROL_ORACLE_D2H_BYTES,
            "d2h_within_limit": int(oracle.get("d2h_bytes", CONTROL_TRANSFER_LIMIT_BYTES + 1)) <= CONTROL_TRANSFER_LIMIT_BYTES,
            "h2d_zero": oracle.get("h2d_bytes") == 0,
            "persistent_gpu_source_zero": oracle.get("persistent_gpu_source_bytes") == 0,
            "hot_sync_zero": oracle.get("hot_path_forced_sync_count") == 0,
            "ring_clean": all(
                oracle.get(name) == 0
                for name in (
                    "ring_backpressure_count",
                    "ring_overflow_count",
                    "ring_overwrite_count",
                    "evidence_drop_count",
                    "duplicate_d2h_count",
                    "lineage_mismatch_count",
                )
            ),
            "final_backlog_zero": oracle.get("final_backlog") == 0,
            "final_slot_states_all_free": final_slot_states
            == ["FREE"] * PINNED_RING_DEPTH,
            "ring_high_water_bounded": isinstance(oracle.get("ring_high_water_mark"), int)
            and 0
            < int(oracle["ring_high_water_mark"])
            <= TRACE_MEASURED_MAX_IN_FLIGHT,
            "cardinality_exact": cardinality["passed"] is True,
            "producer_arrival_rate_measured": isinstance(
                oracle.get("producer_arrival_rate_records_per_second"), (int, float)
            ),
            "worker_service_rate_measured": isinstance(
                oracle.get("worker_service_rate_records_per_second"), (int, float)
            ),
            "cuda_completion_event_not_used_for_timing": oracle.get(
                "d2h_timing_telemetry", {}
            ).get("completion_event_elapsed_time_count")
            == 0,
            "source_cache_cap": int(oracle.get("source_cache_bytes", CACHE_HARD_CAP_BYTES + 1)) <= CACHE_HARD_CAP_BYTES,
        }
        receipt["callback_instrumentation"] = callback
        receipt["evidence_cardinality"] = cardinality
        receipt["execution_gate"] = {"checks": execution_checks, "passed": all(execution_checks.values())}
        if not all(execution_checks.values()):
            raise RuntimeError("CONTROL V2 execution evidence Gate failed")

        identity = generation_identity(
            run_digest_hex=run_digest,
            workflow_digest_hex=APPROVED_WORKFLOW_SHA256,
            model_digest_hex=MODEL_SOURCE_SHA256,
            settings_digest_hex=settings_digest(),
            input_identity_digest_hex=image_digest,
        )
        candidates = generation_candidates(identity, safety["records"])
        for record, candidate in zip(safety["records"], candidates):
            record["complete_lineage_digest"] = candidate["lineage_digest"].hex()
        bridge = RustCachePlanV2Bridge()
        receipt["rust_live_compile_count"] = 1
        rust_live_started = time.perf_counter()
        live_plan = bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        rust_live_seconds = time.perf_counter() - rust_live_started
        replay_bridge = RustCachePlanV2Bridge()
        receipt["rust_offline_replay_count"] = 1
        rust_replay_started = time.perf_counter()
        replay_plan = replay_bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        rust_replay_seconds = time.perf_counter() - rust_replay_started
        planned_transfer = int(live_plan.get("total_planned_d2h_bytes", 0)) + int(live_plan.get("total_planned_h2d_bytes", 0))
        plan_checks = {
            "release_extension_loaded": bridge.extension is not None,
            "live_call_once": bridge.rust_call_count == 1,
            "offline_call_once": replay_bridge.rust_call_count == 1,
            "plan_ready": live_plan.get("decision_code") == PLAN_READY and live_plan.get("fallback_required") is False,
            "planned_q_at_least_three_percent": int(live_plan.get("planned_reduction_ppm", 0)) >= 30_000,
            "selected_cache_at_most_two_gib": int(live_plan.get("total_selected_bytes", CACHE_HARD_CAP_BYTES + 1)) <= CACHE_HARD_CAP_BYTES,
            "selected_transfer_at_most_40_gib": planned_transfer <= 40 * 1024**3,
            "deterministic_replay": _replay_signature(live_plan) == _replay_signature(replay_plan),
            "rust_tensor_zero": live_plan.get("performance_receipt", {}).get("rust_transfer_bytes", {}).get("value") == 0,
            "selected_candidates_identified": bool(live_plan.get("selected")),
        }
        receipt["generation_evidence_batch"] = {
            "label": HOLDOUT_LABEL,
            "record_count": len(candidates),
            "maximum_records": MAX_EVIDENCE_RECORDS,
            "complete": len(candidates) == EXPECTED_RECORD_COUNT,
            "overflow": False,
            "tensor_bytes": 0,
        }
        receipt["rust_plan"] = _json_safe(live_plan)
        receipt["rust_replay"] = {
            "checks": plan_checks,
            "passed": all(plan_checks.values()),
            "live_digest": _json_safe(live_plan.get("plan_digest")),
            "replay_digest": _json_safe(replay_plan.get("plan_digest")),
            "live_compile_seconds": rust_live_seconds,
            "offline_replay_seconds": rust_replay_seconds,
        }
        if not all(plan_checks.values()):
            raise RuntimeError("Rust CachePlan ABI V2 holdout Gate failed")
        receipt["decision"] = READY
        exit_code = 0
    except BaseException as error:
        receipt["runner_error"] = type(error).__name__
        receipt["runner_error_message"] = str(error)[:1000]
        receipt["decision"] = FAILED if submitted else ADMISSION_BLOCKED
    finally:
        if sampler is not None:
            sampler.stop()
            resource_summary = sampler.summary()
            peak_vram = resource_summary.get("peak_nvidia_system_sampled_vram_bytes")
            resource_summary["physical_vram_headroom_bytes"] = (
                PHYSICAL_VRAM_BYTES - int(peak_vram) if isinstance(peak_vram, int) else None
            )
            receipt["resource_sampling"] = resource_summary
        shutdown_passed = True
        if runtime_started:
            try:
                pre_shutdown = build_process_ownership_receipt(
                    backend_process=backend._process,
                    runtime_pid=owned_runtime_pid,
                    comfyui_root=comfyui_root,
                    runtime_output=runtime_output,
                    host="127.0.0.1",
                    port=int(base_url.rsplit(":", 1)[1]),
                    run_id=run_id,
                    phase="PRE_SHUTDOWN",
                )
                launch_owned = (post_launch_ownership or {}).get("launcher_process") or {}
                shutdown_owned = pre_shutdown.get("launcher_process") or {}
                continuity_checks = {
                    "run_id_matches_post_launch": pre_shutdown.get("runtime_run_id")
                    == (post_launch_ownership or {}).get("runtime_run_id"),
                    "launcher_pid_matches_post_launch": pre_shutdown.get("launcher_pid")
                    == (post_launch_ownership or {}).get("launcher_pid"),
                    "runtime_pid_matches_post_launch": pre_shutdown.get("runtime_pid")
                    == (post_launch_ownership or {}).get("runtime_pid"),
                    "listener_pid_matches_post_launch": pre_shutdown.get("listener_pid")
                    == (post_launch_ownership or {}).get("listener_pid"),
                    "console_helper_pid_matches_post_launch": pre_shutdown.get(
                        "console_helper_pid"
                    )
                    == (post_launch_ownership or {}).get("console_helper_pid"),
                    "console_helper_creation_time_matches_post_launch": pre_shutdown.get(
                        "console_helper_create_time"
                    )
                    == (post_launch_ownership or {}).get("console_helper_create_time"),
                    "launcher_creation_time_matches_post_launch": pre_shutdown.get(
                        "launcher_create_time"
                    )
                    == (post_launch_ownership or {}).get("launcher_create_time"),
                    "process_tree_identity_matches_post_launch": pre_shutdown.get(
                        "process_tree", {}
                    ).get("identity_digest")
                    == (post_launch_ownership or {}).get("process_tree", {}).get(
                        "identity_digest"
                    ),
                    "command_digest_matches_post_launch": shutdown_owned.get("command_digest")
                    == launch_owned.get("command_digest"),
                    "executable_digest_matches_post_launch": shutdown_owned.get(
                        "executable_digest"
                    )
                    == launch_owned.get("executable_digest"),
                }
                pre_shutdown["continuity_checks"] = continuity_checks
                pre_shutdown["passed"] = bool(
                    pre_shutdown["passed"] and all(continuity_checks.values())
                )
                receipt["pre_shutdown_ownership"] = pre_shutdown
                if pre_shutdown["passed"] is not True:
                    shutdown_passed = False
                    receipt["runtime_stop"] = {
                        "status": "blocked_unverified_ownership",
                        "stopped": False,
                    }
                else:
                    receipt["runtime_descendant_stop"] = stop_verified_runtime_descendants(
                        pre_shutdown
                    )
                    receipt["runtime_stop"] = backend.stop_runtime()
                    receipt["console_helper_natural_exit"] = (
                        wait_for_console_helper_exit(
                            pre_shutdown.get("console_helper_process")
                        )
                    )
                    post_gpu = _nvidia_memory()
                    post_shutdown = build_post_shutdown_receipt(
                        run_id=run_id,
                        owned_processes=pre_shutdown.get("owned_processes", []),
                        host="127.0.0.1",
                        port=int(base_url.rsplit(":", 1)[1]),
                        baseline_gpu_bytes=(baseline_gpu or {}).get("used_bytes"),
                        current_gpu_bytes=post_gpu.get("used_bytes"),
                        console_helper_process=pre_shutdown.get("console_helper_process"),
                    )
                    receipt["post_shutdown_ownership"] = post_shutdown
                    shutdown_passed = bool(
                        receipt["runtime_stop"].get("stopped") is True
                        and receipt["console_helper_natural_exit"].get("passed") is True
                        and post_shutdown["passed"] is True
                    )
            except BaseException as error:
                shutdown_passed = False
                receipt["runtime_stop"] = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                }
        else:
            receipt["runtime_stop"] = {"status": "not_started", "stopped": False}
        if not shutdown_passed:
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
            time.monotonic() - runner_started,
            "seconds",
            "runner monotonic span",
            scope="runner entry through owned runtime stop",
        )
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["websocket_terminal_event"] = timeline.terminal_event
            gpu_started = bool(receipt["progress_timeline"].get("records", []))
            receipt["gpu_start_count"] = int(gpu_started)
            receipt["diagnostic_gpu_start_count"] = (
                int(gpu_started) if lineage_diagnostic else 0
            )
        if callback_path.is_file() and "callback_instrumentation" not in receipt:
            receipt["callback_instrumentation"] = json.loads(callback_path.read_text(encoding="utf-8"))
        if lineage_diagnostic:
            receipt["formal_control_result_admitted"] = False
            receipt["holdout_admission_count"] = 0
            receipt["valid_control_result_count"] = 0
            receipt["rust_live_compile_count"] = 0
            receipt["rust_offline_replay_count"] = 0
            if lineage_capsule_path.is_file():
                capsule_content = lineage_capsule_path.read_bytes()
                receipt["lineage_capsule"] = {
                    "present": True,
                    "size_bytes": len(capsule_content),
                    "sha256": sha256(capsule_content).hexdigest(),
                }
                if shutdown_passed:
                    receipt["decision"] = (
                        "H3_BACKGROUND_ORACLE_LINEAGE_TRACE_CAPTURED_PENDING_ANALYSIS"
                    )
                    exit_code = 0
                    receipt["exit_code"] = 0
            else:
                receipt["lineage_capsule"] = {"present": False}
                receipt["decision"] = (
                    "H3_BACKGROUND_ORACLE_LINEAGE_TRACE_FAILED"
                    if submitted
                    else "H3_BACKGROUND_ORACLE_LINEAGE_TRACE_ADMISSION_BLOCKED"
                )
        (root / "private-receipt.json").write_text(
            json.dumps(_json_safe(receipt), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (root / "public-summary.json").write_text(
            json.dumps(sanitize_public(_json_safe(receipt)), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exactly one H3 CONTROL V2.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--external-product-database", action="append", default=[], type=Path)
    parser.add_argument("--input-image", required=True, type=Path)
    parser.add_argument("--input-image-sha256", required=True)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--comfyui-root", required=True, type=Path)
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--rust-extension-root", required=True, type=Path)
    parser.add_argument("--synthetic-receipt", required=True, type=Path)
    parser.add_argument("--verification-receipt", required=True, type=Path)
    parser.add_argument("--lineage-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    result = run_control(
        run_id=args.run_id,
        p0_database=args.p0_database,
        external_product_databases=args.external_product_database,
        input_image=args.input_image,
        input_image_sha256=args.input_image_sha256,
        private_run_root=args.private_run_root,
        asset_root=args.asset_root,
        comfyui_root=args.comfyui_root,
        workflow_path=args.workflow,
        base_url=args.base_url,
        rust_extension_root=args.rust_extension_root,
        synthetic_receipt=args.synthetic_receipt,
        verification_receipt=args.verification_receipt,
        lineage_diagnostic=args.lineage_diagnostic,
    )
    print(json.dumps(sanitize_public(_json_safe(result)), sort_keys=True))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
