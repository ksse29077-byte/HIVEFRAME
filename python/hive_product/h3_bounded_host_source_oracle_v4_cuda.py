"""Bounded CUDA admission fixture for H3 host-source GPU oracle V4."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping
import argparse
import json

from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_bounded_host_source_oracle_v4 import (
    GPU_STAGING_BUDGET_BYTES,
    OMITTED_POSITIONS,
    REGION_ROWS,
    REPRESENTATIVE_POSITIONS,
    SOURCE_PAYLOAD_BYTES,
    SOURCE_SHAPE,
)


CUDA_PREFLIGHT_SCHEMA = "h3.bounded-host-source-candidate-gpu-oracle-v4.cuda.1"
METRIC_CHUNK_ROWS = 64
FINGERPRINT_BANDS = 16


def _metric_result(torch_module: Any, accumulator: Mapping[str, Any]) -> dict[str, Any]:
    actual_norm = torch_module.sqrt(accumulator["actual_sq"]).clamp_min(1e-12)
    predicted_norm = torch_module.sqrt(accumulator["predicted_sq"]).clamp_min(1e-12)
    cosine = accumulator["dot"] / (actual_norm * predicted_norm)
    normalized_l2 = torch_module.sqrt(accumulator["diff_sq"]) / actual_norm
    finite = accumulator["finite"] & torch_module.isfinite(
        torch_module.stack((cosine, normalized_l2))
    ).all()
    return {"cosine": cosine, "normalized_l2": normalized_l2, "finite": finite}


def gpu_compressed_fingerprint(
    torch_module: Any, payload: Any, representative_positions: Any
) -> Any:
    """Build a small channel-and-band summary without leaving the GPU."""

    representative = payload.index_select(0, representative_positions).float()
    channel_mean = representative.mean(dim=0)
    band_width = max(1, int(representative.shape[0]) // FINGERPRINT_BANDS)
    band_energy = []
    for start in range(0, int(representative.shape[0]), band_width):
        band = representative[start : start + band_width]
        band_energy.append(torch_module.sqrt((band * band).mean().clamp_min(1e-12)))
    bands = torch_module.stack(band_energy[:FINGERPRINT_BANDS])
    return torch_module.cat((channel_mean, bands))


def gpu_preliminary_metrics(torch_module: Any, source_summary: Any, current_summary: Any) -> Any:
    """Return GPU-resident cosine, nL2, and finite preliminary evidence."""

    source = source_summary.float()
    current = current_summary.float()
    source_norm = torch_module.linalg.vector_norm(source).clamp_min(1e-12)
    current_norm = torch_module.linalg.vector_norm(current).clamp_min(1e-12)
    cosine = torch_module.dot(source, current) / (source_norm * current_norm)
    normalized_l2 = torch_module.linalg.vector_norm(current - source) / current_norm
    finite = torch_module.isfinite(torch_module.stack((cosine, normalized_l2))).all()
    return torch_module.stack((cosine, normalized_l2, finite.float()))


def gpu_exact_oracle_metrics(
    torch_module: Any,
    source: Any,
    current: Any,
    representative_positions: Any,
    omitted_positions: Any,
) -> Any:
    """Compute correction and exact omitted-row metrics with bounded chunks."""

    if tuple(source.shape) != tuple(current.shape) or int(source.ndim) != 2:
        raise ValueError("V4 exact GPU oracle source/current shape mismatch")
    device = source.device
    width = int(source.shape[1])
    delta = torch_module.zeros((width,), dtype=torch_module.float32, device=device)
    representative_count = int(representative_positions.numel())
    for start in range(0, representative_count, METRIC_CHUNK_ROWS):
        positions = representative_positions[start : start + METRIC_CHUNK_ROWS]
        source_chunk = source.index_select(0, positions).float()
        current_chunk = current.index_select(0, positions).float()
        delta.add_((current_chunk - source_chunk).sum(dim=0))
    delta.div_(representative_count)

    def zero():
        return torch_module.zeros((), dtype=torch_module.float32, device=device)

    accumulators = {
        name: {
            "dot": zero(),
            "actual_sq": zero(),
            "predicted_sq": zero(),
            "diff_sq": zero(),
            "finite": torch_module.ones((), dtype=torch_module.bool, device=device),
        }
        for name in ("raw", "corrected")
    }
    omitted_count = int(omitted_positions.numel())
    for start in range(0, omitted_count, METRIC_CHUNK_ROWS):
        positions = omitted_positions[start : start + METRIC_CHUNK_ROWS]
        actual = current.index_select(0, positions).float()
        cached = source.index_select(0, positions).float()
        corrected = cached + delta
        for name, predicted in (("raw", cached), ("corrected", corrected)):
            accumulator = accumulators[name]
            difference = actual - predicted
            accumulator["dot"].add_((actual * predicted).sum())
            accumulator["actual_sq"].add_((actual * actual).sum())
            accumulator["predicted_sq"].add_((predicted * predicted).sum())
            accumulator["diff_sq"].add_((difference * difference).sum())
            accumulator["finite"].logical_and_(
                torch_module.isfinite(actual).all()
                & torch_module.isfinite(predicted).all()
            )
    raw = _metric_result(torch_module, accumulators["raw"])
    corrected = _metric_result(torch_module, accumulators["corrected"])
    return torch_module.stack(
        (
            raw["cosine"],
            raw["normalized_l2"],
            raw["finite"].float(),
            corrected["cosine"],
            corrected["normalized_l2"],
            corrected["finite"].float(),
        )
    )


def threshold_classification(*, cosine: float, normalized_l2: float, finite: bool) -> str:
    if not finite:
        return "INVALID"
    if (
        cosine < CATASTROPHIC_COSINE_MIN
        or normalized_l2 > CATASTROPHIC_NORMALIZED_L2_MAX
    ):
        return "UNSAFE"
    return "SAFE"


def _cpu_reference(source: Any, current: Any, representative: Any, omitted: Any) -> list[float]:
    import torch

    return gpu_exact_oracle_metrics(
        torch, source, current, representative, omitted
    ).tolist()


def run_bounded_cuda_preflight(torch_module: Any) -> dict[str, Any]:
    """Run one bounded real-CUDA fixture and release every allocation."""

    if not torch_module.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch_module.device("cuda:0")
    torch_module.cuda.synchronize(device)
    baseline_allocated = int(torch_module.cuda.memory_allocated(device))
    baseline_reserved = int(torch_module.cuda.memory_reserved(device))
    torch_module.cuda.reset_peak_memory_stats(device)

    source = None
    current = None
    staging = None
    host_source = None
    preliminary_host = None
    exact_host = None
    source_capture_event = None
    source_upload_event = None
    oracle_event = None
    transfer_stream = None
    try:
        generator = torch_module.Generator(device=device)
        generator.manual_seed(101)
        source = torch_module.randn(
            SOURCE_SHAPE,
            dtype=torch_module.bfloat16,
            device=device,
            generator=generator,
        )
        host_source = torch_module.empty(
            SOURCE_SHAPE,
            dtype=torch_module.bfloat16,
            device="cpu",
            pin_memory=True,
        )
        staging = torch_module.empty_like(source)
        transfer_stream = torch_module.cuda.Stream(device=device)
        source_capture_event = torch_module.cuda.Event(enable_timing=True)
        source_upload_event = torch_module.cuda.Event(enable_timing=True)
        oracle_event = torch_module.cuda.Event(enable_timing=True)

        producer = torch_module.cuda.Event()
        producer.record(torch_module.cuda.current_stream(device))
        with torch_module.cuda.stream(transfer_stream):
            transfer_stream.wait_event(producer)
            source_capture_event.record(transfer_stream)
            host_source.copy_(source, non_blocking=True)
        transfer_stream.synchronize()
        with torch_module.cuda.stream(transfer_stream):
            staging.copy_(host_source, non_blocking=True)
            source_upload_event.record(transfer_stream)
        transfer_stream.synchronize()

        bit_identity = bool(
            torch_module.equal(source.view(torch_module.int16), staging.view(torch_module.int16))
        )
        current = source.clone()
        current[::257].add_(torch_module.tensor(0.0009765625, dtype=current.dtype, device=device))
        representative = torch_module.tensor(
            REPRESENTATIVE_POSITIONS, dtype=torch_module.long, device=device
        )
        omitted = torch_module.tensor(
            OMITTED_POSITIONS, dtype=torch_module.long, device=device
        )
        source_summary = gpu_compressed_fingerprint(
            torch_module, staging, representative
        )
        current_summary = gpu_compressed_fingerprint(
            torch_module, current, representative
        )
        preliminary = gpu_preliminary_metrics(
            torch_module, source_summary, current_summary
        )
        exact = gpu_exact_oracle_metrics(
            torch_module, staging, current, representative, omitted
        )
        preliminary_host = torch_module.empty(
            (3,), dtype=torch_module.float32, device="cpu", pin_memory=True
        )
        exact_host = torch_module.empty(
            (6,), dtype=torch_module.float32, device="cpu", pin_memory=True
        )
        with torch_module.cuda.stream(transfer_stream):
            transfer_stream.wait_stream(torch_module.cuda.current_stream(device))
            preliminary_host.copy_(preliminary, non_blocking=True)
            exact_host.copy_(exact, non_blocking=True)
            oracle_event.record(transfer_stream)
        oracle_event.synchronize()

        preliminary_values = [float(value) for value in preliminary_host.tolist()]
        exact_values = [float(value) for value in exact_host.tolist()]
        cpu_source = host_source[:96, :128].clone()
        cpu_current = cpu_source.clone()
        cpu_current[::7].add_(torch_module.tensor(0.0009765625, dtype=cpu_current.dtype))
        small_representative = torch_module.arange(0, 32, dtype=torch_module.long)
        small_omitted = torch_module.arange(32, 96, dtype=torch_module.long)
        cpu_reference = _cpu_reference(
            cpu_source, cpu_current, small_representative, small_omitted
        )
        gpu_small = gpu_exact_oracle_metrics(
            torch_module,
            cpu_source.to(device),
            cpu_current.to(device),
            small_representative.to(device),
            small_omitted.to(device),
        ).cpu().tolist()
        reference_errors = [
            abs(float(gpu) - float(cpu))
            for gpu, cpu in zip(gpu_small, cpu_reference)
        ]
        boundary = {
            "at_threshold": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX,
                finite=True,
            ),
            "below_cosine": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN - 1e-7,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX,
                finite=True,
            ),
            "above_l2": threshold_classification(
                cosine=CATASTROPHIC_COSINE_MIN,
                normalized_l2=CATASTROPHIC_NORMALIZED_L2_MAX + 1e-7,
                finite=True,
            ),
            "nonfinite": threshold_classification(
                cosine=1.0, normalized_l2=0.0, finite=False
            ),
        }
        peak_allocated = int(torch_module.cuda.max_memory_allocated(device))
        peak_reserved = int(torch_module.cuda.max_memory_reserved(device))
        checks = {
            "source_shape_exact": tuple(source.shape) == SOURCE_SHAPE,
            "source_payload_bytes_exact": source.numel() * source.element_size()
            == SOURCE_PAYLOAD_BYTES,
            "shared_staging_bytes_within_bound": staging.numel() * staging.element_size()
            <= GPU_STAGING_BUDGET_BYTES,
            "host_source_is_pinned": bool(host_source.is_pinned()),
            "bf16_d2h_h2d_bit_identity": bit_identity,
            "fingerprint_is_compressed": source_summary.numel() < source.numel() // 100,
            "preliminary_finite": preliminary_values[2] == 1.0,
            "exact_finite": exact_values[2] == 1.0 and exact_values[5] == 1.0,
            "cpu_gpu_reference_within_tolerance": max(reference_errors) <= 1e-5,
            "packed_row_mapping_exact": len(REGION_ROWS) == SOURCE_SHAPE[0]
            and len(REPRESENTATIVE_POSITIONS) + len(OMITTED_POSITIONS) == len(REGION_ROWS),
            "threshold_boundary_exact": boundary
            == {
                "at_threshold": "SAFE",
                "below_cosine": "UNSAFE",
                "above_l2": "UNSAFE",
                "nonfinite": "INVALID",
            },
            "metadata_d2h_within_one_mib": (preliminary_host.numel() + exact_host.numel())
            * 4
            <= 1024**2,
        }
        receipt = {
            "schema_version": CUDA_PREFLIGHT_SCHEMA,
            "torch_version": str(torch_module.__version__),
            "cuda_version": str(torch_module.version.cuda),
            "device_name_digest": sha256(
                torch_module.cuda.get_device_name(device).encode("utf-8")
            ).hexdigest(),
            "source_shape": list(SOURCE_SHAPE),
            "source_payload_bytes": SOURCE_PAYLOAD_BYTES,
            "preliminary_metrics": preliminary_values,
            "exact_metrics": exact_values,
            "cpu_gpu_reference_max_abs_error": max(reference_errors),
            "cpu_gpu_reference_mean_abs_error": sum(reference_errors) / len(reference_errors),
            "threshold_boundary": boundary,
            "metadata_d2h_bytes": (preliminary_host.numel() + exact_host.numel()) * 4,
            "current_payload_d2h_bytes": 0,
            "cpu_oracle_payload_d2h_bytes": 0,
            "fixture_explicit_sync_count": 5,
            "production_hot_path_forced_sync_count": 0,
            "peak_allocated_bytes": peak_allocated,
            "peak_reserved_bytes": peak_reserved,
            "checks": checks,
            "passed": all(checks.values()),
        }
    finally:
        del source, current, staging, host_source, preliminary_host, exact_host
        del source_capture_event, source_upload_event, oracle_event, transfer_stream
        torch_module.cuda.empty_cache()
        torch_module.cuda.synchronize(device)

    final_allocated = int(torch_module.cuda.memory_allocated(device))
    final_reserved = int(torch_module.cuda.memory_reserved(device))
    teardown_checks = {
        "allocated_returned_to_baseline": final_allocated <= baseline_allocated,
        "reserved_returned_to_baseline": final_reserved <= baseline_reserved,
    }
    receipt["baseline_allocated_bytes"] = baseline_allocated
    receipt["baseline_reserved_bytes"] = baseline_reserved
    receipt["final_allocated_bytes"] = final_allocated
    receipt["final_reserved_bytes"] = final_reserved
    receipt["teardown_checks"] = teardown_checks
    receipt["passed"] = bool(receipt["passed"] and all(teardown_checks.values()))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded CUDA V4 admission fixture")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    import torch

    receipt = run_bounded_cuda_preflight(torch)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
