"""Bounded A3-G1C CONTROL plus preplanned direct SELECTIVE experiment."""

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

from .a1_h3_active_query_probe import (
    _sampler_seconds,
    _submit_seconds,
    _visual_review_package,
    compare_videos,
)
from .a3_g1_conditional_reuse import (
    A2_RANKED_BLOCKS,
    CONTROL_MODE,
    DECISION_ISLAND_NOT_ADMITTED,
    DECISION_OMISSION_NOT_PROVEN,
    DECISION_QUALITY_REJECTED,
    DECISION_READY_FOR_VISUAL,
    DECISION_RUNTIME_NOT_POSITIVE,
    SELECTIVE_MODE,
    control_opportunity_gate,
    fixed_contract,
    settings_digest,
)
from .a3_h3_attention_output_reuse_probe import _load_a2_calibration
from .active_query_attention import (
    BLOCK_COUNT,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    inspect_installed_attention_source,
)
from .attention_output_reuse import a2_full_ranking, cache_budget_plan
from .c0_h3_phase_probe import (
    EventTimeline,
    _collect_websocket_run,
    _history_video,
    _safe_run_root,
    measured,
    sanitize_public,
    unsupported,
)
from .c3_r2_h3_residual_probe import APPROVED_WORKFLOW_SHA256
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "a3-g1c.h3.preplan-direct-selective.1"
NODE_CLASS = "HIVEFRAMEH3PreplanDirectSelectiveReuseSampler"
IMMUTABLE_STANDARD_SAMPLER_SECONDS = 488.847320
IMMUTABLE_STANDARD_SUBMIT_SECONDS = 589.913016


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    mode: str,
    candidate_blocks: Sequence[int],
    run_digest: str,
) -> dict[str, Any]:
    if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
        raise ValueError("unsupported A3-G1 mode")
    candidates = tuple(int(value) for value in candidate_blocks)
    if len(candidates) < 3 or len(set(candidates)) != len(candidates):
        raise ValueError("A3-G1 requires at least three unique candidate blocks")
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("A3-G1 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("A3-G1 sampler inputs are malformed")
    inputs.update(
        {
            "mode": mode,
            "candidate_blocks_json": json.dumps(list(candidates), separators=(",", ":")),
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest(mode=mode, candidate_blocks=candidates),
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    sampler["class_type"] = NODE_CLASS
    return workflow


def _run_generation(
    *,
    mode: str,
    candidate_blocks: Sequence[int],
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
    attention_source = (
        base_config.comfyui_root / "comfy/ldm/modules/attention.py"
        if base_config.comfyui_root
        else Path("<missing>")
    )
    source_gate = inspect_installed_attention_source(model_source, attention_source)
    callback_path = root / "a3-g1-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_A3_G1_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_A3_G1_RECEIPT"] = str(callback_path)
    runner_started = time.monotonic()
    timeline: EventTimeline | None = None
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": mode,
        "started_at": _utc_now(),
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "candidate_blocks": list(candidate_blocks),
        "settings_digest": settings_digest(mode=mode, candidate_blocks=candidate_blocks),
        "source_admission": source_gate,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
    }
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("A3-G1 installed-source admission failed")
        startup_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup_started
        if receipt["runtime_start"].get("started_here") is not True:
            raise RuntimeError("A3-G1 requires one fresh owned ComfyUI process")
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
            raise RuntimeError("A3-G1 Local H3 preflight did not reach ready")
        if not node_present:
            raise RuntimeError("repository-owned A3-G1 custom node is unavailable")
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
            raise RuntimeError("A3-G1 Standard execution profile changed")
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/a3-g1-{mode.lower()}-{prompt_hash[:12]}",
        )
        workflow = build_workflow(
            standard,
            mode=mode,
            candidate_blocks=candidate_blocks,
            run_digest=sha256(run_id.encode()).hexdigest(),
        )
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("A3-G1 workflow contains a Sage node")
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
            raise RuntimeError("A3-G1 output failed the fixed integrity contract")
        if not callback_path.is_file():
            raise RuntimeError("A3-G1 callback receipt is missing")
        callback = json.loads(callback_path.read_text(encoding="utf-8"))
        execution = callback.get("attention_execution", {})
        work = execution.get("work", {})
        checks = {
            "sampler_succeeded": callback.get("sampler_succeeded") is True,
            "model_forward_count": execution.get("model_forward_count") == 20,
            "block_call_count": execution.get("block_call_count") == BLOCK_COUNT * 20,
            "mapping_error_zero": execution.get("mapping_error_count") == 0,
            "wrapper_failure_zero": execution.get("wrapper_failure_count") == 0,
            "global_k_full": work.get("actual_k_rows") == work.get("full_k_rows"),
            "global_v_full": work.get("actual_v_rows") == work.get("full_v_rows"),
            "tensor_to_rust_zero": callback.get("region_plan", {}).get("tensor_bytes_to_rust") == 0,
            "guard_d2h_zero": execution.get("guard", {}).get("d2h_bytes") == 0,
            "host_guard_read_zero": execution.get("guard", {}).get("host_reads") == 0,
            "hot_path_sync_zero": execution.get("guard", {}).get("explicit_hot_path_cpu_sync") == 0,
            "conditional_graph_zero": execution.get("conditional_graph_used") is False,
            "same_block_guard_zero": execution.get("gpu_same_block_guard_used") is False,
            "static_qkv_zero": execution.get("static_qkv_used") is False,
            "normal_double_attention_zero": execution.get("normal_partial_plus_full_count") == 0,
            "exception_double_attention_zero": execution.get("exception_partial_then_full_count") == 0,
            "full_size_gpu_staging_zero": execution.get("cache", {}).get("full_size_gpu_staging_count") == 0,
        }
        receipt["callback_instrumentation"] = callback
        receipt["execution_gate"] = {"checks": checks, "passed": all(checks.values())}
        if not all(checks.values()):
            raise RuntimeError("A3-G1 execution mapping gate failed")
        receipt["result"] = {
            "logical_artifact_id": f"A3_G1_{mode}_VIDEO",
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
            os.environ.pop("HIVEFRAME_A3_G1_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_A3_G1_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="owned process launch to ready"),
            "result_collection_seconds": measured(collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "gpu_kernel_seconds": unsupported(
                "Profiler, CUPTI, and Nsight were disabled for the official A3-G1 wall-clock runs.",
                "not collected",
                scope="GPU kernel-duration sum",
            ),
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
                    "Periodic resource polling is excluded from the frozen A3-G1 hot path.",
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
        (root / "private-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (root / "public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return receipt


def _available_host_bytes() -> int:
    try:
        import psutil
    except ImportError as error:
        raise RuntimeError("psutil is required for the frozen host-cache admission") from error
    return int(psutil.virtual_memory().available)


def run_experiment(
    *,
    experiment_id: str,
    p0_database: Path,
    a2_private_receipt: Path,
    private_run_root: Path,
) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, experiment_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    a2_payload, calibration, a2_digest = _load_a2_calibration(a2_private_receipt)
    ranking = a2_full_ranking(calibration)
    if tuple(ranking[: len(A2_RANKED_BLOCKS)]) != A2_RANKED_BLOCKS:
        raise RuntimeError("frozen A2 candidate ranking no longer matches immutable evidence")
    available = _available_host_bytes()
    cache = cache_budget_plan(available_host_bytes=available, ranked_blocks=ranking)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "started_at": _utc_now(),
        "product_question": "Can a pre-Attention Rust pre-plan omit real H3 Q work while preserving quality and reducing accepted runtime on RTX 3060 12GB?",
        "contract": fixed_contract(),
        "a2_evidence": {
            "private_receipt_sha256": a2_digest,
            "source_settings_digest": a2_payload.get("settings_digest"),
            "candidate_ranking_prefix": list(ranking[: len(A2_RANKED_BLOCKS)]),
        },
        "cache_admission": cache.receipt(),
        "generation_budget": 2,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
        "final_2x_target_verified": False,
        "immutable_standard": {
            "sampler_seconds": IMMUTABLE_STANDARD_SAMPLER_SECONDS,
            "submit_to_terminal_seconds": IMMUTABLE_STANDARD_SUBMIT_SECONDS,
        },
    }
    if not cache.admitted:
        summary["decision"] = DECISION_ISLAND_NOT_ADMITTED
        summary["disposition"] = "FALLBACK_ONLY"
    else:
        candidates = cache.candidate_blocks
        control = _run_generation(
            mode=CONTROL_MODE,
            candidate_blocks=candidates,
            run_id=f"{experiment_id}-control",
            prompt=prompt,
            prompt_hash=prompt_hash,
            root=root / "control",
        )
        summary["control"] = sanitize_public(control)
        summary["generation_attempt_count"] += int(control.get("generation_attempt_count", 0))
        if control.get("exit_code") != 0:
            summary["decision"] = DECISION_ISLAND_NOT_ADMITTED
            summary["disposition"] = "FALLBACK_ONLY"
        else:
            callback = control["callback_instrumentation"]
            admission = control_opportunity_gate(
                execution=callback["attention_execution"],
                region_plan=callback["region_plan"],
                c2_shadow=callback["c2_shadow"],
                output_integrity=True,
                cache_capacity=len(candidates),
            )
            summary["control_admission"] = admission
            if not admission["passed"]:
                summary["decision"] = admission["decision"]
                summary["disposition"] = "FALLBACK_ONLY"
            else:
                admitted = callback["attention_execution"]["admitted_blocks"]
                selective = _run_generation(
                    mode=SELECTIVE_MODE,
                    candidate_blocks=admitted,
                    run_id=f"{experiment_id}-selective",
                    prompt=prompt,
                    prompt_hash=prompt_hash,
                    root=root / "selective",
                )
                summary["selective"] = sanitize_public(selective)
                summary["generation_attempt_count"] += int(selective.get("generation_attempt_count", 0))
                if selective.get("exit_code") != 0:
                    summary["decision"] = DECISION_OMISSION_NOT_PROVEN
                    summary["disposition"] = "FALLBACK_ONLY"
                else:
                    quality = compare_videos(
                        Path(control["result"]["private_path"]),
                        Path(selective["result"]["private_path"]),
                    )
                    execution = selective["callback_instrumentation"]["attention_execution"]
                    work = execution["work"]
                    actual_reduction = float(work["actual_q_reduction_ratio"])
                    sampler_speedup = _sampler_seconds(control) / _sampler_seconds(selective)
                    submit_speedup = _submit_seconds(control) / _submit_seconds(selective)
                    runner_speedup = (
                        float(control["metrics"]["runner_total_seconds"]["value"])
                        / float(selective["metrics"]["runner_total_seconds"]["value"])
                    )
                    sampler_speedup_vs_standard = IMMUTABLE_STANDARD_SAMPLER_SECONDS / _sampler_seconds(selective)
                    submit_speedup_vs_standard = IMMUTABLE_STANDARD_SUBMIT_SECONDS / _submit_seconds(selective)
                    summary["quality"] = quality
                    summary["runtime_comparison"] = {
                        "control_sampler_seconds": _sampler_seconds(control),
                        "selective_sampler_seconds": _sampler_seconds(selective),
                        "sampler_speedup": sampler_speedup,
                        "sampler_speedup_vs_immutable_standard": sampler_speedup_vs_standard,
                        "control_submit_to_terminal_seconds": _submit_seconds(control),
                        "selective_submit_to_terminal_seconds": _submit_seconds(selective),
                        "submit_speedup": submit_speedup,
                        "submit_speedup_vs_immutable_standard": submit_speedup_vs_standard,
                        "runner_speedup": runner_speedup,
                    }
                    summary["actual_q_reduction"] = actual_reduction
                    omission_proven = (
                        int(work["reused_omitted_rows"]) > 0
                        and int(work["actual_current_q_rows"]) < int(work["full_q_rows_theoretical"])
                        and actual_reduction >= 0.03
                        and int(execution.get("normal_partial_plus_full_count", -1)) == 0
                        and int(execution.get("exception_partial_then_full_count", -1)) == 0
                    )
                    if not omission_proven:
                        summary["decision"] = DECISION_OMISSION_NOT_PROVEN
                        summary["disposition"] = "FALLBACK_ONLY"
                    elif not quality["passed"]:
                        summary["decision"] = DECISION_QUALITY_REJECTED
                        summary["disposition"] = "FALLBACK_ONLY"
                    elif (
                        sampler_speedup <= 1.0
                        or submit_speedup <= 1.0
                        or sampler_speedup_vs_standard <= 1.0
                        or submit_speedup_vs_standard <= 1.0
                    ):
                        summary["decision"] = DECISION_RUNTIME_NOT_POSITIVE
                        summary["disposition"] = "KEEP_AS_OPTIONAL"
                    else:
                        summary["decision"] = DECISION_READY_FOR_VISUAL
                        summary["disposition"] = "KEEP_AS_OPTIONAL"
                        summary["visual_review"] = _visual_review_package(
                            Path(control["result"]["private_path"]),
                            Path(selective["result"]["private_path"]),
                            quality["highest_control_motion_frames"],
                            root,
                        )
    summary["finished_at"] = _utc_now()
    summary["retry_count"] = 0
    summary["third_generation_count"] = 0
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiment-private-receipt.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (root / "experiment-public-summary.json").write_text(
        json.dumps(sanitize_public(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded A3-G1C CONTROL and preplanned SELECTIVE H3 experiment.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--a2-private-receipt", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = run_experiment(
        experiment_id=args.experiment_id,
        p0_database=args.p0_database,
        a2_private_receipt=args.a2_private_receipt,
        private_run_root=args.private_run_root,
    )
    print(json.dumps(sanitize_public(summary), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
