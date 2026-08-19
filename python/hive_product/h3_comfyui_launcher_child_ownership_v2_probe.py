"""Run one model-free ComfyUI launcher/child ownership lifecycle."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from .comfyui_backend import ComfyUIH3Config, MiniMaxH3ComfyUIBackend
from .comfyui_process_ownership import (
    build_post_shutdown_receipt,
    build_pre_launch_receipt,
    build_process_ownership_receipt,
    collect_listener_pids,
    stop_verified_runtime_descendants,
    wait_for_console_helper_exit,
)


READY = "H3_COMFYUI_LAUNCHER_CHILD_OWNERSHIP_CONTRACT_V2_READY"
BLOCKED = "H3_COMFYUI_LAUNCHER_CHILD_OWNERSHIP_CONTRACT_V2_BLOCKED"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_digest(path: Path) -> str:
    normalized = str(path.resolve()).casefold().encode("utf-8")
    return sha256(normalized).hexdigest()


def _role_identity(receipt: Mapping[str, Any], role: str) -> tuple[Any, ...]:
    process = receipt.get(f"{role}_process") or {}
    return (
        receipt.get(f"{role}_pid"),
        process.get("create_time"),
        process.get("command_digest"),
        process.get("executable_digest"),
        process.get("main_script_digest"),
    )


def _continuity(
    post_launch: Mapping[str, Any], pre_shutdown: Mapping[str, Any]
) -> dict[str, bool]:
    return {
        "run_id_matches": pre_shutdown.get("runtime_run_id")
        == post_launch.get("runtime_run_id"),
        "launcher_identity_matches": _role_identity(pre_shutdown, "launcher")
        == _role_identity(post_launch, "launcher"),
        "runtime_identity_matches": _role_identity(pre_shutdown, "runtime")
        == _role_identity(post_launch, "runtime"),
        "listener_identity_matches": _role_identity(pre_shutdown, "listener")
        == _role_identity(post_launch, "listener"),
        "console_helper_identity_matches": _role_identity(
            pre_shutdown, "console_helper"
        )
        == _role_identity(post_launch, "console_helper"),
        "process_tree_identity_matches": pre_shutdown.get("process_tree", {}).get(
            "identity_digest"
        )
        == post_launch.get("process_tree", {}).get("identity_digest"),
    }


def run(
    args: argparse.Namespace,
    *,
    ready_decision: str = READY,
    blocked_decision: str = BLOCKED,
    schema_version: str = "h3.comfyui-launcher-child-ownership-v2-probe.2",
) -> tuple[int, dict[str, Any]]:
    started_at = _utc_now()
    parsed = urlparse(args.base_url)
    port = int(parsed.port or -1)
    host = parsed.hostname or ""
    private_root = args.private_run_root.resolve() / args.run_id
    runtime_output = private_root / "comfy-output"
    receipt: dict[str, Any] = {
        "schema_version": schema_version,
        "run_id": args.run_id,
        "started_at": started_at,
        "decision": blocked_decision,
        "runtime_start_count": 0,
        "runtime_ready_count": 0,
        "runtime_shutdown_count": 0,
        "h3_model_load_count": 0,
        "generation_count": 0,
        "control_submission_count": 0,
        "selective_count": 0,
        "partial_q_count": 0,
        "attention_omission_count": 0,
        "foreign_process_termination_count": 0,
        "configuration": {
            "host": host,
            "port": port,
            "comfyui_root_digest": _path_digest(args.comfyui_root),
            "asset_root_digest": _path_digest(args.asset_root),
            "private_run_root_digest": _path_digest(private_root),
            "custom_nodes_enabled": False,
        },
    }
    backend: MiniMaxH3ComfyUIBackend | None = None
    runtime_started = False
    shutdown_complete = False
    verified_receipt: dict[str, Any] | None = None
    error: BaseException | None = None
    try:
        if private_root.exists():
            raise RuntimeError("private run root already exists")
        pre_launch = build_pre_launch_receipt(run_id=args.run_id, host=host, port=port)
        receipt["pre_launch"] = pre_launch
        if pre_launch.get("passed") is not True:
            raise RuntimeError("PRE_LAUNCH ownership Gate failed")

        config = ComfyUIH3Config(
            asset_root=args.asset_root.resolve(),
            comfyui_root=args.comfyui_root.resolve(),
            base_url=args.base_url,
            workflow=None,
            output_root=runtime_output,
            custom_nodes_root=None,
            timeout_seconds=args.timeout_seconds,
        )
        backend = MiniMaxH3ComfyUIBackend(config=config)
        receipt["runtime_start_count"] = 1
        start = backend.start_runtime()
        receipt["runtime_start"] = start
        runtime_started = start.get("started_here") is True
        if not runtime_started:
            raise RuntimeError("dedicated runtime was not started by this probe")

        system = backend.client.json("GET", "/system_stats")
        queue = backend.client.json("GET", "/queue")
        listener_collection = collect_listener_pids(host, port)
        listener_pids = listener_collection["listener_pids"]
        runtime_pid = int(listener_pids[0]) if len(listener_pids) == 1 else -1
        post_launch = build_process_ownership_receipt(
            backend_process=backend._process,
            runtime_pid=runtime_pid,
            comfyui_root=args.comfyui_root.resolve(),
            runtime_output=runtime_output,
            host=host,
            port=port,
            run_id=args.run_id,
            phase="POST_LAUNCH",
        )
        initial_snapshot = {
            "schema_version": post_launch.get("schema_version"),
            "runtime_run_identity_digest": post_launch.get(
                "runtime_run_identity_digest"
            ),
            "launcher_pid": post_launch.get("launcher_pid"),
            "launcher_create_time": post_launch.get("launcher_create_time"),
            "runtime_pid": post_launch.get("runtime_pid"),
            "runtime_create_time": post_launch.get("runtime_create_time"),
            "listener_pid": post_launch.get("listener_pid"),
            "listener_create_time": post_launch.get("listener_create_time"),
            "listener_owner_pid": post_launch.get("listener_owner_pid"),
            "console_helper_pid": post_launch.get("console_helper_pid"),
            "console_helper_create_time": post_launch.get(
                "console_helper_create_time"
            ),
            "console_helper_process": deepcopy(
                post_launch.get("console_helper_process")
            ),
            "console_helper_admission": deepcopy(
                post_launch.get("console_helper_admission")
            ),
            "role_ancestry": deepcopy(post_launch.get("role_ancestry")),
            "process_tree": deepcopy(post_launch.get("process_tree")),
            "unexpected_tree_members": deepcopy(
                post_launch.get("unexpected_tree_members")
            ),
        }
        snapshot_bytes = json.dumps(
            initial_snapshot, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        receipt["initial_topology_snapshot"] = initial_snapshot
        receipt["initial_topology_snapshot_digest"] = sha256(snapshot_bytes).hexdigest()
        if post_launch.get("passed") is True:
            verified_receipt = post_launch
        ready_checks = {
            "system_stats_mapping": isinstance(system, Mapping),
            "queue_running_zero": isinstance(queue, Mapping)
            and len(queue.get("queue_running", [])) == 0,
            "queue_pending_zero": isinstance(queue, Mapping)
            and len(queue.get("queue_pending", [])) == 0,
            "listener_collection_accessible": listener_collection["access_error_count"]
            == 0,
            "listener_count_exactly_one": len(listener_pids) == 1,
            "process_tree_ownership_pass": post_launch.get("passed") is True,
        }
        receipt["runtime_ready"] = {"checks": ready_checks, "passed": all(ready_checks.values())}
        receipt["post_launch_ownership"] = post_launch
        if not all(ready_checks.values()):
            raise RuntimeError("model-free runtime ready/ownership Gate failed")
        receipt["runtime_ready_count"] = 1

        pre_shutdown = build_process_ownership_receipt(
            backend_process=backend._process,
            runtime_pid=runtime_pid,
            comfyui_root=args.comfyui_root.resolve(),
            runtime_output=runtime_output,
            host=host,
            port=port,
            run_id=args.run_id,
            phase="PRE_SHUTDOWN",
        )
        continuity = _continuity(post_launch, pre_shutdown)
        pre_shutdown["continuity_checks"] = continuity
        pre_shutdown["passed"] = bool(
            pre_shutdown.get("passed") is True and all(continuity.values())
        )
        receipt["pre_shutdown_ownership"] = pre_shutdown
        if pre_shutdown["passed"] is not True:
            raise RuntimeError("PRE_SHUTDOWN process-tree continuity Gate failed")
        verified_receipt = pre_shutdown

        receipt["runtime_descendant_stop"] = stop_verified_runtime_descendants(
            pre_shutdown
        )
        stop = backend.stop_runtime()
        receipt["runtime_stop"] = stop
        runtime_started = False
        if stop.get("stopped") is not True:
            raise RuntimeError("launcher shutdown failed")
        receipt["runtime_shutdown_count"] = 1
        natural_exit = wait_for_console_helper_exit(
            pre_shutdown.get("console_helper_process")
        )
        receipt["console_helper_natural_exit"] = natural_exit
        if natural_exit.get("passed") is not True:
            raise RuntimeError("console helper did not exit naturally")
        post_shutdown = build_post_shutdown_receipt(
            run_id=args.run_id,
            owned_processes=pre_shutdown.get("owned_processes", []),
            host=host,
            port=port,
            baseline_gpu_bytes=None,
            current_gpu_bytes=None,
            require_gpu_baseline=False,
            console_helper_process=pre_shutdown.get("console_helper_process"),
        )
        receipt["post_shutdown_ownership"] = post_shutdown
        if post_shutdown.get("passed") is not True:
            raise RuntimeError("POST_SHUTDOWN ownership Gate failed")
        shutdown_complete = True
        receipt["decision"] = ready_decision
    except BaseException as caught:
        error = caught
    finally:
        if runtime_started and backend is not None:
            cleanup_receipt = verified_receipt
            if cleanup_receipt is not None and cleanup_receipt.get("passed") is True:
                try:
                    receipt["failure_cleanup_descendants"] = (
                        stop_verified_runtime_descendants(cleanup_receipt)
                    )
                    receipt["failure_cleanup_launcher"] = backend.stop_runtime()
                    receipt["failure_cleanup_console_helper"] = (
                        wait_for_console_helper_exit(
                            cleanup_receipt.get("console_helper_process")
                        )
                    )
                    runtime_started = False
                except BaseException as cleanup_error:
                    receipt["failure_cleanup_error_type"] = type(cleanup_error).__name__
            if runtime_started:
                receipt["failure_cleanup"] = "BLOCKED_UNVERIFIED_PROCESS_TREE"
        if error is not None:
            receipt["error_type"] = type(error).__name__
            receipt["decision"] = blocked_decision
        receipt["shutdown_complete"] = shutdown_complete
        receipt["finished_at"] = _utc_now()
        private_root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        (private_root / "private-receipt.json").write_text(payload, encoding="utf-8")
        (private_root / "public-summary.json").write_text(payload, encoding="utf-8")
    return (0 if receipt["decision"] == ready_decision else 1), receipt


def build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comfyui-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--private-run-root", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser


def main() -> int:
    parser = build_parser(
        description="Verify one model-free ComfyUI launcher/child ownership lifecycle."
    )
    args = parser.parse_args()
    code, receipt = run(args)
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
