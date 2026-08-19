from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import os
import unittest
from unittest.mock import patch

import psutil

from hive_product.comfyui_process_ownership import (
    analyze_process_ownership,
    build_post_shutdown_receipt,
    build_pre_launch_receipt,
    parse_comfy_runtime,
    stop_verified_runtime_descendants,
    wait_for_console_helper_exit,
)
from hive_product import h3_comfyui_launcher_child_ownership_v2_probe
from hive_product import h3_comfyui_console_helper_ownership_v2_probe


RUN_ID = "control-v2-run-1"
ROOT = Path(r"C:\runtime\ComfyUI")
OUTPUT = Path(rf"C:\private\control-v2\{RUN_ID}")
PYTHON = ROOT / ".venv/Scripts/python.exe"
MAIN = ROOT / "main.py"
CONFIG = OUTPUT / "runtime/h3-extra-model-paths.yaml"
TRUSTED_CONHOST = Path(r"C:\Windows\System32\conhost.exe")


def path_digest(path: Path) -> str:
    normalized = os.path.normcase(os.path.abspath(os.fspath(path))).encode("utf-8")
    return sha256(normalized).hexdigest()


def arguments(port: int = 8191) -> list[str]:
    return [
        str(PYTHON),
        str(MAIN),
        "--listen",
        "127.0.0.1",
        "--port",
        str(port),
        "--extra-model-paths-config",
        str(CONFIG),
        "--input-directory",
        str(OUTPUT / "input"),
        "--output-directory",
        str(OUTPUT / "output"),
        "--temp-directory",
        str(OUTPUT / "temp"),
        "--user-directory",
        str(OUTPUT / "user"),
        "--disable-auto-launch",
    ]


def candidate(
    pid: int = 42,
    *,
    parent_pid: int = 7,
    create_time: float = 1.0,
    port: int = 8191,
):
    value = parse_comfy_runtime(arguments(port))
    assert value is not None
    return {
        **value,
        "pid": pid,
        "parent_pid": parent_pid,
        "process_name": "python.exe",
        "create_time": create_time,
    }


def tree(*members):
    return {
        "root_pid": 42,
        "members": list(members),
        "member_count": len(members),
        "identity_digest": "aa" * 32,
        "observed_at_unix": 10.0,
        "error_type": None,
    }


def member(
    pid: int,
    parent_pid: int,
    create_time: float,
    *,
    name: str = "python.exe",
    executable: Path = PYTHON,
    comfy_markers: bool = False,
):
    return {
        "pid": pid,
        "parent_pid": parent_pid,
        "process_name": name,
        "executable_name": name,
        "executable_digest": path_digest(executable),
        "create_time": create_time,
        "command_accessible": True,
        "command_digest": "bb" * 32,
        "argument_count": 1,
        "comfy_argument_markers_present": comfy_markers,
    }


def analyze(
    candidates,
    *,
    runtime_pid: int = 42,
    listeners=(42,),
    process_tree=None,
    launcher_create_time: float = 1.0,
    listener_bindings=(),
    run_id: str = RUN_ID,
):
    if process_tree is None:
        process_tree = tree(member(42, 7, 1.0))
    return analyze_process_ownership(
        candidates=candidates,
        launcher_pid=42,
        runtime_pid=runtime_pid,
        launcher_alive=True,
        launcher_create_time=launcher_create_time,
        runner_pid=7,
        listener_pids=listeners,
        run_id=run_id,
        phase="POST_LAUNCH",
        process_tree=process_tree,
        expected_executable=PYTHON,
        expected_main=MAIN,
        expected_host="127.0.0.1",
        expected_port=8191,
        expected_extra_config=CONFIG,
        expected_input=OUTPUT / "input",
        expected_output=OUTPUT / "output",
        expected_temp=OUTPUT / "temp",
        expected_user=OUTPUT / "user",
        listener_bindings=listener_bindings,
        trusted_console_executables=(TRUSTED_CONHOST,),
    )


class ComfyUIProcessOwnershipTests(unittest.TestCase):
    def test_exact_backend_command_is_parsed(self):
        parsed = parse_comfy_runtime(arguments())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["listen"], "127.0.0.1")
        self.assertEqual(parsed["port"], 8191)
        self.assertEqual(parsed["disable_auto_launch_count"], 1)

    def test_shell_text_containing_comfy_words_is_not_a_runtime(self):
        shell = [
            "powershell.exe",
            "-Command",
            "python probe.py --comfyui-root C:\\ComfyUI; source mentions main.py --listen",
        ]
        self.assertIsNone(parse_comfy_runtime(shell))

    def test_existing_single_pid_runtime_passes(self):
        receipt = analyze([candidate()])
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["launcher_pid"], 42)
        self.assertEqual(receipt["runtime_pid"], 42)
        self.assertEqual(receipt["listener_pid"], 42)
        self.assertIsNone(receipt["console_helper_pid"])
        self.assertEqual(
            receipt["console_helper_admission"]["reason"], "NOT_PRESENT_OPTIONAL"
        )
        self.assertEqual(receipt["foreign_processes"], [])

    def test_observed_windows_launcher_direct_child_runtime_passes(self):
        candidates = [
            candidate(42, parent_pid=7, create_time=1.0),
            candidate(84, parent_pid=42, create_time=2.0),
        ]
        receipt = analyze(
            candidates,
            runtime_pid=84,
            listeners=(84,),
            process_tree=tree(member(42, 7, 1.0), member(84, 42, 2.0)),
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["launcher_pid"], 42)
        self.assertEqual(receipt["runtime_pid"], 84)
        self.assertEqual(receipt["listener_pid"], 84)
        self.assertEqual(len(receipt["owned_processes"]), 2)

    def test_windows_launcher_runtime_and_trusted_console_helper_pass(self):
        candidates = [
            candidate(42, parent_pid=7, create_time=1.0),
            candidate(84, parent_pid=42, create_time=2.0),
        ]
        receipt = analyze(
            candidates,
            runtime_pid=84,
            listeners=(84,),
            process_tree=tree(
                member(42, 7, 1.0),
                member(84, 42, 2.0),
                member(
                    99,
                    42,
                    1.5,
                    name="conhost.exe",
                    executable=TRUSTED_CONHOST,
                ),
            ),
        )
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["console_helper_pid"], 99)
        self.assertEqual(
            receipt["console_helper_admission"]["reason"],
            "TRUSTED_WINDOWS_CONSOLE_HELPER",
        )

    def test_verified_descendant_listener_with_separate_runtime_role_passes(self):
        candidates = [
            candidate(42, parent_pid=7, create_time=1.0),
            candidate(84, parent_pid=42, create_time=2.0),
            candidate(126, parent_pid=84, create_time=3.0),
        ]
        receipt = analyze(
            candidates,
            runtime_pid=84,
            listeners=(126,),
            process_tree=tree(
                member(42, 7, 1.0),
                member(84, 42, 2.0),
                member(126, 84, 3.0),
            ),
        )
        self.assertTrue(receipt["passed"])

    def test_unrelated_child_fails_closed(self):
        receipt = analyze(
            [candidate()],
            process_tree=tree(member(42, 7, 1.0), member(99, 42, 2.0, name="cmd.exe")),
        )
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["tree_members_have_approved_roles"])

    def test_private_path_fake_conhost_fails_closed(self):
        receipt = analyze(
            [candidate()],
            process_tree=tree(
                member(42, 7, 1.0),
                member(
                    99,
                    42,
                    2.0,
                    name="conhost.exe",
                    executable=Path(r"C:\private\conhost.exe"),
                ),
            ),
        )
        self.assertFalse(receipt["passed"])
        self.assertEqual(
            receipt["console_helper_admission"]["reason"],
            "UNTRUSTED_WINDOWS_SYSTEM_PATH",
        )

    def test_console_helper_owning_any_listener_fails_closed(self):
        receipt = analyze(
            [candidate()],
            process_tree=tree(
                member(42, 7, 1.0),
                member(
                    99,
                    42,
                    2.0,
                    name="conhost.exe",
                    executable=TRUSTED_CONHOST,
                ),
            ),
            listener_bindings=({"pid": 99, "address": "127.0.0.1", "port": 9000},),
        )
        self.assertFalse(receipt["passed"])
        self.assertEqual(
            receipt["console_helper_admission"]["reason"],
            "CONSOLE_HELPER_OWNS_LISTENER",
        )

    def test_console_helper_with_comfy_arguments_fails_closed(self):
        receipt = analyze(
            [candidate()],
            process_tree=tree(
                member(42, 7, 1.0),
                member(
                    99,
                    42,
                    2.0,
                    name="conhost.exe",
                    executable=TRUSTED_CONHOST,
                    comfy_markers=True,
                ),
            ),
        )
        self.assertFalse(receipt["passed"])
        self.assertEqual(
            receipt["console_helper_admission"]["reason"],
            "COMFYUI_ARGUMENT_IMPERSONATION",
        )

    def test_foreign_listener_fails_closed(self):
        receipt = analyze([candidate()], listeners=(99,))
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["listener_candidate_present"])
        self.assertFalse(receipt["checks"]["role_pids_inside_tree"])

    def test_pid_reuse_creation_time_mismatch_fails_closed(self):
        candidates = [candidate(42), candidate(84, parent_pid=42, create_time=9.0)]
        receipt = analyze(
            candidates,
            runtime_pid=84,
            listeners=(84,),
            process_tree=tree(member(42, 7, 1.0), member(84, 42, 2.0)),
        )
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["candidate_creation_times_match_tree"])

    def test_console_helper_creation_time_change_breaks_lifecycle_continuity(self):
        post_launch = analyze(
            [candidate()],
            process_tree=tree(
                member(42, 7, 1.0),
                member(
                    99,
                    42,
                    2.0,
                    name="conhost.exe",
                    executable=TRUSTED_CONHOST,
                ),
            ),
        )
        pre_shutdown = deepcopy(post_launch)
        pre_shutdown["console_helper_process"]["create_time"] = 9.0
        continuity = h3_comfyui_launcher_child_ownership_v2_probe._continuity(
            post_launch, pre_shutdown
        )
        self.assertFalse(continuity["console_helper_identity_matches"])

    def test_command_path_mismatch_fails_closed(self):
        wrong_path = candidate()
        wrong_path["output_directory"] = r"C:\other\output"
        receipt = analyze([wrong_path])
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["output_directory_matches"])

    def test_run_identity_mismatch_fails_closed(self):
        receipt = analyze([candidate()], run_id="different-run")
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["run_id_bound_to_dedicated_paths"])

    def test_same_port_hijack_outside_tree_fails_closed(self):
        receipt = analyze([candidate(), candidate(99)], listeners=(99,))
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["foreign_runtime_count_zero"])
        self.assertFalse(receipt["checks"]["listener_is_launcher_or_verified_descendant"])

    def test_foreign_runtime_outside_tree_fails_closed(self):
        receipt = analyze([candidate(), candidate(84, port=8188)])
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["foreign_runtime_count_zero"])

    def test_unrelated_external_conhost_is_not_a_runtime_candidate(self):
        self.assertIsNone(
            parse_comfy_runtime([str(TRUSTED_CONHOST), "0xffffffff", "-ForceV1"])
        )

    def test_runtime_without_verified_parent_chain_fails_closed(self):
        candidates = [candidate(), candidate(84, parent_pid=99, create_time=2.0)]
        receipt = analyze(
            candidates,
            runtime_pid=84,
            listeners=(84,),
            process_tree=tree(member(42, 7, 1.0), member(84, 99, 2.0)),
        )
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["runtime_is_launcher_or_verified_descendant"])

    def test_launcher_creation_time_and_runner_parent_are_bound(self):
        wrong_parent = candidate(parent_pid=8)
        parent_receipt = analyze([wrong_parent])
        time_receipt = analyze([candidate()], launcher_create_time=2.0)
        self.assertFalse(parent_receipt["checks"]["root_parent_is_runner"])
        self.assertFalse(time_receipt["checks"]["launcher_creation_time_matches_popen"])

    @patch("hive_product.comfyui_process_ownership.os.getpid", return_value=7)
    @patch("hive_product.comfyui_process_ownership._process_tree")
    @patch("hive_product.comfyui_process_ownership._listener_pids", return_value=([], 0))
    @patch("hive_product.comfyui_process_ownership.collect_comfy_runtime_processes")
    def test_pre_launch_requires_zero_candidates_and_listener(
        self, collect, _listeners, process_tree, _pid
    ):
        collect.return_value = {
            "candidate_summaries": [],
            "candidate_count": 0,
            "access_error_count": 0,
        }
        process_tree.return_value = tree(member(7, 1, 1.0)) | {"root_pid": 7}
        receipt = build_pre_launch_receipt(run_id=RUN_ID, host="127.0.0.1", port=8191)
        self.assertTrue(receipt["passed"])

    @patch("hive_product.comfyui_process_ownership.psutil.Process")
    @patch("hive_product.comfyui_process_ownership._listener_pids", return_value=([], 0))
    @patch("hive_product.comfyui_process_ownership.collect_comfy_runtime_processes")
    def test_post_shutdown_uses_pid_and_creation_time_identity(
        self, collect, _listeners, process
    ):
        collect.return_value = {
            "candidates": [],
            "candidate_summaries": [],
            "candidate_count": 0,
        }
        process.side_effect = psutil.NoSuchProcess(42)
        receipt = build_post_shutdown_receipt(
            run_id=RUN_ID,
            owned_processes=[{"pid": 42, "create_time": 1.0}],
            host="127.0.0.1",
            port=8191,
            baseline_gpu_bytes=None,
            current_gpu_bytes=None,
            require_gpu_baseline=False,
            console_helper_process={
                "pid": 99,
                "create_time": 2.0,
                "executable_name": "conhost.exe",
                "executable_digest": path_digest(TRUSTED_CONHOST),
            },
        )
        self.assertTrue(receipt["passed"])
        self.assertTrue(receipt["checks"]["console_helper_naturally_absent"])

    @patch("hive_product.comfyui_process_ownership.psutil.Process")
    def test_verified_shutdown_targets_only_descendants_in_receipt(self, process):
        stopped = []

        class FakeProcess:
            def create_time(self):
                return 2.0

            def terminate(self):
                stopped.append(84)

            def wait(self, timeout):
                self.timeout = timeout

        process.return_value = FakeProcess()
        receipt = analyze(
            [candidate(), candidate(84, parent_pid=42, create_time=2.0)],
            runtime_pid=84,
            listeners=(84,),
            process_tree=tree(
                member(42, 7, 1.0),
                member(84, 42, 2.0),
                member(
                    99,
                    42,
                    1.5,
                    name="conhost.exe",
                    executable=TRUSTED_CONHOST,
                ),
            ),
        )
        result = stop_verified_runtime_descendants(receipt)
        self.assertEqual(stopped, [84])
        self.assertEqual(result["console_helper_pid"], 99)
        self.assertEqual(result["console_helper_direct_termination_count"], 0)
        self.assertEqual(result["foreign_process_termination_count"], 0)
        process.assert_called_once_with(84)

    def test_shutdown_rejects_failed_receipt(self):
        with self.assertRaisesRegex(RuntimeError, "passing ownership receipt"):
            stop_verified_runtime_descendants({"passed": False})

    @patch("hive_product.comfyui_process_ownership.psutil.Process")
    def test_console_helper_natural_exit_never_terminates_process(self, process):
        process.side_effect = psutil.NoSuchProcess(99)
        result = wait_for_console_helper_exit(
            {"pid": 99, "create_time": 2.0}, timeout_seconds=0.0
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "natural_exit_observed")
        self.assertEqual(result["direct_termination_count"], 0)

    def test_lifecycle_probe_has_no_generation_submission_path(self):
        source = "\n".join(
            Path(module.__file__).read_text(encoding="utf-8")
            for module in (
                h3_comfyui_launcher_child_ownership_v2_probe,
                h3_comfyui_console_helper_ownership_v2_probe,
            )
        )
        self.assertNotIn('"/prompt"', source)
        self.assertNotIn("build_api_workflow", source)
        self.assertNotIn("create_job", source)


if __name__ == "__main__":
    unittest.main()
