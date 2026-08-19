"""Deterministic process-ownership receipt for a dedicated ComfyUI runtime."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import os

import psutil


SCHEMA_VERSION = "h3.comfyui-process-ownership-receipt.1"


def _normalized_path(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(value)))


def _path_digest(value: str | Path) -> str:
    return sha256(_normalized_path(value).encode("utf-8")).hexdigest()


def _argument_value(arguments: Sequence[str], flag: str) -> str | None:
    positions = [index for index, value in enumerate(arguments) if value == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(arguments):
        return None
    return arguments[positions[0] + 1]


def parse_comfy_runtime(arguments: Sequence[str]) -> dict[str, Any] | None:
    """Parse only the exact argv shape used by the repository backend."""

    values = [str(value) for value in arguments]
    if len(values) < 2 or Path(values[1]).name.lower() != "main.py":
        return None
    listen = _argument_value(values, "--listen")
    port = _argument_value(values, "--port")
    if listen is None or port is None:
        return None
    try:
        port_number = int(port)
    except ValueError:
        return None
    if not 1 <= port_number <= 65_535:
        return None
    return {
        "executable": _normalized_path(values[0]),
        "main_script": _normalized_path(values[1]),
        "listen": listen,
        "port": port_number,
        "extra_config": _argument_value(values, "--extra-model-paths-config"),
        "input_directory": _argument_value(values, "--input-directory"),
        "output_directory": _argument_value(values, "--output-directory"),
        "temp_directory": _argument_value(values, "--temp-directory"),
        "user_directory": _argument_value(values, "--user-directory"),
        "disable_auto_launch_count": values.count("--disable-auto-launch"),
        "command_digest": sha256("\0".join(values).encode("utf-8")).hexdigest(),
        "argument_count": len(values),
    }


def _safe_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pid": int(candidate["pid"]),
        "parent_pid": int(candidate.get("parent_pid", -1)),
        "process_name": str(candidate.get("process_name") or ""),
        "executable_name": Path(str(candidate["executable"])).name,
        "executable_digest": _path_digest(str(candidate["executable"])),
        "main_script_name": Path(str(candidate["main_script"])).name,
        "main_script_digest": _path_digest(str(candidate["main_script"])),
        "listen": str(candidate["listen"]),
        "port": int(candidate["port"]),
        "command_digest": str(candidate["command_digest"]),
        "argument_count": int(candidate["argument_count"]),
        "create_time": candidate.get("create_time"),
    }


def collect_comfy_runtime_processes() -> dict[str, Any]:
    """Collect exact Comfy runtime candidates without retaining private argv."""

    candidates: list[dict[str, Any]] = []
    access_errors = 0
    disappeared = 0
    for process in psutil.process_iter(("pid", "ppid", "name", "cmdline", "create_time")):
        try:
            parsed = parse_comfy_runtime(process.info.get("cmdline") or ())
        except psutil.AccessDenied:
            access_errors += 1
            continue
        except psutil.NoSuchProcess:
            disappeared += 1
            continue
        if parsed is not None:
            candidates.append(
                {
                    **parsed,
                    "pid": int(process.info["pid"]),
                    "parent_pid": int(process.info.get("ppid") or -1),
                    "process_name": process.info.get("name"),
                    "create_time": process.info.get("create_time"),
                }
            )
    candidates.sort(key=lambda item: int(item["pid"]))
    return {
        "candidates": candidates,
        "candidate_summaries": [_safe_candidate(item) for item in candidates],
        "candidate_count": len(candidates),
        "access_error_count": access_errors,
        "disappeared_process_count": disappeared,
    }


def _listener_pids(host: str, port: int) -> tuple[list[int], int]:
    pids: set[int] = set()
    access_errors = 0
    try:
        connections = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied:
        return [], 1
    for connection in connections:
        if connection.status != psutil.CONN_LISTEN or not connection.laddr:
            continue
        address = str(connection.laddr.ip)
        if address == host and int(connection.laddr.port) == int(port) and connection.pid:
            pids.add(int(connection.pid))
    return sorted(pids), access_errors


def analyze_process_ownership(
    *,
    candidates: Sequence[Mapping[str, Any]],
    backend_pid: int,
    node_pid: int,
    backend_alive: bool,
    listener_pids: Sequence[int],
    expected_executable: Path,
    expected_main: Path,
    expected_host: str,
    expected_port: int,
    expected_extra_config: Path,
    expected_input: Path,
    expected_output: Path,
    expected_temp: Path,
    expected_user: Path,
) -> dict[str, Any]:
    """Bind all independent ownership signals to one exact process."""

    owned = [item for item in candidates if int(item["pid"]) == int(backend_pid)]
    foreign = [item for item in candidates if int(item["pid"]) != int(backend_pid)]
    item = owned[0] if len(owned) == 1 else None

    def path_matches(name: str, expected: Path) -> bool:
        value = item.get(name) if item is not None else None
        return isinstance(value, str) and _normalized_path(value) == _normalized_path(expected)

    checks = {
        "backend_pid_positive": int(backend_pid) > 0,
        "backend_process_alive": bool(backend_alive),
        "node_pid_matches_backend_pid": int(node_pid) == int(backend_pid),
        "owned_candidate_exactly_one": len(owned) == 1,
        "foreign_runtime_count_zero": len(foreign) == 0,
        "listener_pid_matches_backend_pid": list(listener_pids) == [int(backend_pid)],
        "python_executable_matches": path_matches("executable", expected_executable),
        "main_script_matches": path_matches("main_script", expected_main),
        "loopback_host_matches": item is not None and item.get("listen") == expected_host,
        "port_matches": item is not None and int(item.get("port", -1)) == int(expected_port),
        "extra_config_matches": path_matches("extra_config", expected_extra_config),
        "input_directory_matches": path_matches("input_directory", expected_input),
        "output_directory_matches": path_matches("output_directory", expected_output),
        "temp_directory_matches": path_matches("temp_directory", expected_temp),
        "user_directory_matches": path_matches("user_directory", expected_user),
        "auto_launch_disabled_once": item is not None
        and int(item.get("disable_auto_launch_count", 0)) == 1,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "backend_pid": int(backend_pid),
        "node_pid": int(node_pid),
        "listener_pids": [int(value) for value in listener_pids],
        "owned_process": _safe_candidate(item) if item is not None else None,
        "foreign_processes": [_safe_candidate(value) for value in foreign],
        "expected": {
            "executable_name": expected_executable.name,
            "executable_digest": _path_digest(expected_executable),
            "main_script_name": expected_main.name,
            "main_script_digest": _path_digest(expected_main),
            "listen": expected_host,
            "port": int(expected_port),
            "extra_config_digest": _path_digest(expected_extra_config),
            "input_directory_digest": _path_digest(expected_input),
            "output_directory_digest": _path_digest(expected_output),
            "temp_directory_digest": _path_digest(expected_temp),
            "user_directory_digest": _path_digest(expected_user),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_process_ownership_receipt(
    *,
    backend_process: Any,
    node_pid: int,
    comfyui_root: Path,
    runtime_output: Path,
    host: str,
    port: int,
) -> dict[str, Any]:
    """Collect and analyze the live runtime in one bounded read-only pass."""

    backend_pid = int(getattr(backend_process, "pid", -1))
    backend_alive = backend_process is not None and backend_process.poll() is None
    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    runtime_root = runtime_output / "runtime"
    receipt = analyze_process_ownership(
        candidates=collection["candidates"],
        backend_pid=backend_pid,
        node_pid=int(node_pid),
        backend_alive=backend_alive,
        listener_pids=listener_pids,
        expected_executable=comfyui_root / ".venv/Scripts/python.exe",
        expected_main=comfyui_root / "main.py",
        expected_host=host,
        expected_port=port,
        expected_extra_config=runtime_root / "h3-extra-model-paths.yaml",
        expected_input=runtime_output / "input",
        expected_output=runtime_output / "output",
        expected_temp=runtime_output / "temp",
        expected_user=runtime_output / "user",
    )
    receipt["collection"] = {
        "candidate_count": collection["candidate_count"],
        "candidate_summaries": collection["candidate_summaries"],
        "access_error_count": collection["access_error_count"],
        "disappeared_process_count": collection["disappeared_process_count"],
        "listener_access_error_count": listener_access_errors,
    }
    receipt["checks"]["listener_collection_accessible"] = listener_access_errors == 0
    receipt["passed"] = all(receipt["checks"].values())
    return receipt


__all__ = [
    "SCHEMA_VERSION",
    "analyze_process_ownership",
    "build_process_ownership_receipt",
    "collect_comfy_runtime_processes",
    "parse_comfy_runtime",
]

