"""Model-free CUDA validation for the real CONTROL V2 CPU oracle metric."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import inspect
import json
import sys

from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .h3_row_region_safety_v2 import (
    HybridControlOracleWorker,
    OMITTED_POSITIONS,
    REPRESENTATIVE_POSITIONS,
    _chunked_metrics,
)


READY = "H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_READY"
FAILED = "H3_ROW_REGION_SAFETY_CONTROL_V2_ORACLE_PREFLIGHT_FAILED"


def _gpu_reference(torch_module: Any, source: Any, current: Any) -> dict[str, Any]:
    representative = torch_module.tensor(REPRESENTATIVE_POSITIONS, dtype=torch_module.long, device=source.device)
    omitted = torch_module.tensor(OMITTED_POSITIONS, dtype=torch_module.long, device=source.device)
    source_float = source.float()
    current_float = current.float()
    delta = (
        current_float.index_select(0, representative)
        - source_float.index_select(0, representative)
    ).mean(dim=0)
    actual = current_float.index_select(0, omitted)
    result = {}
    for name, predicted in (("raw", source_float), ("corrected", source_float + delta)):
        prediction = predicted.index_select(0, omitted)
        difference = actual - prediction
        actual_norm = torch_module.sqrt((actual * actual).sum()).clamp_min(1e-12)
        prediction_norm = torch_module.sqrt((prediction * prediction).sum()).clamp_min(1e-12)
        result[name] = {
            "cosine": float(((actual * prediction).sum() / (actual_norm * prediction_norm)).item()),
            "normalized_l2": float((torch_module.sqrt((difference * difference).sum()) / actual_norm).item()),
            "finite": bool(torch_module.isfinite(prediction).all().item()),
        }
    return result


def run_preflight(torch_module: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "h3_model_load_count": 0,
        "generation_count": 0,
        "control_submission_count": 0,
        "selective_count": 0,
        "partial_q_count": 0,
        "attention_omission_count": 0,
    }
    try:
        if not torch_module.cuda.is_available():
            raise RuntimeError("CUDA is unavailable")
        generator = torch_module.Generator(device="cpu").manual_seed(101)
        source_cpu = torch_module.randn((3367, 32), generator=generator, dtype=torch_module.float32).to(torch_module.bfloat16)
        current_cpu = source_cpu.clone()
        current_cpu[list(REPRESENTATIVE_POSITIONS)] = (
            current_cpu[list(REPRESENTATIVE_POSITIONS)].float() + 0.015
        ).to(torch_module.bfloat16)
        current_cpu[list(OMITTED_POSITIONS)] = (
            current_cpu[list(OMITTED_POSITIONS)].float() + 0.02
        ).to(torch_module.bfloat16)
        source_gpu = source_cpu.cuda()
        current_gpu = current_cpu.cuda()
        pinned = torch_module.empty_like(current_cpu, pin_memory=True)
        pinned.copy_(current_gpu, non_blocking=True)
        torch_module.cuda.current_stream().synchronize()
        bit_preserved = bool(
            torch_module.equal(pinned.view(torch_module.uint16), current_cpu.view(torch_module.uint16))
        )
        observed = _chunked_metrics(torch_module, source_cpu, pinned)
        reference = _gpu_reference(torch_module, source_gpu, current_gpu)
        errors = [
            abs(float(observed[group][name]) - float(reference[group][name]))
            for group in ("raw", "corrected")
            for name in ("cosine", "normalized_l2")
        ]
        maximum_error = max(errors)
        hot_source = inspect.getsource(HybridControlOracleWorker.enqueue)
        hot_sync_zero = all(
            token not in hot_source
            for token in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize(")
        )
        receipt.update(
            {
                "bf16_bit_preserved": bit_preserved,
                "cpu_gpu_metric_max_abs_error": maximum_error,
                "metric_error_limit": 1e-6,
                "classification_identical": (
                    observed["corrected"]["finite"] == reference["corrected"]["finite"]
                    and (observed["corrected"]["cosine"] < CATASTROPHIC_COSINE_MIN)
                    == (reference["corrected"]["cosine"] < CATASTROPHIC_COSINE_MIN)
                    and (
                        observed["corrected"]["normalized_l2"]
                        > CATASTROPHIC_NORMALIZED_L2_MAX
                    )
                    == (
                        reference["corrected"]["normalized_l2"]
                        > CATASTROPHIC_NORMALIZED_L2_MAX
                    )
                ),
                "hot_path_forced_sync_zero": hot_sync_zero,
                "representative_row_count": len(REPRESENTATIVE_POSITIONS),
                "omitted_row_count": len(OMITTED_POSITIONS),
            }
        )
        passed = bool(
            bit_preserved
            and maximum_error <= 1e-6
            and receipt["classification_identical"]
            and hot_sync_zero
        )
        receipt["decision"] = READY if passed else FAILED
    except BaseException as error:
        receipt["error_type"] = type(error).__name__
        receipt["error_message"] = str(error)[:500]
        receipt["decision"] = FAILED
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the model-free CONTROL V2 oracle.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    import torch

    receipt = run_preflight(torch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    args.output.write_text(content, encoding="utf-8")
    print(json.dumps({"decision": receipt["decision"], "sha256": sha256(content.encode()).hexdigest()}))
    return 0 if receipt["decision"] == READY else 1


if __name__ == "__main__":
    sys.exit(main())
