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
    "baseline-reproducibility",
)
PROFILE_RUN_KINDS = {
    "smoke-cold-warm": "smoke-based same-seed cold/warm pair",
    "baseline-reproducibility": "baseline same-seed cold/warm pair",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    settings["repeat"] = (
        repeat
        if repeat is not None
        else int(config["reproducibility"]["repeat"])
    )
    return settings


def build_run_plan(
    config: dict[str, Any],
    prompt: dict[str, Any],
    profile: str,
) -> dict[str, Any]:
    if profile not in RUN_PROFILES:
        choices = ", ".join(RUN_PROFILES)
        raise ValueError(
            f"Unknown run profile {profile!r}; choose one of: {choices}."
        )
    settings = settings_for_profile(
        config,
        profile,
        repeat=int(config["reproducibility"]["repeat"]),
    )
    settings_hash = stable_hash({"sample": prompt, "settings": settings})
    return {
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.run_plan",
        "execution_started": False,
        "selected_profile": profile,
        "expected_run_kind": PROFILE_RUN_KINDS[profile],
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
    }


def gate_state_path(config: dict[str, Any]) -> Path:
    return project_path(config["paths"]["gate_state"])


def read_gate_state(config: dict[str, Any]) -> dict[str, Any]:
    path = gate_state_path(config)
    if not path.is_file():
        return {"schema_version": "0.1.0", "smoke": None, "reproducibility": None}
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
    settings: dict[str, Any],
    profile: str,
    command: list[str],
) -> dict[str, Any]:
    started = utc_now()
    return {
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.run_receipt",
        "run_id": f"{profile}-{prompt['id']}-{prompt['seed']}",
        "status": "blocked",
        "partial": True,
        "profile": profile,
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
        "timing": {
            "wall_clock_seconds": 0.0,
            "model_load_wall_seconds": None,
            "prompt_encode_wall_seconds": None,
            "denoising_wall_seconds": None,
            "denoising_steps": [],
            "vae_encode_wall_seconds": None,
            "vae_decode_wall_seconds": None,
            "video_encode_wall_seconds": None,
            "cuda_gpu_seconds": None,
        },
        "resources": {
            "peak_vram_allocated_bytes": None,
            "peak_vram_reserved_bytes": None,
            "peak_host_rss_bytes": None,
        },
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


def timing_from_instrumentation(
    instrumentation: dict[str, Any] | None, wall_seconds: float
) -> tuple[dict[str, Any], dict[str, str]]:
    unsupported: dict[str, str] = {
        "vae_encode": "Text-to-video has no input VAE encode stage.",
        "scheduler_overhead": (
            "The official scheduler step is included in each denoising step; "
            "scheduler-only time is not isolated by this non-invasive hook."
        ),
        "host_ram_descendants": (
            "Peak host RSS samples the main Wan child process every configured "
            "interval; short-lived descendant encoder processes are not aggregated."
        ),
    }
    timing: dict[str, Any] = {
        "wall_clock_seconds": wall_seconds,
        "model_load_wall_seconds": None,
        "model_load_cuda_seconds": None,
        "runs": [],
        "vae_encode_wall_seconds": None,
        "scheduler_overhead_seconds": None,
    }
    if not instrumentation:
        unsupported["instrumentation"] = (
            "The instrumented child process did not produce a metrics file."
        )
        timing["cuda_gpu_seconds"] = None
        return timing, unsupported

    model_load = instrumentation.get("model_load", {})
    timing["model_load_wall_seconds"] = model_load.get("model_load_wall_seconds")
    timing["model_load_cuda_seconds"] = model_load.get("model_load_cuda_seconds")
    cuda_total = (
        float(timing["model_load_cuda_seconds"])
        if timing["model_load_cuda_seconds"] is not None
        else 0.0
    )
    has_cuda_measurement = timing["model_load_cuda_seconds"] is not None
    for run in instrumentation.get("runs", []):
        prompt_calls = run.get("prompt_encode_calls", [])
        prompt_wall = sum(
            float(item.get("encode_wall_seconds") or 0.0) for item in prompt_calls
        )
        prompt_cuda_values = [
            item.get("encode_cuda_seconds") for item in prompt_calls
        ]
        prompt_cuda = (
            sum(float(value) for value in prompt_cuda_values)
            if prompt_cuda_values and all(value is not None for value in prompt_cuda_values)
            else None
        )
        steps = run.get("denoising_steps", [])
        denoising_wall = sum(
            float(item.get("step_wall_seconds") or 0.0) for item in steps
        )
        step_cuda_values = [item.get("step_cuda_seconds") for item in steps]
        denoising_cuda = (
            sum(float(value) for value in step_cuda_values)
            if step_cuda_values and all(value is not None for value in step_cuda_values)
            else None
        )
        generation_cuda = run.get("generation_cuda_seconds")
        video_encode_cuda = run.get("video_encode_cuda_seconds")
        for value in (generation_cuda, video_encode_cuda):
            if value is not None:
                cuda_total += float(value)
                has_cuda_measurement = True
        timing["runs"].append(
            {
                "label": run.get("label"),
                "prompt_encode_wall_seconds": prompt_wall,
                "prompt_encode_cuda_seconds": prompt_cuda,
                "denoising_wall_seconds": denoising_wall,
                "denoising_cuda_seconds": denoising_cuda,
                "denoising_steps": steps,
                "vae_decode_wall_seconds": run.get("vae_decode_wall_seconds"),
                "vae_decode_cuda_seconds": run.get("vae_decode_cuda_seconds"),
                "video_encode_wall_seconds": run.get("video_encode_wall_seconds"),
                "video_encode_cuda_seconds": video_encode_cuda,
                "generation_wall_seconds": run.get("generation_wall_seconds"),
                "generation_cuda_seconds": generation_cuda,
            }
        )
    timing["cuda_gpu_seconds"] = cuda_total if has_cuda_measurement else None
    if not has_cuda_measurement:
        unsupported["cuda_gpu_time"] = (
            "CUDA events were unavailable or the child failed before CUDA timing."
        )
    return timing, unsupported


def run_sample(
    config: dict[str, Any],
    prompt: dict[str, Any],
    output_dir: Path,
    *,
    profile: str,
    repeat: int | None = None,
) -> tuple[int, dict[str, Any]]:
    settings = settings_for_profile(config, profile, repeat=repeat)
    run_id = f"{profile}-{prompt['id']}-{prompt['seed']}"
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
        write_json(receipt_path, receipt)
        return 2, receipt

    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    start = time.perf_counter()
    peak_host_rss = 0
    peak_gpu_memory_mib = 0
    gpu_utilization_samples: list[int] = []
    execution_error: dict[str, str] | None = None
    try:
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
            return_code = int(process.returncode)
    except Exception as error:
        return_code = -1
        execution_error = {
            "type": type(error).__name__,
            "message": str(error),
        }
    wall_seconds = time.perf_counter() - start
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
    timing, unsupported = timing_from_instrumentation(instrumentation, wall_seconds)
    environment = preflight["environment"]
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
        "schema_version": "0.1.0",
        "kind": "hiveframe.m0.run_receipt",
        "run_id": run_id,
        "status": status,
        "partial": status != "succeeded",
        "profile": profile,
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
        "resources": {
            "peak_host_rss_bytes": peak_host_rss or None,
            "peak_gpu_memory_mib_sampled": peak_gpu_memory_mib or None,
            "average_gpu_utilization_percent": (
                sum(gpu_utilization_samples) / len(gpu_utilization_samples)
                if gpu_utilization_samples
                else None
            ),
            "peak_vram_allocated_bytes": (
                instrumentation.get("peak_vram", {}).get("allocated_bytes")
                if instrumentation
                else None
            ),
            "peak_vram_reserved_bytes": (
                instrumentation.get("peak_vram", {}).get("reserved_bytes")
                if instrumentation
                else None
            ),
        },
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
    return_code, receipt = run_sample(
        config, prompt, output_dir, profile="smoke", repeat=1
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
    plan = build_run_plan(config, prompt, args.profile)
    if args.plan:
        print_json(plan)
        return 0
    if not args.expect_settings_hash:
        print_json(
            stage_gate_error(
                "settings-approval",
                "Execution requires --expect-settings-hash from an approved run plan.",
            )
        )
        return 2
    if args.expect_settings_hash != plan["settings_hash"]:
        print_json(
            stage_gate_error(
                "settings-approval",
                (
                    "Approved settings hash does not match the final effective "
                    f"settings: expected {args.expect_settings_hash}, "
                    f"actual {plan['settings_hash']}."
                ),
            )
        )
        return 2
    state = read_gate_state(config)
    if not gate_matches(state.get("smoke"), config, "succeeded"):
        print_json(
            stage_gate_error(
                "reproducibility",
                "A successful matching smoke gate is required before a cold/warm run.",
            )
        )
        return 2
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else project_path(config["paths"]["run_dir"])
    )
    return_code, receipt = run_sample(
        config,
        prompt,
        output_dir,
        profile=args.profile,
        repeat=int(config["reproducibility"]["repeat"]),
    )
    state = read_gate_state(config)
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
    smoke.set_defaults(handler=command_smoke)

    run = subparsers.add_parser(
        "run",
        help=(
            "Plan or run one explicit same-seed cold/warm profile after the "
            "smoke gate succeeds."
        ),
    )
    run.add_argument(
        "--profile",
        choices=RUN_PROFILES,
        required=True,
        help=(
            "smoke-cold-warm uses the 17-frame/4-step smoke settings; "
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
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config).resolve())
    return int(args.handler(args, config))


if __name__ == "__main__":
    raise SystemExit(main())
