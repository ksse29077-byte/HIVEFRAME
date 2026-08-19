from __future__ import annotations

import importlib.util
import inspect
import sqlite3
import unittest

from hive_product.a3_g1_conditional_reuse import CONTROL_MODE
from hive_product.h3_row_region_safety import (
    CACHE_HARD_CAP_BYTES,
    EVIDENCE_BLOCKS,
    EVIDENCE_KEYS,
    FULL_Q_ROWS,
    MAX_EVIDENCE_RECORDS,
    TRANSFER_BUDGET_BYTES,
    H3RowRegionSafetyController,
    evidence_design_receipt,
    generation_candidates,
    generation_identity,
    settings_digest,
)
from hive_product.h3_row_region_safety_control_probe import (
    NODE_CLASS,
    _select_p1_a2_prompt,
    build_workflow,
)
from hive_product.rust_cache_plan_v2 import PLAN_READY, RustCachePlanV2Bridge


def identity():
    return generation_identity(
        run_digest_hex="11" * 32,
        workflow_digest_hex="22" * 32,
        model_digest_hex="33" * 32,
        settings_digest_hex=settings_digest(),
        input_identity_digest_hex="44" * 32,
    )


def evidence(block: int, source_step: int, *, region: int = 0, state: str = "STABLE"):
    payloads = evidence_design_receipt()["payload_bytes_by_region"]
    return {
        "step": source_step + 1,
        "source_step": source_step,
        "block": block,
        "region": region,
        "predicted_state": state,
        "uncertainty_ppm": 10_000,
        "motion_ppm": 20_000,
        "payload_bytes": payloads[region],
        "corrected": {
            "cosine": 0.99,
            "normalized_l2": 0.1,
            "normalized_mae": 0.1,
            "energy_ratio": 1.0,
            "finite": True,
        },
        "actual_safety": "SAFE",
        "false_safe": False,
        "false_unsafe": state != "STABLE",
    }


class H3RowRegionSafetyControlTests(unittest.TestCase):
    def test_evidence_design_is_exactly_bounded(self):
        design = evidence_design_receipt()
        self.assertEqual(len(EVIDENCE_KEYS), 40)
        self.assertEqual(len(EVIDENCE_BLOCKS), 34)
        self.assertEqual(design["maximum_records"], MAX_EVIDENCE_RECORDS)
        self.assertEqual(design["cache_bytes"], 1_889_398_784)
        self.assertLessEqual(design["cache_bytes"], CACHE_HARD_CAP_BYTES)
        self.assertEqual(TRANSFER_BUDGET_BYTES, 40 * 1024**3)

    def test_control_hook_never_invokes_partial_attention(self):
        source = inspect.getsource(H3RowRegionSafetyController._observe_full_compute_control)
        self.assertNotIn("attention_core(", source)
        self.assertNotIn("_prepare_direct_reuse", source)
        self.assertEqual(CONTROL_MODE, "CONTROL_A3_G1D_MIXED_STATE_REGIONAL_REUSE")

    def test_workflow_is_i2v_full_compute_control(self):
        standard = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
            "10": {"class_type": "SamplerCustomAdvanced", "inputs": {}},
        }
        workflow = build_workflow(
            standard,
            run_digest="55" * 32,
            first_frame_name="reference.png",
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(workflow["10"]["inputs"]["mode"], CONTROL_MODE)
        self.assertEqual(workflow["16"]["class_type"], "LoadImage")
        self.assertEqual(workflow["8"]["inputs"]["first_frame"], ["16", 0])

    def test_generation_batch_rejects_overflow_instead_of_truncating(self):
        values = [evidence(0, index % 16) for index in range(MAX_EVIDENCE_RECORDS + 1)]
        with self.assertRaises(ValueError):
            generation_candidates(identity(), values)

    def test_p1_a2_prompt_selection_is_exact_and_not_first_success(self):
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """CREATE TABLE jobs (
                created_at TEXT, backend TEXT, status TEXT, profile TEXT,
                generation_mode TEXT, reference_asset_id TEXT, prompt TEXT
            )"""
        )
        connection.executemany(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ("1", "minimax_h3_comfyui_local", "succeeded", "standard", "text_to_video", None, "wrong"),
                ("2", "minimax_h3_comfyui_local", "succeeded", "standard", "image_to_video", "asset", "fixed"),
            ),
        )
        prompt, digest = _select_p1_a2_prompt(connection)
        connection.close()
        self.assertEqual(prompt, "fixed")
        self.assertEqual(len(digest), 64)

    def test_candidate_lineage_and_scalar_layout_are_complete(self):
        record = generation_candidates(identity(), [evidence(0, 1)])[0]
        self.assertEqual(record["state"], 1)
        self.assertEqual(record["actual_safety_state"], 1)
        self.assertEqual(record["cache_age"], 1)
        self.assertEqual(len(record["lineage_digest"]), 32)
        self.assertEqual(record["planned_d2h_bytes"], record["payload_bytes"])
        self.assertEqual(record["planned_h2d_bytes"], record["payload_bytes"])

    @unittest.skipUnless(importlib.util.find_spec("_hive_retina_boundary"), "PyO3 extension not built")
    def test_real_rust_replay_admits_three_percent_without_risk_blocks(self):
        import _hive_retina_boundary as boundary

        identity_value = identity()
        values = [
            evidence(block, source_step)
            for block in range(32)
            for source_step in range(1, 8)
        ]
        records = generation_candidates(identity_value, values)
        first = RustCachePlanV2Bridge(boundary).compile_generation(
            identity=identity_value,
            candidates=records,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        second = RustCachePlanV2Bridge(boundary).compile_generation(
            identity=identity_value,
            candidates=records,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="balanced_12gb",
        )
        self.assertEqual(first["decision_code"], PLAN_READY)
        self.assertGreaterEqual(first["planned_reduction_ppm"], 30_000)
        self.assertLessEqual(first["total_selected_bytes"], CACHE_HARD_CAP_BYTES)
        self.assertLessEqual(
            first["total_planned_d2h_bytes"] + first["total_planned_h2d_bytes"],
            TRANSFER_BUDGET_BYTES,
        )
        self.assertEqual(first["plan_digest"], second["plan_digest"])
        self.assertEqual(first["selected"], second["selected"])


if __name__ == "__main__":
    unittest.main()
