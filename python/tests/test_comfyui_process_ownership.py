from __future__ import annotations

from pathlib import Path
import unittest

from hive_product.comfyui_process_ownership import (
    analyze_process_ownership,
    parse_comfy_runtime,
)


ROOT = Path(r"C:\runtime\ComfyUI")
OUTPUT = Path(r"C:\private\control-v2")
PYTHON = ROOT / ".venv/Scripts/python.exe"
MAIN = ROOT / "main.py"
CONFIG = OUTPUT / "runtime/h3-extra-model-paths.yaml"


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


def candidate(pid: int = 42, *, port: int = 8191):
    value = parse_comfy_runtime(arguments(port))
    assert value is not None
    return {**value, "pid": pid, "parent_pid": 7, "process_name": "python.exe", "create_time": 1.0}


def analyze(candidates, *, backend_pid: int = 42, node_pid: int = 42, listeners=(42,)):
    return analyze_process_ownership(
        candidates=candidates,
        backend_pid=backend_pid,
        node_pid=node_pid,
        backend_alive=True,
        listener_pids=listeners,
        expected_executable=PYTHON,
        expected_main=MAIN,
        expected_host="127.0.0.1",
        expected_port=8191,
        expected_extra_config=CONFIG,
        expected_input=OUTPUT / "input",
        expected_output=OUTPUT / "output",
        expected_temp=OUTPUT / "temp",
        expected_user=OUTPUT / "user",
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

    def test_single_owned_process_with_matching_node_and_listener_passes(self):
        receipt = analyze([candidate()])
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["owned_process"]["pid"], 42)
        self.assertNotIn("executable", receipt["owned_process"])
        self.assertEqual(receipt["foreign_processes"], [])

    def test_node_pid_mismatch_fails_closed(self):
        receipt = analyze([candidate()], node_pid=99)
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["node_pid_matches_backend_pid"])

    def test_foreign_runtime_fails_even_when_owned_process_is_valid(self):
        receipt = analyze([candidate(), candidate(84, port=8188)])
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["foreign_runtime_count_zero"])
        self.assertEqual(receipt["foreign_processes"][0]["pid"], 84)

    def test_listener_pid_mismatch_fails_closed(self):
        receipt = analyze([candidate()], listeners=(84,))
        self.assertFalse(receipt["passed"])
        self.assertFalse(receipt["checks"]["listener_pid_matches_backend_pid"])

    def test_command_path_or_port_mismatch_fails_closed(self):
        wrong_path = candidate()
        wrong_path["output_directory"] = r"C:\other\output"
        path_receipt = analyze([wrong_path])
        port_receipt = analyze([candidate(port=8188)])
        self.assertFalse(path_receipt["checks"]["output_directory_matches"])
        self.assertFalse(port_receipt["checks"]["port_matches"])


if __name__ == "__main__":
    unittest.main()

