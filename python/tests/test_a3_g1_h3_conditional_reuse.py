from __future__ import annotations

from pathlib import Path
import inspect
import json
import unittest

import torch

import hive_product.a3_g1_conditional_reuse as g1
from hive_product.active_query_attention import REGIONAL_ACTIVE_QUERY
from hive_product.a3_g1_h3_conditional_probe import NODE_CLASS, build_workflow
from hive_product.attention_output_reuse import cache_budget_plan, make_cache_lineage
from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend
from hive_product.regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


def plan(*, step=5, stable=1, active=0, uncertain=0, refresh=0, **overrides):
    payload = {
        "target_step": step,
        "decision_code": REGIONAL_ACTIVE_QUERY,
        "stable_region_mask": stable,
        "active_mask": active,
        "uncertain_mask": uncertain,
        "refresh_region_mask": refresh,
        "source_valid": True,
        "prediction_valid": True,
        "fallback_used": False,
    }
    payload.update(overrides)
    return payload


def admitted_control_execution():
    return {
        "control_full_output_original": True,
        "partial_attention_calls": 0,
        "conditional_graph_used": False,
        "gpu_same_block_guard_used": False,
        "static_qkv_used": False,
        "admitted_block_count": 3,
        "planned_q_reduction_ratio": 0.04,
        "affected_non_anchor_steps": [4, 5, 6],
        "stable_plan_event_count": 3,
        "false_safe_count": 0,
        "full_compute_fallback_preserved": True,
        "normal_partial_plus_full_count": 0,
        "exception_partial_then_full_count": 0,
        "rust": {"per_block_calls": 0, "per_token_calls": 0},
        "cache": {
            "full_size_gpu_staging_count": 0,
            "max_region_staging_bytes": g1.MAX_REGION_STAGING_BYTES,
        },
        "memory": {"correction_temp_peak": g1.MAX_CORRECTION_TEMP_BYTES},
    }


class A3G1CContractTests(unittest.TestCase):
    def test_01_contract_is_preplanned_and_default_disabled(self):
        contract = g1.fixed_contract()
        self.assertEqual(contract["execution_authority"], g1.EXECUTION_AUTHORITY)
        self.assertEqual(contract["rust_directives"], [g1.FORCE_FULL, g1.SELECTIVE_CANDIDATE])
        self.assertEqual(contract["execution_decision_point"], "BEFORE_ATTENTION")
        self.assertFalse(contract["product_default_enabled"])
        self.assertFalse(contract["conditional_graph_used"])
        self.assertFalse(contract["gpu_same_block_guard_used"])
        self.assertFalse(contract["static_qkv_used"])

    def test_02_settings_digest_is_stable_and_mode_specific(self):
        candidates = g1.A2_RANKED_BLOCKS[:3]
        self.assertEqual(
            g1.settings_digest(mode=g1.CONTROL_MODE, candidate_blocks=candidates),
            g1.settings_digest(mode=g1.CONTROL_MODE, candidate_blocks=candidates),
        )
        self.assertNotEqual(
            g1.settings_digest(mode=g1.CONTROL_MODE, candidate_blocks=candidates),
            g1.settings_digest(mode=g1.SELECTIVE_MODE, candidate_blocks=candidates),
        )

    def test_03_force_full_for_anchor_missing_or_late_plan(self):
        candidates = (0, 1, 2)
        self.assertEqual(g1.rust_directive(plan=plan(step=0), step=0, block_index=0, candidate_blocks=candidates, cache_ready=True)[0], g1.FORCE_FULL)
        self.assertEqual(g1.rust_directive(plan=None, step=5, block_index=0, candidate_blocks=candidates, cache_ready=True)[0], g1.FORCE_FULL)
        self.assertEqual(g1.rust_directive(plan=plan(step=4), step=5, block_index=0, candidate_blocks=candidates, cache_ready=True)[0], g1.FORCE_FULL)

    def test_04_force_full_for_uncertain_active_refresh_or_invalid_source(self):
        candidates = (0, 1, 2)
        cases = (
            plan(uncertain=1),
            plan(active=1),
            plan(refresh=1),
            plan(source_valid=False),
            plan(prediction_valid=False),
            plan(fallback_used=True),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(g1.rust_directive(plan=payload, step=5, block_index=0, candidate_blocks=candidates, cache_ready=True)[0], g1.FORCE_FULL)

    def test_05_missing_or_stale_cache_forces_full(self):
        directive, reason = g1.rust_directive(
            plan=plan(), step=5, block_index=0, candidate_blocks=(0, 1, 2), cache_ready=False
        )
        self.assertEqual(directive, g1.FORCE_FULL)
        self.assertEqual(reason, "cache_missing_stale_or_not_ready")

    def test_06_valid_plan_selects_partial_before_attention(self):
        directive, reason = g1.rust_directive(
            plan=plan(stable=3), step=5, block_index=0, candidate_blocks=(0, 1, 2), cache_ready=True
        )
        self.assertEqual((directive, reason), (g1.SELECTIVE_CANDIDATE, "preplanned_stable_cache_candidate"))

    def test_07_cache_lineage_prohibits_selective_chaining_and_age_two(self):
        self.assertIsNone(make_cache_lineage(block_index=0, source_step=4, source_kind="CORRECTED_ATTENTION_CORE_OUTPUT"))
        lineage = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertTrue(lineage.eligible(target_step=5, region=0))
        self.assertFalse(lineage.eligible(target_step=6, region=0))

    def test_08_host_cache_budget_keeps_fixed_candidate_order(self):
        cache = cache_budget_plan(available_host_bytes=64 * 1024**3, ranked_blocks=g1.A2_RANKED_BLOCKS)
        self.assertTrue(cache.admitted)
        self.assertGreaterEqual(len(cache.candidate_blocks), 3)
        self.assertEqual(cache.candidate_blocks, g1.A2_RANKED_BLOCKS)

    def test_09_region_staging_is_one_region_not_full_cache(self):
        maximum_rows = max(
            len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["representative"])
            + len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["omitted"])
            for region in range(4)
        )
        self.assertEqual(maximum_rows * 7168 * 2, g1.MAX_REGION_STAGING_BYTES)
        self.assertLess(g1.MAX_REGION_STAGING_BYTES, 172_390_400)

    def test_10_correction_chunk_bound_is_below_32_mib(self):
        peak = g1.correction_temp_bytes(rows=g1.CORRECTION_CHUNK_ROWS, width=7168, float_buffers=8)
        self.assertLessEqual(peak, g1.MAX_CORRECTION_TEMP_BYTES)

    def test_11_reconstruction_preserves_full_shape_and_dtype(self):
        selected = torch.tensor([[1.0, 2.0], [3.0, 4.0]], dtype=torch.bfloat16)
        indices = torch.tensor([0, 2])
        full = g1.reconstruct_selected_core(selected, indices, 3)
        self.assertEqual(full.shape, (3, 2))
        self.assertEqual(full.dtype, torch.bfloat16)
        self.assertTrue(torch.equal(full.index_select(0, indices), selected))

    def test_12_full_and_partial_accounting_is_xor(self):
        self.assertTrue(g1.attention_path_is_xor(full_calls=1, partial_calls=0))
        self.assertTrue(g1.attention_path_is_xor(full_calls=0, partial_calls=1))
        self.assertFalse(g1.attention_path_is_xor(full_calls=1, partial_calls=1))
        self.assertFalse(g1.attention_path_is_xor(full_calls=0, partial_calls=0))

    def test_13_work_accounting_exposes_real_q_reduction(self):
        result = g1.work_accounting(
            full_q_rows_theoretical=1000,
            forced_full_q_rows=600,
            partial_q_rows=300,
            reused_omitted_rows=100,
        )
        self.assertEqual(result["actual_attention_q_rows"], 900)
        self.assertAlmostEqual(result["actual_q_reduction_ratio"], 0.1)

    def test_14_control_gate_accepts_only_original_full_counterfactual(self):
        result = g1.control_opportunity_gate(
            execution=admitted_control_execution(),
            region_plan={"tensor_bytes_to_rust": 0},
            c2_shadow={"total_shadow_callback": {"p95_ns": 10}},
            output_integrity=True,
            cache_capacity=3,
        )
        self.assertTrue(result["passed"])
        failed = admitted_control_execution()
        failed["false_safe_count"] = 1
        result = g1.control_opportunity_gate(
            execution=failed,
            region_plan={"tensor_bytes_to_rust": 0},
            c2_shadow={"total_shadow_callback": {"p95_ns": 10}},
            output_integrity=True,
            cache_capacity=3,
        )
        self.assertEqual(result["decision"], g1.DECISION_PREPLAN_NOT_SAFE)

    def test_15_source_has_no_conditional_graph_guard_or_runtime_capture(self):
        source = inspect.getsource(g1)
        self.assertNotIn("GPUConditionalAttentionIsland", source)
        self.assertNotIn("CUDAGraph", source)
        self.assertNotIn("gpu_guard_metrics", source)
        self.assertNotIn("aggregate_all_safe", source)
        self.assertNotIn(".capture(", source)

    def test_16_selective_uses_one_partial_call_and_reuses_representative(self):
        source = inspect.getsource(g1.H3A3G1Controller._prepare_direct_reuse)
        self.assertEqual(source.count("attention_core("), 1)
        self.assertEqual(source.count("_channel_mean_delta("), 1)
        self.assertNotIn("_exact_full(", source)

    def test_17_config_and_backend_remain_experimental(self):
        root = Path(__file__).resolve().parents[2]
        payload = json.loads((root / "configs" / "a3_g1_h3_conditional_attention_reuse.json").read_text(encoding="utf-8"))
        self.assertFalse(payload["product_default_enabled"])
        self.assertFalse(payload["conditional_graph_used"])
        self.assertEqual(payload["cache"]["maximum_gpu_staging_bytes"], g1.MAX_REGION_STAGING_BYTES)
        capability = MiniMaxH3ComfyUIBackend.experimental_capabilities["real_h3_preplan_direct_selective_reuse_v1"]
        self.assertFalse(capability["default_enabled"])
        self.assertEqual(capability["fallback"], "standard_full_compute")

    def test_18_workflow_uses_repository_preplan_node_without_mutating_input(self):
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {}}}
        candidates = g1.A2_RANKED_BLOCKS[:3]
        workflow = build_workflow(
            standard,
            mode=g1.CONTROL_MODE,
            candidate_blocks=candidates,
            run_digest="model-free-run-digest",
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(NODE_CLASS, "HIVEFRAMEH3PreplanDirectSelectiveReuseSampler")
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")


if __name__ == "__main__":
    unittest.main()
