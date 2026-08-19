"""One-shot real H3 Full Compute row/region safety CONTROL."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import asyncio
import copy
import json
import os
import shutil
import sqlite3
import sys
import time

from .a3_g1_conditional_reuse import CONTROL_MODE
from .a3_g1_h3_conditional_probe import APPROVED_WORKFLOW_SHA256
from .active_query_attention import (
    BLOCK_COUNT,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    inspect_installed_attention_source,
)
from .c0_h3_phase_probe import EventTimeline, _collect_websocket_run, _history_video, measured, sanitize_public
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .h3_row_region_safety import (
    CACHE_HARD_CAP_BYTES,
    FULL_Q_ROWS,
    MAX_EVIDENCE_RECORDS,
    TRANSFER_BUDGET_BYTES,
    evidence_design_receipt,
    generation_candidates,
    generation_identity,
    settings_digest,
)
from .rust_cache_plan_v2 import PLAN_READY, RustCachePlanV2Bridge
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video


SCHEMA_VERSION = "h3.row-region-safety-control.1"
NODE_CLASS = "HIVEFRAMEH3RowRegionSafetyControlSampler"
RECEIPT_ENV = "HIVEFRAME_H3_ROW_REGION_RECEIPT"


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


def _load_p1_a2_prompt(database: Path) -> tuple[str, str]:
    if not database.is_file():
        raise ValueError("private P1-A2 database is unavailable")
    connection = sqlite3.connect(database)
    try:
        return _select_p1_a2_prompt(connection)
    finally:
        connection.close()


def _select_p1_a2_prompt(connection: sqlite3.Connection) -> tuple[str, str]:
    rows = connection.execute(
        """
        SELECT prompt
        FROM jobs
        WHERE backend = ?
          AND status = ?
          AND profile = ?
          AND generation_mode = ?
          AND reference_asset_id IS NOT NULL
        ORDER BY created_at
        """,
        ("minimax_h3_comfyui_local", "succeeded", "standard", "image_to_video"),
    ).fetchall()
    if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0].strip():
        raise ValueError("private database must identify exactly one P1-A2 Standard I2V prompt")
    prompt = rows[0][0].strip()
    return prompt, sha256(prompt.encode("utf-8")).hexdigest()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    first_frame_name: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("row/region CONTROL requires the Standard sampler at node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("row/region CONTROL sampler inputs are malformed")
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


def _replay_signature(plan: Mapping[str, Any]) -> dict[str, Any]:
    return _json_safe(
        {
            "selected": plan.get("selected"),
            "rejected": plan.get("rejected"),
            "eviction_order": plan.get("eviction_order"),
            "total_selected_bytes": plan.get("total_selected_bytes"),
            "total_planned_q_rows": plan.get("total_planned_q_rows"),
            "total_full_q_rows": plan.get("total_full_q_rows"),
            "planned_reduction_ppm": plan.get("planned_reduction_ppm"),
            "total_planned_d2h_bytes": plan.get("total_planned_d2h_bytes"),
            "total_planned_h2d_bytes": plan.get("total_planned_h2d_bytes"),
            "plan_digest": plan.get("plan_digest"),
            "lineage_digest": plan.get("lineage_digest"),
        }
    )


def run_control(
    *,
    run_id: str,
    p0_database: Path,
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
        raise ValueError("private CONTROL run directory already exists")
    root.mkdir(parents=True)
    prompt, prompt_hash = _load_p1_a2_prompt(p0_database)
    image_content = input_image.read_bytes()
    image_digest = sha256(image_content).hexdigest()
    if image_digest != input_image_sha256:
        raise RuntimeError("P1-A2 input image identity changed")

    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    runtime_output = root / "comfy-output"
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
    model_source = comfyui_root / MODEL_SOURCE_RELATIVE
    attention_source = comfyui_root / "comfy/ldm/modules/attention.py"
    source_gate = inspect_installed_attention_source(model_source, attention_source)
    callback_path = root / "row-region-callback-private-receipt.json"
    run_digest = sha256(run_id.encode()).hexdigest()
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get(RECEIPT_ENV)
    python_entries = [str(repository_root / "python"), str(rust_extension_root.resolve())]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ[RECEIPT_ENV] = str(callback_path)

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at": _utc_now(),
        "profile": {
            "engine": "H3",
            "mode": "I2V",
            "seed": 101,
            "width": 864,
            "height": 480,
            "frames": 124,
            "fps": 24,
            "steps": 20,
            "scheduler": "simple",
            "sampler": "res_multistep",
            "denoise": 1.0,
            "sage_enabled": False,
            "full_compute": True,
        },
        "input_identity_digest": image_digest,
        "prompt_identity_digest": prompt_hash,
        "source_admission": source_gate,
        "evidence_design": evidence_design_receipt(),
        "control_submission_count": 0,
        "control_gpu_execution_started_count": 0,
        "control_completed_generation_count": 0,
        "retry_count": 0,
        "job_level_fallback_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "external_api_call_count": 0,
        "foreign_job_termination_count": 0,
        "rust_plan_compile_count": 0,
        "model_free_replay_compile_count": 0,
    }
    timeline: EventTimeline | None = None
    runner_started = time.monotonic()
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("installed H3 source admission failed")
        startup_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup_started
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("CONTROL requires one fresh owned ComfyUI process")
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow_status = backend.inspect_workflow()
        objects = backend.client.json("GET", "/object_info")
        queue = backend.client.json("GET", "/queue")
        preflight = {
            "runtime": runtime,
            "assets": assets,
            "workflow": workflow_status,
            "custom_node_present": isinstance(objects, Mapping) and NODE_CLASS in objects,
            "load_image_present": isinstance(objects, Mapping) and "LoadImage" in objects,
            "queue_running": len(queue.get("queue_running", [])) if isinstance(queue, Mapping) else None,
            "queue_pending": len(queue.get("queue_pending", [])) if isinstance(queue, Mapping) else None,
        }
        receipt["preflight"] = preflight
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("dedicated H3 runtime did not reach ready")
        if not preflight["custom_node_present"] or not preflight["load_image_present"]:
            raise RuntimeError("required CONTROL nodes are unavailable")
        if preflight["queue_running"] != 0 or preflight["queue_pending"] != 0:
            raise RuntimeError("dedicated H3 runtime queue is not clean")
        if workflow_status.get("workflow_sha256") != APPROVED_WORKFLOW_SHA256:
            raise RuntimeError("approved H3 workflow digest changed")

        input_name = f"hiveframe-reference-{image_digest[:16]}{input_image.suffix.lower()}"
        input_target = runtime_output / "input" / input_name
        shutil.copyfile(input_image, input_target)
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/row-region-control-{image_digest[:12]}",
        )
        workflow = build_workflow(
            standard,
            run_digest=run_digest,
            first_frame_name=input_name,
        )
        sage_count = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if sage_count != 0:
            raise RuntimeError("CONTROL workflow contains a Sage node")
        timeline = EventTimeline(workflow)
        receipt["control_submission_count"] = 1
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        receipt["backend_prompt_id"] = prompt_id
        receipt["control_gpu_execution_started_count"] = int(
            bool(timeline.progress_summary().get("records", []))
        )
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        receipt["control_completed_generation_count"] = 1

        collection_started = time.monotonic()
        descriptor, content = _history_video(backend, history)
        output = root / "control.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        collection_seconds = time.monotonic() - collection_started
        integrity = (
            decode["decoded_frame_count"] == 124
            and (decode["width"], decode["height"]) == (864, 480)
            and decode["fps"] == 24.0
            and decode["codec"] == "h264"
            and decode["audio_stream_count"] >= 1
            and decode["black_frame_count"] == 0
            and decode["corrupted_frame_count"] == 0
        )
        receipt["output"] = {
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "decode": decode,
            "integrity_passed": integrity,
            "private_path": str(output),
        }
        if not integrity:
            raise RuntimeError("Full Compute CONTROL output integrity failed")
        if not callback_path.is_file():
            raise RuntimeError("row/region callback receipt is missing")
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        execution = callback.get("attention_execution", {})
        safety = execution.get("safety_evidence", {})
        confusion = safety.get("confusion_matrix", {})
        execution_checks = {
            "sampler_succeeded": callback.get("sampler_succeeded") is True,
            "model_forward_count": execution.get("model_forward_count") == 20,
            "block_call_count": execution.get("block_call_count") == BLOCK_COUNT * 20,
            "full_attention_calls": execution.get("full_attention_calls") == BLOCK_COUNT * 20,
            "partial_attention_zero": execution.get("partial_attention_calls") == 0,
            "mapping_error_zero": execution.get("mapping_error_count") == 0,
            "wrapper_failure_zero": execution.get("wrapper_failure_count") == 0,
            "evidence_bounded": int(safety.get("record_count", MAX_EVIDENCE_RECORDS + 1)) <= MAX_EVIDENCE_RECORDS,
            "evidence_not_overflowed": safety.get("overflow") is False,
            "false_safe_zero": confusion.get("false_safe") == 0,
            "false_unsafe_collected": safety.get("false_unsafe_status") == "COLLECTED",
            "cache_cap": int(execution.get("cache", {}).get("host_cache_bytes", CACHE_HARD_CAP_BYTES + 1)) <= CACHE_HARD_CAP_BYTES,
            "actual_transfer_budget": int(execution.get("cache", {}).get("transfer_total_bytes", TRANSFER_BUDGET_BYTES + 1)) <= TRANSFER_BUDGET_BYTES,
            "rust_tensor_transfer_zero": safety.get("rust_tensor_transfer_bytes") == 0,
        }
        receipt["callback_instrumentation"] = callback
        receipt["execution_gate"] = {"checks": execution_checks, "passed": all(execution_checks.values())}
        if not all(execution_checks.values()):
            raise RuntimeError("row/region execution evidence Gate failed")

        identity = generation_identity(
            run_digest_hex=run_digest,
            workflow_digest_hex=APPROVED_WORKFLOW_SHA256,
            model_digest_hex=MODEL_SOURCE_SHA256,
            settings_digest_hex=settings_digest(),
            input_identity_digest_hex=image_digest,
        )
        candidates = generation_candidates(identity, safety["records"])
        bridge = RustCachePlanV2Bridge()
        receipt["rust_plan_compile_count"] = 1
        plan = bridge.compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=int(execution.get("work", {}).get("full_q_rows_theoretical", FULL_Q_ROWS)),
            profile_name="balanced_12gb",
        )
        receipt["generation_evidence_batch"] = {
            "record_count": len(candidates),
            "maximum_records": MAX_EVIDENCE_RECORDS,
            "overflow": len(candidates) > MAX_EVIDENCE_RECORDS,
            "tensor_bytes": 0,
        }
        receipt["rust_plan"] = _json_safe(plan)

        replay_a = RustCachePlanV2Bridge().compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=int(execution.get("work", {}).get("full_q_rows_theoretical", FULL_Q_ROWS)),
            profile_name="balanced_12gb",
        )
        replay_b = RustCachePlanV2Bridge().compile_generation(
            identity=identity,
            candidates=candidates,
            total_full_q_rows=int(execution.get("work", {}).get("full_q_rows_theoretical", FULL_Q_ROWS)),
            profile_name="balanced_12gb",
        )
        receipt["model_free_replay_compile_count"] = 2
        replay_passed = _replay_signature(plan) == _replay_signature(replay_a) == _replay_signature(replay_b)
        planned_transfer = int(plan.get("total_planned_d2h_bytes", 0)) + int(plan.get("total_planned_h2d_bytes", 0))
        plan_checks = {
            "rust_module_loaded": bridge.extension is not None,
            "rust_call_count_one": bridge.rust_call_count == 1,
            "plan_ready": plan.get("decision_code") == PLAN_READY and plan.get("fallback_required") is False,
            "planned_q_reduction_at_least_three_percent": int(plan.get("planned_reduction_ppm", 0)) >= 30_000,
            "selected_cache_within_two_gib": int(plan.get("total_selected_bytes", CACHE_HARD_CAP_BYTES + 1)) <= CACHE_HARD_CAP_BYTES,
            "selected_transfer_within_forty_gib": planned_transfer <= TRANSFER_BUDGET_BYTES,
            "lineage_digest_present": plan.get("lineage_digest") not in {None, bytes(32)},
            "deterministic_replay": replay_passed,
        }
        receipt["rust_replay"] = {
            "checks": plan_checks,
            "passed": all(plan_checks.values()),
            "replay_compile_count": 2,
            "signature": _replay_signature(plan),
        }
        if not all(plan_checks.values()):
            raise RuntimeError("Rust CachePlan ABI V2 evidence Gate failed")
        receipt["decision"] = "H3_ROW_REGION_SAFETY_EVIDENCE_READY_FOR_SELECTIVE_GPU_PROOF"
        exit_code = 0
    except Exception as error:
        receipt["runner_error"] = type(error).__name__
        receipt["runner_error_message"] = str(error)[:1000]
        receipt.setdefault("decision", "H3_ROW_REGION_CONTROL_FAILED")
    finally:
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
            os.environ.pop(RECEIPT_ENV, None)
        else:
            os.environ[RECEIPT_ENV] = prior_receipt
        receipt["finished_at"] = _utc_now()
        receipt["exit_code"] = exit_code
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(
                startup_seconds, "seconds", "runner monotonic span", scope="owned runtime launch to ready"
            ),
            "result_collection_seconds": measured(
                collection_seconds,
                "seconds",
                "runner monotonic span",
                scope="terminal event to local result collection",
            ),
            "shutdown_seconds": measured(
                shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"
            ),
            "runner_total_seconds": measured(
                time.monotonic() - runner_started,
                "seconds",
                "runner monotonic span",
                scope="runner entry through runtime stop",
            ),
        }
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["websocket_terminal_event"] = timeline.terminal_event
        if "callback_instrumentation" not in receipt and callback_path.is_file():
            receipt["callback_instrumentation"] = json.loads(callback_path.read_text(encoding="utf-8"))
        if receipt.get("callback_instrumentation", {}).get("error_type") == "EvidenceBudgetError":
            receipt["decision"] = "H3_ROW_REGION_TRANSFER_BUDGET_FAILED"
        (root / "private-receipt.json").write_text(
            json.dumps(_json_safe(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        public = sanitize_public(_json_safe(receipt))
        (root / "public-summary.json").write_text(
            json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one bounded H3 row/region safety CONTROL.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
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
        p0_database=args.p0_database,
        input_image=args.input_image,
        input_image_sha256=args.input_image_sha256,
        private_run_root=args.private_run_root,
        asset_root=args.asset_root,
        comfyui_root=args.comfyui_root,
        workflow_path=args.workflow,
        base_url=args.base_url,
        rust_extension_root=args.rust_extension_root,
    )
    print(json.dumps(sanitize_public(_json_safe(result)), ensure_ascii=False, sort_keys=True))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
