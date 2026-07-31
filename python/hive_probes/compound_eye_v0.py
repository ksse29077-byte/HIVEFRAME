"""Run the deterministic compound-eye v0 reference simulation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from hive_eyes.reference import build_reference_eyes, sequence_sha256, validate_sequence
from hive_fusion.reference import fuse_observations
from hive_visual_state.contracts import (
    SCHEMA_VERSION,
    build_compute_plan,
    hash_json,
    unsupported_measurement,
    validate_compute_plan,
    validate_eye_contract,
    validate_eye_observation,
    validate_shared_visual_state,
)


def make_synthetic_sequence(
    *,
    seed: int = 101,
    frames: int = 4,
    height: int = 16,
    width: int = 16,
    channels: int = 3,
) -> np.ndarray:
    if frames < 2 or min(height, width, channels) < 1:
        raise ValueError("Synthetic sequence dimensions are invalid.")
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.05, 0.15, size=(height, width, channels)).astype(
        np.float32
    )
    sequence = np.repeat(base[None, ...], frames, axis=0)
    x0 = max(0, width // 2 - 2)
    x1 = min(width, width // 2 + 2)
    y0 = max(0, height // 4)
    y1 = min(height, y0 + max(1, height // 4))
    sequence[frames // 2 :, y0:y1, x0:x1, :] += np.float32(0.75)
    return np.clip(sequence, 0.0, 1.0)


def run_reference_simulation(
    sequence: np.ndarray | None = None,
    *,
    seed: int = 101,
    sequence_id: str = "synthetic-eye-v0",
) -> dict[str, Any]:
    if sequence is None:
        sequence = make_synthetic_sequence(seed=seed)
    frames, height, width, channels = validate_sequence(sequence)
    eyes = build_reference_eyes(sequence)
    contracts = [eye.contract(sequence) for eye in eyes]
    observations = [
        eye.observe(sequence, sequence_id=sequence_id, seed=seed) for eye in eyes
    ]
    for contract, observation in zip(contracts, observations):
        validate_eye_contract(
            contract,
            canvas_width=width,
            canvas_height=height,
            frames=frames,
        )
        validate_eye_observation(
            observation,
            contract,
            canvas_width=width,
            canvas_height=height,
            frames=frames,
        )
    canvas = {
        "width": width,
        "height": height,
        "frames": frames,
        "channels": channels,
    }
    shared_state = fuse_observations(observations, canvas=canvas)
    validate_shared_visual_state(shared_state)
    compute_plan = build_compute_plan(shared_state)
    validate_compute_plan(compute_plan)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "hiveframe.compound_eye.observation_receipt",
        "sequence_id": sequence_id,
        "seed": seed,
        "deterministic": True,
        "input_sha256": sequence_sha256(sequence),
        "eye_contract_sha256": [hash_json(item) for item in contracts],
        "eye_observation_sha256": [hash_json(item) for item in observations],
        "shared_visual_state_sha256": hash_json(shared_state),
        "compute_plan_sha256": hash_json(compute_plan),
        "unsupported_metrics": {
            "actual_sparse_speedup": unsupported_measurement(
                unit="ratio",
                reason="No model backend executes in the v0 reference simulation.",
                measurement_method="requires a same-condition model experiment",
            ),
            "gpu_kernel_seconds": unsupported_measurement(
                unit="seconds",
                status="unsupported",
                reason="The v0 reference simulation is CPU/NumPy only.",
                measurement_method="requires a separate GPU profiling run",
            ),
        },
    }
    return {
        "eye_contracts": contracts,
        "eye_observations": observations,
        "shared_visual_state": shared_state,
        "compute_plan": compute_plan,
        "observation_receipt": receipt,
    }


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Model-free HIVEFRAME compound-eye v0 reference simulation."
    )
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New or empty directory for JSON reference artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit(f"Output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run_reference_simulation(seed=args.seed)
    artifacts = {
        "eye_contracts.json": result["eye_contracts"],
        "eye_observations.json": result["eye_observations"],
        "shared_visual_state.json": result["shared_visual_state"],
        "compute_plan.json": result["compute_plan"],
        "observation_receipt.json": result["observation_receipt"],
    }
    for name, value in artifacts.items():
        _write_json(args.output_dir / name, value)
    print(
        json.dumps(
            {
                "status": "succeeded",
                "model_loaded": False,
                "cuda_used": False,
                "artifacts": sorted(artifacts),
                "receipt": result["observation_receipt"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
