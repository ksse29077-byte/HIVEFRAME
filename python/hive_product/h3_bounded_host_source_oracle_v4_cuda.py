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
    """Run the production-equivalent explicit-ownership lifecycle once."""

    from .h3_cuda_fixture_teardown_v4 import run_teardown_remediation

    remediation = run_teardown_remediation(
        torch_module, verification_cycles=1, run_negative_tests=False
    )
    verification = remediation["verification_cycles"][0]
    return {
        "schema_version": CUDA_PREFLIGHT_SCHEMA,
        "functional": verification["functional"],
        "teardown": verification["close"],
        "cold_baseline": remediation["cold_baseline"],
        "warm_baseline": remediation["warm_baseline"],
        "checks": remediation["checks"],
        "passed": remediation["passed"],
    }


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
