"""Run the one authorized V4 teardown remediation sequence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import json

from .h3_cuda_fixture_teardown_v4 import run_teardown_remediation


def _public_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "label",
        "fixture_state",
        "allocated_bytes",
        "reserved_bytes",
        "peak_allocated_bytes",
        "peak_reserved_bytes",
        "active_bytes",
        "inactive_split_bytes",
        "allocation_count",
        "active_allocation_count",
        "segment_count",
        "pinned_host_allocation_bytes",
        "python_live_cuda_tensor_count",
        "python_live_cuda_tensor_bytes",
        "cuda_storage_count",
        "worker_thread_count",
        "fixture_owned_cuda_tensor_count",
        "fixture_owned_cuda_tensor_bytes",
        "fixture_owned_pinned_tensor_count",
        "fixture_owned_pinned_bytes",
        "outstanding_event_count",
        "outstanding_stream_count",
        "outstanding_future_count",
        "future_cuda_result_count",
        "worker_owner_count",
        "fixture_owned_helper_count",
        "released_fixture_cuda_tensor_count",
        "released_fixture_pinned_tensor_count",
    )
    public = {name: snapshot.get(name) for name in allowed}
    public["snapshot_digest"] = sha256(
        json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return public


def sanitize_public(receipt: Mapping[str, Any]) -> dict[str, Any]:
    warmup = receipt["warm_up"]
    verifications = receipt["verification_cycles"]
    return {
        "schema_version": receipt["schema_version"],
        "decision": receipt["decision"],
        "passed": receipt["passed"],
        "root_cause_classification": receipt["root_cause_classification"],
        "allocator_baseline_classification": receipt[
            "allocator_baseline_classification"
        ],
        "cold_baseline": _public_snapshot(receipt["cold_baseline"]),
        "warm_baseline": _public_snapshot(receipt["warm_baseline"]),
        "warm_up": {
            "functional": warmup["functional"],
            "transitions": warmup["close"]["transitions"],
            "close_idempotence": warmup["close_idempotence"],
            "allocation_after": _public_snapshot(
                warmup["close"]["snapshots"]["allocation_after"]
            ),
            "final": _public_snapshot(
                warmup["close"]["snapshots"]["empty_cache"]
            ),
        },
        "negative_tests": [
            {
                "name": case["name"],
                "leak_detected": case["leak_detected"],
                "release_passed": case["release_passed"],
                "passed": case["passed"],
                "retained": _public_snapshot(case["retained_snapshot"]),
                "released": _public_snapshot(case["released_snapshot"]),
            }
            for case in receipt["negative_tests"]
        ],
        "rolling_slot_normal": {
            key: value
            for key, value in receipt["rolling_slot_normal"].items()
            if key != "final_snapshot"
        },
        "rolling_slot_abort": {
            key: value
            for key, value in receipt["rolling_slot_abort"].items()
            if key != "final_snapshot"
        },
        "verification_cycles": [
            {
                "cycle_name": cycle["functional"]["cycle_name"],
                "functional": cycle["functional"],
                "transitions": cycle["close"]["transitions"],
                "close_idempotence": cycle["close_idempotence"],
                "allocation_after": _public_snapshot(
                    cycle["close"]["snapshots"]["allocation_after"]
                ),
                "close_immediate": _public_snapshot(
                    cycle["close"]["snapshots"]["close_immediate"]
                ),
                "worker_join": _public_snapshot(
                    cycle["close"]["snapshots"]["worker_join"]
                ),
                "event_stream_completion": _public_snapshot(
                    cycle["close"]["snapshots"]["event_stream_completion"]
                ),
                "gc_collect": _public_snapshot(
                    cycle["close"]["snapshots"]["gc_collect"]
                ),
                "final": _public_snapshot(
                    cycle["close"]["snapshots"]["empty_cache"]
                ),
            }
            for cycle in verifications
        ],
        "verification_final_allocated_bytes": receipt[
            "verification_final_allocated_bytes"
        ],
        "verification_final_reserved_bytes": receipt[
            "verification_final_reserved_bytes"
        ],
        "allocated_growth_bytes": receipt["allocated_growth_bytes"],
        "reserved_growth_bytes": receipt["reserved_growth_bytes"],
        "planned_warmup_count": receipt["planned_warmup_count"],
        "planned_verification_count": receipt["planned_verification_count"],
        "retry_count": receipt["retry_count"],
        "checks": receipt["checks"],
        "h3_model_load_count": 0,
        "formal_control_submission_count": 0,
        "formal_control_gpu_start_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "attention_omission_count": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run V4 CUDA teardown remediation")
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args(argv)
    import torch

    receipt = run_teardown_remediation(
        torch, verification_cycles=3, run_negative_tests=True
    )
    public = sanitize_public(receipt)
    args.private_output.parent.mkdir(parents=True, exist_ok=True)
    args.public_output.parent.mkdir(parents=True, exist_ok=True)
    args.private_output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.public_output.write_text(
        json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(public, sort_keys=True))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
