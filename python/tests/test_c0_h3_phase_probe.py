from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend
from hive_product.c0_h3_phase_probe import (
    EventTimeline,
    HOOK_STATES,
    _safe_run_root,
    public_result,
    sanitize_public,
    validate_hook_map,
)


class C0H3PhaseProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        backend = MiniMaxH3ComfyUIBackend(client=object())
        self.workflow = backend.build_api_workflow(
            {"content": [{"type": "text", "text": "fixture prompt"}]},
            output_prefix="hiveframe/c0-fixture",
        )
        self.timeline = EventTimeline(self.workflow, prompt_id="p1", submitted_monotonic=100.0)

    def ingest(self, event_type: str, second: float, **data) -> None:
        payload = {"prompt_id": "p1", **data}
        self.timeline.ingest({"type": event_type, "data": payload}, 100.0 + second)

    def complete_fixture(self) -> None:
        self.ingest("execution_start", 0.05)
        self.ingest("execution_cached", 0.06, nodes=[])
        self.ingest("executing", 0.10, node="1")
        self.ingest("executing", 0.20, node="2")
        self.ingest("executing", 0.30, node="3")
        self.ingest("executing", 0.40, node="4")
        self.ingest("executing", 0.50, node="5")
        self.ingest("executing", 0.60, node="6")
        self.ingest("executing", 0.70, node="7")
        self.ingest("executing", 0.80, node="8")
        self.ingest("executing", 1.80, node="9")
        self.ingest("executing", 1.90, node="10")
        self.ingest("progress", 3.90, node="10", value=1, max=3)
        self.ingest("progress", 5.90, node="10", value=2, max=3)
        self.ingest("progress", 8.90, node="10", value=3, max=3)
        self.ingest("executing", 9.00, node="11")
        self.ingest("executing", 10.00, node="12")
        self.ingest("executing", 11.00, node="13")
        self.ingest("executing", 11.50, node="14")
        self.ingest("executed", 12.00, node="14")
        self.ingest("execution_success", 12.10)

    def test_websocket_event_parser_builds_all_node_boundaries(self) -> None:
        self.complete_fixture()
        nodes = {node["node_id"]: node for node in self.timeline.node_timeline()}
        self.assertEqual(len(nodes), 14)
        self.assertAlmostEqual(nodes["10"]["observed_wall_seconds"], 7.1)
        self.assertTrue(nodes["14"]["output_observed"])
        self.assertEqual(self.timeline.terminal_event, "execution_success")

    def test_progress_intervals_are_not_claimed_as_exact_step_time(self) -> None:
        self.complete_fixture()
        progress = self.timeline.progress_summary()
        self.assertEqual(progress["semantic"], "observed_progress_interval")
        self.assertEqual(progress["not_claimed_as"], "exact GPU denoising step duration")
        self.assertEqual(progress["interval_count"], 3)
        self.assertEqual(progress["mean_seconds"], 7 / 3)
        self.assertEqual(progress["median_seconds"], 2.0)

    def test_phase_attribution_has_parent_scope_and_nonnegative_unattributed(self) -> None:
        self.complete_fixture()
        phase = self.timeline.phase_attribution(
            runner_total_seconds=15.0,
            runtime_startup_seconds=1.0,
            result_collection_seconds=0.5,
            shutdown_seconds=0.5,
        )
        self.assertEqual(phase["scope"], "runner entry through owned runtime stop")
        self.assertGreater(phase["phases"]["denoising"]["seconds"], 0)
        self.assertGreaterEqual(phase["unattributed_seconds"], 0)
        self.assertIn("lazy model materialization", phase["phases"]["denoising"]["note"])

    def test_resource_samples_associate_with_current_node_and_step(self) -> None:
        self.ingest("executing", 1.0, node="10")
        self.ingest("progress", 2.0, node="10", value=1, max=20)
        context = self.timeline.active_context()
        self.assertEqual(context, {"node_id": "10", "step": 1, "step_max": 20})

    def test_hook_status_schema_rejects_unknown_state(self) -> None:
        hook = {
            "hook_id": "sampler.callback",
            "status": "controllable_now",
            "h3_specific": False,
            "backend_independent": True,
            "expected_overhead": "low",
            "data_copied": False,
            "gpu_synchronization": False,
            "cache_candidate": True,
            "invalidation_required": True,
            "full_compute_fallback": True,
            "rust_ffi_fit": "coarse-control-only",
            "compound_eye_connection": "execution-plan gate",
        }
        validate_hook_map([hook])
        self.assertIn(hook["status"], HOOK_STATES)
        hook["status"] = "invented"
        with self.assertRaisesRegex(ValueError, "unsupported hook status"):
            validate_hook_map([hook])

    def test_public_sanitizer_removes_prompt_and_absolute_paths(self) -> None:
        value = {
            "prompt": "private fixture",
            "private_path": r"C:\private\output.mp4",
            "nested": {"message": r"C:\Users\person\file", "logical": "C0_OUTPUT"},
        }
        public = sanitize_public(value)
        dump = json.dumps(public)
        self.assertNotIn("private fixture", dump)
        self.assertNotIn("Users", dump)
        self.assertEqual(public["nested"]["message"], "<private-path>")

    def test_standard_workflow_has_zero_sage_nodes_and_fixed_profile(self) -> None:
        self.assertEqual(sum(node.get("class_type") == "PathchSageAttentionKJ" for node in self.workflow.values()), 0)
        self.assertEqual(self.workflow["8"]["inputs"]["length"], 124)
        self.assertEqual(self.workflow["6"]["inputs"]["steps"], 20)
        self.assertEqual(self.workflow["5"]["inputs"]["noise_seed"], 101)

    def test_failure_public_receipt_keeps_null_unavailable_and_no_private_path(self) -> None:
        receipt = {
            "schema_version": "c0.h3.phase.1",
            "run_id": "c0-test",
            "exit_code": 1,
            "generation_attempt_count": 0,
            "retry_count": 0,
            "sage_node_count": 0,
            "prompt_sha256": "a" * 64,
            "runner_error": "RuntimeError",
            "metrics": {
                "model_materialization_seconds": {
                    "value": None,
                    "support_status": "unavailable",
                    "unsupported_reason": "fixture",
                }
            },
            "private_path": r"C:\private\receipt.json",
        }
        public = public_result(receipt)
        self.assertEqual(public["terminal_status"], "failed")
        self.assertIsNone(public["metrics"]["model_materialization_seconds"]["value"])
        self.assertEqual(public["metrics"]["model_materialization_seconds"]["support_status"], "unavailable")
        self.assertNotIn("private_path", json.dumps(public))

    def test_run_root_collision_blocks_before_runtime(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-c0-") as temporary:
            root = Path(temporary) / "run"
            root.mkdir()
            (root / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already contains artifacts"):
                _safe_run_root(root, "c0-fixture-001")


if __name__ == "__main__":
    unittest.main()
