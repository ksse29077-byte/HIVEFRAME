"""Model-free preflight runner for H3 hybrid cache staging."""

from __future__ import annotations

import argparse
from hashlib import sha256
import inspect
import json
from pathlib import Path
from typing import Any

from .h3_gpu_local_evidence_v2_probe import comfy_queue_snapshot
from .h3_hybrid_cache_staging import (
    BALANCED_PROFILE,
    CONTROL_ORACLE_D2H_BYTES,
    CONTROL_TRANSFER_LIMIT_BYTES,
    HOLDOUT_STATUS,
    PINNED_RING_DEPTH,
    HybridControlOracleRing,
    RingBackpressureError,
    _classification,
    _host_scalars,
    _metric_values,
    build_runtime_admission,
    calibration_gate,
)


READY = "H3_12GB_HYBRID_CACHE_STAGING_PREFLIGHT_READY"
FAILED = "H3_12GB_HYBRID_CACHE_STAGING_PREFLIGHT_FAILED"


def _maximum_metric_error(reference: dict[str, Any], observed: dict[str, Any]) -> float:
    return max(
        abs(float(reference[group][name]) - float(observed[group][name]))
        for group in ("raw", "corrected")
        for name in ("cosine", "normalized_l2")
    )


def run_bounded_synthetic_cuda(torch_module: Any) -> dict[str, Any]:
    """Verify BF16 D2H staging and exact CPU oracle on a tiny fixture."""

    if not torch_module.cuda.is_available():
        return {"status": "NOT_EXECUTED", "reason": "CUDA_UNAVAILABLE", "passed": False}
    device = torch_module.device("cuda:0")
    generator = torch_module.Generator(device="cpu").manual_seed(101)
    source_cpu = torch_module.randn(
        (96, 32), generator=generator, dtype=torch_module.float32
    ).to(dtype=torch_module.bfloat16)
    current_cpu = source_cpu.clone()
    current_cpu[:16] = (current_cpu[:16].float() + 0.015).to(torch_module.bfloat16)
    current_cpu[16:] = (current_cpu[16:].float() + 0.02).to(torch_module.bfloat16)
    source_gpu = source_cpu.to(device=device)
    current_gpu = current_cpu.to(device=device)
    lineage = sha256(b"h3-hybrid-control-oracle-synthetic").hexdigest()
    ring = HybridControlOracleRing(
        torch_module,
        device=device,
        slot_shape=source_cpu.shape,
        dtype=torch_module.bfloat16,
        maximum_records=4,
    )
    first_enqueued = ring.enqueue(
        block=0,
        region=0,
        step=1,
        lineage_digest=lineage,
        payload=source_gpu,
    )
    duplicate_deduplicated = ring.enqueue(
        block=0,
        region=0,
        step=1,
        lineage_digest=lineage,
        payload=source_gpu,
    )
    first_result = ring.consume(0)
    second_enqueued = ring.enqueue(
        block=0,
        region=0,
        step=2,
        lineage_digest=lineage,
        payload=current_gpu,
    )
    second_result = ring.consume(1)
    reference = _host_scalars(_metric_values(torch_module, source_gpu, current_gpu))
    observed = second_result["metrics"] if second_result is not None else {}
    maximum_error = _maximum_metric_error(reference, observed)
    bit_preserved = bool(
        torch_module.equal(
            ring._source_cache[(0, 0)].view(torch_module.uint16),
            current_cpu.view(torch_module.uint16),
        )
    )
    classification_identical = bool(
        second_result is not None
        and second_result["actual_safety"] == _classification(reference)
    )

    backpressure_ring = HybridControlOracleRing(
        torch_module,
        device=device,
        slot_shape=source_cpu.shape,
        dtype=torch_module.bfloat16,
        ring_depth=PINNED_RING_DEPTH,
        maximum_records=4,
    )
    backpressure_ring.enqueue(
        block=0, region=0, step=1, lineage_digest=lineage, payload=source_gpu
    )
    backpressure_ring.enqueue(
        block=1, region=0, step=1, lineage_digest=lineage, payload=source_gpu
    )
    backpressure_blocked = False
    try:
        backpressure_ring.enqueue(
            block=2, region=0, step=1, lineage_digest=lineage, payload=source_gpu
        )
    except RingBackpressureError:
        backpressure_blocked = True
    finally:
        backpressure_ring.consume(0)
        backpressure_ring.consume(1)

    source = inspect.getsource(HybridControlOracleRing.enqueue)
    forbidden = (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize(")
    hot_path_forced_sync_zero = all(token not in source for token in forbidden)
    receipt = ring.receipt()
    payload_bytes = int(source_cpu.numel()) * int(source_cpu.element_size())
    passed = bool(
        first_enqueued
        and duplicate_deduplicated
        and first_result is None
        and second_enqueued
        and second_result is not None
        and bit_preserved
        and maximum_error <= 1e-6
        and classification_identical
        and backpressure_blocked
        and hot_path_forced_sync_zero
        and receipt["D2H_TRANSFER_BYTES"]["value"] == payload_bytes * 2
        and receipt["H2D_TRANSFER_BYTES"]["value"] == 0
        and receipt["DUPLICATE_D2H_AVOIDED_BYTES"]["value"] == payload_bytes
        and receipt["RING_BACKPRESSURE_COUNT"]["value"] == 0
        and receipt["RING_OVERFLOW_COUNT"]["value"] == 0
    )
    return {
        "status": "MEASURED_SYNTHETIC",
        "passed": passed,
        "device_name": torch_module.cuda.get_device_name(device),
        "fixture_shape": list(source_cpu.shape),
        "bf16_bit_preserved": bit_preserved,
        "cpu_gpu_metric_max_abs_error": maximum_error,
        "prior_metric_error_reference": 2.980232e-7,
        "classification_identical": classification_identical,
        "backpressure_prevents_overwrite": backpressure_blocked,
        "hot_path_forced_sync_zero": hot_path_forced_sync_zero,
        "ring": receipt,
        "h3_model_load_count": 0,
        "comfy_generation_count": 0,
        "control_submission_count": 0,
        "selective_execution_count": 0,
        "partial_q_execution_count": 0,
        "actual_attention_omission_count": 0,
    }


def completion_gates(
    calibration: dict[str, Any], admission: dict[str, Any], synthetic: dict[str, Any]
) -> dict[str, bool]:
    balanced = admission["balanced_12gb"]
    receipt = balanced["receipt"]
    common = admission["common_contract"]
    return {
        "balanced_profile_exact": receipt["PROFILE"] == BALANCED_PROFILE,
        "persistent_full_source_cuda_zero": balanced["persistent_full_source_cuda_bytes"] == 0,
        "control_oracle_h2d_zero": receipt["CONTROL_ORACLE_H2D_BYTES"]["value"] == 0,
        "projected_d2h_at_most_32gib": CONTROL_ORACLE_D2H_BYTES
        <= CONTROL_TRANSFER_LIMIT_BYTES,
        "duplicate_d2h_schedule_zero": receipt["DUPLICATE_D2H_AVOIDED_BYTES"]["value"] == 0,
        "hot_path_forced_sync_zero": receipt["HOT_PATH_FORCED_SYNC_COUNT"]["value"] == 0
        and synthetic.get("hot_path_forced_sync_zero") is True,
        "bounded_pinned_ring_proven": synthetic.get("backpressure_prevents_overwrite") is True,
        "synthetic_ring_overflow_zero": synthetic.get("ring", {})
        .get("RING_OVERFLOW_COUNT", {})
        .get("value")
        == 0,
        "bf16_bit_preserved": synthetic.get("bf16_bit_preserved") is True,
        "metric_abs_error_at_most_1e_6": synthetic.get("cpu_gpu_metric_max_abs_error", 1.0)
        <= 1e-6,
        "classification_identical": synthetic.get("classification_identical") is True,
        "projected_cuda_peak_below_physical": balanced["projected_peak_vram_bytes"]
        < balanced["physical_vram_bytes"],
        "host_ram_admission_pass": balanced["host_ram"]["admission"] == "PASS",
        "runtime_admission_pass": balanced["runtime_admission"] == "PASS",
        "rust_tensor_bytes_zero": common["rust_tensor_bytes"] == 0,
        "rust_calls_at_most_one": receipt["RUST_CALLS_PER_GENERATION"]["value"] <= 1,
        "calibration_false_safe_zero": calibration["selected_false_safe_count"] == 0,
        "holdout_unknown": calibration["holdout_status"] == HOLDOUT_STATUS,
        "potential_at_least_three_percent": calibration["planned_q_ratio"] >= 0.03,
        "quality_profile_simulated": admission["quality_24gb_plus"]["execution_status"]
        == "SIMULATED_NOT_EXECUTED",
        "no_generation_or_omission": all(
            synthetic.get(field) == 0
            for field in (
                "h3_model_load_count",
                "comfy_generation_count",
                "control_submission_count",
                "selective_execution_count",
                "partial_q_execution_count",
                "actual_attention_omission_count",
            )
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physical-ram-bytes", type=int, required=True)
    parser.add_argument("--available-ram-bytes", type=int, required=True)
    parser.add_argument("--physical-vram-bytes", type=int, required=True)
    parser.add_argument("--synthetic-cuda", action="store_true")
    args = parser.parse_args(argv)

    receipt_bytes = args.receipt.read_bytes()
    calibration = calibration_gate(json.loads(receipt_bytes))
    admission = build_runtime_admission(
        physical_ram_bytes=args.physical_ram_bytes,
        current_available_ram_bytes=args.available_ram_bytes,
        physical_vram_bytes=args.physical_vram_bytes,
    )
    queue = comfy_queue_snapshot()
    if args.synthetic_cuda and queue["idle"]:
        import torch

        synthetic = run_bounded_synthetic_cuda(torch)
    elif args.synthetic_cuda:
        synthetic = {
            "status": "NOT_EXECUTED",
            "reason": "EXTERNAL_COMFY_QUEUE_BUSY",
            "passed": False,
        }
    else:
        synthetic = {"status": "NOT_EXECUTED", "reason": "NOT_REQUESTED", "passed": False}
    gates = completion_gates(calibration, admission, synthetic)
    result = {
        "schema_version": admission["schema_version"],
        "issue": 107,
        "source_receipt_sha256": sha256(receipt_bytes).hexdigest(),
        "queue_preflight": queue,
        "calibration": calibration,
        "runtime_admission": admission,
        "synthetic_cuda": synthetic,
        "completion_gates": gates,
        "decision": READY if all(gates.values()) else FAILED,
        "external_verification_pending": [
            "focused_python",
            "rust_cache_plan_abi_v2",
            "release_pyo3_15_of_15_skip_zero",
            "unchanged_pr_heads",
        ],
        "next_approval_only": "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2",
        "next_stage_started": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["decision"])
    return 0 if result["decision"] == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
