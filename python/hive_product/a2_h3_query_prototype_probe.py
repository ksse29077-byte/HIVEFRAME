"""Bounded A2 CONTROL plus conditional SELECTIVE Local H3 experiment."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import argparse
import asyncio
import copy
import json
import os
import sys
import time

from .a1_h3_active_query_probe import compare_videos, _sampler_seconds, _submit_seconds, _visual_review_package
from .active_query_attention import BLOCK_COUNT
from .c0_h3_phase_probe import EventTimeline, _collect_websocket_run, _history_video, _safe_run_root, measured, sanitize_public, unsupported
from .c3_r2_h3_residual_probe import APPROVED_WORKFLOW_SHA256
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .regional_query_prototype_attention import (
    COMPARABILITY_RELATIVE_LIMIT,
    CONTROL_MODE,
    MECHANISM_ID,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    REFERENCE_SAMPLER_SECONDS,
    SELECTIVE_MODE,
    control_admission,
    fixed_contract,
    inspect_installed_attention_source,
    prototype_settings_digest,
)
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "a2.h3.query-prototype.1"
NODE_CLASS = "HIVEFRAMEH3RegionalQueryPrototypeSampler"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    mode: str,
    admitted_blocks: Sequence[int],
    run_digest: str,
) -> dict[str, Any]:
    if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
        raise ValueError("unsupported A2 mode")
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("A2 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("A2 sampler inputs are malformed")
    blocks = tuple(sorted(set(int(index) for index in admitted_blocks)))
    if mode == CONTROL_MODE and blocks:
        raise ValueError("A2 CONTROL cannot carry admitted blocks")
    if mode == SELECTIVE_MODE and not blocks:
        raise ValueError("A2 SELECTIVE requires admitted blocks")
    inputs.update(
        {
            "mode": mode,
            "admitted_blocks_json": json.dumps(list(blocks), separators=(",", ":")),
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": prototype_settings_digest(mode=mode, admitted_blocks=blocks),
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    sampler["class_type"] = NODE_CLASS
    return workflow


def _run_generation(
    *,
    mode: str,
    admitted_blocks: Sequence[int],
    run_id: str,
    prompt: str,
    prompt_hash: str,
    root: Path,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    backend = MiniMaxH3ComfyUIBackend(
        config=replace(base_config, custom_nodes_root=custom_nodes_root, output_root=root / "comfy-output")
    )
    model_source = base_config.comfyui_root / MODEL_SOURCE_RELATIVE if base_config.comfyui_root else Path("<missing>")
    attention_source = base_config.comfyui_root / "comfy/ldm/modules/attention.py" if base_config.comfyui_root else Path("<missing>")
    source_gate = inspect_installed_attention_source(model_source, attention_source)
    callback_path = root / "a2-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_A2_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_A2_RECEIPT"] = str(callback_path)
    runner_started = time.monotonic()
    timeline: EventTimeline | None = None
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": mode,
        "mechanism": MECHANISM_ID,
        "started_at": _utc_now(),
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "admitted_blocks": list(admitted_blocks),
        "settings_digest": prototype_settings_digest(mode=mode, admitted_blocks=admitted_blocks),
        "source_admission": source_gate,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
    }
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("A2 installed-source admission failed")
        startup_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup_started
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("A2 requires one fresh owned ComfyUI process")
        runtime, assets, workflow_status = backend.inspect_runtime(), backend.inspect_assets(), backend.inspect_workflow()
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
            raise RuntimeError("A2 Local H3 preflight did not reach ready")
        if not node_present:
            raise RuntimeError("repository-owned A2 custom node is unavailable")
        if workflow_status.get("workflow_sha256") != APPROVED_WORKFLOW_SHA256:
            raise RuntimeError("approved Standard workflow hash changed")
        expected = {
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
        if not isinstance(profile, Mapping) or any(profile.get(key) != value for key, value in expected.items()):
            raise RuntimeError("A2 Standard execution profile changed")
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/a2-{mode.lower()}-{prompt_hash[:12]}",
        )
        workflow = build_workflow(
            standard,
            mode=mode,
            admitted_blocks=admitted_blocks,
            run_digest=sha256(run_id.encode()).hexdigest(),
        )
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("A2 workflow contains a Sage node")
        timeline = EventTimeline(workflow)
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
        integrity = (
            decode["decoded_frame_count"] == 124
            and (decode["width"], decode["height"]) == (864, 480)
            and decode["fps"] == 24.0
            and decode["codec"] == "h264"
            and decode["audio_stream_count"] >= 1
            and decode["black_frame_count"] == 0
            and decode["corrupted_frame_count"] == 0
        )
        if not integrity:
            raise RuntimeError("A2 output failed the fixed integrity contract")
        if not callback_path.is_file():
            raise RuntimeError("A2 callback receipt is missing")
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        execution = callback.get("attention_execution", {})
        checks = {
            "sampler_succeeded": callback.get("sampler_succeeded") is True,
            "model_forward_count": execution.get("model_forward_count") == 20,
            "block_call_count": execution.get("block_call_count") == BLOCK_COUNT * 20,
            "mapping_error_zero": execution.get("mapping_error_count") == 0,
            "wrapper_failure_zero": execution.get("wrapper_failure_count") == 0,
            "global_kv_preserved": execution.get("global_kv_preserved") is True,
            "tensor_to_rust_zero": callback.get("region_plan", {}).get("tensor_bytes_to_rust") == 0,
            "per_block_rust_zero": execution.get("per_block_rust_call_count") == 0,
            "per_token_rust_zero": execution.get("per_token_rust_call_count") == 0,
            "explicit_cuda_sync_zero": execution.get("explicit_cuda_synchronization_count") == 0,
            "dynamic_plan_allocation_zero": execution.get("dynamic_per_block_gpu_plan_allocation_count") == 0,
        }
        receipt["callback_instrumentation"] = callback
        receipt["execution_gate"] = {"checks": checks, "passed": all(checks.values())}
        if not all(checks.values()):
            raise RuntimeError("A2 execution mapping gate failed")
        receipt["result"] = {
            "logical_artifact_id": f"A2_{mode}_VIDEO",
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
            os.environ.pop("HIVEFRAME_A2_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_A2_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="owned process launch to ready"),
            "result_collection_seconds": measured(collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "gpu_kernel_seconds": unsupported("Profiler, CUPTI, and Nsight were disabled for A2.", "not collected", scope="GPU kernel-duration sum"),
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
                "resource_sampler": unsupported(
                    "Periodic resource polling is excluded from the frozen A2 hot-path contract.",
                    "not collected",
                    scope="process-tree RAM and NVIDIA sampled VRAM",
                ),
            }
            (root / "websocket-events.jsonl").write_text(
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline.events),
                encoding="utf-8",
            )
        if "callback_instrumentation" not in receipt and callback_path.is_file():
            receipt["callback_instrumentation"] = json.loads(callback_path.read_text(encoding="utf-8"))
        receipt["exit_code"] = exit_code
        (root / "private-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (root / "public-summary.json").write_text(json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def run_experiment(*, experiment_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, experiment_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "started_at": _utc_now(),
        "product_question": "Can exact regional representative Q rows reduce H3 attention-core work while preserving global K/V, Full Compute safety, and Standard quality?",
        "contract": fixed_contract(),
        "generation_budget": 2,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
        "a0_combined_generation_count": 0,
        "final_2x_target_verified": False,
    }
    control = _run_generation(
        mode=CONTROL_MODE,
        admitted_blocks=(),
        run_id=f"{experiment_id}-control",
        prompt=prompt,
        prompt_hash=prompt_hash,
        root=root / "control",
    )
    summary["control"] = sanitize_public(control)
    summary["generation_attempt_count"] += int(control.get("generation_attempt_count", 0))
    if control.get("exit_code") != 0:
        summary["decision"] = "A2_QUERY_PROTOTYPE_RUNTIME_REJECTED"
        summary["component_disposition"] = "FALLBACK_ONLY"
        summary["next_candidate"] = "FULL_COMPUTE_FALLBACK"
    else:
        callback = control["callback_instrumentation"]
        admission = control_admission(
            execution=callback["attention_execution"],
            region_plan=callback["region_plan"],
            c2_shadow=callback["c2_shadow"],
            sampler_seconds=_sampler_seconds(control),
            output_integrity_passed=True,
            source_admitted=bool(control["source_admission"]["admitted"]),
        )
        summary["control_admission"] = admission
        if not admission["passed"]:
            summary["decision"] = admission["decision"]
            summary["component_disposition"] = "FALLBACK_ONLY"
            summary["next_candidate"] = admission["next_candidate"]
        else:
            admitted_blocks = callback["attention_execution"]["admitted_blocks"]
            selective = _run_generation(
                mode=SELECTIVE_MODE,
                admitted_blocks=admitted_blocks,
                run_id=f"{experiment_id}-selective",
                prompt=prompt,
                prompt_hash=prompt_hash,
                root=root / "selective",
            )
            summary["selective"] = sanitize_public(selective)
            summary["generation_attempt_count"] += int(selective.get("generation_attempt_count", 0))
            if selective.get("exit_code") != 0:
                summary["decision"] = "A2_QUERY_PROTOTYPE_RUNTIME_REJECTED"
                summary["component_disposition"] = "FALLBACK_ONLY"
                summary["next_candidate"] = "FULL_COMPUTE_FALLBACK"
            else:
                control_path = Path(control["result"]["private_path"])
                selective_path = Path(selective["result"]["private_path"])
                quality = compare_videos(control_path, selective_path)
                execution = selective["callback_instrumentation"]["attention_execution"]
                actual_reduction = float(execution["actual_query_reduction"])
                sampler_ratio = _sampler_seconds(control) / _sampler_seconds(selective)
                submit_ratio = _submit_seconds(control) / _submit_seconds(selective)
                e2e_regression = _submit_seconds(selective) / _submit_seconds(control) - 1.0
                summary["quality"] = quality
                summary["runtime_comparison"] = {
                    "control_sampler_seconds": _sampler_seconds(control),
                    "selective_sampler_seconds": _sampler_seconds(selective),
                    "sampler_ratio": sampler_ratio,
                    "control_submit_to_terminal_seconds": _submit_seconds(control),
                    "selective_submit_to_terminal_seconds": _submit_seconds(selective),
                    "submit_to_terminal_ratio": submit_ratio,
                    "selective_e2e_regression": e2e_regression,
                }
                summary["actual_query_reduction"] = actual_reduction
                if actual_reduction < 0.05:
                    summary["decision"] = "A2_QUERY_PROTOTYPE_OPPORTUNITY_TOO_LOW"
                    summary["component_disposition"] = "FALLBACK_ONLY"
                    summary["next_candidate"] = "REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1"
                elif not quality["passed"]:
                    summary["decision"] = "A2_QUERY_PROTOTYPE_QUALITY_REJECTED"
                    summary["component_disposition"] = "FALLBACK_ONLY"
                    summary["next_candidate"] = "REGIONAL_ATTENTION_OUTPUT_REUSE_WITH_CORRECTION_V1"
                elif e2e_regression > 0.02:
                    summary["decision"] = "A2_QUERY_PROTOTYPE_RUNTIME_REJECTED"
                    summary["component_disposition"] = "FALLBACK_ONLY"
                    summary["next_candidate"] = "RUNTIME_INTEGRATION_REFINEMENT"
                elif sampler_ratio > 1.0 and submit_ratio > 1.0:
                    summary["decision"] = "A2_HIVEFRAME_QUERY_PROTOTYPE_READY_FOR_VISUAL_REVIEW"
                    summary["component_disposition"] = "KEEP_AS_OPTIONAL"
                    summary["next_candidate"] = "HUMAN_VISUAL_REVIEW"
                else:
                    summary["decision"] = "A2_QUERY_PROTOTYPE_WORK_REDUCTION_VERIFIED_RUNTIME_NOT_YET_POSITIVE"
                    summary["component_disposition"] = "KEEP_AS_OPTIONAL"
                    summary["next_candidate"] = "RUNTIME_INTEGRATION_REFINEMENT"
                if quality["passed"]:
                    summary["visual_review"] = _visual_review_package(
                        control_path,
                        selective_path,
                        quality["highest_control_motion_frames"],
                        root,
                    )
    summary["finished_at"] = _utc_now()
    summary["retry_count"] = 0
    summary["third_generation_count"] = 0
    (root / "experiment-private-receipt.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "experiment-public-summary.json").write_text(json.dumps(sanitize_public(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded A2 CONTROL and conditional SELECTIVE H3 experiment.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = run_experiment(
        experiment_id=args.experiment_id,
        p0_database=args.p0_database,
        private_run_root=args.private_run_root,
    )
    print(json.dumps(sanitize_public(summary), ensure_ascii=False, sort_keys=True))
    failure = summary.get("decision") in {"A2_QUERY_PROTOTYPE_RUNTIME_REJECTED", "A2_QUERY_PROTOTYPE_STRUCTURALLY_NOT_ADMITTED"}
    return 1 if failure else 0


if __name__ == "__main__":
    sys.exit(main())
