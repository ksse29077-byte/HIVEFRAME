"""Deterministic process-ownership receipt for a dedicated ComfyUI runtime."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import os

import psutil


SCHEMA_VERSION = "h3.comfyui-process-ownership-receipt.3"


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


def collect_listener_pids(host: str, port: int) -> dict[str, Any]:
    """Collect the exact listener identities for one loopback endpoint."""

    pids, access_errors = _listener_pids(host, port)
    return {"listener_pids": pids, "access_error_count": access_errors}


def _same_creation_time(left: Any, right: Any) -> bool:
    return (
        isinstance(left, (int, float))
        and isinstance(right, (int, float))
        and abs(float(left) - float(right)) <= 1e-6
    )


def _verified_descendant(
    pid: int, launcher_pid: int, members: Mapping[int, Mapping[str, Any]]
) -> bool:
    if int(pid) == int(launcher_pid):
        return int(launcher_pid) in members
    current = int(pid)
    visited: set[int] = set()
    while current != int(launcher_pid):
        if current in visited or current not in members:
            return False
        visited.add(current)
        child = members[current]
        parent_pid = int(child.get("parent_pid", -1))
        parent = members.get(parent_pid)
        if parent is None:
            return False
        child_time = child.get("create_time")
        parent_time = parent.get("create_time")
        if not _same_creation_time(child_time, child_time) or not _same_creation_time(
            parent_time, parent_time
        ):
            return False
        if float(child_time) + 1e-6 < float(parent_time):
            return False
        current = parent_pid
    return True


def _run_id_in_path(run_id: str, value: str | Path) -> bool:
    expected = os.path.normcase(str(run_id))
    return expected in {os.path.normcase(part) for part in Path(value).parts}


def analyze_process_ownership(
    *,
    candidates: Sequence[Mapping[str, Any]],
    launcher_pid: int,
    runtime_pid: int,
    launcher_alive: bool,
    launcher_create_time: float | None,
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
    """Bind launcher, runtime, and listener roles to one verified process tree."""

    tree_members = {
        int(item["pid"]): item
        for item in process_tree.get("members", [])
        if isinstance(item, Mapping) and isinstance(item.get("pid"), int)
    }
    candidates_by_pid = {
        int(item["pid"]): item
        for item in candidates
        if isinstance(item.get("pid"), int)
    }
    tree_pids = set(tree_members)
    candidate_pids = set(candidates_by_pid)
    owned_pids = tree_pids & candidate_pids
    foreign = [item for item in candidates if int(item["pid"]) not in tree_pids]
    listener_pid = int(listener_pids[0]) if len(listener_pids) == 1 else -1
    launcher = candidates_by_pid.get(int(launcher_pid))
    runtime = candidates_by_pid.get(int(runtime_pid))
    listener = candidates_by_pid.get(listener_pid)

    def paths_match(name: str, expected: Path) -> bool:
        return bool(owned_pids) and all(
            isinstance(candidates_by_pid[pid].get(name), str)
            and _normalized_path(str(candidates_by_pid[pid][name]))
            == _normalized_path(expected)
            for pid in owned_pids
        )

    def values_match(name: str, expected: Any) -> bool:
        return bool(owned_pids) and all(
            candidates_by_pid[pid].get(name) == expected for pid in owned_pids
        )

    candidate_creation_times_match_tree = bool(owned_pids) and all(
        _same_creation_time(
            candidates_by_pid[pid].get("create_time"),
            tree_members[pid].get("create_time"),
        )
        for pid in owned_pids
    )
    role_pids = {int(launcher_pid), int(runtime_pid), listener_pid}

    checks = {
        "phase_known": phase in {"POST_LAUNCH", "PRE_SHUTDOWN"},
        "runtime_run_id_present": bool(run_id),
        "run_id_bound_to_dedicated_paths": bool(run_id)
        and all(
            _run_id_in_path(run_id, value)
            for value in (
                expected_extra_config,
                expected_input,
                expected_output,
                expected_temp,
                expected_user,
            )
        ),
        "launcher_pid_positive": int(launcher_pid) > 0,
        "runtime_pid_positive": int(runtime_pid) > 0,
        "launcher_process_alive": bool(launcher_alive),
        "listener_count_exactly_one": len(listener_pids) == 1,
        "launcher_candidate_present": launcher is not None,
        "runtime_candidate_present": runtime is not None,
        "listener_candidate_present": listener is not None,
        "foreign_runtime_count_zero": len(foreign) == 0,
        "tree_members_are_runtime_candidates": bool(tree_pids)
        and tree_pids == candidate_pids,
        "role_pids_inside_tree": listener_pid > 0 and role_pids <= tree_pids,
        "runtime_is_launcher_or_verified_descendant": _verified_descendant(
            int(runtime_pid), int(launcher_pid), tree_members
        ),
        "listener_is_launcher_or_verified_descendant": listener_pid > 0
        and _verified_descendant(listener_pid, int(launcher_pid), tree_members),
        "python_executable_matches": paths_match("executable", expected_executable),
        "main_script_matches": paths_match("main_script", expected_main),
        "loopback_host_matches": values_match("listen", expected_host),
        "port_matches": values_match("port", int(expected_port)),
        "extra_config_matches": paths_match("extra_config", expected_extra_config),
        "input_directory_matches": paths_match("input_directory", expected_input),
        "output_directory_matches": paths_match("output_directory", expected_output),
        "temp_directory_matches": paths_match("temp_directory", expected_temp),
        "user_directory_matches": paths_match("user_directory", expected_user),
        "auto_launch_disabled_once": bool(owned_pids)
        and all(
            int(candidates_by_pid[pid].get("disable_auto_launch_count", 0)) == 1
            for pid in owned_pids
        ),
        "tree_processes_are_python": bool(tree_members)
        and all(
            str(member.get("process_name", "")).lower() == "python.exe"
            for member in tree_members.values()
        ),
        "creation_times_present": bool(tree_members)
        and all(
            isinstance(member.get("create_time"), (int, float))
            for member in tree_members.values()
        )
        and all(
            isinstance(candidates_by_pid[pid].get("create_time"), (int, float))
            for pid in owned_pids
        )
        and isinstance(launcher_create_time, (int, float)),
        "candidate_creation_times_match_tree": candidate_creation_times_match_tree,
        "launcher_creation_time_matches_popen": launcher is not None
        and _same_creation_time(launcher.get("create_time"), launcher_create_time),
        "root_parent_is_runner": launcher is not None
        and int(launcher.get("parent_pid", -1)) == int(runner_pid)
        and int(tree_members.get(int(launcher_pid), {}).get("parent_pid", -1))
        == int(runner_pid),
        "process_tree_root_matches_launcher": int(process_tree.get("root_pid", -1))
        == int(launcher_pid),
        "process_tree_collection_succeeded": process_tree.get("error_type") is None,
        "process_tree_identity_present": isinstance(process_tree.get("identity_digest"), str)
        and len(str(process_tree["identity_digest"])) == 64,
        "process_tree_contains_launcher": int(launcher_pid) in tree_members,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "runtime_run_id": run_id,
        "launcher_pid": int(launcher_pid),
        "launcher_create_time": launcher_create_time,
        "runtime_pid": int(runtime_pid),
        "listener_pid": listener_pid if listener_pid > 0 else None,
        "runner_pid": int(runner_pid),
        "listener_pids": [int(value) for value in listener_pids],
        "launcher_process": _safe_candidate(launcher) if launcher is not None else None,
        "runtime_process": _safe_candidate(runtime) if runtime is not None else None,
        "listener_process": _safe_candidate(listener) if listener is not None else None,
        "owned_processes": [
            _safe_candidate(candidates_by_pid[pid]) for pid in sorted(owned_pids)
        ],
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
    runtime_pid: int,
    comfyui_root: Path,
    runtime_output: Path,
    host: str,
    port: int,
    run_id: str,
    phase: str,
) -> dict[str, Any]:
    """Collect and analyze the live runtime in one bounded read-only pass."""

    launcher_pid = int(getattr(backend_process, "pid", -1))
    launcher_alive = backend_process is not None and backend_process.poll() is None
    try:
        launcher_create_time = float(psutil.Process(launcher_pid).create_time())
    except (psutil.AccessDenied, psutil.NoSuchProcess, ValueError):
        launcher_create_time = None
    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    process_tree = _process_tree(launcher_pid)
    runtime_root = runtime_output / "runtime"
    receipt = analyze_process_ownership(
        candidates=collection["candidates"],
        launcher_pid=launcher_pid,
        runtime_pid=int(runtime_pid),
        launcher_alive=launcher_alive,
        launcher_create_time=launcher_create_time,
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
    owned_processes: Sequence[Mapping[str, Any]],
    host: str,
    port: int,
    baseline_gpu_bytes: int | None,
    current_gpu_bytes: int | None,
    require_gpu_baseline: bool = True,
) -> dict[str, Any]:
    """Prove the owned runtime and listener are gone after normal shutdown."""

    collection = collect_comfy_runtime_processes()
    listener_pids, listener_access_errors = _listener_pids(host, port)
    live_owned_identities: list[dict[str, Any]] = []
    identity_access_errors = 0
    for identity in owned_processes:
        pid = int(identity.get("pid", -1))
        try:
            process = psutil.Process(pid)
            if _same_creation_time(process.create_time(), identity.get("create_time")):
                live_owned_identities.append(
                    {"pid": pid, "create_time": identity.get("create_time")}
                )
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, ValueError, TypeError):
            identity_access_errors += 1
    gpu_known = isinstance(baseline_gpu_bytes, int) and isinstance(current_gpu_bytes, int)
    checks = {
        "runtime_run_id_present": bool(run_id),
        "owned_processes_declared": len(owned_processes) >= 1,
        "owned_process_identities_absent": len(live_owned_identities) == 0,
        "owned_identity_collection_accessible": identity_access_errors == 0,
        "listener_count_zero": len(listener_pids) == 0,
        "foreign_runtime_count_zero": collection["candidate_count"] == 0,
        "listener_collection_accessible": listener_access_errors == 0,
        "gpu_measurements_satisfied": not require_gpu_baseline
        or (
            gpu_known
            and int(current_gpu_bytes) <= max(int(baseline_gpu_bytes), 16 * 1024**2)
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "POST_SHUTDOWN",
        "runtime_run_id": run_id,
        "owned_processes": [
            {
                "pid": int(identity.get("pid", -1)),
                "create_time": identity.get("create_time"),
            }
            for identity in owned_processes
        ],
        "live_owned_identities": live_owned_identities,
        "candidate_summaries": collection["candidate_summaries"],
        "listener_pids": listener_pids,
        "baseline_gpu_bytes": baseline_gpu_bytes,
        "current_gpu_bytes": current_gpu_bytes,
        "gpu_baseline_required": require_gpu_baseline,
        "checks": checks,
        "passed": all(checks.values()),
    }


def stop_verified_runtime_descendants(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Stop only creation-time-bound descendants from a passing ownership receipt."""

    if receipt.get("passed") is not True:
        raise RuntimeError("process-tree shutdown requires a passing ownership receipt")
    launcher_pid = int(receipt.get("launcher_pid", -1))
    members = [
        item
        for item in receipt.get("process_tree", {}).get("members", [])
        if isinstance(item, Mapping) and int(item.get("pid", -1)) != launcher_pid
    ]

    def depth(identity: Mapping[str, Any]) -> int:
        by_pid = {
            int(item["pid"]): item
            for item in receipt.get("process_tree", {}).get("members", [])
            if isinstance(item, Mapping) and isinstance(item.get("pid"), int)
        }
        current = int(identity["pid"])
        result = 0
        while current != launcher_pid and current in by_pid:
            result += 1
            current = int(by_pid[current].get("parent_pid", -1))
        return result

    stopped: list[int] = []
    already_absent: list[int] = []
    for identity in sorted(members, key=depth, reverse=True):
        pid = int(identity["pid"])
        try:
            process = psutil.Process(pid)
            if not _same_creation_time(process.create_time(), identity.get("create_time")):
                raise RuntimeError("process creation time changed before shutdown")
            process.terminate()
            process.wait(timeout=20)
            stopped.append(pid)
        except psutil.NoSuchProcess:
            already_absent.append(pid)
        except psutil.TimeoutExpired:
            process = psutil.Process(pid)
            if not _same_creation_time(process.create_time(), identity.get("create_time")):
                raise RuntimeError("process creation time changed before forced shutdown")
            process.kill()
            process.wait(timeout=10)
            stopped.append(pid)
    return {
        "status": "verified_descendants_stopped",
        "launcher_pid": launcher_pid,
        "stopped_pids": stopped,
        "already_absent_pids": already_absent,
        "foreign_process_termination_count": 0,
    }


__all__ = [
    "SCHEMA_VERSION",
    "analyze_process_ownership",
    "build_post_shutdown_receipt",
    "build_pre_launch_receipt",
    "build_process_ownership_receipt",
    "collect_listener_pids",
    "collect_comfy_runtime_processes",
    "parse_comfy_runtime",
    "stop_verified_runtime_descendants",
]
