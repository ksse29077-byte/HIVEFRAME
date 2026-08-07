"""Run the single approved C4-S0 Full Compute H3 cost-surface probe."""

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
from .c3_r2_h3_residual_probe import APPROVED_WORKFLOW_SHA256
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .h3_subblock_cost_surface import (
    EXPECTED_BLOCK_CALLS,
    LOGICAL_GROUPS,
    MODEL_SOURCE_RELATIVE,
    MODEL_SOURCE_SHA256,
    instrumentation_comparability,
    inspect_installed_source,
    rank_compute_levers,
)
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "c4-s0.h3.subblock-cost-surface.1"
NODE_CLASS = "HIVEFRAMEH3SubBlockCostSampler"
RUN_KIND = "FULL_COMPUTE_SUBBLOCK_PROFILE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def settings_digest() -> str:
    payload = {
        "run_kind": RUN_KIND,
        "model_source_sha256": MODEL_SOURCE_SHA256,
        "workflow_sha256": APPROVED_WORKFLOW_SHA256,
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
        "logical_groups": [group.public() for group in LOGICAL_GROUPS],
        "full_compute_only": True,
        "profiler_enabled": False,
        "comparability_relative_limit": 0.05,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    settings_digest_value: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C4-S0 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C4-S0 sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update(
        {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest_value,
            "model_revision_digest": MODEL_SOURCE_SHA256,
        }
    )
    return workflow


def mapping_gate(callback: Mapping[str, Any]) -> dict[str, Any]:
    timing = callback.get("timing") if isinstance(callback.get("timing"), Mapping) else {}
    groups = timing.get("logical_groups") if isinstance(timing.get("logical_groups"), list) else []
    group_counts = {
        str(group.get("group_id")): group.get("timing", {}).get("count")
        for group in groups
        if isinstance(group, Mapping) and isinstance(group.get("timing"), Mapping)
    }
    checks = {
        "sampler_succeeded": callback.get("sampler_succeeded") is True,
        "full_compute_only": callback.get("full_compute_only") is True,
        "model_forward_count": timing.get("model_forward_count") == 20,
        "block_call_count": timing.get("block_call_count") == EXPECTED_BLOCK_CALLS,
        "mapping_error_zero": timing.get("mapping_error_count") == 0,
        "wrapper_failure_zero": timing.get("wrapper_failure_count") == 0,
        "logical_group_count": len(groups) == len(LOGICAL_GROUPS),
        "every_group_called_1000_times": all(
            group_counts.get(group.group_id) == EXPECTED_BLOCK_CALLS for group in LOGICAL_GROUPS
        ),
        "single_synchronization": timing.get("synchronization_count") == 1,
        "event_pair_bound": int(timing.get("event_pair_creation_count", 10**9))
        <= int(timing.get("event_pair_bound", -1)),
        "event_object_bound": int(timing.get("event_object_count", 10**9))
        <= int(timing.get("event_object_bound", -1)),
        "profiler_disabled": timing.get("profiler_enabled") is False,
        "cuda_event_timing_collected": timing.get("support_status") == "collected",
        "skip_zero": timing.get("skip_count") == 0 and callback.get("skip_count") == 0,
        "reuse_zero": timing.get("reuse_count") == 0 and callback.get("reuse_count") == 0,
        "prediction_zero": timing.get("prediction_count") == 0 and callback.get("prediction_count") == 0,
        "regional_execution_zero": timing.get("regional_execution_count") == 0
        and callback.get("regional_execution_count") == 0,
        "token_omission_zero": timing.get("token_omission_count") == 0
        and callback.get("token_omission_count") == 0,
        "attention_omission_zero": timing.get("attention_omission_count") == 0
        and callback.get("attention_omission_count") == 0,
    }
    return {"checks": checks, "passed": all(checks.values())}


def run_probe(
    *,
    run_id: str,
    p0_database: Path,
    private_run_root: Path,
) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    source = base_config.comfyui_root / MODEL_SOURCE_RELATIVE if base_config.comfyui_root else Path("<missing>")
    source_gate = inspect_installed_source(source)
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    callback_receipt_path = root / "c4-s0-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C4_S0_RECEIPT")
    python_entries = [str(repository_root / "python")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C4_S0_RECEIPT"] = str(callback_receipt_path)
    runner_started = time.monotonic()
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    exit_code = 1
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": RUN_KIND,
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "settings_digest": settings_digest(),
        "source_admission": source_gate,
        "full_compute_only": True,
        "actual_selective_work_reduction": 0,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
        "claim_boundary": "single-profile read-only cost attribution; CUDA event spans are not kernel-duration sums or product speedup",
    }
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("C4-S0 installed-source admission failed")
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
            "c4_s0_custom_node_present": custom_node_present,
            "source_admission": source_gate,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C4-S0 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C4-S0 custom node is unavailable")
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
            raise RuntimeError("C4-S0 Standard execution profile changed")
        receipt["execution_profile"] = profile
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/c4-s0-{prompt_hash[:16]}",
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        workflow = build_workflow(
            standard,
            run_digest=run_digest,
            settings_digest_value=receipt["settings_digest"],
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": receipt["settings_digest"],
            "model_revision_digest": MODEL_SOURCE_SHA256,
            "runtime_wrapper": NODE_CLASS,
            "full_compute_only": True,
            "logical_group_count": len(LOGICAL_GROUPS),
            "rust_abi": "unchanged; no Rust call is required for C4-S0 timing",
        }
        receipt["sage_node_count"] = sum(
            node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values()
        )
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C4-S0 workflow contains a Sage node")
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
        output = root / "c4-s0-full-compute-subblock-profile.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        collection_seconds = time.monotonic() - collection_started
        if (
            decode["decoded_frame_count"] != 124
            or (decode["width"], decode["height"]) != (864, 480)
            or decode["fps"] != 24.0
            or decode["codec"] != "h264"
            or decode["audio_stream_count"] < 1
            or decode["black_frame_count"] != 0
            or decode["corrupted_frame_count"] != 0
        ):
            receipt["technical_decision"] = "C4_S0_OUTPUT_PARITY_FAILED"
            raise RuntimeError("C4-S0 output failed fixed video integrity contract")
        if not callback_receipt_path.is_file():
            raise RuntimeError("C4-S0 callback receipt is missing")
        callback = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["callback_instrumentation"] = callback
        receipt["mapping_gate"] = mapping_gate(callback)
        if not receipt["mapping_gate"]["passed"]:
            receipt["technical_decision"] = "C4_S0_INSTRUMENTATION_NOT_ADMITTED"
            raise RuntimeError("C4-S0 instrumentation mapping Gate failed")
        receipt["candidate_ranking"] = rank_compute_levers(callback["timing"])
        receipt["result"] = {
            "logical_artifact_id": "C4_S0_FULL_COMPUTE_VIDEO",
            "private_path": str(output),
            "filename": descriptor.get("filename"),
            "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(),
            "decode": decode,
        }
        exit_code = 0
    except Exception as error:
        receipt.setdefault("technical_decision", "C4_S0_INSTRUMENTATION_NOT_ADMITTED")
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
            os.environ.pop("HIVEFRAME_C4_S0_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C4_S0_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(
                startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"
            ),
            "result_collection_seconds": measured(
                collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"
            ),
            "shutdown_seconds": measured(
                shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"
            ),
            "runner_total_seconds": measured(
                runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"
            ),
            "gpu_kernel_seconds": unsupported(
                "PyTorch profiler, CUPTI, Nsight, and kernel profiling were disabled for C4-S0.",
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
                "resource_sampler": resource_sampler.summary() if resource_sampler else None,
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
        if "callback_instrumentation" not in receipt and callback_receipt_path.is_file():
            receipt["callback_instrumentation"] = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        if exit_code == 0:
            sampler_seconds = receipt["phase_attribution"]["phases"]["denoising"]["seconds"]
            receipt["instrumentation_comparability"] = instrumentation_comparability(sampler_seconds)
            if receipt["instrumentation_comparability"]["passed"]:
                receipt["technical_decision"] = "C4_S0_SUBBLOCK_COST_SURFACE_MAPPED"
            else:
                receipt["technical_decision"] = "C4_S0_INSTRUMENTATION_OVERHEAD_TOO_HIGH"
        receipt["exit_code"] = exit_code
        private_receipt = root / "c4-s0-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        public_summary = root / "c4-s0-public-summary.json"
        public_summary.write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
        receipt["public_summary_path"] = str(public_summary)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    phase = receipt.get("phase_attribution") if isinstance(receipt.get("phase_attribution"), Mapping) else {}
    phases = phase.get("phases") if isinstance(phase.get("phases"), Mapping) else {}
    callback = (
        receipt.get("callback_instrumentation")
        if isinstance(receipt.get("callback_instrumentation"), Mapping)
        else {}
    )
    timing = callback.get("timing") if isinstance(callback.get("timing"), Mapping) else {}
    return sanitize_public(
        {
            "run_id": receipt.get("run_id"),
            "run_kind": receipt.get("run_kind"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "technical_decision": receipt.get("technical_decision"),
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "model_forward_count": timing.get("model_forward_count"),
            "block_call_count": timing.get("block_call_count"),
            "sampler_seconds": phases.get("denoising", {}).get("seconds") if isinstance(phases.get("denoising"), Mapping) else None,
            "submit_to_terminal_seconds": phase.get("submit_to_terminal_seconds"),
            "runner_total_seconds": receipt.get("metrics", {}).get("runner_total_seconds"),
            "instrumentation_comparability": receipt.get("instrumentation_comparability"),
            "candidate_ranking": receipt.get("candidate_ranking"),
            "timing": timing,
            "result_sha256": result.get("sha256"),
            "decode": result.get("decode"),
            "error": receipt.get("runner_error_message"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one C4-S0 Full Compute H3 sub-block cost probe.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = run_probe(
        run_id=args.run_id,
        p0_database=args.p0_database,
        private_run_root=args.private_run_root,
    )
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
