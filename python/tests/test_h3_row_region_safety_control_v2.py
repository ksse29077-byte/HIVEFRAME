from __future__ import annotations

import inspect
import unittest

import torch

from hive_product.h3_hybrid_cache_staging import (
    CONTROL_ORACLE_D2H_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PINNED_HOST_TOTAL_BYTES,
)
from hive_product.h3_row_region_safety import FULL_Q_ROWS, generation_candidates, generation_identity
from hive_product.h3_row_region_safety_control_v2_probe import (
    ADMISSION_BLOCKED,
    FAILED,
    NODE_CLASS,
    READY,
    build_workflow,
)
from hive_product.h3_row_region_safety_v2 import (
    CANDIDATE_BLOCKS,
    EXPECTED_ENQUEUE_COUNT,
    EXPECTED_RECORD_COUNT,
    HOLDOUT_LABEL,
    H3RowRegionSafetyControllerV2,
    HybridControlOracleWorker,
    OMITTED_POSITIONS,
    REPRESENTATIVE_POSITIONS,
    SLOT_SHAPE,
    VETO_BLOCKS,
    _chunked_metrics,
    evidence_design_receipt,
    settings_digest,
)


class H3RowRegionSafetyControlV2Tests(unittest.TestCase):
    def test_balanced_holdout_shape_and_budgets_are_exact(self):
        design = evidence_design_receipt()
        self.assertEqual(CANDIDATE_BLOCKS, tuple(range(30)))
        self.assertEqual(VETO_BLOCKS, frozenset({30, 31, 48, 49}))
        self.assertEqual(EXPECTED_ENQUEUE_COUNT, 600)
        self.assertEqual(EXPECTED_RECORD_COUNT, 480)
        self.assertEqual(design["label"], HOLDOUT_LABEL)
        self.assertEqual(design["expected_d2h_bytes"], CONTROL_ORACLE_D2H_BYTES)
        self.assertEqual(design["source_cache_bytes"], HOST_SOURCE_CACHE_BYTES)
        self.assertEqual(design["pinned_ring_bytes"], PINNED_HOST_TOTAL_BYTES)
        self.assertEqual(design["h2d_bytes"], 0)
        self.assertEqual(SLOT_SHAPE, (3367, 7168))

    def test_hot_path_has_no_host_read_or_forced_sync(self):
        source = inspect.getsource(HybridControlOracleWorker.enqueue)
        for forbidden in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize("):
            self.assertNotIn(forbidden, source)
        self.assertIn("non_blocking=True", source)
        self.assertIn("wait_event", source)

    def test_controller_is_full_compute_observer_only(self):
        refresh = inspect.getsource(H3RowRegionSafetyControllerV2._refresh_cache)
        observe = inspect.getsource(H3RowRegionSafetyControllerV2._observe_full_compute_control)
        for source in (refresh, observe):
            self.assertNotIn("attention_core(", source)
            self.assertNotIn("_prepare_direct_reuse", source)

    def test_cpu_metric_uses_real_representative_and_omitted_rows(self):
        self.assertEqual(len(REPRESENTATIVE_POSITIONS), 1036)
        self.assertEqual(len(OMITTED_POSITIONS), 2331)
        source = torch.zeros((3367, 8), dtype=torch.bfloat16)
        current = source.clone()
        current[list(REPRESENTATIVE_POSITIONS)] = 0.5
        current[list(OMITTED_POSITIONS)] = 0.5
        metrics = _chunked_metrics(torch, source, current)
        self.assertAlmostEqual(metrics["corrected"]["cosine"], 1.0, places=6)
        self.assertAlmostEqual(metrics["corrected"]["normalized_l2"], 0.0, places=6)
        self.assertTrue(metrics["corrected"]["finite"])

    def test_workflow_remains_standard_i2v_full_compute(self):
        standard = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
            "10": {"class_type": "SamplerCustomAdvanced", "inputs": {}},
        }
        workflow = build_workflow(
            standard, run_digest="55" * 32, first_frame_name="reference.png"
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(workflow["10"]["inputs"]["settings_digest"], settings_digest())
        self.assertEqual(workflow["8"]["inputs"]["first_frame"], ["16", 0])

    def test_decisions_and_full_q_baseline_are_frozen(self):
        self.assertEqual(READY, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_READY_FOR_EXECUTOR_INTEGRATION")
        self.assertEqual(FAILED, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_FAILED")
        self.assertEqual(ADMISSION_BLOCKED, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED")
        self.assertEqual(FULL_Q_ROWS, 15_424_000)

    def test_v2_record_maps_to_complete_tensor_free_rust_candidate(self):
        identity = generation_identity(
            run_digest_hex="11" * 32,
            workflow_digest_hex="22" * 32,
            model_digest_hex="33" * 32,
            settings_digest_hex=settings_digest(),
            input_identity_digest_hex="44" * 32,
        )
        evidence = {
            "step": 2,
            "source_step": 1,
            "block": 0,
            "region": 0,
            "predicted_state": "STABLE",
            "uncertainty_ppm": 1000,
            "motion_ppm": 2000,
            "payload_bytes": 48_269_312,
            "corrected": {"cosine": 0.999, "normalized_l2": 0.01, "finite": True},
            "actual_safety": "SAFE",
            "false_safe": False,
            "false_unsafe": False,
        }
        candidate = generation_candidates(identity, [evidence])[0]
        self.assertEqual(candidate["admission_eligible"], 1)
        self.assertEqual(candidate["planned_q_rows"], 2331)
        self.assertEqual(len(candidate["lineage_digest"]), 32)
        self.assertTrue(all(not isinstance(value, torch.Tensor) for value in candidate.values()))


if __name__ == "__main__":
    unittest.main()

