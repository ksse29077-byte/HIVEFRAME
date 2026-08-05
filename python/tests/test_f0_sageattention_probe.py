from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest

from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend
from hive_product.sageattention_probe import (
    MODEL_CONSUMERS,
    SAGE_NODE_CLASS,
    SAGE_NODE_ID,
    SageAttentionAutoComfyUIBackend,
    _load_private_prompt,
    _public_result,
    _safe_run_root,
    apply_sageattention_auto,
    workflow_patch_summary,
)


REQUEST = {"content": [{"type": "text", "text": "fixture prompt"}]}


class F0SageAttentionProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = MiniMaxH3ComfyUIBackend(client=object())
        self.standard = self.backend.build_api_workflow(REQUEST, output_prefix="hiveframe/f0-standard")

    def test_standard_has_zero_sage_nodes(self) -> None:
        self.assertEqual(sum(node.get("class_type") == SAGE_NODE_CLASS for node in self.standard.values()), 0)
        for consumer in MODEL_CONSUMERS:
            self.assertEqual(self.standard[consumer]["inputs"]["model"], ["1", 0])

    def test_sage_copy_adds_exactly_one_node_and_rewires_both_consumers(self) -> None:
        original = deepcopy(self.standard)
        sage = apply_sageattention_auto(self.standard)
        self.assertEqual(self.standard, original)
        self.assertEqual(sum(node.get("class_type") == SAGE_NODE_CLASS for node in sage.values()), 1)
        self.assertEqual(
            sage[SAGE_NODE_ID],
            {
                "class_type": SAGE_NODE_CLASS,
                "inputs": {"model": ["1", 0], "sage_attention": "auto", "allow_compile": False},
            },
        )
        for consumer in MODEL_CONSUMERS:
            self.assertEqual(sage[consumer]["inputs"]["model"], [SAGE_NODE_ID, 0])

    def test_workflow_patch_rejects_unexpected_model_edge(self) -> None:
        broken = deepcopy(self.standard)
        broken["9"]["inputs"]["model"] = ["99", 0]
        with self.assertRaisesRegex(ValueError, "unexpected MODEL edge"):
            apply_sageattention_auto(broken)

    def test_workflow_summary_locks_the_only_difference(self) -> None:
        sage = apply_sageattention_auto(self.standard)
        summary = workflow_patch_summary(self.standard, sage)
        self.assertEqual(summary["standard_sage_node_count"], 0)
        self.assertEqual(summary["sage_sage_node_count"], 1)
        self.assertEqual(summary["rewired_model_consumers"], ["6", "9"])
        mutated = deepcopy(sage)
        mutated["8"]["inputs"]["length"] = 17
        with self.assertRaisesRegex(ValueError, "declared one-node patch"):
            workflow_patch_summary(self.standard, mutated)

    def test_sage_backend_uses_patcher_and_standard_fallback_is_unchanged(self) -> None:
        sage_backend = SageAttentionAutoComfyUIBackend(client=object())
        sage = sage_backend.build_api_workflow(REQUEST, output_prefix="hiveframe/f0-sage")
        self.assertEqual(sage[SAGE_NODE_ID]["inputs"]["sage_attention"], "auto")
        new_standard = self.backend.build_api_workflow(REQUEST, output_prefix="hiveframe/f0-standard")
        self.assertNotIn(SAGE_NODE_ID, new_standard)
        self.assertEqual(new_standard["8"]["inputs"]["length"], 124)
        self.assertEqual(new_standard["6"]["inputs"]["steps"], 20)
        self.assertEqual(new_standard["5"]["inputs"]["noise_seed"], 101)

    def test_standard_error_normalization_and_polling_remain_bounded(self) -> None:
        timeout = self.backend.normalize_error(TimeoutError("fixture"))
        failure = self.backend.normalize_error(RuntimeError("fixture"))
        self.assertEqual(timeout.code, "timeout")
        self.assertTrue(timeout.retryable)
        self.assertEqual(failure.code, "generation_failed")
        self.assertGreater(self.backend.poll_interval_seconds, 0)
        self.assertGreater(self.backend.poll_timeout_seconds, self.backend.poll_interval_seconds)

    def test_private_prompt_reader_returns_hash_without_mutating_database(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-f0-test-") as temporary:
            database = Path(temporary) / "p0.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE jobs (backend TEXT, status TEXT, created_at TEXT, prompt TEXT)")
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?)",
                ("minimax_h3_comfyui_local", "succeeded", "2026-08-05", "private fixture prompt"),
            )
            connection.commit()
            connection.close()
            before = database.read_bytes()
            prompt, digest = _load_private_prompt(database)
            self.assertEqual(prompt, "private fixture prompt")
            self.assertEqual(len(digest), 64)
            self.assertEqual(database.read_bytes(), before)

    def test_run_root_collision_is_blocked_before_runtime(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-f0-test-") as temporary:
            root = Path(temporary) / "run"
            root.mkdir()
            (root / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already contains artifacts"):
                _safe_run_root(root, "f0-standard-001")

    def test_public_result_excludes_prompt_and_paths(self) -> None:
        private = {
            "run_id": "f0-standard-001",
            "mode": "standard",
            "terminal_status": "succeeded",
            "prompt_sha256": "a" * 64,
            "receipt": {"metrics": {"total_wall_seconds": {"value": 1.0}}},
            "result": {"private_path": "C:/private/output.mp4", "sha256": "b" * 64, "size_bytes": 10},
            "private_prompt": "do not publish",
        }
        public = _public_result(private)
        dump = json.dumps(public)
        self.assertNotIn("private/output", dump)
        self.assertNotIn("do not publish", dump)
        self.assertEqual(public["result_sha256"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
