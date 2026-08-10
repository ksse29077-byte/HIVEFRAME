"""Model-free A3 structural admission runner.

The runner owns evidence collection only. Attention/cache/correction policy is
implemented in ``attention_output_reuse``. A failed structural gate consumes no
Generation or CUDA budget and cannot be overridden by this command.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import argparse
import json
import sys

from .active_query_attention import inspect_installed_attention_source
from .attention_output_reuse import (
    CONTROL_MODE,
    MECHANISM_ID,
    a2_full_ranking,
    cache_budget_plan,
    fixed_contract,
    settings_digest,
    structural_admission,
)


SCHEMA_VERSION = "a3.h3.output-reuse-structural.1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_output_root(parent: Path, experiment_id: str) -> Path:
    if not experiment_id or any(value in experiment_id for value in ("/", "\\", "..", ":")):
        raise ValueError("unsafe A3 experiment id")
    root = (parent / experiment_id).resolve()
    parent = parent.resolve()
    if parent not in root.parents or root.exists():
        raise ValueError("A3 output directory must be new and inside the approved parent")
    return root


def _load_a2_calibration(path: Path) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], str]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    execution = payload.get("attention_execution")
    if not isinstance(execution, Mapping):
        execution = payload.get("callback_instrumentation", {}).get("attention_execution")
    calibration = execution.get("block_calibration") if isinstance(execution, Mapping) else None
    if not isinstance(calibration, list):
        raise ValueError("A2 private receipt has no full block calibration")
    return payload, calibration, sha256(raw).hexdigest()


def run_structural_admission(
    *,
    experiment_id: str,
    a2_private_receipt: Path,
    model_source: Path,
    attention_source: Path,
    available_host_bytes: int,
    private_run_parent: Path,
) -> dict[str, Any]:
    root = _safe_output_root(private_run_parent, experiment_id)
    a2_payload, calibration, a2_digest = _load_a2_calibration(a2_private_receipt)
    ranking = a2_full_ranking(calibration)
    cache = cache_budget_plan(available_host_bytes=available_host_bytes, ranked_blocks=ranking)
    source = inspect_installed_attention_source(model_source, attention_source)
    admission = structural_admission(
        source_admission=source,
        cache_plan=cache,
        runtime_conditional_dispatch_available=False,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "started_at": _utc_now(),
        "finished_at": _utc_now(),
        "mechanism": MECHANISM_ID,
        "contract": fixed_contract(),
        "settings_digest": settings_digest(mode=CONTROL_MODE, candidate_blocks=cache.candidate_blocks),
        "a2_evidence": {
            "private_receipt_sha256": a2_digest,
            "source_settings_digest": a2_payload.get("settings_digest"),
            "ranking_method": [
                "mean_normalized_l2_ascending",
                "mean_cosine_descending",
                "p95_normalized_l2_ascending",
                "block_index_ascending",
            ],
            "full_ranking": list(ranking),
            "selected_candidate_blocks": list(cache.candidate_blocks),
        },
        "source_admission": source,
        "structural_admission": admission,
        "generation_attempt_count": 0,
        "retry_count": 0,
        "model_load_count": 0,
        "cuda_execution_count": 0,
        "selective_execution_count": 0,
        "speedup_claim": 0,
        "quality_promotion": 0,
        "product_promotion": 0,
    }
    public = {
        key: value for key, value in payload.items()
        if key not in {"source_admission"}
    }
    public["source_admission"] = {
        "admitted": source.get("admitted"),
        "reason": source.get("reason"),
        "model_source_sha256": source.get("model_source_sha256"),
        "attention_source_sha256": source.get("attention_source_sha256"),
        "checks": source.get("checks"),
        "claim_boundary": source.get("claim_boundary"),
    }
    root.mkdir(parents=True, exist_ok=False)
    (root / "structural-admission-private-receipt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "structural-admission-public-summary.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return public


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run model-free A3 structural admission only.")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--a2-private-receipt", type=Path, required=True)
    parser.add_argument("--model-source", type=Path, required=True)
    parser.add_argument("--attention-source", type=Path, required=True)
    parser.add_argument("--available-host-bytes", type=int, required=True)
    parser.add_argument("--private-run-parent", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_structural_admission(
        experiment_id=args.experiment_id,
        a2_private_receipt=args.a2_private_receipt,
        model_source=args.model_source,
        attention_source=args.attention_source,
        available_host_bytes=args.available_host_bytes,
        private_run_parent=args.private_run_parent,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["structural_admission"]["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
