"""One-shot C3-R3 CONTROL or admitted SELECTIVE Local H3 probe."""

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
    EventTimeline, ResourceSampler, _collect_websocket_run, _history_video,
    _safe_run_root, measured, sanitize_public, unsupported,
)
from .c3_r2_h3_residual_probe import (
    APPROVED_WORKFLOW_SHA256, MODEL_SOURCE_SHA256, QUALITY_GATE,
    compare_videos, source_admission,
)
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .compact_residual_correction import (
    BLOCK_COUNT, CONTROL, FROZEN_CEILING, MECHANISM, MIN_CALIBRATED_TARGETS,
    SEGMENT_BLOCKS, SELECTIVE, correction_settings_digest,
    select_calibrated_targets, validate_calibrated_targets,
)
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


SCHEMA_VERSION = "c3-r3.h3.compact-residual-correction.1"
NODE_CLASS = "HIVEFRAMEH3CompactResidualCorrectionSampler"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]], *, run_digest: str,
    workflow_revision_digest: str, settings_digest: str, model_revision_digest: str,
    calibrated_targets: tuple[int, ...], actual_corrected_replay_enabled: bool,
) -> dict[str, Any]:
    validate_calibrated_targets(calibrated_targets)
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C3-R3 requires Standard SamplerCustomAdvanced at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C3-R3 sampler inputs are malformed")
    sampler["class_type"] = NODE_CLASS
    inputs.update({
        "run_digest": run_digest,
        "workflow_revision_digest": workflow_revision_digest,
        "settings_digest": settings_digest,
        "model_revision_digest": model_revision_digest,
        "calibrated_targets_csv": ",".join(str(value) for value in calibrated_targets),
        "actual_corrected_replay_enabled": bool(actual_corrected_replay_enabled),
    })
    return workflow


def _mapping_gate(mode: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    execution = policy.get("segment_execution") if isinstance(policy.get("segment_execution"), Mapping) else {}
    plan = policy.get("c3_r3_plan") if isinstance(policy.get("c3_r3_plan"), Mapping) else {}
    original = int(execution.get("original_block_call_count", -1))
    replayed = int(execution.get("replayed_block_call_count", -1))
    replay_steps = int(execution.get("actual_replay_steps", -1))
    checks = {
        "sampler_succeeded": policy.get("sampler_succeeded") is True,
        "model_forward_count": execution.get("model_forward_count") == 20,
        "exact_block_accounting": original + replayed == 1000,
        "exact_replay_accounting": replayed == replay_steps * len(SEGMENT_BLOCKS),
        "mapping_error_zero": execution.get("mapping_error_count") == 0,
        "wrapper_failure_zero": execution.get("wrapper_failure_count") == 0,
        "tensor_bytes_to_rust_zero": plan.get("tensor_bytes_to_rust") == 0,
        "persistent_predicted_residual_zero": execution.get("persistent_predicted_residual_count") == 0,
        "per_block_cache_zero": execution.get("per_block_cache_count") == 0,
        "bounded_residual_buffers": int(execution.get("max_concurrent_residual_sized_buffers", 99)) <= 2,
        "full_size_fp32_zero": execution.get("full_size_fp32_materialization_count") == 0,
    }
    if mode == CONTROL:
        checks.update({"control_original_calls": original == BLOCK_COUNT * 20,
                       "control_replay_zero": replayed == 0 and replay_steps == 0})
    return {"checks": checks, "passed": all(checks.values())}


def run_probe(
    *, mode: str, run_id: str, p0_database: Path, private_run_root: Path,
    calibrated_targets: tuple[int, ...] = (), compare_control_video: Path | None = None,
) -> dict[str, Any]:
    if mode not in {CONTROL, SELECTIVE}:
        raise ValueError("invalid C3-R3 mode")
    validate_calibrated_targets(calibrated_targets)
    if mode == CONTROL and calibrated_targets:
        raise ValueError("CONTROL must not receive calibrated targets")
    if mode == SELECTIVE and len(calibrated_targets) < MIN_CALIBRATED_TARGETS:
        raise ValueError("SELECTIVE requires at least two CONTROL-calibrated targets")
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    source_gate = source_admission(base_config.comfyui_root)
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    callback_receipt_path = root / "c3-r3-callback-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C3_R3_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C3_R3_RECEIPT"] = str(callback_receipt_path)
    actual_replay = mode == SELECTIVE
    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "run_id": run_id,
        "run_kind": "c3_r3_compact_residual_correction", "mode": mode,
        "mechanism": MECHANISM, "started_at": _utc_now(), "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0, "retry_count": 0, "external_api_call_count": 0,
        "model_download_count": 0, "sage_node_count": 0,
        "actual_corrected_replay_enabled": actual_replay,
        "calibrated_targets": list(calibrated_targets), "frozen_ceiling": list(FROZEN_CEILING),
        "segment_blocks": list(SEGMENT_BLOCKS), "source_admission": source_gate,
        "product_promotion": 0, "product_acceleration_ready": False, "speedup_claim": 0,
        "claim_boundary": "single-profile mechanism evidence; product acceleration remains false",
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    startup_seconds = collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        if not source_gate.get("admitted"):
            raise RuntimeError("C3-R3 installed-source admission failed")
        startup_started = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup_started
        runtime, assets, workflow_status = backend.inspect_runtime(), backend.inspect_assets(), backend.inspect_workflow()
        objects = backend.client.json("GET", "/object_info")
        custom_node_present = isinstance(objects, Mapping) and NODE_CLASS in objects
        receipt["preflight"] = {"runtime": runtime, "assets": assets, "workflow": workflow_status,
                                "c3_r3_custom_node_present": custom_node_present,
                                "source_admission": source_gate}
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C3-R3 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C3-R3 custom node is unavailable")
        if workflow_status.get("workflow_sha256") != APPROVED_WORKFLOW_SHA256:
            raise RuntimeError("approved Standard workflow hash changed")
        expected_profile = {"width": 864, "height": 480, "frame_count": 124, "fps": 24,
                            "steps": 20, "scheduler": "simple", "sampler": "res_multistep",
                            "denoise": 1.0, "seed": 101}
        profile = workflow_status.get("execution_profile")
        if not isinstance(profile, Mapping) or any(profile.get(k) != v for k, v in expected_profile.items()):
            raise RuntimeError("C3-R3 Standard execution profile changed")
        receipt["execution_profile"] = profile
        standard = backend.build_api_workflow(
            {"content": [{"type": "text", "text": prompt}]},
            output_prefix=f"hiveframe/c3-r3-{mode.lower()}-{prompt_hash[:16]}",
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        settings_digest = correction_settings_digest(
            actual_replay_enabled=actual_replay, calibrated_targets=calibrated_targets
        )
        workflow = build_workflow(
            standard, run_digest=run_digest,
            workflow_revision_digest=APPROVED_WORKFLOW_SHA256,
            settings_digest=settings_digest, model_revision_digest=MODEL_SOURCE_SHA256,
            calibrated_targets=calibrated_targets,
            actual_corrected_replay_enabled=actual_replay,
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest, "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest, "model_revision_digest": MODEL_SOURCE_SHA256,
            "runtime_wrapper": NODE_CLASS, "actual_corrected_replay_enabled": actual_replay,
            "calibrated_targets": list(calibrated_targets),
        }
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C3-R3 workflow contains a Sage node")
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
        output = root / f"c3-r3-{mode.lower()}.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        collection_seconds = time.monotonic() - collection_started
        if (decode["decoded_frame_count"] != 124 or (decode["width"], decode["height"]) != (864, 480)
                or decode["fps"] != 24.0 or decode["codec"] != "h264"
                or decode["audio_stream_count"] < 1 or decode["black_frame_count"] != 0
                or decode["corrupted_frame_count"] != 0):
            raise RuntimeError("C3-R3 output failed fixed video integrity contract")
        if not callback_receipt_path.is_file():
            raise RuntimeError("C3-R3 callback receipt is missing")
        callback_policy = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["callback_policy"] = callback_policy
        receipt["mapping_gate"] = _mapping_gate(mode, callback_policy)
        if not receipt["mapping_gate"]["passed"]:
            raise RuntimeError("C3-R3 block/cache/predictor mapping gate failed")
        execution = callback_policy.get("segment_execution", {})
        if mode == CONTROL:
            diagnostics = execution.get("diagnostics", [])
            selected = select_calibrated_targets(diagnostics if isinstance(diagnostics, list) else [])
            receipt["control_calibration"] = {
                "frozen_before_selective": True, "selected_targets": list(selected),
                "minimum_required": MIN_CALIBRATED_TARGETS,
                "selective_admitted": len(selected) >= MIN_CALIBRATED_TARGETS,
                "selection_method": "chronological deterministic spacing >=3 inside frozen ceiling",
                "thresholds_unchanged_from_c3_r2": {
                    "cosine_min": 0.99, "normalized_l2_max": 0.20,
                    "raw_non_regression_required": True,
                },
            }
        receipt["result"] = {
            "logical_artifact_id": f"C3_R3_{mode}_VIDEO", "private_path": str(output),
            "filename": descriptor.get("filename"), "size_bytes": len(content),
            "sha256": sha256(content).hexdigest(), "decode": decode,
        }
        if mode == SELECTIVE:
            if compare_control_video is None or not compare_control_video.is_file():
                raise RuntimeError("SELECTIVE requires the completed CONTROL video")
            receipt["quality_comparison"] = compare_videos(compare_control_video, output, root)
            original = int(execution.get("original_block_call_count", -1))
            replay_steps = int(execution.get("actual_replay_steps", 0))
            receipt["compute_accounting"] = {
                "control_expected_original_block_calls": 1000,
                "selective_original_block_calls": original,
                "actual_replay_steps": replay_steps,
                "omitted_original_block_calls": 1000 - original,
                "exact": 1000 - original == replay_steps * len(SEGMENT_BLOCKS),
            }
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
            os.environ.pop("HIVEFRAME_C3_R3_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C3_R3_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"),
            "result_collection_seconds": measured(collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"),
            "shutdown_seconds": measured(shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"),
            "runner_total_seconds": measured(runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"),
            "torch_gpu_kernel_seconds": unsupported("No GPU profiler run was authorized for C3-R3.", "not collected", scope="GPU kernel"),
        }
        if timeline is not None:
            receipt["node_timeline"] = timeline.node_timeline()
            receipt["progress_timeline"] = timeline.progress_summary()
            receipt["phase_attribution"] = timeline.phase_attribution(
                runner_total_seconds=runner_total, runtime_startup_seconds=startup_seconds,
                result_collection_seconds=collection_seconds, shutdown_seconds=shutdown_seconds,
            )
            receipt["instrumentation"] = {"websocket_parser_wall_seconds": timeline.parser_wall_seconds,
                                          "resource_sampler": resource_sampler.summary() if resource_sampler else None}
            (root / "websocket-events.jsonl").write_text(
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline.events), encoding="utf-8"
            )
        if resource_sampler is not None:
            (root / "resource-samples.json").write_text(
                json.dumps(resource_sampler.samples, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if "callback_policy" not in receipt and callback_receipt_path.is_file():
            receipt["callback_policy"] = json.loads(callback_receipt_path.read_text(encoding="utf-8"))
        receipt["exit_code"] = exit_code
        private_receipt = root / f"c3-r3-{mode.lower()}-private-receipt.json"
        private_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (root / f"c3-r3-{mode.lower()}-public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    execution = receipt.get("callback_policy", {}).get("segment_execution", {})
    phase = receipt.get("phase_attribution", {})
    return sanitize_public({
        "run_id": receipt.get("run_id"), "mode": receipt.get("mode"),
        "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
        "generation_attempt_count": receipt.get("generation_attempt_count"),
        "retry_count": receipt.get("retry_count"),
        "original_block_call_count": execution.get("original_block_call_count"),
        "replayed_block_call_count": execution.get("replayed_block_call_count"),
        "actual_replay_steps": execution.get("actual_replay_steps"),
        "diagnostics": execution.get("diagnostics"),
        "control_calibration": receipt.get("control_calibration"),
        "compute_accounting": receipt.get("compute_accounting"),
        "submit_to_terminal_seconds": phase.get("submit_to_terminal_seconds"),
        "quality_comparison": receipt.get("quality_comparison"),
        "result_sha256": result.get("sha256"), "decode": result.get("decode"),
        "error": receipt.get("runner_error_message"),
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one C3-R3 correction CONTROL or SELECTIVE H3 probe.")
    parser.add_argument("--mode", required=True, choices=(CONTROL, SELECTIVE))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    parser.add_argument("--calibrated-targets", default="")
    parser.add_argument("--compare-control-video", type=Path)
    args = parser.parse_args(argv)
    targets = tuple(int(value) for value in args.calibrated_targets.split(",") if value.strip())
    receipt = run_probe(mode=args.mode, run_id=args.run_id, p0_database=args.p0_database,
                        private_run_root=args.private_run_root, calibrated_targets=targets,
                        compare_control_video=args.compare_control_video)
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
