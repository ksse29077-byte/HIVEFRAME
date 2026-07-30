"""Pinned command builder for the official Wan 2.1 T2V 1.3B backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


OFFICIAL_CODE_REPOSITORY = "https://github.com/Wan-Video/Wan2.1.git"
OFFICIAL_CODE_REVISION = "9737cba9c1c3c4d04b33fcad41c111989865d315"
OFFICIAL_MODEL_ID = "Wan-AI/Wan2.1-T2V-1.3B"
OFFICIAL_MODEL_REVISION = "37ec512624d61f7aa208f7ea8140a131f93afc9a"


@dataclass(frozen=True)
class Wan21RunSpec:
    prompt: str
    seed: int
    output_path: Path
    size: str = "832*480"
    frame_num: int = 49
    sample_steps: int = 50
    sample_shift: float = 8.0
    sample_guide_scale: float = 6.0
    sample_solver: str = "unipc"
    offload_model: bool = True
    t5_cpu: bool = True

    def validate(self) -> None:
        if self.size not in {"832*480", "480*832"}:
            raise ValueError(
                "Wan 2.1 T2V 1.3B official code supports 832*480 or 480*832."
            )
        if self.frame_num < 1 or (self.frame_num - 1) % 4 != 0:
            raise ValueError("Wan frame_num must be 4n+1.")
        if self.sample_steps < 1:
            raise ValueError("sample_steps must be positive.")
        if self.seed < 0:
            raise ValueError("seed must be non-negative and deterministic.")


def build_generate_command(
    *,
    python_executable: Path,
    code_dir: Path,
    checkpoint_dir: Path,
    spec: Wan21RunSpec,
) -> list[str]:
    """Build the pinned official ``generate.py`` invocation."""
    spec.validate()
    command = [
        str(python_executable),
        str(code_dir / "generate.py"),
        "--task",
        "t2v-1.3B",
        "--size",
        spec.size,
        "--frame_num",
        str(spec.frame_num),
        "--ckpt_dir",
        str(checkpoint_dir),
        "--sample_solver",
        spec.sample_solver,
        "--sample_steps",
        str(spec.sample_steps),
        "--sample_shift",
        str(spec.sample_shift),
        "--sample_guide_scale",
        str(spec.sample_guide_scale),
        "--base_seed",
        str(spec.seed),
        "--prompt",
        spec.prompt,
        "--save_file",
        str(spec.output_path),
        "--offload_model",
        str(spec.offload_model),
    ]
    if spec.t5_cpu:
        command.append("--t5_cpu")
    return command
