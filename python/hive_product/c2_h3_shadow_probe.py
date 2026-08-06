"""One-shot C2 Standard H3 Compound Eye shadow-policy probe."""

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
from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .sageattention_probe import SAGE_NODE_CLASS, _decode_video, _load_private_prompt


C2_SCHEMA_VERSION = "c2.h3.compound-eye-shadow.1"
APPROVED_WORKFLOW_SHA256 = "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6"
C2_NODE_CLASS = "HIVEFRAMECompoundEyeShadowSampler"
SHADOW_P95_LIMIT_SECONDS = 0.1118
BOUNDARY_P95_LIMIT_SECONDS = 0.001
CUMULATIVE_SHADOW_LIMIT_SECONDS = 4.866
SUBMIT_TO_TERMINAL_LIMIT_SECONDS = 616.336


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def c2_settings_digest() -> str:
    settings = {
        "width": 864,
        "height": 480,
        "frames": 124,
        "fps": 24,
        "steps": 20,
        "seed": 101,
        "sampler": "res_multistep",
        "scheduler": "simple",
        "denoise": 1.0,
        "audio": True,
        "policy": "compound_eye_shadow_full_compute",
        "topology": "overlap_2x2",
        "eye_count": 5,
        "sketch_source": "x0",
        "signal_adapter": "h3_nested_video_v1",
        "signal_path": "x0.tensors[0]",
        "sketch_grid": [4, 4],
        "sketch_metrics": ["mean", "mean_abs", "rms"],
        "quantization_scale": 4096,
        "stable_delta_limit_ppm": 20000,
        "active_delta_limit_ppm": 80000,
        "global_invalidation_limit_ppm": 150000,
        "stable_validation_limit_ppm": 30000,
        "local_to_global_limit_ppm": 950000,
        "warmup_callbacks": 2,
        "sage": False,
        "actual_selective_compute": False,
    }
    return sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_c2_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    workflow_revision_digest: str,
    settings_digest: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C2 requires the existing Standard SamplerCustomAdvanced node at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C2 sampler inputs are malformed")
    sampler["class_type"] = C2_NODE_CLASS
    inputs["run_digest"] = run_digest
    inputs["workflow_revision_digest"] = workflow_revision_digest
    inputs["settings_digest"] = settings_digest
    return workflow


def inspect_callback_source(comfyui_root: Path) -> dict[str, Any]:
    latent_preview = comfyui_root / "latent_preview.py"
    samplers = comfyui_root / "comfy" / "samplers.py"
    nested_tensor = comfyui_root / "comfy" / "nested_tensor.py"
    h3_nodes = comfyui_root / "comfy_extras" / "nodes_minimax_h3.py"
    if not all(path.is_file() for path in (latent_preview, samplers, nested_tensor, h3_nodes)):
        raise RuntimeError("C2 callback source files are unavailable")
    preview_source = latent_preview.read_text(encoding="utf-8")
    sampler_source = samplers.read_text(encoding="utf-8")
    nested_source = nested_tensor.read_text(encoding="utf-8")
    h3_source = h3_nodes.read_text(encoding="utf-8")
    checks = {
        "prepare_callback_signature": "def prepare_callback(model, steps, x0_output_dict=None):" in preview_source,
        "callback_signature": "def callback(step, x0, x, total_steps):" in preview_source,
        "x0_receipt_assignment": 'x0_output_dict["x0"] = x0' in preview_source,
        "denoised_is_x0_argument": 'callback(x["i"], x["denoised"], x["x"], total_steps)' in sampler_source,
        "callback_rebuilds_nested_x0": "NestedTensor(comfy.utils.unpack_latents(x0, latent_shapes))" in sampler_source,
        "nested_tensor_owns_ordered_list": "self.tensors = list(tensors)" in nested_source,
        "h3_video_audio_slot_order": "NestedTensor((video, audio))" in h3_source,
        "h3_video_shape_contract": "[batch_size, 24, latent_t, height // 16, width // 16]" in h3_source,
        "h3_audio_shape_contract": "[batch_size, 32, 2, audio_t]" in h3_source,
    }
    if not all(checks.values()):
        raise RuntimeError("C2 callback source contract changed")
    return {
        "state": "admitted",
        "logical_locations": [
            "<comfyui-root>/latent_preview.py",
            "<comfyui-root>/comfy/samplers.py",
            "<comfyui-root>/comfy/nested_tensor.py",
            "<comfyui-root>/comfy_extras/nodes_minimax_h3.py",
        ],
        "checks": checks,
        "latent_preview_sha256": sha256(latent_preview.read_bytes()).hexdigest(),
        "samplers_sha256": sha256(samplers.read_bytes()).hexdigest(),
        "nested_tensor_sha256": sha256(nested_tensor.read_bytes()).hexdigest(),
        "h3_nodes_sha256": sha256(h3_nodes.read_bytes()).hexdigest(),
        "x0_provenance": "sampler callback denoised argument",
        "signal_adapter": "h3_nested_video_v1",
        "signal_path": "x0.tensors[0]",
        "x_argument_used": False,
    }


def _shadow_gate(policy: Mapping[str, Any], submit_seconds: float | None) -> dict[str, Any]:
    total_p95_ns = policy.get("total_shadow_callback", {}).get("p95_ns")
    boundary_p95_ns = policy.get("boundary_roundtrip", {}).get("p95_ns")
    cumulative_ns = policy.get("cumulative_shadow_overhead_ns")
    callbacks = policy.get("callback_count")
    events = policy.get("events") if isinstance(policy.get("events"), list) else []
    source_admitted = bool(events) and all(
        isinstance(event.get("source_shape"), list)
        and len(event["source_shape"]) == 5
        and event.get("source_dtype") == "torch.bfloat16"
        and event.get("source_device_type") == "cuda"
        and event.get("signal_adapter") == "h3_nested_video_v1"
        for event in events
    )
    actual_zero = all(
        policy.get(name) == 0
        for name in (
            "skipped_step_count",
            "skipped_block_count",
            "skipped_token_count",
            "skipped_latent_count",
            "reused_cache_count",
            "partial_compute_count",
            "tensor_bytes_to_rust",
        )
    )
    checks = {
        "callback_count_positive": isinstance(callbacks, int) and callbacks > 0,
        "rust_call_count_matches": callbacks == policy.get("rust_call_count"),
        "full_compute_only": callbacks == policy.get("full_compute_count"),
        "escalate_zero": policy.get("escalate_full_compute_count") == 0,
        "fallback_zero": policy.get("fallback_count") == 0,
        "source_x0_admitted": source_admitted,
        "overlap_2x2_five_eyes": policy.get("topology") == "overlap_2x2" and policy.get("eye_count") == 5,
        "actual_selective_compute_zero": actual_zero,
        "full_tensor_host_copy_zero": policy.get("max_host_transfers_per_callback") == 1
        and policy.get("sketch", {}).get("value_count") == 48,
        "stable_candidates_at_least_two": int(policy.get("stable_candidate_count", 0)) >= 2,
        "validated_stable_at_least_two": int(policy.get("validated_stable_count", 0)) >= 2,
        "contradicted_stable_zero": policy.get("contradicted_stable_count") == 0,
        "shadow_p95_within_limit": isinstance(total_p95_ns, int)
        and total_p95_ns / 1_000_000_000 <= SHADOW_P95_LIMIT_SECONDS,
        "boundary_p95_within_limit": isinstance(boundary_p95_ns, int)
        and boundary_p95_ns / 1_000_000_000 <= BOUNDARY_P95_LIMIT_SECONDS,
        "cumulative_shadow_within_limit": isinstance(cumulative_ns, int)
        and cumulative_ns / 1_000_000_000 <= CUMULATIVE_SHADOW_LIMIT_SECONDS,
        "submit_to_terminal_within_limit": isinstance(submit_seconds, (int, float))
        and submit_seconds <= SUBMIT_TO_TERMINAL_LIMIT_SECONDS,
        "persistent_state_within_limit": int(policy.get("persistent_host_state_estimate_bytes", 65_537)) <= 65_536
        and policy.get("persistent_rust_state_bytes") == 0
        and policy.get("persistent_gpu_state_bytes") == 0,
    }
    if not checks["source_x0_admitted"] or not checks["callback_count_positive"]:
        decision = "C2_SHADOW_SIGNAL_NOT_ADMITTED"
    elif int(policy.get("contradicted_stable_count", 0)) > 0:
        decision = "C2_SHADOW_FALSE_STABLE_DETECTED"
    elif int(policy.get("stable_candidate_count", 0)) < 2 or int(policy.get("validated_stable_count", 0)) < 2:
        decision = "C2_SHADOW_NO_STABLE_ADMISSION"
    elif not all(
        checks[name]
        for name in (
            "shadow_p95_within_limit",
            "boundary_p95_within_limit",
            "cumulative_shadow_within_limit",
            "submit_to_terminal_within_limit",
            "persistent_state_within_limit",
        )
    ):
        decision = "C2_SHADOW_OVERHEAD_TOO_HIGH"
    elif all(checks.values()):
        decision = "C2_COMPOUND_EYE_SHADOW_READY"
    else:
        decision = "C2_SHADOW_REVISE_ONCE"
    return {
        "checks": checks,
        "passed": decision == "C2_COMPOUND_EYE_SHADOW_READY",
        "decision": decision,
        "limits": {
            "shadow_p95_seconds": SHADOW_P95_LIMIT_SECONDS,
            "boundary_p95_seconds": BOUNDARY_P95_LIMIT_SECONDS,
            "cumulative_shadow_seconds": CUMULATIVE_SHADOW_LIMIT_SECONDS,
            "submit_to_terminal_seconds": SUBMIT_TO_TERMINAL_LIMIT_SECONDS,
            "persistent_state_bytes": 65_536,
        },
    }


def select_c3_hook(policy: Mapping[str, Any]) -> dict[str, Any]:
    events = policy.get("events") if isinstance(policy.get("events"), list) else []
    all_regional_stable = any(
        event.get("stable_regional_eyes") == [1, 2, 3, 4]
        and event.get("validation_of_previous", {}).get("status") == "validated_stable"
        for event in events
    )
    has_stable = int(policy.get("validated_stable_count", 0)) >= 2
    contradicted = int(policy.get("contradicted_stable_count", 0)) > 0
    if all_regional_stable:
        return {
            "selection": "sampler.pre_step_model_call_gate",
            "candidate": "A",
            "status": "candidate_only",
            "reason": "all four regional eyes have a validated next-step stable candidate",
        }
    if has_stable and not contradicted:
        return {
            "selection": "h3.transformer_block_wrapper",
            "candidate": "B",
            "status": "candidate_only",
            "reason": "regional stability exists without an all-region stable admission",
        }
    return {
        "selection": "no_c3_admission",
        "candidate": "C",
        "status": "not_admitted",
        "reason": "stable evidence is absent or contradicted",
    }


def run_probe(*, run_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    if base_config.comfyui_root is None:
        raise RuntimeError("HIVEFRAME_COMFYUI_ROOT is required for C2 source admission")
    source_admission = inspect_callback_source(base_config.comfyui_root)
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    shadow_receipt_path = root / "compound-eye-shadow-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C2_SHADOW_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C2_SHADOW_RECEIPT"] = str(shadow_receipt_path)

    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": C2_SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": "c2_compound_eye_shadow_full_compute",
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "standard_full_compute": True,
        "selective_compute_enabled": False,
        "callback_source_admission": source_admission,
    }
    timeline: EventTimeline | None = None
    resource_sampler: ResourceSampler | None = None
    startup_seconds = result_collection_seconds = shutdown_seconds = 0.0
    exit_code = 1
    try:
        startup = time.monotonic()
        receipt["runtime_start"] = backend.start_runtime()
        startup_seconds = time.monotonic() - startup
        runtime = backend.inspect_runtime()
        assets = backend.inspect_assets()
        workflow_status = backend.inspect_workflow()
        objects = backend.client.json("GET", "/object_info")
        custom_node_present = isinstance(objects, Mapping) and C2_NODE_CLASS in objects
        receipt["preflight"] = {
            "runtime": runtime,
            "assets": assets,
            "workflow": workflow_status,
            "c2_custom_node_present": custom_node_present,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C2 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C2 custom node is unavailable")
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
            raise RuntimeError("C2 Standard execution profile changed")
        receipt["execution_profile"] = profile
        generation_request = {"content": [{"type": "text", "text": prompt}]}
        standard_workflow = backend.build_api_workflow(
            generation_request, output_prefix=f"hiveframe/c2-{prompt_hash[:16]}"
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        settings_digest = c2_settings_digest()
        workflow = build_c2_workflow(
            standard_workflow,
            run_digest=run_digest,
            workflow_revision_digest=APPROVED_WORKFLOW_SHA256,
            settings_digest=settings_digest,
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest,
            "selected_hook": "sampler.progress_callback.x0",
            "runtime_wrapper": C2_NODE_CLASS,
            "topology": "overlap_2x2",
            "actual_compute": "FULL_COMPUTE",
        }
        receipt["sage_node_count"] = sum(node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values())
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C2 Standard workflow contains a Sage node")
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
        output = root / "c2-compound-eye-shadow.mp4"
        output.write_bytes(content)
        decode = _decode_video(output)
        result_collection_seconds = time.monotonic() - collection_started
        if (
            decode["decoded_frame_count"] != 124
            or (decode["width"], decode["height"]) != (864, 480)
            or decode["fps"] != 24.0
            or decode["audio_stream_count"] < 1
            or decode["black_output_detected"]
        ):
            raise RuntimeError("C2 output failed the fixed video integrity contract")
        if not shadow_receipt_path.is_file():
            raise RuntimeError("C2 shadow callback receipt is missing")
        policy = json.loads(shadow_receipt_path.read_text(encoding="utf-8"))
        receipt["shadow_policy"] = policy
        receipt["result"] = {
            "logical_artifact_id": "C2_COMPOUND_EYE_SHADOW_VIDEO",
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
            os.environ.pop("HIVEFRAME_C2_SHADOW_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C2_SHADOW_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(
                startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"
            ),
            "result_collection_seconds": measured(
                result_collection_seconds, "seconds", "runner monotonic span", scope="terminal event to decoded local result"
            ),
            "shutdown_seconds": measured(
                shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"
            ),
            "runner_total_seconds": measured(
                runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"
            ),
            "torch_gpu_kernel_seconds": unsupported(
                "No GPU profiler run was authorized for C2.", "not collected", scope="GPU kernel"
            ),
        }
        if timeline is not None:
            receipt["websocket_event_types"] = sorted({event["type"] for event in timeline.events})
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
                "".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline.events), encoding="utf-8"
            )
        if resource_sampler is not None:
            (root / "resource-samples.json").write_text(
                json.dumps(resource_sampler.samples, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        if "shadow_policy" not in receipt and shadow_receipt_path.is_file():
            receipt["shadow_policy"] = json.loads(shadow_receipt_path.read_text(encoding="utf-8"))
        submit_seconds = receipt.get("phase_attribution", {}).get("submit_to_terminal_seconds")
        policy = receipt.get("shadow_policy") if isinstance(receipt.get("shadow_policy"), Mapping) else {}
        receipt["c2_gate"] = _shadow_gate(policy, submit_seconds)
        receipt["c3_hook_admission"] = select_c3_hook(policy)
        if exit_code == 0 and not receipt["c2_gate"]["passed"]:
            exit_code = 2
        receipt["exit_code"] = exit_code
        private_receipt = root / "c2-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (root / "c2-public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    return sanitize_public(
        {
            "schema_version": receipt.get("schema_version"),
            "run_id": receipt.get("run_id"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "shadow_policy": receipt.get("shadow_policy"),
            "phase_attribution": receipt.get("phase_attribution"),
            "c2_gate": receipt.get("c2_gate"),
            "c3_hook_admission": receipt.get("c3_hook_admission"),
            "result_sha256": result.get("sha256"),
            "result_size_bytes": result.get("size_bytes"),
            "decode": result.get("decode"),
            "runner_error": receipt.get("runner_error"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exactly one Standard H3 C2 Compound Eye shadow probe.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = run_probe(run_id=args.run_id, p0_database=args.p0_database, private_run_root=args.private_run_root)
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
