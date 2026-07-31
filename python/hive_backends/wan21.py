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
    negative_prompt: str
    seed: int
    output_prefix: Path
    metrics_path: Path
    size: str = "832*480"
    frame_num: int = 49
    fps: int = 16
    sample_steps: int = 50
    sample_shift: float = 8.0
    sample_guide_scale: float = 6.0
    sample_solver: str = "unipc"
    dtype: str = "bfloat16"
    device: str = "cuda:0"
    offload_model: bool = True
    t5_cpu: bool = True
    repeat: int = 2
    kernel_profiler: str = "disabled"

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
        if self.fps < 1:
            raise ValueError("fps must be positive.")
        if self.dtype != "bfloat16":
            raise ValueError("The pinned official Wan 1.3B dtype is bfloat16.")
        if not self.device.startswith("cuda:"):
            raise ValueError("The pinned official Wan backend requires cuda:N.")
        if self.repeat not in {1, 2}:
            raise ValueError("repeat must be one smoke run or cold/warm pair.")
        if self.kernel_profiler not in {"disabled", "torch"}:
            raise ValueError(
                "kernel_profiler must be 'disabled' or 'torch'."
            )


def build_generate_command(
    *,
    python_executable: Path,
    driver_path: Path,
    code_dir: Path,
    checkpoint_dir: Path,
    spec: Wan21RunSpec,
) -> list[str]:
    """Build the instrumented invocation over the pinned official backend."""
    spec.validate()
    command = [
        str(python_executable),
        str(driver_path),
        "--wan-code-dir",
        str(code_dir),
        "--checkpoint-dir",
        str(checkpoint_dir),
        "--output-prefix",
        str(spec.output_prefix),
        "--metrics-output",
        str(spec.metrics_path),
        "--prompt",
        spec.prompt,
        "--negative-prompt",
        spec.negative_prompt,
        "--seed",
        str(spec.seed),
        "--size",
        spec.size,
        "--frame-num",
        str(spec.frame_num),
        "--fps",
        str(spec.fps),
        "--sample-solver",
        spec.sample_solver,
        "--sample-steps",
        str(spec.sample_steps),
        "--sample-shift",
        str(spec.sample_shift),
        "--sample-guide-scale",
        str(spec.sample_guide_scale),
        "--dtype",
        spec.dtype,
        "--device",
        spec.device,
        "--offload-model",
        str(spec.offload_model).lower(),
        "--t5-cpu",
        str(spec.t5_cpu).lower(),
        "--repeat",
        str(spec.repeat),
        "--kernel-profiler",
        spec.kernel_profiler,
    ]
    return command
