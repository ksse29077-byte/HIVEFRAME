"""Model-free and bounded CUDA probe for GPU-local H3 evidence V2."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from .h3_gpu_local_evidence_v2 import (
    CACHE_HARD_CAP_BYTES,
    CALIBRATION_STATUS,
    EXPECTED_FALSE_SAFE_COUNT,
    EXPECTED_RECORD_COUNT,
    HOLDOUT_STATUS,
    MAX_EVIDENCE_RECORDS,
    TRANSFER_HEADROOM_MIN_BYTES,
    TRANSFER_PREFLIGHT_LIMIT_BYTES,
    GpuLocalEvidenceCollector,
    analyze_partial_control_receipt,
)


READY = "H3_GPU_LOCAL_EVIDENCE_TRANSFER_V2_PREFLIGHT_READY"
FAILED = "H3_GPU_LOCAL_EVIDENCE_TRANSFER_V2_PREFLIGHT_FAILED"


def comfy_queue_snapshot(ports: tuple[int, ...] = (8188, 8191)) -> dict[str, Any]:
    """Read loopback ComfyUI queues without mutating or terminating anything."""

    endpoints = []
    running = pending = 0
    for port in ports:
        url = f"http://127.0.0.1:{port}/queue"
        try:
            with urlopen(url, timeout=1.0) as response:  # noqa: S310 - fixed loopback URL
                payload = json.loads(response.read().decode("utf-8"))
            endpoint_running = len(payload.get("queue_running", ()))
            endpoint_pending = len(payload.get("queue_pending", ()))
            endpoints.append(
                {
                    "port": port,
                    "status": "REACHABLE",
                    "running": endpoint_running,
                    "pending": endpoint_pending,
                }
            )
            running += endpoint_running
            pending += endpoint_pending
        except (OSError, URLError, TimeoutError, json.JSONDecodeError):
            endpoints.append(
                {"port": port, "status": "NO_LISTENER", "running": 0, "pending": 0}
            )
    return {
        "endpoints": endpoints,
        "running": running,
        "pending": pending,
        "idle": running == 0 and pending == 0,
        "termination_count": 0,
    }


def _cpu_metrics(torch_module: Any, source: Any, current: Any) -> dict[str, dict[str, float | bool]]:
    representative = torch_module.arange(0, 16, dtype=torch_module.long)
    omitted = torch_module.arange(16, int(source.shape[0]), dtype=torch_module.long)
    delta = (current.index_select(0, representative).float() - source.index_select(0, representative).float()).mean(dim=0)

    def values(predicted: Any) -> dict[str, float | bool]:
        actual = current.index_select(0, omitted).float()
        prediction = predicted.float()
        difference = actual - prediction
        actual_norm = torch_module.sqrt((actual * actual).sum()).clamp_min(1e-12)
        predicted_norm = torch_module.sqrt((prediction * prediction).sum()).clamp_min(1e-12)
        result = {
            "cosine": float(((actual * prediction).sum() / (actual_norm * predicted_norm)).item()),
            "normalized_l2": float((torch_module.sqrt((difference * difference).sum()) / actual_norm).item()),
            "normalized_mae": float((difference.abs().sum() / actual.abs().sum().clamp_min(1e-12)).item()),
            "energy_ratio": float((predicted_norm / actual_norm).item()),
        }
        result["finite"] = all(torch_module.isfinite(torch_module.tensor(value)) for value in result.values())
        return result

    cached = source.index_select(0, omitted)
    return {"raw": values(cached), "corrected": values(cached.float() + delta)}


def run_bounded_synthetic_cuda(torch_module: Any) -> dict[str, Any]:
    """Run one small tensor fixture; no ComfyUI node or H3 model is imported."""

    if not torch_module.cuda.is_available():
        return {"status": "NOT_EXECUTED", "reason": "CUDA_UNAVAILABLE", "passed": False}
    device = torch_module.device("cuda:0")
    free_bytes, total_bytes = torch_module.cuda.mem_get_info(device)
    generator = torch_module.Generator(device="cpu").manual_seed(101)
    source_cpu = torch_module.randn((96, 32), generator=generator, dtype=torch_module.float32).to(
        dtype=torch_module.bfloat16
    )
    current_cpu = source_cpu.clone()
    current_cpu[:16] = (current_cpu[:16].float() + 0.015).to(dtype=torch_module.bfloat16)
    current_cpu[16:] = (current_cpu[16:].float() + 0.02).to(dtype=torch_module.bfloat16)
    source = source_cpu.to(device=device)
    current = current_cpu.to(device=device)
    rows = torch_module.arange(96, dtype=torch_module.long, device=device)
    representative = torch_module.arange(0, 16, dtype=torch_module.long, device=device)
    omitted = torch_module.arange(16, 96, dtype=torch_module.long, device=device)
    collector = GpuLocalEvidenceCollector(
        torch_module,
        device=device,
        measured_free_vram_bytes=int(free_bytes),
        minimum_reserve_bytes=256 * 1024**2,
        maximum_records=4,
    )
    vetoed_before_allocation = not collector.prepare_slot(
        block=30,
        region=0,
        row_indices=rows,
        representative_positions=representative,
        omitted_positions=omitted,
        width=32,
        dtype=torch_module.bfloat16,
    )
    slot_prepared = collector.prepare_slot(
        block=0,
        region=0,
        row_indices=rows,
        representative_positions=representative,
        omitted_positions=omitted,
        width=32,
        dtype=torch_module.bfloat16,
    )
    lineage = sha256(b"bounded-synthetic-gpu-local-evidence-v2").hexdigest()
    captured = collector.capture_source(
        block=0, region=0, source_step=1, lineage_digest=lineage, full_core=source
    )
    duplicate_deduplicated = collector.capture_source(
        block=0, region=0, source_step=1, lineage_digest=lineage, full_core=source
    )
    observed = collector.observe(
        block=0,
        region=0,
        step=2,
        lineage_digest=lineage,
        predicted_state="STABLE",
        uncertainty_ppm=10_000,
        motion_ppm=20_000,
        full_core=current,
    )
    result = collector.finalize(completed=True)
    reference = _cpu_metrics(torch_module, source_cpu, current_cpu)
    record = result["records"][0]
    errors = {
        group: {
            name: abs(float(record[group][name]) - float(reference[group][name]))
            for name in ("cosine", "normalized_l2", "normalized_mae", "energy_ratio")
        }
        for group in ("raw", "corrected")
    }
    maximum_error = max(value for group in errors.values() for value in group.values())
    passed = bool(
        captured
        and vetoed_before_allocation
        and slot_prepared
        and duplicate_deduplicated
        and observed
        and result["record_count"] == 1
        and not result["overflow"]
        and result["invalid_count"] == 0
        and maximum_error <= 1e-5
        and result["performance_receipt"]["FORCED_HOT_PATH_SYNC_COUNT"]["value"] == 0
        and result["performance_receipt"]["BATCH_FLUSH_COUNT"]["value"] == 1
        and result["performance_receipt"]["RUST_TENSOR_BYTES"]["value"] == 0
        and result["pre_attention_veto_count"] == 1
    )
    return {
        "status": "MEASURED_SYNTHETIC",
        "passed": passed,
        "fixture_shape": [96, 32],
        "device_name": torch_module.cuda.get_device_name(device),
        "measured_free_vram_bytes_before_fixture": int(free_bytes),
        "device_total_vram_bytes": int(total_bytes),
        "cpu_gpu_metric_max_abs_error": maximum_error,
        "cpu_gpu_metric_abs_errors": errors,
        "collector": result,
        "h3_model_load_count": 0,
        "comfy_generation_count": 0,
        "control_generation_count": 0,
        "selective_generation_count": 0,
        "partial_q_execution_count": 0,
    }


def completion_gates(calibration: dict[str, Any], synthetic: dict[str, Any]) -> dict[str, bool]:
    performance = calibration["performance_receipt"]
    profiles = calibration["profiles"]
    return {
        "nineteen_false_safe_attributed": len(calibration["false_safe_attributions"])
        == EXPECTED_FALSE_SAFE_COUNT,
        "record_count_reproduced": calibration["record_count"] == EXPECTED_RECORD_COUNT,
        "transfer_ledger_reproduced": calibration["failed_control_transfer_ledger"]["total_bytes"]
        == 42_914_600_960,
        "metadata_only_gpu_reduction": synthetic.get("passed") is True,
        "rust_tensors_zero": calibration["rust_tensor_bytes"] == 0,
        "rust_calls_at_most_one": calibration["rust_calls"] <= 1,
        "per_block_region_row_rust_calls_zero": all(
            calibration[field] == 0
            for field in ("rust_calls_per_block", "rust_calls_per_region", "rust_calls_per_row")
        ),
        "hot_path_forced_sync_zero": synthetic.get("collector", {})
        .get("performance_receipt", {})
        .get("FORCED_HOT_PATH_SYNC_COUNT", {})
        .get("value")
        == 0,
        "evidence_bounded": calibration["record_count"] <= MAX_EVIDENCE_RECORDS,
        "incomplete_admission_zero": calibration["admission_eligible"] is False,
        "overflow_admission_zero": calibration["overflow"] is False
        and calibration["admission_eligible"] is False,
        "calibration_selected_false_safe_zero": calibration["conservative_pre_attention_veto"][
            "selected_calibration_false_safe"
        ]
        == 0,
        "holdout_unknown": calibration["holdout_status"] == HOLDOUT_STATUS,
        "planned_q_potential_at_least_three_percent": calibration["safe_geometry_potential"][
            "planned_q_ratio"
        ]
        >= 0.03,
        "projected_transfer_at_most_32gib": performance[
            "PROJECTED_CONTROL_TOTAL_TRANSFER_BYTES"
        ]["value"]
        <= TRANSFER_PREFLIGHT_LIMIT_BYTES,
        "projected_headroom_at_least_twenty_percent": performance[
            "PROJECTED_CONTROL_TRANSFER_HEADROOM_BYTES"
        ]["value"]
        >= TRANSFER_HEADROOM_MIN_BYTES,
        "cache_at_most_two_gib": calibration["gpu_local_cache"]["payload_bytes"]
        <= CACHE_HARD_CAP_BYTES,
        "same_algorithm_for_both_profiles": profiles["Balanced12GB"]["algorithm_id"]
        == profiles["Quality24GBPlus"]["algorithm_id"],
        "calibration_only": calibration["decision_input_status"] == CALIBRATION_STATUS,
        "no_generation": synthetic.get("control_generation_count") == 0
        and synthetic.get("selective_generation_count") == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--synthetic-cuda", action="store_true")
    args = parser.parse_args(argv)

    receipt_bytes = args.receipt.read_bytes()
    source = json.loads(receipt_bytes)
    calibration = analyze_partial_control_receipt(source)
    queue = comfy_queue_snapshot()
    if args.synthetic_cuda and queue["idle"]:
        import torch

        synthetic = run_bounded_synthetic_cuda(torch)
    elif args.synthetic_cuda:
        synthetic = {"status": "NOT_EXECUTED", "reason": "EXTERNAL_COMFY_QUEUE_BUSY", "passed": False}
    else:
        synthetic = {"status": "NOT_EXECUTED", "reason": "NOT_REQUESTED", "passed": False}
    gates = completion_gates(calibration, synthetic)
    result = {
        "schema_version": calibration["schema_version"],
        "issue": 105,
        "source_receipt_sha256": sha256(receipt_bytes).hexdigest(),
        "source_classification": CALIBRATION_STATUS,
        "holdout_status": HOLDOUT_STATUS,
        "queue_preflight": queue,
        "calibration": calibration,
        "synthetic_cuda": synthetic,
        "completion_gates": gates,
        "decision": READY if all(gates.values()) else FAILED,
        "next_approval_only": "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2",
        "next_stage_started": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["decision"])
    return 0 if result["decision"] == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
