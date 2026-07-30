"""M0 reproducible baseline preflight, planning, execution, and receipts.

This module deliberately has no third-party imports. It can inspect a machine and
explain blockers before PyTorch or model weights are installed.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hive_backends.wan21 import Wan21RunSpec, build_generate_command


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "m0.wan21.toml"
REQUIRED_DISTRIBUTIONS = (
    "torch",
    "torchvision",
    "opencv-python",
    "diffusers",
    "transformers",
    "tokenizers",
    "accelerate",
    "imageio",
    "easydict",
    "ftfy",
    "imageio-ffmpeg",
    "numpy",
    "flash-attn",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    config["_config_path"] = str(path.resolve())
    return config


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def command_output(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_fingerprint(path: Path) -> dict[str, Any]:
    revision = command_output(["git", "rev-parse", "HEAD"], cwd=path)
    status = command_output(["git", "status", "--porcelain"], cwd=path)
    return {
        "revision": revision,
        "dirty": bool(status) if status is not None else None,
    }


def installed_distributions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in REQUIRED_DISTRIBUTIONS:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def memory_total_bytes() -> int | None:
    if os.name == "nt":
        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _parse_dxdiag(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("Card name:"):
            current = {"name": line.split(":", 1)[1].strip()}
            devices.append(current)
        elif current is not None and line.startswith("Dedicated Memory:"):
            value = line.split(":", 1)[1].strip()
            current["dedicated_memory"] = value
        elif current is not None and line.startswith("Driver Version:"):
            current.setdefault("driver_version", line.split(":", 1)[1].strip())
        elif current is not None and line.startswith("Driver Model:"):
            current["driver_model"] = line.split(":", 1)[1].strip()
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for device in devices:
        key = (
            device.get("name"),
            device.get("dedicated_memory"),
            device.get("driver_version"),
        )
        if key not in seen:
            seen.add(key)
            unique.append(device)
    return unique


def windows_display_devices() -> list[dict[str, Any]]:
    if os.name != "nt" or shutil.which("dxdiag.exe") is None:
        return []
    path = Path(tempfile.gettempdir()) / f"hiveframe-dxdiag-{os.getpid()}.txt"
    try:
        subprocess.run(
            ["dxdiag.exe", "/dontskip", "/whql:off", "/t", str(path)],
            check=False,
            capture_output=True,
            timeout=90,
        )
        if not path.exists():
            return []
        raw = path.read_bytes()
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16", errors="ignore")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("mbcs", errors="ignore")
        return _parse_dxdiag(text)
    except (OSError, subprocess.TimeoutExpired):
        return []
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def nvidia_smi_path() -> Path | None:
    discovered = shutil.which("nvidia-smi")
    if discovered:
        return Path(discovered)
    for candidate in (
        Path(r"C:\Windows\System32\nvidia-smi.exe"),
        Path(r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
    ):
        if candidate.exists():
            return candidate
    return None


def torch_devices() -> dict[str, Any]:
    result: dict[str, Any] = {
        "torch_importable": False,
        "torch_version": None,
        "cuda_available": False,
        "cuda_version": None,
        "cuda_devices": [],
        "xpu_available": False,
        "xpu_devices": [],
    }
    try:
        import torch  # type: ignore
    except ImportError:
        return result
    result["torch_importable"] = True
    result["torch_version"] = getattr(torch, "__version__", None)
    result["cuda_version"] = getattr(getattr(torch, "version", None), "cuda", None)
    if hasattr(torch, "cuda"):
        result["cuda_available"] = bool(torch.cuda.is_available())
        if result["cuda_available"]:
            result["cuda_devices"] = [
                {
                    "index": index,
                    "name": torch.cuda.get_device_name(index),
                    "total_memory_bytes": torch.cuda.get_device_properties(
                        index
                    ).total_memory,
                }
                for index in range(torch.cuda.device_count())
            ]
    if hasattr(torch, "xpu"):
        try:
            result["xpu_available"] = bool(torch.xpu.is_available())
            if result["xpu_available"]:
                result["xpu_devices"] = [
                    {"index": index, "name": torch.xpu.get_device_name(index)}
                    for index in range(torch.xpu.device_count())
                ]
        except (AttributeError, RuntimeError):
            pass
    return result


def collect_environment() -> dict[str, Any]:
    return {
        "captured_at": utc_now(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "host_ram_bytes": memory_total_bytes(),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
        },
        "display_devices": windows_display_devices(),
        "nvidia_smi": str(nvidia_smi_path()) if nvidia_smi_path() else None,
        "torch": torch_devices(),
        "packages": installed_distributions(),
        "project_git": git_fingerprint(ROOT),
    }


def inspect_code(config: dict[str, Any]) -> dict[str, Any]:
    code_dir = project_path(config["backend"]["code_dir"])
    generate_path = code_dir / "generate.py"
    fingerprint = git_fingerprint(code_dir) if code_dir.exists() else {}
    expected = config["upstream"]["code_revision"]
    return {
        "path": str(code_dir),
        "exists": code_dir.exists(),
        "generate_py_exists": generate_path.is_file(),
        "expected_revision": expected,
        "actual_revision": fingerprint.get("revision"),
        "dirty": fingerprint.get("dirty"),
        "revision_matches": fingerprint.get("revision") == expected,
    }


def inspect_model(config: dict[str, Any], full_hash: bool = False) -> dict[str, Any]:
    model_dir = project_path(config["model"]["local_dir"])
    expected_files = config["model"]["files"]
    files: list[dict[str, Any]] = []
    all_present = True
    sizes_match = True
    hashes_match: bool | None = True if full_hash else None
    for relative_name, expected in expected_files.items():
        path = model_dir / relative_name
        exists = path.is_file()
        actual_size = path.stat().st_size if exists else None
        size_matches = exists and actual_size == expected["size"]
        item: dict[str, Any] = {
            "path": str(path),
            "exists": exists,
            "expected_size": expected["size"],
            "actual_size": actual_size,
            "size_matches": size_matches,
            "expected_sha256": expected["sha256"],
        }
        if full_hash and exists and size_matches:
            item["actual_sha256"] = sha256_file(path)
            item["hash_matches"] = item["actual_sha256"] == expected["sha256"]
            hashes_match = bool(hashes_match and item["hash_matches"])
        elif full_hash:
            item["actual_sha256"] = None
            item["hash_matches"] = False
            hashes_match = False
        files.append(item)
        all_present = all_present and exists
        sizes_match = sizes_match and bool(size_matches)
    return {
        "path": str(model_dir),
        "exists": model_dir.is_dir(),
        "expected_repository_bytes": config["model"]["expected_repository_bytes"],
        "key_files": files,
        "all_key_files_present": all_present,
        "key_file_sizes_match": sizes_match,
        "key_file_hashes_match": hashes_match,
    }


def load_license_record(config: dict[str, Any]) -> dict[str, Any]:
    path = project_path(config["admission"]["license_record"])
    if not path.is_file():
        return {"path": str(path), "exists": False, "status": None}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path),
        "exists": True,
        "status": payload.get("status"),
        "license": payload.get("license", {}).get("spdx"),
        "model_revision": payload.get("artifact", {}).get("revision"),
    }


def evaluate_preflight(config: dict[str, Any]) -> dict[str, Any]:
    environment = collect_environment()
    code = inspect_code(config)
    model = inspect_model(config)
    license_record = load_license_record(config)
    model_path = project_path(config["model"]["local_dir"])
    disk = shutil.disk_usage(model_path.parent if model_path.parent.exists() else ROOT)
    blockers: list[dict[str, str]] = []
    warnings: list[str] = []

    if not environment["torch"]["cuda_available"]:
        blockers.append(
            {
                "code": "cuda_unavailable",
                "message": (
                    "The pinned official Wan backend requires NVIDIA CUDA and "
                    "flash_attn; no usable CUDA device is available."
                ),
            }
        )
    missing = [
        name for name, version in environment["packages"].items() if version is None
    ]
    if missing:
        blockers.append(
            {
                "code": "dependencies_missing",
                "message": "Missing Python distributions: " + ", ".join(missing),
            }
        )
    if not code["generate_py_exists"]:
        blockers.append(
            {
                "code": "upstream_code_missing",
                "message": f"Pinned Wan code is not present at {code['path']}.",
            }
        )
    elif not code["revision_matches"] or code["dirty"]:
        blockers.append(
            {
                "code": "upstream_code_unpinned",
                "message": "Wan code revision is different from the pinned clean commit.",
            }
        )
    if not model["all_key_files_present"]:
        blockers.append(
            {
                "code": "model_missing",
                "message": f"Checkpoint is not present at {model['path']}.",
            }
        )
    elif not model["key_file_sizes_match"]:
        blockers.append(
            {
                "code": "model_size_mismatch",
                "message": "One or more checkpoint files have unexpected sizes.",
            }
        )
    if license_record["status"] != "approved_for_research_baseline":
        blockers.append(
            {
                "code": "license_not_admitted",
                "message": "Model license record is not approved for the research baseline.",
            }
        )
    if disk.free < config["model"]["expected_repository_bytes"]:
        blockers.append(
            {
                "code": "disk_space_insufficient",
                "message": "Free disk space is smaller than the model repository size.",
            }
        )
    if environment["display_devices"] and any(
        "Intel(R) Arc(TM)" in item.get("name", "")
        for item in environment["display_devices"]
    ):
        warnings.append(
            "Intel Arc was detected, but the pinned official Wan code is CUDA-only. "
            "An XPU port must be evaluated as a separate backend, not mixed into M0."
        )

    return {
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.preflight",
        "captured_at": utc_now(),
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "environment": environment,
        "upstream_code": code,
        "model": model,
        "license_record": license_record,
        "disk": {
            "path": str(model_path.parent),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
    }


def download_plan(config: dict[str, Any]) -> dict[str, Any]:
    expected = int(config["model"]["expected_repository_bytes"])
    reserve = int(config["model"]["minimum_free_space_after_download_bytes"])
    model_path = project_path(config["model"]["local_dir"])
    disk = shutil.disk_usage(model_path.parent if model_path.parent.exists() else ROOT)
    return {
        "download_performed": False,
        "repository": config["model"]["repo_id"],
        "revision": config["model"]["revision"],
        "license": config["model"]["license"],
        "expected_bytes": expected,
        "expected_gb_decimal": round(expected / 1_000_000_000, 3),
        "expected_gib": round(expected / (1024**3), 3),
        "destination": str(model_path),
        "current_free_bytes": disk.free,
        "required_free_before_download_bytes": expected + reserve,
        "minimum_free_after_download_bytes": reserve,
        "enough_space": disk.free >= expected + reserve,
        "command_after_approval": [
            "huggingface-cli",
            "download",
            config["model"]["repo_id"],
            "--revision",
            config["model"]["revision"],
            "--local-dir",
            str(model_path),
        ],
    }


def load_suite(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = project_path(config["benchmark"]["suite_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["prompts"])


def process_rss_bytes(pid: int) -> int | None:
    if os.name != "nt":
        status_path = Path(f"/proc/{pid}/status")
        try:
            for line in status_path.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except OSError:
            return None
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    process_query = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(process_query, False, pid)
    if not handle:
        return None
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    try:
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def sample_nvidia_gpu() -> dict[str, int] | None:
    executable = nvidia_smi_path()
    if executable is None:
        return None
    output = command_output(
        [
            str(executable),
            "--query-gpu=memory.used,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return None
    first = output.splitlines()[0].split(",")
    try:
        return {
            "memory_used_mib": int(first[0].strip()),
            "utilization_percent": int(first[1].strip()),
        }
    except (IndexError, ValueError):
        return None


def blocked_receipt(
    config: dict[str, Any],
    prompt: dict[str, Any],
    preflight: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.run_receipt",
        "run_id": f"{prompt['id']}-{prompt['seed']}-{int(time.time())}",
        "status": "blocked",
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "backend": {
            "name": "wan21_t2v_1_3b_official",
            "code_revision": config["upstream"]["code_revision"],
            "model_id": config["model"]["repo_id"],
            "model_revision": config["model"]["revision"],
        },
        "sample": prompt,
        "settings": config["generation"],
        "timing": {},
        "resources": {},
        "artifacts": {},
        "preflight": {
            "ready": False,
            "blockers": preflight["blockers"],
            "warnings": preflight["warnings"],
        },
    }


def run_sample(
    config: dict[str, Any],
    prompt: dict[str, Any],
    output_dir: Path,
) -> tuple[int, dict[str, Any]]:
    preflight = evaluate_preflight(config)
    run_id = f"{prompt['id']}-{prompt['seed']}"
    receipt_path = output_dir / f"{run_id}.receipt.json"
    if not preflight["ready"]:
        receipt = blocked_receipt(config, prompt, preflight)
        write_json(receipt_path, receipt)
        return 2, receipt

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.mp4"
    stdout_path = output_dir / f"{run_id}.stdout.log"
    stderr_path = output_dir / f"{run_id}.stderr.log"
    generation = config["generation"]
    spec = Wan21RunSpec(
        prompt=prompt["intent"],
        seed=int(prompt["seed"]),
        output_path=output_path,
        size=generation["size"],
        frame_num=int(generation["frame_num"]),
        sample_steps=int(generation["sample_steps"]),
        sample_shift=float(generation["sample_shift"]),
        sample_guide_scale=float(generation["sample_guide_scale"]),
        sample_solver=generation["sample_solver"],
        offload_model=bool(generation["offload_model"]),
        t5_cpu=bool(generation["t5_cpu"]),
    )
    command = build_generate_command(
        python_executable=Path(sys.executable),
        code_dir=project_path(config["backend"]["code_dir"]),
        checkpoint_dir=project_path(config["model"]["local_dir"]),
        spec=spec,
    )

    started_at = utc_now()
    start = time.perf_counter()
    peak_host_rss = 0
    peak_gpu_memory_mib = 0
    gpu_utilization_samples: list[int] = []
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=project_path(config["backend"]["code_dir"]),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        while process.poll() is None:
            rss = process_rss_bytes(process.pid)
            if rss is not None:
                peak_host_rss = max(peak_host_rss, rss)
            gpu = sample_nvidia_gpu()
            if gpu:
                peak_gpu_memory_mib = max(
                    peak_gpu_memory_mib, gpu["memory_used_mib"]
                )
                gpu_utilization_samples.append(gpu["utilization_percent"])
            time.sleep(float(config["receipt"]["sample_interval_seconds"]))
        return_code = process.returncode
    wall_seconds = time.perf_counter() - start
    output_exists = output_path.is_file()
    status = "succeeded" if return_code == 0 and output_exists else "failed"
    receipt = {
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.run_receipt",
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": utc_now(),
        "backend": {
            "name": "wan21_t2v_1_3b_official",
            "code_repository": config["upstream"]["code_repository"],
            "code_revision": config["upstream"]["code_revision"],
            "model_id": config["model"]["repo_id"],
            "model_revision": config["model"]["revision"],
            "license": config["model"]["license"],
        },
        "sample": prompt,
        "settings": generation,
        "command": command,
        "return_code": return_code,
        "timing": {
            "wall_clock_seconds": wall_seconds,
            "gpu_kernel_seconds": None,
            "denoising_seconds": None,
            "vae_encode_seconds": None,
            "vae_decode_seconds": None,
            "communication_seconds": 0.0,
            "scheduler_overhead_seconds": None,
            "repair_overhead_seconds": 0.0,
        },
        "resources": {
            "peak_host_rss_bytes": peak_host_rss or None,
            "peak_gpu_memory_mib_sampled": peak_gpu_memory_mib or None,
            "average_gpu_utilization_percent": (
                sum(gpu_utilization_samples) / len(gpu_utilization_samples)
                if gpu_utilization_samples
                else None
            ),
            "transferred_bytes": 0,
            "cache_memory_bytes": 0,
        },
        "sparse": {
            "enabled": False,
            "active_patch_ratio": 1.0,
            "skipped_patch_ratio": 0.0,
            "boundary_only_refresh_ratio": 0.0,
        },
        "artifacts": {
            "video": str(output_path) if output_exists else None,
            "video_bytes": output_path.stat().st_size if output_exists else None,
            "video_sha256": sha256_file(output_path) if output_exists else None,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
        "environment": collect_environment(),
        "warnings": [
            "GPU kernel, denoising, VAE, and scheduler timings require the M0 "
            "instrumentation hook and remain null rather than being estimated."
        ],
    }
    write_json(receipt_path, receipt)
    return (0 if status == "succeeded" else 1), receipt


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def command_preflight(args: argparse.Namespace, config: dict[str, Any]) -> int:
    report = evaluate_preflight(config)
    output = (
        Path(args.output).resolve()
        if args.output
        else project_path(config["paths"]["preflight_report"])
    )
    write_json(output, report)
    print_json(report)
    return 0 if report["ready"] else 2


def command_plan(_: argparse.Namespace, config: dict[str, Any]) -> int:
    print_json(download_plan(config))
    return 0


def command_verify_model(args: argparse.Namespace, config: dict[str, Any]) -> int:
    result = inspect_model(config, full_hash=args.full)
    print_json(result)
    if not result["all_key_files_present"] or not result["key_file_sizes_match"]:
        return 2
    if args.full and result["key_file_hashes_match"] is not True:
        return 2
    return 0


def command_run(args: argparse.Namespace, config: dict[str, Any]) -> int:
    suite = load_suite(config)
    prompt = next((item for item in suite if item["id"] == args.prompt_id), None)
    if prompt is None:
        print(f"Unknown prompt id: {args.prompt_id}", file=sys.stderr)
        return 2
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else project_path(config["paths"]["run_dir"])
    )
    return_code, receipt = run_sample(config, prompt, output_dir)
    print_json(receipt)
    return return_code


def command_run_suite(args: argparse.Namespace, config: dict[str, Any]) -> int:
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else project_path(config["paths"]["run_dir"])
    )
    results = []
    final_code = 0
    for prompt in load_suite(config):
        code, receipt = run_sample(config, prompt, output_dir)
        results.append(
            {
                "run_id": receipt["run_id"],
                "status": receipt["status"],
                "receipt": str(output_dir / f"{receipt['run_id']}.receipt.json"),
            }
        )
        final_code = max(final_code, code)
        if code == 2:
            break
    summary = {
        "kind": "hiveframe.m0.suite_summary",
        "created_at": utc_now(),
        "suite": config["benchmark"]["suite_id"],
        "results": results,
    }
    write_json(output_dir / "suite.summary.json", summary)
    print_json(summary)
    return final_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hiveframe-m0",
        description="HIVEFRAME M0 reproducible baseline runner",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="Path to the pinned M0 TOML configuration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight", help="Inspect compatibility without downloading a model."
    )
    preflight.add_argument("--output")
    preflight.set_defaults(handler=command_preflight)

    plan = subparsers.add_parser(
        "download-plan", help="Show exact size and destination; never download."
    )
    plan.set_defaults(handler=command_plan)

    verify = subparsers.add_parser(
        "verify-model", help="Verify downloaded key files."
    )
    verify.add_argument(
        "--full", action="store_true", help="Hash large files in addition to size checks."
    )
    verify.set_defaults(handler=command_verify_model)

    run = subparsers.add_parser("run", help="Run one deterministic canonical sample.")
    run.add_argument("--prompt-id", required=True)
    run.add_argument("--output-dir")
    run.set_defaults(handler=command_run)

    suite = subparsers.add_parser(
        "run-suite", help="Run all ten canonical prompts sequentially."
    )
    suite.add_argument("--output-dir")
    suite.set_defaults(handler=command_run_suite)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config).resolve())
    return int(args.handler(args, config))


if __name__ == "__main__":
    raise SystemExit(main())
