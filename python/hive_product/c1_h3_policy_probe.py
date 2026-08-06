"""One-shot C1 Standard H3 full-compute parity probe."""

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
    HISTORICAL_STANDARD_SUBMIT_SECONDS,
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


C1_SCHEMA_VERSION = "c1.h3.rust-step-policy.1"
APPROVED_WORKFLOW_SHA256 = "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6"
C1_NODE_CLASS = "HIVEFRAMERustPolicySampler"
BOUNDARY_P95_LIMIT_SECONDS = 0.2235
CUMULATIVE_POLICY_LIMIT_SECONDS = 4.866
SUBMIT_TO_TERMINAL_LIMIT_SECONDS = 616.336


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def c1_settings_digest() -> str:
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
        "policy": "rust_full_compute_parity",
        "sage": False,
    }
    return sha256(json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_c1_workflow(
    standard_workflow: Mapping[str, Mapping[str, Any]],
    *,
    run_digest: str,
    workflow_revision_digest: str,
    settings_digest: str,
) -> dict[str, Any]:
    workflow = copy.deepcopy(dict(standard_workflow))
    sampler = workflow.get("10")
    if not isinstance(sampler, dict) or sampler.get("class_type") != "SamplerCustomAdvanced":
        raise ValueError("C1 requires the existing Standard SamplerCustomAdvanced node at logical node 10")
    inputs = sampler.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("C1 sampler inputs are malformed")
    sampler["class_type"] = C1_NODE_CLASS
    inputs["run_digest"] = run_digest
    inputs["workflow_revision_digest"] = workflow_revision_digest
    inputs["settings_digest"] = settings_digest
    return workflow


def _policy_gate(policy: Mapping[str, Any], submit_seconds: float | None) -> dict[str, Any]:
    boundary_p95_ns = policy.get("boundary_roundtrip", {}).get("p95_ns")
    cumulative_ns = policy.get("cumulative_policy_overhead_ns")
    checks = {
        "callback_and_call_counts_match": policy.get("callback_count") == policy.get("rust_call_count") == 20,
        "full_compute_only": policy.get("full_compute_count") == 20,
        "escalate_zero": policy.get("escalate_full_compute_count") == 0,
        "fallback_zero": policy.get("fallback_count") == 0,
        "selective_compute_zero": all(
            policy.get(name) == 0
            for name in (
                "skipped_step_count",
                "skipped_block_count",
                "skipped_token_count",
                "skipped_latent_count",
                "reused_cache_count",
                "partial_compute_count",
                "tensor_bytes_transferred",
            )
        ),
        "boundary_p95_within_limit": isinstance(boundary_p95_ns, int)
        and boundary_p95_ns / 1_000_000_000 <= BOUNDARY_P95_LIMIT_SECONDS,
        "cumulative_policy_within_limit": isinstance(cumulative_ns, int)
        and cumulative_ns / 1_000_000_000 <= CUMULATIVE_POLICY_LIMIT_SECONDS,
        "submit_to_terminal_within_limit": isinstance(submit_seconds, (int, float))
        and submit_seconds <= SUBMIT_TO_TERMINAL_LIMIT_SECONDS,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "boundary_p95_limit_seconds": BOUNDARY_P95_LIMIT_SECONDS,
        "cumulative_policy_limit_seconds": CUMULATIVE_POLICY_LIMIT_SECONDS,
        "submit_to_terminal_limit_seconds": SUBMIT_TO_TERMINAL_LIMIT_SECONDS,
    }


def run_probe(*, run_id: str, p0_database: Path, private_run_root: Path) -> dict[str, Any]:
    root = _safe_run_root(private_run_root, run_id)
    prompt, prompt_hash = _load_private_prompt(p0_database)
    repository_root = Path(__file__).resolve().parents[2]
    custom_nodes_root = repository_root / "python" / "hive_product" / "comfyui_nodes"
    base_config = ComfyUIH3Config.from_env()
    backend = MiniMaxH3ComfyUIBackend(config=replace(base_config, custom_nodes_root=custom_nodes_root))
    policy_receipt_path = root / "rust-step-policy-private-receipt.json"
    prior_pythonpath = os.environ.get("PYTHONPATH")
    prior_receipt = os.environ.get("HIVEFRAME_C1_POLICY_RECEIPT")
    python_entries = [str(repository_root / "python"), str(repository_root / "target" / "release")]
    if prior_pythonpath:
        python_entries.append(prior_pythonpath)
    os.environ["PYTHONPATH"] = os.pathsep.join(python_entries)
    os.environ["HIVEFRAME_C1_POLICY_RECEIPT"] = str(policy_receipt_path)

    runner_started = time.monotonic()
    receipt: dict[str, Any] = {
        "schema_version": C1_SCHEMA_VERSION,
        "run_id": run_id,
        "run_kind": "c1_rust_full_compute_parity",
        "started_at": _utc_now(),
        "prompt_sha256": prompt_hash,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "external_api_call_count": 0,
        "model_download_count": 0,
        "sage_node_count": 0,
        "standard_full_compute": True,
        "selective_compute_enabled": False,
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
        custom_node_present = isinstance(objects, Mapping) and C1_NODE_CLASS in objects
        receipt["preflight"] = {
            "runtime": runtime,
            "assets": assets,
            "workflow": workflow_status,
            "c1_custom_node_present": custom_node_present,
        }
        if any(item.get("state") != "ready" for item in (runtime, assets, workflow_status)):
            raise RuntimeError("C1 Local H3 preflight did not reach ready")
        if not custom_node_present:
            raise RuntimeError("repository-owned C1 custom node is unavailable")
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
            raise RuntimeError("C1 Standard execution profile changed")
        receipt["execution_profile"] = profile
        generation_request = {"content": [{"type": "text", "text": prompt}]}
        standard_workflow = backend.build_api_workflow(
            generation_request, output_prefix=f"hiveframe/c1-{prompt_hash[:16]}"
        )
        run_digest = sha256(run_id.encode()).hexdigest()
        settings_digest = c1_settings_digest()
        workflow = build_c1_workflow(
            standard_workflow,
            run_digest=run_digest,
            workflow_revision_digest=APPROVED_WORKFLOW_SHA256,
            settings_digest=settings_digest,
        )
        receipt["policy_contract"] = {
            "run_digest": run_digest,
            "workflow_revision_digest": APPROVED_WORKFLOW_SHA256,
            "settings_digest": settings_digest,
            "selected_hook": "sampler.progress_callback",
            "runtime_wrapper": C1_NODE_CLASS,
        }
        receipt["sage_node_count"] = sum(
            node.get("class_type") == SAGE_NODE_CLASS for node in workflow.values()
        )
        if receipt["sage_node_count"] != 0:
            raise RuntimeError("C1 Standard workflow contains a Sage node")
        timeline = EventTimeline(workflow)
        resource_sampler = ResourceSampler(backend, timeline, interval_seconds=1.0)
        resource_sampler.start()
        receipt["generation_attempt_count"] = 1
        prompt_id, history = asyncio.run(_collect_websocket_run(backend, workflow, timeline))
        if timeline.terminal_event != "execution_success":
            raise RuntimeError(f"ComfyUI terminal event was {timeline.terminal_event}")
        receipt["backend_prompt_id"] = prompt_id
        collection_started = time.monotonic()
        descriptor, content = _history_video(backend, history)
        output = root / "c1-rust-full-compute.mp4"
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
            raise RuntimeError("C1 output failed the fixed video integrity contract")
        if not policy_receipt_path.is_file():
            raise RuntimeError("C1 policy callback receipt is missing")
        policy = json.loads(policy_receipt_path.read_text(encoding="utf-8"))
        receipt["step_policy"] = policy
        receipt["result"] = {
            "logical_artifact_id": "C1_RUST_FULL_COMPUTE_VIDEO",
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
            os.environ.pop("HIVEFRAME_C1_POLICY_RECEIPT", None)
        else:
            os.environ["HIVEFRAME_C1_POLICY_RECEIPT"] = prior_receipt
        runner_total = time.monotonic() - runner_started
        receipt["finished_at"] = _utc_now()
        receipt["metrics"] = {
            "runtime_startup_seconds": measured(
                startup_seconds, "seconds", "runner monotonic span", scope="process launch to API ready"
            ),
            "result_collection_seconds": measured(
                result_collection_seconds,
                "seconds",
                "runner monotonic span",
                scope="terminal event to decoded local result",
            ),
            "shutdown_seconds": measured(
                shutdown_seconds, "seconds", "runner monotonic span", scope="owned runtime stop"
            ),
            "runner_total_seconds": measured(
                runner_total, "seconds", "runner monotonic span", scope="runner entry through runtime stop"
            ),
            "torch_gpu_kernel_seconds": unsupported(
                "No GPU profiler run was authorized for C1.", "not collected", scope="GPU kernel"
            ),
        }
        if timeline is not None:
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
        if "step_policy" not in receipt and policy_receipt_path.is_file():
            receipt["step_policy"] = json.loads(policy_receipt_path.read_text(encoding="utf-8"))
        submit_seconds = receipt.get("phase_attribution", {}).get("submit_to_terminal_seconds")
        policy = receipt.get("step_policy") if isinstance(receipt.get("step_policy"), Mapping) else {}
        receipt["c1_gate"] = _policy_gate(policy, submit_seconds)
        receipt["historical_comparison"] = {
            "c0_submit_to_terminal_seconds": HISTORICAL_STANDARD_SUBMIT_SECONDS,
            "c1_submit_to_terminal_seconds": submit_seconds,
            "difference_seconds": (
                submit_seconds - HISTORICAL_STANDARD_SUBMIT_SECONDS
                if isinstance(submit_seconds, (int, float))
                else None
            ),
            "single_run_only": True,
        }
        if exit_code == 0 and not receipt["c1_gate"]["passed"]:
            exit_code = 2
        receipt["exit_code"] = exit_code
        private_receipt = root / "c1-private-receipt.json"
        private_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (root / "c1-public-summary.json").write_text(
            json.dumps(sanitize_public(receipt), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt["private_receipt_path"] = str(private_receipt)
    return receipt


def public_result(receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    instrumentation = receipt.get("instrumentation") if isinstance(receipt.get("instrumentation"), Mapping) else {}
    return sanitize_public(
        {
            "schema_version": receipt.get("schema_version"),
            "run_id": receipt.get("run_id"),
            "terminal_status": "succeeded" if receipt.get("exit_code") == 0 else "failed",
            "generation_attempt_count": receipt.get("generation_attempt_count"),
            "retry_count": receipt.get("retry_count"),
            "prompt_id": receipt.get("backend_prompt_id"),
            "step_policy": receipt.get("step_policy"),
            "phase_attribution": receipt.get("phase_attribution"),
            "resources": instrumentation.get("resource_sampler"),
            "historical_comparison": receipt.get("historical_comparison"),
            "c1_gate": receipt.get("c1_gate"),
            "result_sha256": result.get("sha256"),
            "result_size_bytes": result.get("size_bytes"),
            "decode": result.get("decode"),
            "runner_error": receipt.get("runner_error"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run exactly one Standard H3 C1 Rust policy parity probe.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--p0-database", required=True, type=Path)
    parser.add_argument("--private-run-root", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = run_probe(run_id=args.run_id, p0_database=args.p0_database, private_run_root=args.private_run_root)
    print(json.dumps(public_result(receipt), ensure_ascii=False, sort_keys=True))
    return int(receipt.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
