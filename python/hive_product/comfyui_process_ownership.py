"""Deterministic process-ownership receipt for a dedicated ComfyUI runtime."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import os

import psutil


SCHEMA_VERSION = "h3.comfyui-process-ownership-receipt.2"


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


def _safe_process(process: Any) -> dict[str, Any]:
    try:
        executable = process.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        executable = ""
    return {
        "pid": int(process.pid),
        "parent_pid": int(process.ppid()),
        "process_name": str(process.name()),
        "executable_name": Path(executable).name if executable else "",
        "executable_digest": _path_digest(executable) if executable else None,
        "create_time": float(process.create_time()),
    }


def _process_tree(root_pid: int) -> dict[str, Any]:
    try:
        root = psutil.Process(int(root_pid))
        members = [root, *root.children(recursive=True)]
        safe = sorted((_safe_process(process) for process in members), key=lambda item: item["pid"])
    except (psutil.AccessDenied, psutil.NoSuchProcess) as error:
        return {
            "root_pid": int(root_pid),
            "members": [],
            "member_count": 0,
            "identity_digest": None,
            "error_type": type(error).__name__,
        }
    identity = json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "root_pid": int(root_pid),
        "members": safe,
        "member_count": len(safe),
        "identity_digest": sha256(identity).hexdigest(),
        "error_type": None,
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
    backend_create_time: float | None,
    runner_pid: int,
    listener_pids: Sequence[int],
    run_id: str,
    phase: str,
    process_tree: Mapping[str, Any],
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
        "phase_known": phase in {"POST_LAUNCH", "PRE_SHUTDOWN"},
        "runtime_run_id_present": bool(run_id),
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
        "creation_time_present": item is not None
        and isinstance(item.get("create_time"), (int, float))
        and isinstance(backend_create_time, (int, float)),
        "creation_time_matches": item is not None
        and isinstance(item.get("create_time"), (int, float))
        and isinstance(backend_create_time, (int, float))
        and abs(float(item["create_time"]) - float(backend_create_time)) <= 1e-6,
        "root_parent_is_runner": item is not None
        and int(item.get("parent_pid", -1)) == int(runner_pid),
        "process_tree_root_matches": int(process_tree.get("root_pid", -1)) == int(backend_pid),
        "process_tree_identity_present": isinstance(process_tree.get("identity_digest"), str)
        and len(str(process_tree["identity_digest"])) == 64,
        "process_tree_contains_root": any(
            int(member.get("pid", -1)) == int(backend_pid)
            for member in process_tree.get("members", [])
            if isinstance(member, Mapping)
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "runtime_run_id": run_id,
        "backend_pid": int(backend_pid),
        "backend_create_time": backend_create_time,
        "runner_pid": int(runner_pid),
        "node_pid": int(node_pid),
        "listener_pids": [int(value) for value in listener_pids],
        "owned_process": _safe_candidate(item) if item is not None else None,
        "foreign_processes": [_safe_candidate(value) for value in foreign],
        "process_tree": dict(process_tree),
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
    run_id: str,
    phase: str,
) -> dict[str, Any]:
    """Collect and analyze the live runtime in one bounded read-only pass."""

    backend_pid = int(getattr(backend_process, "pid", -1))
    backend_alive = backend_process is not None and backend_process.poll() is None
    try:
        backend_create_time = float(psutil.Process(backend_pid).create_time())
    except (psutil.AccessDenied, psutil.NoSuchProcess, ValueError):
        backend_create_time = None
    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    process_tree = _process_tree(backend_pid)
    runtime_root = runtime_output / "runtime"
    receipt = analyze_process_ownership(
        candidates=collection["candidates"],
        backend_pid=backend_pid,
        node_pid=int(node_pid),
        backend_alive=backend_alive,
        backend_create_time=backend_create_time,
        runner_pid=os.getpid(),
        listener_pids=listener_pids,
        run_id=run_id,
        phase=phase,
        process_tree=process_tree,
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


def build_pre_launch_receipt(*, run_id: str, host: str, port: int) -> dict[str, Any]:
    """Freeze the no-runtime/no-listener state before starting ComfyUI."""

    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    runner_tree = _process_tree(os.getpid())
    checks = {
        "runtime_run_id_present": bool(run_id),
        "runtime_candidate_count_zero": collection["candidate_count"] == 0,
        "listener_count_zero": len(listener_pids) == 0,
        "listener_collection_accessible": listener_access_errors == 0,
        "runner_root_pid_present": runner_tree["root_pid"] == os.getpid(),
        "runner_creation_time_present": bool(runner_tree.get("members"))
        and isinstance(runner_tree["members"][0].get("create_time"), (int, float)),
        "runner_process_tree_identity_present": isinstance(runner_tree.get("identity_digest"), str),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "PRE_LAUNCH",
        "runtime_run_id": run_id,
        "runner_pid": os.getpid(),
        "runner_process_tree": runner_tree,
        "candidate_summaries": collection["candidate_summaries"],
        "candidate_count": collection["candidate_count"],
        "listener_pids": listener_pids,
        "access_error_count": collection["access_error_count"],
        "listener_access_error_count": listener_access_errors,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_post_shutdown_receipt(
    *,
    run_id: str,
    owned_pid: int,
    host: str,
    port: int,
    baseline_gpu_bytes: int | None,
    current_gpu_bytes: int | None,
) -> dict[str, Any]:
    """Prove the owned runtime and listener are gone after normal shutdown."""

    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    owned = [item for item in collection["candidates"] if int(item["pid"]) == int(owned_pid)]
    try:
        process_exists = psutil.pid_exists(int(owned_pid))
    except (TypeError, ValueError):
        process_exists = True
    gpu_known = isinstance(baseline_gpu_bytes, int) and isinstance(current_gpu_bytes, int)
    checks = {
        "runtime_run_id_present": bool(run_id),
        "owned_process_absent": not process_exists and len(owned) == 0,
        "listener_count_zero": len(listener_pids) == 0,
        "foreign_runtime_count_zero": collection["candidate_count"] == 0,
        "listener_collection_accessible": listener_access_errors == 0,
        "gpu_measurements_known": gpu_known,
        "gpu_returned_to_baseline": gpu_known
        and int(current_gpu_bytes) <= max(int(baseline_gpu_bytes), 16 * 1024**2),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "POST_SHUTDOWN",
        "runtime_run_id": run_id,
        "owned_pid": int(owned_pid),
        "candidate_summaries": collection["candidate_summaries"],
        "listener_pids": listener_pids,
        "baseline_gpu_bytes": baseline_gpu_bytes,
        "current_gpu_bytes": current_gpu_bytes,
        "checks": checks,
        "passed": all(checks.values()),
    }


__all__ = [
    "SCHEMA_VERSION",
    "analyze_process_ownership",
    "build_post_shutdown_receipt",
    "build_pre_launch_receipt",
    "build_process_ownership_receipt",
    "collect_comfy_runtime_processes",
    "parse_comfy_runtime",
]
