from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import (
    FROZEN_EVENTS,
    HOST_SOURCE_BUDGET_BYTES,
    HOST_SOURCE_RESIDENT_BYTES,
    MINIMUM_EXACT_RECORDS,
    MINIMUM_PLANNED_Q_RATIO,
    SOURCE_BLOCKS,
    SOURCE_STEPS,
)
from hive_product.h3_bounded_host_source_oracle_v4_cuda import (
    gpu_compressed_fingerprint,
    gpu_exact_oracle_metrics,
    gpu_exact_oracle_metrics_indexed,
    gpu_indexed_compressed_fingerprint,
)
from hive_product.a3_g1_conditional_reuse import CONTROL_MODE
from hive_product.h3_observer_v4 import (
    H3ObserverControllerV4,
    PROFILE_DIGEST,
    SOURCE_CAPTURE_COUNT,
    V4ObserverAbort,
)
from hive_product.h3_observer_v4_control_probe import (
    ADMISSION_BLOCKED,
    NODE_CLASS,
    NOT_VIABLE,
    VALIDATED,
    _p1_a2_profile_receipt,
    _performance_receipt,
    build_workflow,
)


class H3ObserverV4Tests(unittest.TestCase):
    def test_frozen_runtime_inventory_is_exact(self):
        self.assertEqual(len(FROZEN_EVENTS), MINIMUM_EXACT_RECORDS)
        self.assertEqual(MINIMUM_EXACT_RECORDS, 199)
        self.assertEqual(SOURCE_CAPTURE_COUNT, 208)
        self.assertEqual(SOURCE_CAPTURE_COUNT, len(SOURCE_BLOCKS) * len(SOURCE_STEPS))
        self.assertGreaterEqual(MINIMUM_PLANNED_Q_RATIO, 0.03)
        self.assertLessEqual(HOST_SOURCE_RESIDENT_BYTES, HOST_SOURCE_BUDGET_BYTES)

    def test_lifecycle_is_generation_scoped_and_fail_closed(self):
        controller = H3ObserverControllerV4.__new__(H3ObserverControllerV4)
        controller.state = "created"
        controller.lifecycle = ["created"]
        controller._transition("admitted")
        controller.start_observing()
        controller._transition("finalizing")
        controller._transition("complete")
        self.assertEqual(
            controller.lifecycle,
            ["created", "admitted", "observing", "finalizing", "complete"],
        )
        with self.assertRaises(V4ObserverAbort):
            controller._transition("observing")

    def test_indexed_gpu_helpers_match_packed_helpers_on_small_tensor(self):
        import torch

        generator = torch.Generator().manual_seed(101)
        current = torch.randn((12, 8), generator=generator)
        packed_indices = torch.tensor([1, 3, 4, 7, 8, 10], dtype=torch.long)
        source = current.index_select(0, packed_indices).clone()
        source[2] += 0.125
        representative = torch.tensor([0, 2, 5], dtype=torch.long)
        omitted = torch.tensor([1, 3, 4], dtype=torch.long)
        packed_current = current.index_select(0, packed_indices)

        expected_fingerprint = gpu_compressed_fingerprint(
            torch, packed_current, representative
        )
        indexed_fingerprint = gpu_indexed_compressed_fingerprint(
            torch, current, packed_indices, representative
        )
        self.assertTrue(torch.equal(expected_fingerprint, indexed_fingerprint))

        expected = gpu_exact_oracle_metrics(
            torch, source, packed_current, representative, omitted
        )
        indexed = gpu_exact_oracle_metrics_indexed(
            torch, source, current, packed_indices, representative, omitted
        )
        self.assertTrue(torch.equal(expected, indexed))

    def test_hot_path_has_no_host_read_or_forced_cuda_sync(self):
        source = "\n".join(
            inspect.getsource(function)
            for function in (
                H3ObserverControllerV4._observe_full_compute_control,
                H3ObserverControllerV4._refresh_cache,
                gpu_indexed_compressed_fingerprint,
                gpu_exact_oracle_metrics_indexed,
            )
        )
        for forbidden in (
            ".cpu(",
            ".item(",
            ".tolist(",
            ".numpy(",
            ".synchronize(",
        ):
            self.assertNotIn(forbidden, source)

    def test_controller_observes_after_exact_full_without_partial_execution(self):
        source = inspect.getsource(H3ObserverControllerV4)
        exact_position = source.index("result = super()._exact_full")
        observe_position = source.index("def _observe_full_compute_control")
        self.assertLess(exact_position, observe_position)
        self.assertIn('"selective_execution_count": 0', source)
        self.assertIn('"partial_q_execution_count": 0', source)
        self.assertIn('"attention_omission_count": 0', source)
        self.assertIn('"output_mutation_zero"', source)
        self.assertIn("self._inventory_digest", source)

    def test_comfy_node_is_isolated_and_explicit_control_only(self):
        repository = Path(__file__).resolve().parents[2]
        node_path = (
            repository
            / "python"
            / "hive_product"
            / "comfyui_v4_nodes"
            / "hiveframe_h3_observer_v4"
            / "__init__.py"
        )
        common_node_path = (
            repository
            / "python"
            / "hive_product"
            / "comfyui_nodes"
            / "hiveframe_h3_observer_v4"
            / "__init__.py"
        )
        source = node_path.read_text(encoding="utf-8")
        self.assertTrue(node_path.is_file())
        self.assertFalse(common_node_path.exists())
        self.assertIn("mode != CONTROL_MODE", source)
        self.assertIn("observer_profile_digest != PROFILE_DIGEST", source)
        self.assertNotIn("h3_row_region_safety_v2", source)
        self.assertNotIn("H3V2PinnedRingResources", source)
        self.assertEqual(len(PROFILE_DIGEST), 64)

    def test_workflow_replaces_only_standard_sampler_and_adds_first_frame(self):
        standard = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["5", 0],
                    "guider": ["9", 0],
                    "sampler": ["7", 0],
                    "sigmas": ["6", 0],
                    "latent_image": ["8", 1],
                },
            },
        }
        workflow = build_workflow(
            standard, run_digest="a" * 64, first_frame_name="frame.png"
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(workflow["10"]["inputs"]["mode"], CONTROL_MODE)
        self.assertEqual(
            workflow["10"]["inputs"]["observer_profile_digest"], PROFILE_DIGEST
        )
        self.assertEqual(workflow["8"]["inputs"]["first_frame"], ["16", 0])
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")

    def test_p1_a2_profile_accepts_frame_count_alias_only(self):
        profile = {
            "width": 864,
            "height": 480,
            "frame_count": 124,
            "fps": 24,
            "steps": 20,
            "seed": 101,
            "sampler": "res_multistep",
            "scheduler": "simple",
            "sage_enabled": False,
        }
        repository = Path(__file__).resolve().parents[2]
        temporary_root = repository / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        path = temporary_root / "observer-v4-p1-a2-receipt.json"
        try:
            path.write_text(json.dumps({"nested": {"profile": profile}}), encoding="utf-8")
            self.assertTrue(_p1_a2_profile_receipt(path)["passed"])
        finally:
            path.unlink(missing_ok=True)

    def test_performance_decision_excludes_control_only_exact_oracle(self):
        callback = {
            "attention_execution": {
                "v4_oracle": {
                    "timing_ms": {
                        "full_attention": 100_000.0,
                        "observer": 3_500.0,
                        "exact_gpu_oracle": 3_000.0,
                        "source_d2h": 500.0,
                        "candidate_h2d": 400.0,
                    }
                }
            }
        }
        performance = _performance_receipt(
            callback=callback, sampler_seconds=490.0, submit_seconds=590.0
        )
        self.assertEqual(performance["projected_production_observer_cost_ms"], 1_000.0)
        self.assertGreater(performance["projected_production_net_ms"], 0.0)

    def test_runner_source_enforces_single_submission_and_terminal_decisions(self):
        import hive_product.h3_observer_v4_control_probe as runner

        source = inspect.getsource(runner.run_control)
        self.assertEqual(source.count('receipt["submission_count"] = 1'), 1)
        self.assertEqual(source.count("_collect_websocket_run("), 1)
        self.assertNotIn("lineage_diagnostic", source)
        self.assertIn("custom_nodes_root=repository", source)
        self.assertIn("comfyui_v4_nodes", source)
        self.assertEqual(VALIDATED, "H3_V4_OBSERVER_RUNTIME_AND_FORMAL_CONTROL_VALIDATED")
        self.assertEqual(NOT_VIABLE, "H3_COMPOUND_EYE_PATH_NOT_YET_PRODUCT_VIABLE")
        self.assertEqual(ADMISSION_BLOCKED, "H3_V4_FORMAL_CONTROL_ADMISSION_BLOCKED")


if __name__ == "__main__":
    unittest.main()
