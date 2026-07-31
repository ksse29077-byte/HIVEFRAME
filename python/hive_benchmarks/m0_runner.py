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
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 handoff host
    import tomli as tomllib

from hive_backends.wan21 import Wan21RunSpec, build_generate_command


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "m0.wan21.toml"
PATH_ENVIRONMENT_OVERRIDES = {
    "HIVEFRAME_WAN_CODE_DIR": ("backend", "code_dir"),
    "HIVEFRAME_MODEL_DIR": ("model", "local_dir"),
    "HIVEFRAME_HF_CACHE_DIR": ("model", "cache_dir"),
}
REQUIRED_DISTRIBUTIONS = (
    "torch",
    "torchvision",
    "opencv-python",
    "diffusers",
    "transformers",
    "tokenizers",
    "accelerate",
    "tqdm",
    "imageio",
    "easydict",
    "ftfy",
    "imageio-ffmpeg",
    "numpy",
    "flash-attn",
)
RUN_PROFILES = (
    "smoke-cold-warm",
    "baseline-memory-admission",
    "baseline-reproducibility",
)
PROFILE_RUN_KINDS = {
    "smoke-cold-warm": "smoke-based same-seed cold/warm pair",
    "baseline-memory-admission": "baseline memory admission probe",
    "baseline-reproducibility": "baseline same-seed cold/warm pair",
}
PROFILE_REPEATS = {
    "smoke-cold-warm": 2,
    "baseline-memory-admission": 1,
    "baseline-reproducibility": 2,
}
MEMORY_ADMISSION_ELIGIBILITY = {
    "benchmark_status": "safety_test",
    "quality_eligible": False,
    "speedup_comparison_eligible": False,
    "official_baseline_eligible": False,
    "memory_admission_eligible": True,
}
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RECEIPT_SCHEMA_VERSION = "0.2.0"
MEASUREMENT_SUPPORT_STATUSES = {
    "supported",
    "unsupported",
    "not_collected",
    "not_applicable",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def measurement(
    value: float | int | None,
    *,
    unit: str,
    scope: str,
    measurement_method: str,
    aggregation: str,
    support_status: str | None = None,
    unsupported_reason: str | None = None,
    parent_span: str | None = None,
    run_label: str | None = None,
    repeat_index: int | None = None,
) -> dict[str, Any]:
    status = support_status or (
        "supported" if value is not None else "not_collected"
    )
    if status not in MEASUREMENT_SUPPORT_STATUSES:
        raise ValueError(f"Unknown measurement support status: {status}")
    if value is None and not unsupported_reason:
        raise ValueError("Null measurements require an unsupported reason.")
    if value is not None and status != "supported":
        raise ValueError("Only supported measurements may contain a value.")
    return {
        "value": value,
        "unit": unit,
        "scope": scope,
        "measurement_method": measurement_method,
        "aggregation": aggregation,
        "support_status": status,
        "unsupported_reason": unsupported_reason,
        "parent_span": parent_span,
        "run_label": run_label,
        "repeat_index": repeat_index,
    }


def nonnegative_remainder(parent: float | None, children: list[float]) -> float | None:
    if parent is None:
        return None
    return max(0.0, float(parent) - sum(float(value) for value in children))


def load_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    for variable, (section, key) in PATH_ENVIRONMENT_OVERRIDES.items():
        value = os.environ.get(variable)
        if value:
            config[section][key] = str(Path(value).expanduser().resolve())
    report_dir = os.environ.get("HIVEFRAME_M0_REPORT_DIR")
    if report_dir:
        report_root = Path(report_dir).expanduser().resolve()
        config["paths"]["preflight_report"] = str(report_root / "preflight.json")
        config["paths"]["run_dir"] = str(report_root / "runs")
        config["paths"]["gate_state"] = str(report_root / "gates.json")
    config["_config_path"] = str(path.resolve())
    return config


def project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def existing_storage_ancestor(path: Path) -> Path:
    candidate = path.resolve()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return ROOT
        candidate = parent
    return candidate if candidate.is_dir() else candidate.parent


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


def validate_receipt_contract(receipt: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "kind",
        "run_id",
        "status",
        "partial",
        "profile",
        "timing",
        "resources",
        "unsupported_metrics",
        "error",
    }
    missing = sorted(required - receipt.keys())
    if missing:
        raise ValueError(f"Receipt is missing required fields: {missing}")
    version = receipt["schema_version"]
    if version not in {"0.1.0", RECEIPT_SCHEMA_VERSION}:
        raise ValueError(f"Unsupported receipt schema version: {version}")
    if version == "0.1.0":
        return
    if receipt["profile"] == "baseline-memory-admission":
        if receipt.get("run_kind") != PROFILE_RUN_KINDS[
            "baseline-memory-admission"
        ]:
            raise ValueError(
                "Memory-admission receipt has an incorrect run kind."
            )
        if receipt.get("benchmark_eligibility") != (
            MEMORY_ADMISSION_ELIGIBILITY
        ):
            raise ValueError(
                "Memory-admission receipt must be excluded from quality, "
                "speedup, and official-baseline use."
            )

    timing_required = {
        "cli_python_process_wall",
        "cli_to_receipt_wall",
        "runner_child_process_wall",
        "instrumented_child_process_wall",
        "setup_finalization_wall",
        "unattributed_wall",
        "model_load",
        "runs",
        "span_relationships",
        "process_cuda_event_span",
        "process_gpu_kernel",
        "profiling_contract",
    }
    missing_timing = sorted(timing_required - receipt["timing"].keys())
    if missing_timing:
        raise ValueError(f"Receipt v0.2 timing is incomplete: {missing_timing}")
    resource_required = {"process", "runs", "host_ram", "allocator"}
    missing_resources = sorted(resource_required - receipt["resources"].keys())
    if missing_resources:
        raise ValueError(
            f"Receipt v0.2 resources are incomplete: {missing_resources}"
        )

    measurement_keys = {
        "value",
        "unit",
        "scope",
        "measurement_method",
        "aggregation",
        "support_status",
        "unsupported_reason",
        "parent_span",
        "run_label",
        "repeat_index",
    }

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if "value" in value and "support_status" in value:
                absent = sorted(measurement_keys - value.keys())
                if absent:
                    raise ValueError(
                        f"Measurement {path} is missing metadata: {absent}"
                    )
                status = value["support_status"]
                if status not in MEASUREMENT_SUPPORT_STATUSES:
                    raise ValueError(
                        f"Measurement {path} has invalid status {status!r}."
                    )
                if status == "supported":
                    if value["value"] is None:
                        raise ValueError(
                            f"Supported measurement {path} has no value."
                        )
                    if value["unsupported_reason"] is not None:
                        raise ValueError(
                            f"Supported measurement {path} has an unsupported reason."
                        )
                else:
                    if value["value"] is not None:
                        raise ValueError(
                            f"Unsupported measurement {path} must have null value."
                        )
                    if not value["unsupported_reason"]:
                        raise ValueError(
                            f"Unsupported measurement {path} needs a reason."
                        )
            for key, child in value.items():
                visit(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(receipt["timing"], "timing")
    visit(receipt["resources"], "resources")
    encoded = json.dumps(receipt["timing"], sort_keys=True)
    if "cuda_gpu_seconds" in encoded:
        raise ValueError(
            "Receipt v0.2 must not label a CUDA event span as cuda_gpu_seconds."
        )


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


def nvidia_inventory() -> list[dict[str, Any]]:
    executable = nvidia_smi_path()
    if executable is None:
        return []
    output = command_output(
        [
            str(executable),
            "--query-gpu=index,name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return []
    devices: list[dict[str, Any]] = []
    for line in output.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 5:
            continue
        devices.append(
            {
                "index": int(values[0]),
                "name": values[1],
                "driver_version": values[2],
                "memory_total_mib": int(values[3]),
                "compute_capability": values[4],
            }
        )
    return devices


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
        "nvidia_devices": nvidia_inventory(),
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
    checkpoint_license = payload.get("checkpoint_license", payload.get("license", {}))
    return {
        "path": str(path),
        "exists": True,
        "status": payload.get("status"),
        "license": checkpoint_license.get("spdx"),
        "model_revision": payload.get("artifact", {}).get("revision"),
        "code_license": payload.get("official_code", {})
        .get("license", {})
        .get("spdx"),
    }


def evaluate_preflight(config: dict[str, Any]) -> dict[str, Any]:
    environment = collect_environment()
    code = inspect_code(config)
    model = inspect_model(config)
    license_record = load_license_record(config)
    model_path = project_path(config["model"]["local_dir"])
    disk_anchor = existing_storage_ancestor(model_path.parent)
    disk = shutil.disk_usage(disk_anchor)
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
    recommended_free = (
        int(config["model"]["expected_installed_bytes"])
        + int(config["model"]["temporary_and_cache_headroom_bytes"])
        + int(config["model"]["minimum_free_space_after_download_bytes"])
    )
    required_free = (
        recommended_free
        if not model["all_key_files_present"]
        else int(config["model"]["minimum_free_space_after_download_bytes"])
    )
    if disk.free < required_free:
        blockers.append(
            {
                "code": "disk_space_insufficient",
                "message": (
                    "Free disk space is below the configured download, temporary "
                    "cache, and post-install reserve requirement."
                ),
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

    cuda_ready = bool(environment["torch"]["cuda_available"])
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
        "execution_decision": {
            "official_backend_runnable_on_this_pc": cuda_ready,
            "reason": (
                "Pinned official Wan can use the detected NVIDIA CUDA device."
                if cuda_ready
                else (
                    "Pinned official Wan requires an NVIDIA CUDA device and "
                    "flash_attn, but CUDA is not available in this environment."
                )
            ),
            "recommended_dtype": config["generation"]["dtype"],
            "recommended_resolution": config["generation"]["size"],
            "smoke_frames": config["smoke"]["frame_num"],
            "baseline_frames": config["generation"]["frame_num"],
            "fps": config["generation"]["fps"],
            "cpu_offload": config["generation"]["offload_model"],
            "t5_on_cpu": config["generation"]["t5_cpu"],
        },
        "disk": {
            "path": str(disk_anchor),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "recommended_free_before_download_bytes": recommended_free,
        },
    }


def download_plan(config: dict[str, Any]) -> dict[str, Any]:
    expected = int(config["model"]["expected_repository_bytes"])
    installed = int(config["model"]["expected_installed_bytes"])
    temporary = int(config["model"]["temporary_and_cache_headroom_bytes"])
    reserve = int(config["model"]["minimum_free_space_after_download_bytes"])
    model_path = project_path(config["model"]["local_dir"])
    cache_path = project_path(config["model"]["cache_dir"])
    disk_anchor = existing_storage_ancestor(model_path.parent)
    disk = shutil.disk_usage(disk_anchor)
    required = installed + temporary + reserve
    return {
        "download_performed": False,
        "repository": config["model"]["repo_id"],
        "revision": config["model"]["revision"],
        "license": config["model"]["license"],
        "expected_bytes": expected,
        "expected_gb_decimal": round(expected / 1_000_000_000, 3),
        "expected_gib": round(expected / (1024**3), 3),
        "expected_installed_bytes": installed,
        "expected_installed_gb_decimal": round(installed / 1_000_000_000, 3),
        "temporary_and_cache_headroom_bytes": temporary,
        "temporary_and_cache_headroom_gb_decimal": round(
            temporary / 1_000_000_000, 3
        ),
        "destination": str(model_path),
        "cache_destination": str(cache_path),
        "storage_volume_checked_at": str(disk_anchor),
        "current_free_bytes": disk.free,
        "recommended_free_before_download_bytes": required,
        "recommended_free_before_download_gb_decimal": round(
            required / 1_000_000_000, 3
        ),
        "recommended_free_before_download_gib": round(required / (1024**3), 3),
        "minimum_free_after_download_bytes": reserve,
        "enough_space": disk.free >= required,
        "command_after_approval": [
            "HF_HOME=" + str(cache_path),
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


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def settings_for_profile(
    config: dict[str, Any], profile: str, *, repeat: int | None = None
) -> dict[str, Any]:
    known_profiles = {
        "smoke",
        "smoke-cold-warm",
        "baseline-memory-admission",
        "baseline-reproducibility",
        "reproducibility",
        "canonical",
    }
    if profile not in known_profiles:
        choices = ", ".join(sorted(known_profiles))
        raise ValueError(
            f"Unknown M0 profile {profile!r}; choose one of: {choices}."
        )
    settings = dict(config["generation"])
    if profile in {"smoke", "smoke-cold-warm"}:
        smoke = dict(config["smoke"])
        smoke.pop("prompt_id", None)
        settings.update(smoke)
    elif profile == "baseline-memory-admission":
        admission = dict(config["memory_admission"])
        admission.pop("prompt_id", None)
        settings.update(admission)
    settings["repeat"] = (
        repeat
        if repeat is not None
        else (
            int(config["memory_admission"]["repeat"])
            if profile == "baseline-memory-admission"
            else int(config["reproducibility"]["repeat"])
        )
    )
    return settings


def receipt_execution_classification(profile: str) -> dict[str, Any]:
    if profile != "baseline-memory-admission":
        return {}
    return {
        "run_kind": PROFILE_RUN_KINDS[profile],
        "benchmark_eligibility": dict(MEMORY_ADMISSION_ELIGIBILITY),
    }


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise argparse.ArgumentTypeError(
            "Run ID must be 1-128 characters, start with an ASCII letter or "
            "digit, and contain only ASCII letters, digits, '.', '_', or '-'."
        )
    return run_id


def expected_run_artifacts(
    output_dir: Path, run_id: str, *, repeat: int
) -> list[dict[str, Any]]:
    labels = ["cold"] if repeat == 1 else ["cold", "warm"]
    artifacts = [
        {
            "kind": "video",
            "label": label,
            "path": str(output_dir / f"{run_id}.{label}.mp4"),
        }
        for label in labels
    ]
    artifacts.extend(
        {
            "kind": kind,
            "label": None,
            "path": str(output_dir / f"{run_id}.{suffix}"),
        }
        for kind, suffix in (
            ("instrumentation", "instrumentation.json"),
            ("receipt", "receipt.json"),
            ("stdout", "stdout.log"),
            ("stderr", "stderr.log"),
        )
    )
    return artifacts


def build_execution_plan(
    config: dict[str, Any],
    prompt: dict[str, Any],
    profile: str,
    *,
    repeat: int,
    expected_run_kind: str,
    run_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    validate_run_id(run_id)
    settings = settings_for_profile(
        config,
        profile,
        repeat=repeat,
    )
    settings_hash = stable_hash({"sample": prompt, "settings": settings})
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "hiveframe.m0.run_plan",
        "execution_started": False,
        "selected_profile": profile,
        "expected_run_kind": expected_run_kind,
        **receipt_execution_classification(profile),
        "run_id": run_id,
        "prompt_id": prompt["id"],
        "sample": prompt,
        "effective_settings": settings,
        "settings_hash": settings_hash,
        "backend": {
            "name": config["backend"]["name"],
            "model_id": config["model"]["repo_id"],
            "model_revision": config["model"]["revision"],
            "code_repository": config["upstream"]["code_repository"],
            "code_revision": config["upstream"]["code_revision"],
        },
        "execution_approval": {
            "required_argument": "--expect-settings-hash",
            "required_value": settings_hash,
        },
        "output": {
            "directory": str(output_dir),
            "expected_artifacts": expected_run_artifacts(
                output_dir, run_id, repeat=repeat
            ),
            "existing_collisions": run_artifact_collisions(output_dir, run_id),
            "overwrite_allowed": False,
        },
    }


def build_run_plan(
    config: dict[str, Any],
    prompt: dict[str, Any],
    profile: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if profile not in RUN_PROFILES:
        choices = ", ".join(RUN_PROFILES)
        raise ValueError(
            f"Unknown run profile {profile!r}; choose one of: {choices}."
        )
    run_id = f"{profile}-{prompt['id']}-{prompt['seed']}"
    return build_execution_plan(
        config,
        prompt,
        profile,
        repeat=PROFILE_REPEATS[profile],
        expected_run_kind=PROFILE_RUN_KINDS[profile],
        run_id=run_id,
        output_dir=output_dir or project_path(config["paths"]["run_dir"]),
    )


def build_smoke_plan(
    config: dict[str, Any],
    prompt: dict[str, Any],
    run_id: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    return build_execution_plan(
        config,
        prompt,
        "smoke",
        repeat=1,
        expected_run_kind="single regression smoke",
        run_id=run_id,
        output_dir=output_dir or project_path(config["paths"]["run_dir"]),
    )


def settings_approval_error(
    plan: dict[str, Any], expected_settings_hash: str | None
) -> dict[str, Any] | None:
    if not expected_settings_hash:
        return stage_gate_error(
            "settings-approval",
            "Execution requires --expect-settings-hash from an approved plan.",
        )
    if expected_settings_hash != plan["settings_hash"]:
        return stage_gate_error(
            "settings-approval",
            (
                "Approved settings hash does not match the final effective "
                f"settings: expected {expected_settings_hash}, "
                f"actual {plan['settings_hash']}."
            ),
        )
    return None


def run_artifact_collisions(output_dir: Path, run_id: str) -> list[str]:
    validate_run_id(run_id)
    if not output_dir.exists():
        return []
    return sorted(str(path) for path in output_dir.glob(f"{run_id}.*"))


def gate_state_path(config: dict[str, Any]) -> Path:
    return project_path(config["paths"]["gate_state"])


def read_gate_state(config: dict[str, Any]) -> dict[str, Any]:
    path = gate_state_path(config)
    if not path.is_file():
        return {
            "schema_version": "0.1.0",
            "smoke": None,
            "reproducibility": None,
            "memory_admission": None,
        }
    return json.loads(path.read_text(encoding="utf-8"))


def write_gate_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    write_json(gate_state_path(config), state)


def gate_fingerprint(config: dict[str, Any]) -> dict[str, str]:
    return {
        "project_commit": git_fingerprint(ROOT).get("revision"),
        "code_revision": config["upstream"]["code_revision"],
        "model_revision": config["model"]["revision"],
        "config_hash": stable_hash(
            {key: value for key, value in config.items() if not key.startswith("_")}
        ),
    }


def gate_matches(
    gate: dict[str, Any] | None, config: dict[str, Any], expected_status: str
) -> bool:
    if not gate or gate.get("status") != expected_status:
        return False
    fingerprint = gate_fingerprint(config)
    return all(gate.get(key) == value for key, value in fingerprint.items())


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


def process_tree_pids(root_pid: int) -> tuple[set[int], str | None]:
    if os.name == "nt":
        return {root_pid}, (
            "Process-tree enumeration is not implemented on Windows; only the "
            "main child process is sampled."
        )
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return {root_pid}, "/proc is unavailable; only the main process is sampled."
    parent_to_children: dict[int, set[int]] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        return {root_pid}, f"Unable to enumerate /proc: {error}"
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            close_paren = stat.rfind(")")
            fields = stat[close_paren + 2 :].split()
            parent_pid = int(fields[1])
            parent_to_children.setdefault(parent_pid, set()).add(int(entry.name))
        except (OSError, ValueError, IndexError):
            continue
    discovered = {root_pid}
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        for child in parent_to_children.get(parent, set()):
            if child not in discovered:
                discovered.add(child)
                pending.append(child)
    return discovered, None


def sample_process_tree_rss(root_pid: int) -> dict[str, Any]:
    pids, unsupported_reason = process_tree_pids(root_pid)
    main_rss = process_rss_bytes(root_pid)
    child_values = [
        value
        for pid in pids
        if pid != root_pid
        if (value := process_rss_bytes(pid)) is not None
    ]
    child_rss = sum(child_values) if unsupported_reason is None else None
    tree_rss = (
        (main_rss or 0) + sum(child_values)
        if unsupported_reason is None and main_rss is not None
        else None
    )
    return {
        "main_process_rss_bytes": main_rss,
        "child_process_rss_bytes": child_rss,
        "process_tree_rss_bytes": tree_rss,
        "sampled_process_count": len(pids),
        "support_status": (
            "supported" if unsupported_reason is None else "unsupported"
        ),
        "unsupported_reason": unsupported_reason,
        "measurement_method": (
            "/proc process-tree enumeration and VmRSS sampling"
            if os.name != "nt"
            else "Windows main-process working-set sampling"
        ),
    }


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


def unavailable_measurement(
    *,
    unit: str,
    scope: str,
    measurement_method: str,
    reason: str,
    status: str = "not_collected",
    aggregation: str = "single",
    parent_span: str | None = None,
    run_label: str | None = None,
    repeat_index: int | None = None,
) -> dict[str, Any]:
    return measurement(
        None,
        unit=unit,
        scope=scope,
        measurement_method=measurement_method,
        aggregation=aggregation,
        support_status=status,
        unsupported_reason=reason,
        parent_span=parent_span,
        run_label=run_label,
        repeat_index=repeat_index,
    )


def blocked_timing(reason: str) -> dict[str, Any]:
    runtime_wall = unavailable_measurement(
        unit="seconds",
        scope="runtime",
        measurement_method="time.perf_counter",
        reason=reason,
    )
    kernel = unavailable_measurement(
        unit="seconds",
        scope="runtime",
        measurement_method="torch.profiler/CUPTI (disabled)",
        reason=reason,
    )
    return {
        "cli_python_process_wall": unavailable_measurement(
            unit="seconds",
            scope="CLI Python process entry to process exit",
            measurement_method="external parent process required",
            reason=(
                "Exact process-exit duration cannot be written by the exiting "
                "process; use a parent launcher measurement."
            ),
        ),
        "cli_to_receipt_wall": runtime_wall,
        "runner_child_process_wall": runtime_wall,
        "instrumented_child_process_wall": runtime_wall,
        "setup_finalization_wall": runtime_wall,
        "unattributed_wall": runtime_wall,
        "model_load": {
            "wall": runtime_wall,
            "cuda_event_span": unavailable_measurement(
                unit="seconds",
                scope="model load",
                measurement_method="torch.cuda.Event elapsed_time",
                reason=reason,
            ),
            "gpu_kernel": kernel,
        },
        "runs": [],
        "span_relationships": [],
        "process_cuda_event_span": unavailable_measurement(
            unit="seconds",
            scope="model load and all repeated runs",
            measurement_method="sum of disjoint parent CUDA event spans",
            reason=reason,
            aggregation="sum",
        ),
        "process_gpu_kernel": kernel,
        "profiling_contract": {
            "official_wall_clock_eligible": True,
            "kernel_profiler_mode": "disabled",
            "overhead_disclosure": (
                "Kernel profiling was not started. torch.profiler/CUPTI runs "
                "must be separate from official wall-clock samples."
            ),
        },
    }


def blocked_resources(reason: str) -> dict[str, Any]:
    byte_metric = unavailable_measurement(
        unit="bytes",
        scope="runtime",
        measurement_method="runtime resource sampler",
        reason=reason,
        aggregation="max",
    )
    return {
        "process": {
            "peak_vram_allocated": byte_metric,
            "peak_vram_reserved": byte_metric,
            "final_current_vram_allocated": byte_metric,
            "final_current_vram_reserved": byte_metric,
            "nvidia_system_sampled_peak": unavailable_measurement(
                unit="MiB",
                scope="entire selected GPU",
                measurement_method="nvidia-smi sampled every configured interval",
                reason=reason,
                aggregation="sampled_max",
            ),
            "average_gpu_utilization": unavailable_measurement(
                unit="percent",
                scope="entire selected GPU",
                measurement_method="nvidia-smi sampled every configured interval",
                reason=reason,
                aggregation="sampled_mean",
            ),
        },
        "runs": [],
        "host_ram": {
            "main_process_peak_rss": byte_metric,
            "child_process_peak_rss": byte_metric,
            "process_tree_peak_rss": byte_metric,
        },
        "allocator": {
            "allocator_backend": None,
            "pytorch_alloc_conf": os.environ.get("PYTORCH_ALLOC_CONF"),
            "pytorch_cuda_alloc_conf_alias": os.environ.get(
                "PYTORCH_CUDA_ALLOC_CONF"
            ),
            "device_total_memory_bytes": None,
            "pool_statistics": None,
            "support_status": "not_collected",
            "unsupported_reason": reason,
            "measurement_method": "PyTorch allocator APIs and environment",
        },
    }


def blocked_receipt(
    config: dict[str, Any],
    prompt: dict[str, Any],
    preflight: dict[str, Any],
    settings: dict[str, Any],
    profile: str,
    command: list[str],
) -> dict[str, Any]:
    started = utc_now()
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "hiveframe.m0.run_receipt",
        "run_id": f"{profile}-{prompt['id']}-{prompt['seed']}",
        "status": "blocked",
        "partial": True,
        "profile": profile,
        **receipt_execution_classification(profile),
        "started_at": started,
        "finished_at": utc_now(),
        "backend": {
            "name": "wan21_t2v_1_3b_official",
            "code_repository": config["upstream"]["code_repository"],
            "code_revision": config["upstream"]["code_revision"],
            "model_id": config["model"]["repo_id"],
            "model_revision": config["model"]["revision"],
            "code_license": "Apache-2.0",
            "checkpoint_license": config["model"]["license"],
        },
        "sample": prompt,
        "settings": settings,
        "settings_hash": stable_hash({"sample": prompt, "settings": settings}),
        "configuration_hash": gate_fingerprint(config)["config_hash"],
        "command": command,
        "timing": blocked_timing(
            "Execution was blocked before model load; runtime measurements do not exist."
        ),
        "resources": blocked_resources(
            "Execution was blocked before model load; runtime measurements do not exist."
        ),
        "artifacts": {},
        "environment": preflight["environment"],
        "preflight": {
            "ready": False,
            "blockers": preflight["blockers"],
            "warnings": preflight["warnings"],
        },
        "unsupported_metrics": {
            "all_runtime_metrics": (
                "Execution was blocked before model load; runtime measurements "
                "do not exist."
            ),
            "vae_encode": "Text-to-video has no input VAE encode stage.",
        },
        "error": {
            "type": "PreflightBlocked",
            "message": "; ".join(item["message"] for item in preflight["blockers"]),
        },
    }


def support_record_measurement(
    record: dict[str, Any] | None,
    *,
    scope: str,
    aggregation: str,
    parent_span: str | None,
    run_label: str | None = None,
    repeat_index: int | None = None,
) -> dict[str, Any]:
    if not record:
        return unavailable_measurement(
            unit="seconds",
            scope=scope,
            measurement_method="torch.profiler/CUPTI",
            reason="The instrumentation did not provide a kernel profiler record.",
            aggregation=aggregation,
            parent_span=parent_span,
            run_label=run_label,
            repeat_index=repeat_index,
        )
    status = str(record.get("support_status", "not_collected"))
    value = record.get("value")
    reason = record.get("unsupported_reason")
    return measurement(
        float(value) if value is not None else None,
        unit=str(record.get("unit", "seconds")),
        scope=scope,
        measurement_method=str(
            record.get("measurement_method", "torch.profiler/CUPTI")
        ),
        aggregation=aggregation,
        support_status=status,
        unsupported_reason=str(reason) if reason is not None else None,
        parent_span=parent_span,
        run_label=run_label,
        repeat_index=repeat_index,
    )


def timing_from_instrumentation(
    instrumentation: dict[str, Any] | None,
    wall_seconds: float | None,
    *,
    cli_observed_seconds: float | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    unsupported: dict[str, str] = {
        "vae_encode": "Text-to-video has no input VAE encode stage.",
        "scheduler_overhead": (
            "The official scheduler step is included in each denoising step; "
            "scheduler-only time is not isolated by this non-invasive hook."
        ),
    }
    runner_wall = (
        measurement(
            wall_seconds,
            unit="seconds",
            scope="parent runner from child process start through observed exit",
            measurement_method="time.perf_counter around subprocess.Popen/poll",
            aggregation="single",
            parent_span="cli_python_process",
        )
        if wall_seconds is not None
        else unavailable_measurement(
            unit="seconds",
            scope="parent runner from child process start through observed exit",
            measurement_method="time.perf_counter around subprocess.Popen/poll",
            reason="The child process did not start.",
            parent_span="cli_python_process",
        )
    )
    timing: dict[str, Any] = {
        "cli_python_process_wall": unavailable_measurement(
            unit="seconds",
            scope="CLI Python process entry to process exit",
            measurement_method="external parent process required",
            reason=(
                "The exiting Python process cannot persist an exact post-exit "
                "duration. Windows shell and WSL startup are also outside scope."
            ),
            parent_span=None,
        ),
        "cli_to_receipt_wall": (
            measurement(
                cli_observed_seconds,
                unit="seconds",
                scope="CLI main entry through receipt assembly",
                measurement_method="time.perf_counter",
                aggregation="single",
                parent_span="cli_python_process",
            )
            if cli_observed_seconds is not None
            else unavailable_measurement(
                unit="seconds",
                scope="CLI main entry through receipt assembly",
                measurement_method="time.perf_counter",
                reason="The command was invoked without a CLI entry timestamp.",
                parent_span="cli_python_process",
            )
        ),
        "runner_child_process_wall": runner_wall,
        "instrumented_child_process_wall": unavailable_measurement(
            unit="seconds",
            scope="instrumented Wan child process",
            measurement_method="time.perf_counter in child",
            reason="Instrumentation was unavailable.",
            parent_span="runner_child_process",
        ),
        "setup_finalization_wall": unavailable_measurement(
            unit="seconds",
            scope="instrumented child outside model load and repeated runs",
            measurement_method="derived non-overlapping remainder",
            reason="Instrumentation was unavailable.",
            aggregation="derived_union_remainder",
            parent_span="instrumented_child_process",
        ),
        "unattributed_wall": unavailable_measurement(
            unit="seconds",
            scope="parent runner outside instrumented child lifetime",
            measurement_method="derived non-overlapping remainder",
            reason="Instrumentation was unavailable.",
            aggregation="derived_union_remainder",
            parent_span="runner_child_process",
        ),
        "model_load": {},
        "runs": [],
        "span_relationships": [],
        "profiling_contract": {
            "official_wall_clock_eligible": True,
            "kernel_profiler_mode": "unknown",
            "overhead_disclosure": (
                "Kernel profiling runs carry torch.profiler/CUPTI overhead and "
                "must be separate from official wall-clock samples."
            ),
        },
    }
    if not instrumentation:
        unsupported["instrumentation"] = (
            "The instrumented child process did not produce a metrics file."
        )
        timing["model_load"] = {
            "wall": unavailable_measurement(
                unit="seconds",
                scope="model load",
                measurement_method="time.perf_counter",
                reason="Instrumentation was unavailable.",
                parent_span="instrumented_child_process",
            ),
            "cuda_event_span": unavailable_measurement(
                unit="seconds",
                scope="model load",
                measurement_method="torch.cuda.Event elapsed_time",
                reason="Instrumentation was unavailable.",
                parent_span="instrumented_child_process",
            ),
            "gpu_kernel": unavailable_measurement(
                unit="seconds",
                scope="model load",
                measurement_method="torch.profiler/CUPTI",
                reason="Instrumentation was unavailable.",
                parent_span="instrumented_child_process",
            ),
        }
        timing["process_cuda_event_span"] = unavailable_measurement(
            unit="seconds",
            scope="model load and all repeated runs",
            measurement_method="sum of disjoint parent CUDA event spans",
            reason="Instrumentation was unavailable.",
            aggregation="sum",
        )
        timing["process_gpu_kernel"] = unavailable_measurement(
            unit="seconds",
            scope="model load and all repeated runs",
            measurement_method="torch.profiler/CUPTI",
            reason="Instrumentation was unavailable.",
            aggregation="sum",
        )
        return timing, unsupported

    child_total_value = instrumentation.get("total_wall_seconds")
    child_total = (
        float(child_total_value) if child_total_value is not None else None
    )
    timing["instrumented_child_process_wall"] = (
        measurement(
            child_total,
            unit="seconds",
            scope="instrumented child entry through metrics finalization",
            measurement_method="time.perf_counter in child",
            aggregation="single",
            parent_span="runner_child_process",
        )
        if child_total is not None
        else unavailable_measurement(
            unit="seconds",
            scope="instrumented child entry through metrics finalization",
            measurement_method="time.perf_counter in child",
            reason="Child instrumentation omitted total_wall_seconds.",
            parent_span="runner_child_process",
        )
    )
    runner_unattributed = (
        nonnegative_remainder(wall_seconds, [child_total])
        if wall_seconds is not None and child_total is not None
        else None
    )
    timing["unattributed_wall"] = (
        measurement(
            runner_unattributed,
            unit="seconds",
            scope="parent runner outside instrumented child lifetime",
            measurement_method="runner wall minus instrumented child wall",
            aggregation="derived_union_remainder",
            parent_span="runner_child_process",
        )
        if runner_unattributed is not None
        else unavailable_measurement(
            unit="seconds",
            scope="parent runner outside instrumented child lifetime",
            measurement_method="runner wall minus instrumented child wall",
            reason=(
                "Runner or instrumented-child wall timing was omitted."
            ),
            aggregation="derived_union_remainder",
            parent_span="runner_child_process",
        )
    )

    model_load = instrumentation.get("model_load", {})
    model_wall_value = model_load.get("model_load_wall_seconds")
    model_wall = (
        float(model_wall_value) if model_wall_value is not None else None
    )
    model_cuda_value = model_load.get(
        "model_load_cuda_event_span_seconds",
        model_load.get("model_load_cuda_seconds"),
    )
    model_cuda = (
        float(model_cuda_value) if model_cuda_value is not None else None
    )
    timing["model_load"] = {
        "wall": (
            measurement(
                model_wall,
                unit="seconds",
                scope="one pipeline/model construction per child process",
                measurement_method="time.perf_counter",
                aggregation="single",
                parent_span="instrumented_child_process",
            )
            if model_wall is not None
            else unavailable_measurement(
                unit="seconds",
                scope="one pipeline/model construction per child process",
                measurement_method="time.perf_counter",
                reason="Model-load wall timing was not produced.",
                parent_span="instrumented_child_process",
            )
        ),
        "cuda_event_span": (
            measurement(
                model_cuda,
                unit="seconds",
                scope="CUDA event span around pipeline/model construction",
                measurement_method="torch.cuda.Event elapsed_time / 1000",
                aggregation="single",
                parent_span="instrumented_child_process",
            )
            if model_cuda is not None
            else unavailable_measurement(
                unit="seconds",
                scope="CUDA event span around pipeline/model construction",
                measurement_method="torch.cuda.Event elapsed_time / 1000",
                reason="CUDA events were unavailable.",
                parent_span="instrumented_child_process",
            )
        ),
        "gpu_kernel": support_record_measurement(
            model_load.get("gpu_kernel_seconds"),
            scope="model load CUDA kernels",
            aggregation="sum",
            parent_span="model_load",
        ),
    }
    cuda_parent_values = [model_cuda] if model_cuda is not None else []
    cuda_parent_spans_complete = model_cuda is not None
    kernel_parent_metrics = [timing["model_load"]["gpu_kernel"]]
    run_wall_values: list[float] = []
    for repeat_index, run in enumerate(instrumentation.get("runs", [])):
        label = str(run.get("label") or f"repeat_{repeat_index}")
        recorded_repeat_index = int(run.get("repeat_index", repeat_index))
        run_span = f"run:{label}"
        generation_span = f"generation:{label}"
        prompt_calls = run.get("prompt_encode_calls", [])
        prompt_wall_values = [
            item.get("encode_wall_seconds") for item in prompt_calls
        ]
        prompt_wall = (
            sum(float(value) for value in prompt_wall_values)
            if prompt_wall_values
            and all(value is not None for value in prompt_wall_values)
            else None
        )
        prompt_cuda_values = [
            item.get(
                "encode_cuda_event_span_seconds",
                item.get("encode_cuda_seconds"),
            )
            for item in prompt_calls
        ]
        prompt_cuda = (
            sum(float(value) for value in prompt_cuda_values)
            if prompt_cuda_values and all(value is not None for value in prompt_cuda_values)
            else None
        )
        steps = run.get("denoising_steps", [])
        denoising_wall_values = [
            item.get("step_wall_seconds") for item in steps
        ]
        denoising_wall = (
            sum(float(value) for value in denoising_wall_values)
            if denoising_wall_values
            and all(value is not None for value in denoising_wall_values)
            else None
        )
        step_cuda_values = [
            item.get(
                "step_cuda_event_span_seconds",
                item.get("step_cuda_seconds"),
            )
            for item in steps
        ]
        denoising_cuda = (
            sum(float(value) for value in step_cuda_values)
            if step_cuda_values and all(value is not None for value in step_cuda_values)
            else None
        )
        generation_wall_value = run.get("generation_wall_seconds")
        generation_wall = (
            float(generation_wall_value)
            if generation_wall_value is not None
            else None
        )
        vae_wall_value = run.get("vae_decode_wall_seconds")
        vae_wall = (
            float(vae_wall_value) if vae_wall_value is not None else None
        )
        generation_cuda_value = run.get(
            "generation_cuda_event_span_seconds",
            run.get("generation_cuda_seconds"),
        )
        generation_cuda = (
            float(generation_cuda_value)
            if generation_cuda_value is not None
            else None
        )
        vae_cuda_value = run.get(
            "vae_decode_cuda_event_span_seconds",
            run.get("vae_decode_cuda_seconds"),
        )
        vae_cuda = (
            float(vae_cuda_value) if vae_cuda_value is not None else None
        )
        video_encode_wall_value = run.get("video_encode_wall_seconds")
        video_encode_wall = (
            float(video_encode_wall_value)
            if video_encode_wall_value is not None
            else None
        )
        video_encode_cuda_value = run.get(
            "video_encode_cuda_event_span_seconds",
            run.get("video_encode_cuda_seconds"),
        )
        video_encode_cuda = (
            float(video_encode_cuda_value)
            if video_encode_cuda_value is not None
            else None
        )
        run_wall_value = run.get("run_wall_seconds")
        run_wall = (
            float(run_wall_value)
            if run_wall_value is not None
            else (
                (generation_wall or 0.0) + (video_encode_wall or 0.0)
                if generation_wall is not None or video_encode_wall is not None
                else None
            )
        )
        if run_wall is not None:
            run_wall_values.append(run_wall)
        generation_unattributed = (
            nonnegative_remainder(
                generation_wall, [prompt_wall, denoising_wall, vae_wall]
            )
            if all(
                value is not None
                for value in (
                    generation_wall,
                    prompt_wall,
                    denoising_wall,
                    vae_wall,
                )
            )
            else None
        )
        run_unattributed = (
            nonnegative_remainder(
                run_wall, [generation_wall, video_encode_wall]
            )
            if all(
                value is not None
                for value in (run_wall, generation_wall, video_encode_wall)
            )
            else None
        )
        if generation_cuda is not None:
            cuda_parent_values.append(generation_cuda)
        else:
            cuda_parent_spans_complete = False
        if video_encode_cuda is not None:
            cuda_parent_values.append(video_encode_cuda)
        else:
            cuda_parent_spans_complete = False
        generation_kernel = support_record_measurement(
            run.get("gpu_kernel_seconds"),
            scope=f"{label} generation CUDA kernels",
            aggregation="sum",
            parent_span=generation_span,
            run_label=label,
            repeat_index=recorded_repeat_index,
        )
        video_kernel = support_record_measurement(
            run.get("video_encode_gpu_kernel_seconds"),
            scope=f"{label} MP4 preprocessing CUDA kernels",
            aggregation="sum",
            parent_span=f"video_encode:{label}",
            run_label=label,
            repeat_index=recorded_repeat_index,
        )
        kernel_parent_metrics.extend((generation_kernel, video_kernel))
        prompt_call_receipts = []
        for call_index, call in enumerate(prompt_calls):
            call_label = str(call.get("label", f"call_{call_index + 1}"))
            call_wall_value = call.get("encode_wall_seconds")
            call_cuda_value = call.get(
                "encode_cuda_event_span_seconds",
                call.get("encode_cuda_seconds"),
            )
            prompt_call_receipts.append(
                {
                    "label": call_label,
                    "wall": measurement(
                        float(call_wall_value),
                        unit="seconds",
                        scope=f"{label} prompt encode call {call_label}",
                        measurement_method="time.perf_counter",
                        aggregation="single",
                        parent_span=f"prompt_encode:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if call_wall_value is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} prompt encode call {call_label}",
                        measurement_method="time.perf_counter",
                        reason="Prompt encode call wall timing was omitted.",
                        parent_span=f"prompt_encode:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "cuda_event_span": measurement(
                        float(call_cuda_value),
                        unit="seconds",
                        scope=f"{label} prompt encode call {call_label}",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        aggregation="single",
                        parent_span=f"prompt_encode:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if call_cuda_value is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} prompt encode call {call_label}",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        reason="CUDA event timing was unavailable.",
                        parent_span=f"prompt_encode:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                }
            )
        step_receipts = []
        for step_index, step in enumerate(steps):
            step_label = int(step.get("index", step_index))
            step_wall_value = step.get("step_wall_seconds")
            step_cuda_value = step.get(
                "step_cuda_event_span_seconds",
                step.get("step_cuda_seconds"),
            )
            step_receipts.append(
                {
                    "index": step_label,
                    "model_forward_calls": int(
                        step.get("model_forward_calls", 0)
                    ),
                    "wall": measurement(
                        float(step_wall_value),
                        unit="seconds",
                        scope=f"{label} denoising step {step_label}",
                        measurement_method="time.perf_counter",
                        aggregation="single",
                        parent_span=f"denoising:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if step_wall_value is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} denoising step {step_label}",
                        measurement_method="time.perf_counter",
                        reason="Step wall timing was omitted.",
                        parent_span=f"denoising:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "cuda_event_span": measurement(
                        float(step_cuda_value),
                        unit="seconds",
                        scope=f"{label} denoising step {step_label}",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        aggregation="single",
                        parent_span=f"denoising:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if step_cuda_value is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} denoising step {step_label}",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        reason="CUDA event timing was unavailable.",
                        parent_span=f"denoising:{label}",
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                }
            )
        timing["runs"].append(
            {
                "label": label,
                "repeat_index": recorded_repeat_index,
                "run_wall": measurement(
                    run_wall,
                    unit="seconds",
                    scope=f"{label} repeated run including MP4 encode",
                    measurement_method="time.perf_counter",
                    aggregation="single",
                    parent_span="instrumented_child_process",
                    run_label=label,
                    repeat_index=recorded_repeat_index,
                )
                if run_wall is not None
                else unavailable_measurement(
                    unit="seconds",
                    scope=f"{label} repeated run including MP4 encode",
                    measurement_method="time.perf_counter",
                    reason="Run wall timing was omitted.",
                    parent_span="instrumented_child_process",
                    run_label=label,
                    repeat_index=recorded_repeat_index,
                ),
                "unattributed_wall": measurement(
                    run_unattributed,
                    unit="seconds",
                    scope=f"{label} run outside generation and MP4 encode",
                    measurement_method="derived non-overlapping remainder",
                    aggregation="derived_union_remainder",
                    parent_span=run_span,
                    run_label=label,
                    repeat_index=recorded_repeat_index,
                )
                if run_unattributed is not None
                else unavailable_measurement(
                    unit="seconds",
                    scope=f"{label} run outside generation and MP4 encode",
                    measurement_method="derived non-overlapping remainder",
                    reason="Run wall timing was omitted.",
                    aggregation="derived_union_remainder",
                    parent_span=run_span,
                    run_label=label,
                    repeat_index=recorded_repeat_index,
                ),
                "prompt_encode": {
                    "wall": (
                        measurement(
                            prompt_wall,
                            unit="seconds",
                            scope=f"{label} positive and negative prompt calls",
                            measurement_method=(
                                "sum of non-overlapping call wall spans"
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                        if prompt_wall is not None
                        else unavailable_measurement(
                            unit="seconds",
                            scope=f"{label} positive and negative prompt calls",
                            measurement_method=(
                                "sum of non-overlapping call wall spans"
                            ),
                            reason=(
                                "One or more prompt wall spans are missing."
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                    "cuda_event_span": (
                        measurement(
                            prompt_cuda,
                            unit="seconds",
                            scope=f"{label} positive and negative prompt calls",
                            measurement_method=(
                                "sum of torch.cuda.Event elapsed_time / 1000"
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                        if prompt_cuda is not None
                        else unavailable_measurement(
                            unit="seconds",
                            scope=f"{label} positive and negative prompt calls",
                            measurement_method=(
                                "sum of torch.cuda.Event elapsed_time / 1000"
                            ),
                            reason="One or more prompt CUDA event spans are missing.",
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                    "calls": prompt_call_receipts,
                },
                "denoising": {
                    "wall": (
                        measurement(
                            denoising_wall,
                            unit="seconds",
                            scope=f"{label} denoising steps",
                            measurement_method=(
                                "sum of non-overlapping step wall spans"
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                        if denoising_wall is not None
                        else unavailable_measurement(
                            unit="seconds",
                            scope=f"{label} denoising steps",
                            measurement_method=(
                                "sum of non-overlapping step wall spans"
                            ),
                            reason=(
                                "One or more denoising step wall spans are missing."
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                    "cuda_event_span": (
                        measurement(
                            denoising_cuda,
                            unit="seconds",
                            scope=f"{label} denoising steps",
                            measurement_method=(
                                "sum of torch.cuda.Event elapsed_time / 1000"
                            ),
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                        if denoising_cuda is not None
                        else unavailable_measurement(
                            unit="seconds",
                            scope=f"{label} denoising steps",
                            measurement_method=(
                                "sum of torch.cuda.Event elapsed_time / 1000"
                            ),
                            reason="One or more step CUDA event spans are missing.",
                            aggregation="sum",
                            parent_span=generation_span,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                    "steps": step_receipts,
                },
                "vae_decode": {
                    "wall": measurement(
                        vae_wall,
                        unit="seconds",
                        scope=f"{label} VAE decode",
                        measurement_method="time.perf_counter",
                        aggregation="single",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if vae_wall is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} VAE decode",
                        measurement_method="time.perf_counter",
                        reason="VAE decode wall timing was omitted.",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "cuda_event_span": measurement(
                        vae_cuda,
                        unit="seconds",
                        scope=f"{label} VAE decode",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        aggregation="single",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if vae_cuda is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} VAE decode",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        reason="VAE CUDA event timing was unavailable.",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                },
                "generation": {
                    "wall": measurement(
                        generation_wall,
                        unit="seconds",
                        scope=f"{label} pipeline.generate call",
                        measurement_method="time.perf_counter",
                        aggregation="single",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if generation_wall is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} pipeline.generate call",
                        measurement_method="time.perf_counter",
                        reason="Generation wall timing was omitted.",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "cuda_event_span": measurement(
                        generation_cuda,
                        unit="seconds",
                        scope=f"{label} pipeline.generate CUDA event span",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        aggregation="single",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if generation_cuda is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} pipeline.generate CUDA event span",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        reason="Generation CUDA event timing was unavailable.",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "gpu_kernel": generation_kernel,
                    "unattributed_wall": measurement(
                        generation_unattributed,
                        unit="seconds",
                        scope=f"{label} generation outside prompt, steps, and VAE",
                        measurement_method="derived non-overlapping remainder",
                        aggregation="derived_union_remainder",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if generation_unattributed is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} generation outside prompt, steps, and VAE",
                        measurement_method="derived non-overlapping remainder",
                        reason="Generation wall timing was omitted.",
                        aggregation="derived_union_remainder",
                        parent_span=generation_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                },
                "video_encode": {
                    "wall": measurement(
                        video_encode_wall,
                        unit="seconds",
                        scope=f"{label} tensor preprocessing and MP4 encoding",
                        measurement_method="time.perf_counter",
                        aggregation="single",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if video_encode_wall is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} tensor preprocessing and MP4 encoding",
                        measurement_method="time.perf_counter",
                        reason="MP4 encode wall timing was omitted.",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "cuda_event_span": measurement(
                        video_encode_cuda,
                        unit="seconds",
                        scope=f"{label} MP4 preprocessing CUDA event span",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        aggregation="single",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    )
                    if video_encode_cuda is not None
                    else unavailable_measurement(
                        unit="seconds",
                        scope=f"{label} MP4 preprocessing CUDA event span",
                        measurement_method="torch.cuda.Event elapsed_time / 1000",
                        reason="MP4 CUDA event timing was unavailable.",
                        parent_span=run_span,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "gpu_kernel": video_kernel,
                },
            }
        )
        timing["span_relationships"].extend(
            [
                {"parent": "instrumented_child_process", "child": run_span},
                {"parent": run_span, "child": generation_span},
                {"parent": generation_span, "child": f"prompt_encode:{label}"},
                {"parent": generation_span, "child": f"denoising:{label}"},
                {"parent": generation_span, "child": f"vae_decode:{label}"},
                {"parent": run_span, "child": f"video_encode:{label}"},
            ]
        )

    expected_run_count = len(instrumentation.get("runs", []))
    setup_finalization = (
        nonnegative_remainder(child_total, [model_wall] + run_wall_values)
        if child_total is not None
        and model_wall is not None
        and len(run_wall_values) == expected_run_count
        else None
    )
    timing["setup_finalization_wall"] = (
        measurement(
            setup_finalization,
            unit="seconds",
            scope="instrumented child outside model load and repeated runs",
            measurement_method="derived non-overlapping remainder",
            aggregation="derived_union_remainder",
            parent_span="instrumented_child_process",
        )
        if setup_finalization is not None
        else unavailable_measurement(
            unit="seconds",
            scope="instrumented child outside model load and repeated runs",
            measurement_method="derived non-overlapping remainder",
            reason="Instrumented child total wall timing was omitted.",
            aggregation="derived_union_remainder",
            parent_span="instrumented_child_process",
        )
    )
    timing["span_relationships"].extend(
        [
            {
                "parent": "runner_child_process",
                "child": "instrumented_child_process",
            },
            {
                "parent": "instrumented_child_process",
                "child": "model_load",
            },
        ]
    )
    timing["process_cuda_event_span"] = (
        measurement(
            sum(cuda_parent_values),
            unit="seconds",
            scope="model load, generation, and MP4 parent event spans",
            measurement_method="sum of disjoint parent CUDA event spans",
            aggregation="sum",
        )
        if cuda_parent_spans_complete
        else unavailable_measurement(
            unit="seconds",
            scope="model load, generation, and MP4 parent event spans",
            measurement_method="sum of disjoint parent CUDA event spans",
            reason=(
                "One or more model-load, generation, or MP4 parent CUDA "
                "event spans were unavailable; a partial sum is not reported."
            ),
            aggregation="sum",
        )
    )
    kernel_values = [
        float(item["value"])
        for item in kernel_parent_metrics
        if item["support_status"] == "supported" and item["value"] is not None
    ]
    all_kernel_supported = bool(kernel_parent_metrics) and all(
        item["support_status"] == "supported"
        for item in kernel_parent_metrics
    )
    timing["process_gpu_kernel"] = (
        measurement(
            sum(kernel_values),
            unit="seconds",
            scope="model load and all repeated-run profiled CUDA kernels",
            measurement_method="sum of torch.profiler/CUPTI stage totals",
            aggregation="sum",
        )
        if all_kernel_supported
        else unavailable_measurement(
            unit="seconds",
            scope="model load and all repeated-run profiled CUDA kernels",
            measurement_method="torch.profiler/CUPTI",
            reason=(
                "Kernel profiler was disabled, unsupported, or incomplete. "
                "Official wall-clock runs intentionally do not collect it."
            ),
            aggregation="sum",
        )
    )
    profiler_contract = instrumentation.get("kernel_profiler", {})
    timing["profiling_contract"] = {
        "official_wall_clock_eligible": bool(
            profiler_contract.get("official_wall_clock_eligible", True)
        ),
        "kernel_profiler_mode": str(
            profiler_contract.get("mode", "disabled")
        ),
        "overhead_disclosure": str(
            profiler_contract.get(
                "overhead_disclosure",
                "torch.profiler/CUPTI adds measurement overhead.",
            )
        ),
    }
    if not cuda_parent_spans_complete:
        unsupported["cuda_event_span"] = (
            "One or more required parent CUDA event spans were unavailable."
        )
    return timing, unsupported


def allocator_byte_measurement(
    value: Any,
    *,
    scope: str,
    aggregation: str,
    parent_span: str | None = None,
    run_label: str | None = None,
    repeat_index: int | None = None,
    reason: str = "PyTorch allocator did not provide this statistic.",
) -> dict[str, Any]:
    return (
        measurement(
            int(value),
            unit="bytes",
            scope=scope,
            measurement_method="PyTorch CUDA caching allocator",
            aggregation=aggregation,
            parent_span=parent_span,
            run_label=run_label,
            repeat_index=repeat_index,
        )
        if value is not None
        else unavailable_measurement(
            unit="bytes",
            scope=scope,
            measurement_method="PyTorch CUDA caching allocator",
            reason=reason,
            aggregation=aggregation,
            parent_span=parent_span,
            run_label=run_label,
            repeat_index=repeat_index,
        )
    )


def resources_from_instrumentation(
    instrumentation: dict[str, Any] | None,
    *,
    peak_main_rss: int | None,
    peak_child_rss: int | None,
    peak_tree_rss: int | None,
    process_tree_support_status: str,
    process_tree_unsupported_reason: str | None,
    peak_gpu_memory_mib: int | None,
    gpu_utilization_samples: list[int],
) -> dict[str, Any]:
    process_memory = (
        instrumentation.get("process_memory", {}) if instrumentation else {}
    )
    unavailable_runtime = (
        "The instrumented child did not provide allocator measurements."
    )
    process = {
        "peak_vram_allocated": allocator_byte_measurement(
            process_memory.get("process_peak_allocated_bytes"),
            scope="model load and all repeated runs in one process",
            aggregation="max_across_allocator_reset_windows",
            reason=unavailable_runtime,
        ),
        "peak_vram_reserved": allocator_byte_measurement(
            process_memory.get("process_peak_reserved_bytes"),
            scope=(
                "model load and all repeated runs; caching-allocator high-water "
                "mark, not asserted as simultaneous physical residency"
            ),
            aggregation="max_across_allocator_reset_windows",
            reason=unavailable_runtime,
        ),
        "final_current_vram_allocated": allocator_byte_measurement(
            process_memory.get("final_current_allocated_bytes"),
            scope="instrumented process after all repeated runs",
            aggregation="single",
            reason=unavailable_runtime,
        ),
        "final_current_vram_reserved": allocator_byte_measurement(
            process_memory.get("final_current_reserved_bytes"),
            scope=(
                "instrumented process after all repeated runs; allocator-managed "
                "memory, not physical-residency proof"
            ),
            aggregation="single",
            reason=unavailable_runtime,
        ),
        "nvidia_system_sampled_peak": (
            measurement(
                peak_gpu_memory_mib,
                unit="MiB",
                scope="entire selected GPU, including other processes",
                measurement_method=(
                    "nvidia-smi memory.used sampled every configured interval"
                ),
                aggregation="sampled_max",
            )
            if peak_gpu_memory_mib is not None
            else unavailable_measurement(
                unit="MiB",
                scope="entire selected GPU, including other processes",
                measurement_method=(
                    "nvidia-smi memory.used sampled every configured interval"
                ),
                reason="No supported NVIDIA memory sample was collected.",
                aggregation="sampled_max",
            )
        ),
        "average_gpu_utilization": (
            measurement(
                sum(gpu_utilization_samples) / len(gpu_utilization_samples),
                unit="percent",
                scope="entire selected GPU over parent runner sampling window",
                measurement_method=(
                    "nvidia-smi utilization.gpu sampled every configured interval"
                ),
                aggregation="sampled_mean",
            )
            if gpu_utilization_samples
            else unavailable_measurement(
                unit="percent",
                scope="entire selected GPU over parent runner sampling window",
                measurement_method=(
                    "nvidia-smi utilization.gpu sampled every configured interval"
                ),
                reason="No supported NVIDIA utilization sample was collected.",
                aggregation="sampled_mean",
            )
        ),
    }
    run_resources = []
    if instrumentation:
        for repeat_index, run in enumerate(instrumentation.get("runs", [])):
            label = str(run.get("label") or f"repeat_{repeat_index}")
            recorded_repeat_index = int(run.get("repeat_index", repeat_index))
            memory = run.get("memory", {})
            parent = f"generation:{label}"
            run_resources.append(
                {
                    "label": label,
                    "repeat_index": recorded_repeat_index,
                    "generation_peak_vram_allocated": allocator_byte_measurement(
                        memory.get("peak_allocated_bytes"),
                        scope=f"{label} generation allocator reset window",
                        aggregation="max",
                        parent_span=parent,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "generation_peak_vram_reserved": allocator_byte_measurement(
                        memory.get("peak_reserved_bytes"),
                        scope=(
                            f"{label} generation allocator reset window; "
                            "allocator-managed memory, not physical-residency proof"
                        ),
                        aggregation="max",
                        parent_span=parent,
                        run_label=label,
                        repeat_index=recorded_repeat_index,
                    ),
                    "generation_end_current_vram_allocated": (
                        allocator_byte_measurement(
                            memory.get("current_allocated_bytes"),
                            scope=f"{label} immediately after generation",
                            aggregation="single",
                            parent_span=parent,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                    "generation_end_current_vram_reserved": (
                        allocator_byte_measurement(
                            memory.get("current_reserved_bytes"),
                            scope=(
                                f"{label} immediately after generation; "
                                "allocator-managed memory"
                            ),
                            aggregation="single",
                            parent_span=parent,
                            run_label=label,
                            repeat_index=recorded_repeat_index,
                        )
                    ),
                }
            )
    main_metric = (
        measurement(
            peak_main_rss,
            unit="bytes",
            scope="main instrumented child process only",
            measurement_method="periodic VmRSS/working-set sampling",
            aggregation="sampled_max",
        )
        if peak_main_rss is not None
        else unavailable_measurement(
            unit="bytes",
            scope="main instrumented child process only",
            measurement_method="periodic VmRSS/working-set sampling",
            reason="Main process RSS samples were unavailable.",
            aggregation="sampled_max",
        )
    )
    if (
        process_tree_support_status == "supported"
        and (peak_child_rss is None or peak_tree_rss is None)
    ):
        process_tree_support_status = "not_collected"
        process_tree_unsupported_reason = (
            "No complete descendant/tree RSS sample was collected."
        )
    if process_tree_support_status == "supported":
        child_metric = measurement(
            peak_child_rss,
            unit="bytes",
            scope="all descendants of the main instrumented child",
            measurement_method="/proc process-tree VmRSS aggregation",
            aggregation="sampled_max",
        )
        tree_metric = (
            measurement(
                peak_tree_rss,
                unit="bytes",
                scope="main instrumented child and all descendants",
                measurement_method="/proc process-tree VmRSS aggregation",
                aggregation="sampled_max",
            )
            if peak_tree_rss is not None
            else unavailable_measurement(
                unit="bytes",
                scope="main instrumented child and all descendants",
                measurement_method="/proc process-tree VmRSS aggregation",
                reason="Process-tree samples unexpectedly had no aggregate value.",
                aggregation="sampled_max",
            )
        )
    else:
        reason = process_tree_unsupported_reason or (
            "Process-tree RSS aggregation is unsupported on this platform."
        )
        unsupported_status = (
            process_tree_support_status
            if process_tree_support_status
            in {"unsupported", "not_collected", "not_applicable"}
            else "unsupported"
        )
        child_metric = unavailable_measurement(
            unit="bytes",
            scope="all descendants of the main instrumented child",
            measurement_method="process-tree RSS aggregation",
            reason=reason,
            status=unsupported_status,
            aggregation="sampled_max",
        )
        tree_metric = unavailable_measurement(
            unit="bytes",
            scope="main instrumented child and all descendants",
            measurement_method="process-tree RSS aggregation",
            reason=reason,
            status=unsupported_status,
            aggregation="sampled_max",
        )
    allocator = (
        instrumentation.get("allocator_environment", {})
        if instrumentation
        else {}
    )
    allocator_unsupported = allocator.get("unsupported", {})
    return {
        "process": process,
        "runs": run_resources,
        "host_ram": {
            "main_process_peak_rss": main_metric,
            "child_process_peak_rss": child_metric,
            "process_tree_peak_rss": tree_metric,
        },
        "allocator": {
            "allocator_backend": allocator.get("allocator_backend"),
            "pytorch_alloc_conf": allocator.get("pytorch_alloc_conf"),
            "pytorch_cuda_alloc_conf_alias": allocator.get(
                "pytorch_cuda_alloc_conf_alias"
            ),
            "device_total_memory_bytes": allocator.get(
                "device_total_memory_bytes"
            ),
            "pool_statistics": allocator.get("pool_statistics"),
            "support_status": (
                "supported"
                if allocator and not allocator_unsupported
                else "unsupported"
                if allocator
                else "not_collected"
            ),
            "unsupported_reason": (
                "; ".join(
                    f"{key}: {value}"
                    for key, value in allocator_unsupported.items()
                )
                if allocator_unsupported
                else None
                if allocator
                else unavailable_runtime
            ),
            "measurement_method": str(
                allocator.get(
                    "measurement_method",
                    "PyTorch allocator APIs and process environment",
                )
            ),
            "scope": str(
                allocator.get(
                    "scope",
                    "selected CUDA device in the instrumented process",
                )
            ),
        },
    }


def run_sample(
    config: dict[str, Any],
    prompt: dict[str, Any],
    output_dir: Path,
    *,
    profile: str,
    repeat: int | None = None,
    run_id: str | None = None,
    kernel_profiler: str = "disabled",
    cli_started_perf: float | None = None,
) -> tuple[int, dict[str, Any]]:
    settings = settings_for_profile(config, profile, repeat=repeat)
    run_id = validate_run_id(
        run_id or f"{profile}-{prompt['id']}-{prompt['seed']}"
    )
    output_prefix = output_dir / run_id
    metrics_path = output_dir / f"{run_id}.instrumentation.json"
    stdout_path = output_dir / f"{run_id}.stdout.log"
    stderr_path = output_dir / f"{run_id}.stderr.log"
    receipt_path = output_dir / f"{run_id}.receipt.json"
    spec = Wan21RunSpec(
        prompt=prompt["intent"],
        negative_prompt=settings["negative_prompt"],
        seed=int(prompt["seed"]),
        output_prefix=output_prefix,
        metrics_path=metrics_path,
        size=settings["size"],
        frame_num=int(settings["frame_num"]),
        fps=int(settings["fps"]),
        sample_steps=int(settings["sample_steps"]),
        sample_shift=float(settings["sample_shift"]),
        sample_guide_scale=float(settings["sample_guide_scale"]),
        sample_solver=settings["sample_solver"],
        dtype=settings["dtype"],
        device=settings["device"],
        offload_model=bool(settings["offload_model"]),
        t5_cpu=bool(settings["t5_cpu"]),
        repeat=int(settings["repeat"]),
        kernel_profiler=str(settings.get("kernel_profiler", kernel_profiler)),
    )
    command = build_generate_command(
        python_executable=Path(sys.executable),
        driver_path=ROOT / "python" / "hive_hooks" / "wan21_m0_instrumented.py",
        code_dir=project_path(config["backend"]["code_dir"]),
        checkpoint_dir=project_path(config["model"]["local_dir"]),
        spec=spec,
    )
    preflight = evaluate_preflight(config)
    if not preflight["ready"]:
        receipt = blocked_receipt(
            config, prompt, preflight, settings, profile, command
        )
        validate_receipt_contract(receipt)
        write_json(receipt_path, receipt)
        return 2, receipt

    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    child_started = False
    child_start: float | None = None
    peak_main_rss: int | None = None
    peak_child_rss: int | None = None
    peak_tree_rss: int | None = None
    process_tree_sample_count = 0
    process_tree_support_status = "supported"
    process_tree_unsupported_reason: str | None = None
    peak_gpu_memory_mib: int | None = None
    gpu_utilization_samples: list[int] = []
    execution_error: dict[str, str] | None = None
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr_handle:
            child_start = time.perf_counter()
            process = subprocess.Popen(
                command,
                cwd=project_path(config["backend"]["code_dir"]),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
            child_started = True
            while process.poll() is None:
                rss = sample_process_tree_rss(process.pid)
                if rss["main_process_rss_bytes"] is not None:
                    observed = int(rss["main_process_rss_bytes"])
                    peak_main_rss = (
                        observed
                        if peak_main_rss is None
                        else max(peak_main_rss, observed)
                    )
                if rss["child_process_rss_bytes"] is not None:
                    observed = int(rss["child_process_rss_bytes"])
                    peak_child_rss = (
                        observed
                        if peak_child_rss is None
                        else max(peak_child_rss, observed)
                    )
                if rss["process_tree_rss_bytes"] is not None:
                    observed = int(rss["process_tree_rss_bytes"])
                    peak_tree_rss = (
                        observed
                        if peak_tree_rss is None
                        else max(peak_tree_rss, observed)
                    )
                if rss["support_status"] == "supported":
                    process_tree_sample_count += 1
                if rss["support_status"] != "supported":
                    process_tree_support_status = str(rss["support_status"])
                    process_tree_unsupported_reason = str(
                        rss["unsupported_reason"]
                    )
                gpu = sample_nvidia_gpu()
                if gpu:
                    observed_gpu = int(gpu["memory_used_mib"])
                    peak_gpu_memory_mib = (
                        observed_gpu
                        if peak_gpu_memory_mib is None
                        else max(peak_gpu_memory_mib, observed_gpu)
                    )
                    gpu_utilization_samples.append(gpu["utilization_percent"])
                time.sleep(float(config["receipt"]["sample_interval_seconds"]))
            return_code = int(process.returncode)
    except Exception as error:
        return_code = -1
        execution_error = {
            "type": type(error).__name__,
            "message": str(error),
        }
    wall_seconds = (
        time.perf_counter() - child_start
        if child_started and child_start is not None
        else None
    )
    if (
        process_tree_sample_count == 0
        and process_tree_support_status == "supported"
    ):
        process_tree_support_status = "not_collected"
        process_tree_unsupported_reason = (
            "The child exited before a supported process-tree RSS sample "
            "was collected."
        )
    instrumentation = (
        json.loads(metrics_path.read_text(encoding="utf-8"))
        if metrics_path.is_file()
        else None
    )
    output_artifacts: list[dict[str, Any]] = []
    if instrumentation:
        for run in instrumentation.get("runs", []):
            output_value = run.get("output")
            if not output_value:
                continue
            output_path = Path(output_value)
            if output_path.is_file():
                output_artifacts.append(
                    {
                        "label": run.get("label"),
                        "path": str(output_path),
                        "bytes": output_path.stat().st_size,
                        "sha256": sha256_file(output_path),
                    }
                )
    expected_outputs = int(settings["repeat"])
    status = (
        "succeeded"
        if return_code == 0
        and instrumentation
        and instrumentation.get("status") == "succeeded"
        and len(output_artifacts) == expected_outputs
        else "failed"
    )
    reproducibility: dict[str, Any] = {
        "evaluated": expected_outputs == 2,
        "status": "not_evaluated",
        "same_seed": int(prompt["seed"]),
        "cold_hash": None,
        "warm_hash": None,
        "possible_causes_if_mismatch": [
            "nondeterministic CUDA kernels",
            "driver or library differences",
            "uncontrolled random state in the upstream backend",
            "video encoder nondeterminism",
        ],
    }
    if expected_outputs == 2 and len(output_artifacts) == 2:
        cold = next(
            (item for item in output_artifacts if item["label"] == "cold"), None
        )
        warm = next(
            (item for item in output_artifacts if item["label"] == "warm"), None
        )
        if cold and warm:
            reproducibility["cold_hash"] = cold["sha256"]
            reproducibility["warm_hash"] = warm["sha256"]
            if cold["sha256"] == warm["sha256"]:
                reproducibility["status"] = "hash_match"
            else:
                reproducibility["status"] = "hash_mismatch"
                status = "failed"
    cli_observed_seconds = (
        time.perf_counter() - cli_started_perf
        if cli_started_perf is not None
        else None
    )
    timing, unsupported = timing_from_instrumentation(
        instrumentation,
        wall_seconds,
        cli_observed_seconds=cli_observed_seconds,
    )
    resources = resources_from_instrumentation(
        instrumentation,
        peak_main_rss=peak_main_rss,
        peak_child_rss=peak_child_rss,
        peak_tree_rss=peak_tree_rss,
        process_tree_support_status=process_tree_support_status,
        process_tree_unsupported_reason=process_tree_unsupported_reason,
        peak_gpu_memory_mib=peak_gpu_memory_mib,
        gpu_utilization_samples=gpu_utilization_samples,
    )
    environment = dict(preflight["environment"])
    environment["cuda_allocator"] = resources["allocator"]
    error = (
        instrumentation.get("error")
        if instrumentation
        else execution_error
    )
    if status == "failed" and error is None:
        error = {
            "type": "RunValidationFailed",
            "message": (
                "Child return code, output count, instrumentation status, or "
                "same-seed reproducibility did not satisfy M0."
            ),
        }
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "kind": "hiveframe.m0.run_receipt",
        "run_id": run_id,
        "status": status,
        "partial": status != "succeeded",
        "profile": profile,
        **receipt_execution_classification(profile),
        "started_at": started_at,
        "finished_at": utc_now(),
        "backend": {
            "name": "wan21_t2v_1_3b_official",
            "code_repository": config["upstream"]["code_repository"],
            "code_revision": config["upstream"]["code_revision"],
            "model_id": config["model"]["repo_id"],
            "model_revision": config["model"]["revision"],
            "code_license": "Apache-2.0",
            "checkpoint_license": config["model"]["license"],
        },
        "sample": prompt,
        "settings": settings,
        "settings_hash": stable_hash({"sample": prompt, "settings": settings}),
        "configuration_hash": gate_fingerprint(config)["config_hash"],
        "command": command,
        "return_code": return_code,
        "timing": timing,
        "resources": resources,
        "artifacts": {
            "outputs": output_artifacts,
            "instrumentation": str(metrics_path) if metrics_path.is_file() else None,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        },
        "environment": environment,
        "reproducibility": reproducibility,
        "unsupported_metrics": unsupported,
        "error": error,
    }
    validate_receipt_contract(receipt)
    write_json(receipt_path, receipt)
    return (0 if status == "succeeded" else 1), receipt


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=True))


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


def stage_gate_error(stage: str, message: str) -> dict[str, Any]:
    return {
        "kind": "hiveframe.m0.stage_gate",
        "stage": stage,
        "status": "blocked",
        "message": message,
    }


def command_smoke(args: argparse.Namespace, config: dict[str, Any]) -> int:
    suite = load_suite(config)
    prompt_id = config["smoke"]["prompt_id"]
    prompt = next(item for item in suite if item["id"] == prompt_id)
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else project_path(config["paths"]["run_dir"])
    )
    plan = build_smoke_plan(config, prompt, args.run_id, output_dir)
    if args.plan:
        print_json(plan)
        return 0
    approval_error = settings_approval_error(
        plan, args.expect_settings_hash
    )
    if approval_error:
        print_json(approval_error)
        return 2
    collisions = list(plan["output"]["existing_collisions"])
    if collisions:
        print_json(
            stage_gate_error(
                "run-id-collision",
                (
                    f"Run ID {args.run_id!r} already has artifacts; "
                    f"refusing to overwrite: {', '.join(collisions)}"
                ),
            )
        )
        return 2
    return_code, receipt = run_sample(
        config,
        prompt,
        output_dir,
        profile="smoke",
        repeat=1,
        run_id=args.run_id,
        cli_started_perf=getattr(args, "_cli_started_perf", None),
    )
    if return_code == 0:
        state = read_gate_state(config)
        state["smoke"] = {
            "status": "succeeded",
            "receipt": str(output_dir / f"{receipt['run_id']}.receipt.json"),
            "completed_at": utc_now(),
            **gate_fingerprint(config),
        }
        write_gate_state(config, state)
    print_json(receipt)
    return return_code


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
    plan = build_run_plan(config, prompt, args.profile, output_dir)
    if args.plan:
        print_json(plan)
        return 0
    approval_error = settings_approval_error(
        plan, args.expect_settings_hash
    )
    if approval_error:
        print_json(approval_error)
        return 2
    collisions = list(plan["output"]["existing_collisions"])
    if collisions:
        print_json(
            stage_gate_error(
                "run-id-collision",
                (
                    f"Run ID {plan['run_id']!r} already has artifacts; "
                    f"refusing to overwrite: {', '.join(collisions)}"
                ),
            )
        )
        return 2
    state = read_gate_state(config)
    if not gate_matches(state.get("smoke"), config, "succeeded"):
        admission = args.profile == "baseline-memory-admission"
        print_json(
            stage_gate_error(
                "memory_admission" if admission else "reproducibility",
                (
                    "A successful matching regression smoke gate is required "
                    "before the memory admission probe."
                    if admission
                    else (
                        "A successful matching smoke gate is required before "
                        "a cold/warm run."
                    )
                ),
            )
        )
        return 2
    return_code, receipt = run_sample(
        config,
        prompt,
        output_dir,
        profile=args.profile,
        repeat=int(plan["effective_settings"]["repeat"]),
        cli_started_perf=getattr(args, "_cli_started_perf", None),
    )
    state = read_gate_state(config)
    if args.profile == "baseline-memory-admission":
        state["memory_admission"] = {
            "status": "passed" if return_code == 0 else "failed",
            "receipt": str(output_dir / f"{receipt['run_id']}.receipt.json"),
            "completed_at": utc_now(),
            **gate_fingerprint(config),
        }
    else:
        state["reproducibility"] = {
            "status": (
                "passed"
                if return_code == 0
                and receipt["reproducibility"]["status"] == "hash_match"
                else "failed"
            ),
            "receipt": str(output_dir / f"{receipt['run_id']}.receipt.json"),
            "completed_at": utc_now(),
            **gate_fingerprint(config),
        }
    write_gate_state(config, state)
    print_json(receipt)
    return return_code


def command_run_suite(args: argparse.Namespace, config: dict[str, Any]) -> int:
    state = read_gate_state(config)
    if not gate_matches(state.get("smoke"), config, "succeeded"):
        print_json(
            stage_gate_error(
                "canonical_suite",
                "A successful matching smoke gate is required before the suite.",
            )
        )
        return 2
    if not gate_matches(state.get("reproducibility"), config, "passed"):
        print_json(
            stage_gate_error(
                "canonical_suite",
                "A matching same-seed cold/warm hash check must pass first.",
            )
        )
        return 2
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else project_path(config["paths"]["run_dir"])
    )
    results = []
    final_code = 0
    for prompt in load_suite(config):
        code, receipt = run_sample(
            config, prompt, output_dir, profile="canonical", repeat=1
        )
        results.append(
            {
                "run_id": receipt["run_id"],
                "status": receipt["status"],
                "receipt": str(output_dir / f"{receipt['run_id']}.receipt.json"),
            }
        )
        final_code = max(final_code, code)
        if code != 0:
            break
    summary = {
        "kind": "hiveframe.m0.suite_summary",
        "created_at": utc_now(),
        "suite": config["benchmark"]["suite_id"],
        "gate_fingerprint": gate_fingerprint(config),
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

    smoke = subparsers.add_parser(
        "smoke", help="Run the minimum-cost gated smoke profile once."
    )
    smoke.add_argument("--output-dir")
    smoke.add_argument(
        "--run-id",
        required=True,
        type=validate_run_id,
        help=(
            "Unique receipt and artifact ID (ASCII letters, digits, '.', "
            "'_', and '-' only)."
        ),
    )
    smoke.add_argument(
        "--plan",
        "--dry-run",
        action="store_true",
        help="Print final smoke settings and hash without loading the model.",
    )
    smoke.add_argument(
        "--expect-settings-hash",
        metavar="SHA256",
        help=(
            "Required for execution; must exactly match the hash printed by "
            "--plan."
        ),
    )
    smoke.set_defaults(handler=command_smoke)

    run = subparsers.add_parser(
        "run",
        help=(
            "Plan or run one explicit M0 profile after the smoke gate succeeds."
        ),
    )
    run.add_argument(
        "--profile",
        choices=RUN_PROFILES,
        required=True,
        help=(
            "smoke-cold-warm uses the 17-frame/4-step smoke settings; "
            "baseline-memory-admission uses 49 frames/1 step/repeat 1 and is "
            "not an official performance or quality baseline; "
            "baseline-reproducibility preserves the 49-frame/50-step baseline."
        ),
    )
    run.add_argument("--prompt-id", required=True)
    run.add_argument("--output-dir")
    run.add_argument(
        "--plan",
        "--dry-run",
        action="store_true",
        help="Print final effective settings and hash without loading the model.",
    )
    run.add_argument(
        "--expect-settings-hash",
        metavar="SHA256",
        help=(
            "Required for execution; must exactly match the hash printed by "
            "--plan."
        ),
    )
    run.set_defaults(handler=command_run)

    suite = subparsers.add_parser(
        "run-suite", help="Run all ten canonical prompts sequentially."
    )
    suite.add_argument("--output-dir")
    suite.set_defaults(handler=command_run_suite)
    return parser


def main(argv: list[str] | None = None) -> int:
    cli_started_perf = time.perf_counter()
    parser = build_parser()
    args = parser.parse_args(argv)
    args._cli_started_perf = cli_started_perf
    config = load_config(Path(args.config).resolve())
    return int(args.handler(args, config))


if __name__ == "__main__":
    raise SystemExit(main())
