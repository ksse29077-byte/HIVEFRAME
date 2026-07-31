"""Instrumented M0 driver for the pinned official Wan 2.1 implementation.

This file does not alter upstream source. It imports the pinned checkout and
wraps public runtime objects to measure M0 stages. The upstream code and model
remain separately licensed artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class StageRecorder:
    """Records wall time and CUDA-event spans without calling them kernel time."""

    def __init__(self, torch_module: Any, target: dict[str, Any]):
        self.torch = torch_module
        self.target = target
        self.cuda_pairs: list[tuple[dict[str, Any], str, Any, Any]] = []
        self.current_step: dict[str, Any] | None = None

    def begin(self) -> tuple[float, Any | None]:
        start_event = None
        if self.torch.cuda.is_available():
            start_event = self.torch.cuda.Event(enable_timing=True)
            start_event.record()
        return time.perf_counter(), start_event

    def finish(
        self,
        record: dict[str, Any],
        field_prefix: str,
        started: tuple[float, Any | None],
    ) -> None:
        wall_start, start_event = started
        record[f"{field_prefix}_wall_seconds"] = time.perf_counter() - wall_start
        if start_event is None:
            record[f"{field_prefix}_cuda_event_span_seconds"] = None
            return
        end_event = self.torch.cuda.Event(enable_timing=True)
        end_event.record()
        self.cuda_pairs.append(
            (
                record,
                f"{field_prefix}_cuda_event_span_seconds",
                start_event,
                end_event,
            )
        )

    def resolve_cuda(self) -> None:
        if not self.torch.cuda.is_available():
            return
        self.torch.cuda.synchronize()
        for record, field, start_event, end_event in self.cuda_pairs:
            record[field] = start_event.elapsed_time(end_event) / 1000.0


def support_record(
    *,
    value: float | None,
    status: str,
    reason: str | None,
    measurement_method: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": "seconds",
        "support_status": status,
        "unsupported_reason": reason,
        "measurement_method": measurement_method,
    }


def execute_with_kernel_profiler(
    torch_module: Any,
    mode: str,
    operation: Callable[[], Any],
) -> tuple[Any, dict[str, Any]]:
    """Run once and optionally collect kernel duration in a profiling-only run."""
    if mode == "disabled":
        return operation(), support_record(
            value=None,
            status="not_collected",
            reason=(
                "Kernel profiling is disabled for official wall-clock runs because "
                "torch.profiler/CUPTI adds measurement overhead. Use a separate "
                "profiling run."
            ),
            measurement_method="torch.profiler/CUPTI (disabled)",
        )

    profiler = getattr(torch_module, "profiler", None)
    if profiler is None or not hasattr(profiler, "profile"):
        return operation(), support_record(
            value=None,
            status="unsupported",
            reason="This PyTorch build does not expose torch.profiler.",
            measurement_method="torch.profiler/CUPTI",
        )

    operation_started = False
    try:
        activities = [profiler.ProfilerActivity.CUDA]
        with profiler.profile(activities=activities) as captured:
            operation_started = True
            result = operation()
    except (AttributeError, RuntimeError) as error:
        if operation_started and "result" not in locals():
            # Preserve model/OOM/runtime failures from the single execution.
            raise
        if not operation_started:
            result = operation()
        return result, support_record(
            value=None,
            status="unsupported",
            reason=f"torch.profiler could not collect CUDA kernel events: {error}",
            measurement_method="torch.profiler/CUPTI",
        )

    total_microseconds = 0.0
    supported_field = False
    try:
        for event in captured.key_averages():
            value = getattr(event, "self_cuda_time_total", None)
            if value is None:
                value = getattr(event, "self_device_time_total", None)
            if value is not None:
                supported_field = True
                total_microseconds += float(value)
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        return result, support_record(
            value=None,
            status="unsupported",
            reason=f"Profiler result extraction failed: {error}",
            measurement_method="torch.profiler/CUPTI",
        )
    if not supported_field:
        return result, support_record(
            value=None,
            status="unsupported",
            reason=(
                "Profiler completed but exposed no self CUDA/device duration field."
            ),
            measurement_method="torch.profiler/CUPTI",
        )
    return result, support_record(
        value=total_microseconds / 1_000_000.0,
        status="supported",
        reason=None,
        measurement_method=(
            "torch.profiler/CUPTI sum(key_averages.self_cuda_time_total)"
        ),
    )


def safe_cuda_call(
    operation: Callable[[], Any],
) -> tuple[Any | None, str | None]:
    try:
        return operation(), None
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        return None, f"{type(error).__name__}: {error}"


def allocator_snapshot(torch_module: Any, device_index: int) -> dict[str, Any]:
    fields = {
        "peak_allocated_bytes": lambda: int(
            torch_module.cuda.max_memory_allocated(device_index)
        ),
        "peak_reserved_bytes": lambda: int(
            torch_module.cuda.max_memory_reserved(device_index)
        ),
        "current_allocated_bytes": lambda: int(
            torch_module.cuda.memory_allocated(device_index)
        ),
        "current_reserved_bytes": lambda: int(
            torch_module.cuda.memory_reserved(device_index)
        ),
    }
    values: dict[str, Any] = {}
    unsupported: dict[str, str] = {}
    for name, operation in fields.items():
        value, error = safe_cuda_call(operation)
        values[name] = value
        if error:
            unsupported[name] = error
    return {
        **values,
        "scope": "selected CUDA device in the instrumented process",
        "measurement_method": "PyTorch CUDA caching allocator",
        "unsupported": unsupported,
    }


def reset_allocator_peak(torch_module: Any, device_index: int) -> None:
    torch_module.cuda.reset_peak_memory_stats(device_index)


def allocator_environment(torch_module: Any, device_index: int) -> dict[str, Any]:
    backend, backend_error = safe_cuda_call(
        lambda: str(torch_module.cuda.get_allocator_backend())
    )
    total_memory, total_error = safe_cuda_call(
        lambda: int(
            torch_module.cuda.get_device_properties(device_index).total_memory
        )
    )
    raw_stats, stats_error = safe_cuda_call(
        lambda: dict(torch_module.cuda.memory_stats(device_index))
    )
    pool_statistics = None
    if raw_stats is not None:
        prefixes = (
            "allocated_bytes.",
            "reserved_bytes.",
            "active_bytes.",
            "segment.",
        )
        pool_statistics = {
            key: int(value)
            for key, value in raw_stats.items()
            if key.startswith(prefixes)
        }
    unsupported: dict[str, str] = {}
    if backend_error:
        unsupported["allocator_backend"] = backend_error
    if total_error:
        unsupported["device_total_memory_bytes"] = total_error
    if stats_error:
        unsupported["pool_statistics"] = stats_error
    return {
        "allocator_backend": backend,
        "pytorch_alloc_conf": os.environ.get("PYTORCH_ALLOC_CONF"),
        "pytorch_cuda_alloc_conf_alias": os.environ.get(
            "PYTORCH_CUDA_ALLOC_CONF"
        ),
        "device_total_memory_bytes": total_memory,
        "pool_statistics": pool_statistics,
        "scope": "selected CUDA device in the instrumented process",
        "measurement_method": "PyTorch allocator APIs and process environment",
        "unsupported": unsupported,
    }


def instrument_generation(
    *,
    torch_module: Any,
    pipeline: Any,
    scheduler_classes: list[type[Any]],
    operation: Callable[[], Any],
    run_metrics: dict[str, Any],
) -> Any:
    """Measure prompt encoding, each full denoising step, and VAE decode."""
    recorder = StageRecorder(torch_module, run_metrics)
    prompt_calls = 0
    original_encoder_call = type(pipeline.text_encoder).__call__
    original_model_forward = pipeline.model.forward
    original_vae_decode = pipeline.vae.decode
    original_scheduler_steps = {
        scheduler_class: scheduler_class.step for scheduler_class in scheduler_classes
    }

    def encoder_call(instance: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal prompt_calls
        prompt_calls += 1
        label = (
            "positive"
            if prompt_calls == 1
            else "negative"
            if prompt_calls == 2
            else f"call_{prompt_calls}"
        )
        record: dict[str, Any] = {"label": label}
        started = recorder.begin()
        try:
            return original_encoder_call(instance, *args, **kwargs)
        finally:
            recorder.finish(record, "encode", started)
            run_metrics["prompt_encode_calls"].append(record)

    def model_forward(*args: Any, **kwargs: Any) -> Any:
        if recorder.current_step is None:
            recorder.current_step = {
                "index": len(run_metrics["denoising_steps"]),
                "_started": recorder.begin(),
                "model_forward_calls": 0,
            }
        recorder.current_step["model_forward_calls"] += 1
        return original_model_forward(*args, **kwargs)

    def scheduler_step(instance: Any, *args: Any, **kwargs: Any) -> Any:
        original = original_scheduler_steps[type(instance)]
        try:
            return original(instance, *args, **kwargs)
        finally:
            if recorder.current_step is not None:
                step = recorder.current_step
                started = step.pop("_started")
                recorder.finish(step, "step", started)
                run_metrics["denoising_steps"].append(step)
                recorder.current_step = None

    def vae_decode(*args: Any, **kwargs: Any) -> Any:
        started = recorder.begin()
        try:
            return original_vae_decode(*args, **kwargs)
        finally:
            recorder.finish(run_metrics, "vae_decode", started)

    type(pipeline.text_encoder).__call__ = encoder_call
    pipeline.model.forward = model_forward
    pipeline.vae.decode = vae_decode
    for scheduler_class in scheduler_classes:
        scheduler_class.step = scheduler_step

    try:
        result = operation()
        if recorder.current_step is not None:
            step = recorder.current_step
            started = step.pop("_started")
            recorder.finish(step, "step", started)
            step["incomplete"] = True
            run_metrics["denoising_steps"].append(step)
            recorder.current_step = None
        recorder.resolve_cuda()
        return result
    finally:
        type(pipeline.text_encoder).__call__ = original_encoder_call
        pipeline.model.forward = original_model_forward
        pipeline.vae.decode = original_vae_decode
        for scheduler_class, original in original_scheduler_steps.items():
            scheduler_class.step = original


def parse_device_index(device: str) -> int:
    if not device.startswith("cuda:"):
        raise ValueError(
            "Pinned official Wan M0 supports CUDA devices only, for example cuda:0."
        )
    return int(device.split(":", 1)[1])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Instrumented Wan 2.1 M0 driver")
    parser.add_argument("--wan-code-dir", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--output-prefix", required=True)
    parser.add_argument("--metrics-output", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--size", default="832*480")
    parser.add_argument("--frame-num", type=int, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--sample-solver", choices=("unipc", "dpm++"), required=True)
    parser.add_argument("--sample-steps", type=int, required=True)
    parser.add_argument("--sample-shift", type=float, required=True)
    parser.add_argument("--sample-guide-scale", type=float, required=True)
    parser.add_argument("--dtype", choices=("bfloat16",), required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--offload-model", choices=("true", "false"), required=True)
    parser.add_argument("--t5-cpu", choices=("true", "false"), required=True)
    parser.add_argument("--repeat", type=int, choices=(1, 2), required=True)
    parser.add_argument(
        "--kernel-profiler",
        choices=("disabled", "torch"),
        default="disabled",
        help=(
            "disabled preserves official wall-clock timing; torch enables a "
            "separate overhead-bearing torch.profiler/CUPTI measurement."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    metrics_path = Path(args.metrics_output).resolve()
    output_prefix = Path(args.output_prefix).resolve()
    code_dir = Path(args.wan_code_dir).resolve()
    checkpoint_dir = Path(args.checkpoint_dir).resolve()
    metrics: dict[str, Any] = {
        "schema_version": "0.2.0",
        "kind": "hiveframe.m0.instrumentation",
        "status": "running",
        "started_at": utc_now(),
        "finished_at": None,
        "model_load": {},
        "runs": [],
        "process_memory": {},
        "allocator_environment": {},
        "kernel_profiler": {
            "mode": args.kernel_profiler,
            "official_wall_clock_eligible": args.kernel_profiler == "disabled",
            "overhead_disclosure": (
                "torch.profiler/CUPTI adds runtime and memory overhead; profiled "
                "runs are diagnostic and must not be used as official wall-clock "
                "samples."
            ),
        },
        "error": None,
    }
    total_start = time.perf_counter()
    pipeline = None
    observe_process_peak_callback: Callable[[], dict[str, Any]] | None = None
    process_peak_allocated: int | None = None
    process_peak_reserved: int | None = None
    torch_runtime: Any | None = None
    device_index_runtime: int | None = None

    try:
        sys.path.insert(0, str(code_dir))
        import torch
        import wan
        from wan.configs import SIZE_CONFIGS, WAN_CONFIGS
        from wan.text2video import (
            FlowDPMSolverMultistepScheduler,
            FlowUniPCMultistepScheduler,
        )
        from wan.utils.utils import cache_video

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable in the instrumented Wan process.")
        torch_runtime = torch
        device_index = parse_device_index(args.device)
        device_index_runtime = device_index
        torch.cuda.set_device(device_index)
        reset_allocator_peak(torch, device_index)

        def observe_process_peak() -> dict[str, Any]:
            nonlocal process_peak_allocated, process_peak_reserved
            snapshot = allocator_snapshot(torch, device_index)
            if snapshot["peak_allocated_bytes"] is not None:
                observed_allocated = int(snapshot["peak_allocated_bytes"])
                process_peak_allocated = (
                    observed_allocated
                    if process_peak_allocated is None
                    else max(process_peak_allocated, observed_allocated)
                )
            if snapshot["peak_reserved_bytes"] is not None:
                observed_reserved = int(snapshot["peak_reserved_bytes"])
                process_peak_reserved = (
                    observed_reserved
                    if process_peak_reserved is None
                    else max(process_peak_reserved, observed_reserved)
                )
            return snapshot

        observe_process_peak_callback = observe_process_peak
        config = WAN_CONFIGS["t2v-1.3B"]
        actual_dtype = str(config.param_dtype).removeprefix("torch.")
        if actual_dtype != args.dtype:
            raise RuntimeError(
                f"Pinned Wan dtype is {actual_dtype}, requested {args.dtype}."
            )
        if args.size not in SIZE_CONFIGS:
            raise RuntimeError(f"Unsupported official Wan size: {args.size}")

        load_recorder = StageRecorder(torch, metrics["model_load"])
        load_started = load_recorder.begin()
        pipeline, model_load_kernel = execute_with_kernel_profiler(
            torch,
            args.kernel_profiler,
            lambda: wan.WanT2V(
                config=config,
                checkpoint_dir=str(checkpoint_dir),
                device_id=device_index,
                rank=0,
                t5_fsdp=False,
                dit_fsdp=False,
                use_usp=False,
                t5_cpu=args.t5_cpu == "true",
            ),
        )
        load_recorder.finish(metrics["model_load"], "model_load", load_started)
        load_recorder.resolve_cuda()
        metrics["model_load"]["gpu_kernel_seconds"] = model_load_kernel
        metrics["model_load"]["memory"] = observe_process_peak()

        labels = ["cold"] if args.repeat == 1 else ["cold", "warm"]
        for repeat_index, label in enumerate(labels):
            run_total_start = time.perf_counter()
            run_metrics: dict[str, Any] = {
                "label": label,
                "repeat_index": repeat_index,
                "started_at": utc_now(),
                "finished_at": None,
                "prompt_encode_calls": [],
                "denoising_steps": [],
                "vae_decode_wall_seconds": None,
                "vae_decode_cuda_event_span_seconds": None,
                "video_encode_wall_seconds": None,
                "video_encode_cuda_event_span_seconds": None,
                "generation_wall_seconds": None,
                "generation_cuda_event_span_seconds": None,
                "gpu_kernel_seconds": None,
                "video_encode_gpu_kernel_seconds": None,
                "memory": {},
                "run_wall_seconds": None,
                "output": None,
            }
            metrics["runs"].append(run_metrics)
            observe_process_peak()
            reset_allocator_peak(torch, device_index)
            generation_recorder = StageRecorder(torch, run_metrics)
            generation_started = generation_recorder.begin()

            def generate() -> Any:
                return pipeline.generate(
                    args.prompt,
                    size=SIZE_CONFIGS[args.size],
                    frame_num=args.frame_num,
                    shift=args.sample_shift,
                    sample_solver=args.sample_solver,
                    sampling_steps=args.sample_steps,
                    guide_scale=args.sample_guide_scale,
                    n_prompt=args.negative_prompt,
                    seed=args.seed,
                    offload_model=args.offload_model == "true",
                )

            video, generation_kernel = execute_with_kernel_profiler(
                torch,
                args.kernel_profiler,
                lambda: instrument_generation(
                    torch_module=torch,
                    pipeline=pipeline,
                    scheduler_classes=[
                        FlowUniPCMultistepScheduler,
                        FlowDPMSolverMultistepScheduler,
                    ],
                    operation=generate,
                    run_metrics=run_metrics,
                ),
            )
            run_metrics["gpu_kernel_seconds"] = generation_kernel
            generation_recorder.finish(
                run_metrics, "generation", generation_started
            )
            generation_recorder.resolve_cuda()
            run_metrics["memory"] = observe_process_peak()

            output_path = output_prefix.with_name(
                f"{output_prefix.name}.{label}.mp4"
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            encode_recorder = StageRecorder(torch, run_metrics)
            encode_started = encode_recorder.begin()
            _, video_encode_kernel = execute_with_kernel_profiler(
                torch,
                args.kernel_profiler,
                lambda: cache_video(
                    tensor=video[None],
                    save_file=str(output_path),
                    fps=args.fps,
                    nrow=1,
                    normalize=True,
                    value_range=(-1, 1),
                ),
            )
            run_metrics["video_encode_gpu_kernel_seconds"] = video_encode_kernel
            encode_recorder.finish(run_metrics, "video_encode", encode_started)
            encode_recorder.resolve_cuda()
            observe_process_peak()
            if not output_path.is_file():
                raise RuntimeError(f"Video encoding failed for {label} run.")
            run_metrics["output"] = str(output_path)
            run_metrics["run_wall_seconds"] = time.perf_counter() - run_total_start
            run_metrics["finished_at"] = utc_now()

        torch.cuda.synchronize(device_index)
        final_snapshot = observe_process_peak()
        metrics["process_memory"] = {
            "process_peak_allocated_bytes": process_peak_allocated,
            "process_peak_reserved_bytes": process_peak_reserved,
            "final_current_allocated_bytes": final_snapshot[
                "current_allocated_bytes"
            ],
            "final_current_reserved_bytes": final_snapshot[
                "current_reserved_bytes"
            ],
            "scope": "model load and all repeated runs in one process",
            "measurement_method": (
                "maximum of PyTorch allocator peaks observed before each reset"
            ),
        }
        metrics["allocator_environment"] = allocator_environment(
            torch, device_index
        )
        metrics["status"] = "succeeded"
        return 0
    except BaseException as error:
        metrics["status"] = "failed"
        metrics["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
        raise
    finally:
        if (
            metrics["status"] != "succeeded"
            and observe_process_peak_callback is not None
            and torch_runtime is not None
            and device_index_runtime is not None
        ):
            try:
                final_snapshot = observe_process_peak_callback()
                metrics["process_memory"] = {
                    "process_peak_allocated_bytes": process_peak_allocated,
                    "process_peak_reserved_bytes": process_peak_reserved,
                    "final_current_allocated_bytes": final_snapshot[
                        "current_allocated_bytes"
                    ],
                    "final_current_reserved_bytes": final_snapshot[
                        "current_reserved_bytes"
                    ],
                    "scope": (
                        "partial process lifetime through the failed stage, "
                        "including model load where reached"
                    ),
                    "measurement_method": (
                        "maximum of available PyTorch allocator reset-window "
                        "peaks; partial failure receipt"
                    ),
                    "unsupported": final_snapshot.get("unsupported", {}),
                }
                metrics["allocator_environment"] = allocator_environment(
                    torch_runtime, device_index_runtime
                )
            except BaseException as cleanup_error:
                metrics["process_memory"] = {
                    "process_peak_allocated_bytes": process_peak_allocated,
                    "process_peak_reserved_bytes": process_peak_reserved,
                    "final_current_allocated_bytes": None,
                    "final_current_reserved_bytes": None,
                    "scope": "partial failed process",
                    "measurement_method": "best-effort PyTorch allocator capture",
                    "unsupported": {
                        "failure_cleanup": (
                            f"{type(cleanup_error).__name__}: {cleanup_error}"
                        )
                    },
                }
        metrics["total_wall_seconds"] = time.perf_counter() - total_start
        metrics["finished_at"] = utc_now()
        write_json(metrics_path, metrics)


if __name__ == "__main__":
    raise SystemExit(main())
