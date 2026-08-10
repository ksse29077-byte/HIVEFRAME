from __future__ import annotations

from pathlib import Path
import json
import unittest

import torch

from hive_product.active_query_attention import (
    ANCHOR_STEPS,
    REGION_LOCAL_ROWS,
    REGIONAL_ACTIVE_QUERY,
    VIDEO_TOKEN_COUNT,
)
from hive_product.attention_output_reuse import (
    ATTENTION_CORE_WIDTH,
    CACHE_LOCAL_ROWS,
    CONTROL_MODE,
    CORRECTION_ID,
    FULL_COMPUTE_ACTION,
    H3RegionalAttentionOutputReuseCapability,
    MAX_HOST_CACHE_BYTES,
    MECHANISM_ID,
    PER_BLOCK_GPU_STAGING_BYTES,
    PER_BLOCK_WORST_CASE_CACHE_BYTES,
    REUSE_ACTION,
    SELECTIVE_MODE,
    a2_full_ranking,
    cache_budget_plan,
    correction_tensors,
    fixed_contract,
    make_cache_lineage,
    metric_tensors,
    region_action,
    representative_guard_from_scalars,
    settings_digest,
    structural_admission,
)
from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend
from hive_product.regional_query_prototype_attention import (
    CPU_PROTOTYPE_PLANS,
    attention_core,
)


class TinyAttention:
    heads = 1


def reference_attention(q, k, v, _heads, **_kwargs):
    scores = torch.matmul(q, k.transpose(-1, -2)) / (q.shape[-1] ** 0.5)
    return torch.matmul(scores.softmax(dim=-1), v).transpose(1, 2).reshape(q.shape[0], q.shape[2], -1)


def selective_plan(*, stable=1, active=0, uncertain=0, refresh=0, anchor=False):
    return {
        "decision_code": REGIONAL_ACTIVE_QUERY,
        "stable_region_mask": stable,
        "active_mask": active,
        "uncertain_mask": uncertain,
        "refresh_region_mask": refresh,
        "anchor_step": anchor,
    }


class A3AttentionOutputReuseTests(unittest.TestCase):
    def test_01_fixed_contract_is_cache_only_current_q_reduction(self):
        contract = fixed_contract()
        self.assertEqual(contract["mechanism"], MECHANISM_ID)
        self.assertEqual(contract["correction"], CORRECTION_ID)
        self.assertEqual(contract["global_kv"], "FULL")
        self.assertEqual(contract["qkv_projection"], "FULL")
        self.assertEqual(contract["output_projection"], "FULL_ORIGINAL")
        self.assertFalse(contract["product_default_enabled"])

    def test_02_full_path_contract_preserves_every_non_attention_stage(self):
        contract = fixed_contract()
        self.assertEqual(contract["mlp"], "FULL")
        self.assertEqual(contract["vae"], "FULL")
        self.assertEqual(contract["audio"], "FULL")
        self.assertEqual(contract["tensor_bytes_to_rust"], 0)

    def test_03_cache_source_is_actual_full_compute_only(self):
        lineage = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertIsNotNone(lineage)
        self.assertTrue(lineage.eligible(target_step=5, region=0))

    def test_04_selective_or_corrected_output_never_becomes_cache_source(self):
        for source in ("SELECTIVE_ATTENTION_CORE_OUTPUT", "CORRECTED_ATTENTION_CORE_OUTPUT", "CACHE_DERIVED"):
            self.assertIsNone(make_cache_lineage(block_index=0, source_step=4, source_kind=source))

    def test_05_cache_age_is_exactly_one_source_interval(self):
        lineage = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertFalse(lineage.eligible(target_step=4, region=0))
        self.assertTrue(lineage.eligible(target_step=5, region=0))
        self.assertFalse(lineage.eligible(target_step=6, region=0))

    def test_06_active_region_is_full_compute(self):
        action = region_action(plan=selective_plan(stable=0, active=1), step=5, region=0, cache=None, runtime_guard_passed=True)
        self.assertEqual(action[0], FULL_COMPUTE_ACTION)

    def test_07_uncertain_region_is_full_compute(self):
        action = region_action(plan=selective_plan(stable=0, uncertain=1), step=5, region=0, cache=None, runtime_guard_passed=True)
        self.assertEqual(action[0], FULL_COMPUTE_ACTION)

    def test_08_halo_rows_never_enter_regional_interior_cache(self):
        cached = set(CACHE_LOCAL_ROWS)
        self.assertEqual(cached, set().union(*(set(rows) for rows in REGION_LOCAL_ROWS)))
        self.assertEqual(len(cached), sum(len(rows) for rows in REGION_LOCAL_ROWS))
        self.assertGreater(VIDEO_TOKEN_COUNT - len(cached), 0)

    def test_09_anchor_is_full_compute(self):
        cache = make_cache_lineage(block_index=0, source_step=0, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        for step in ANCHOR_STEPS:
            action = region_action(plan=selective_plan(stable=1), step=step, region=0, cache=cache, runtime_guard_passed=True)
            self.assertEqual(action[0], FULL_COMPUTE_ACTION)

    def test_10_stale_or_missing_cache_is_full_compute(self):
        stale = make_cache_lineage(block_index=0, source_step=2, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=stale, runtime_guard_passed=True)[0], FULL_COMPUTE_ACTION)
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=None, runtime_guard_passed=True)[0], FULL_COMPUTE_ACTION)

    def test_11_event_not_ready_is_full_compute(self):
        cache = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT", event_ready=False)
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=cache, runtime_guard_passed=True)[0], FULL_COMPUTE_ACTION)

    def test_12_representative_mapping_reuses_exact_a2_partition(self):
        for region in range(4):
            rows = CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]
            representative = set(rows["representative"])
            omitted = set(rows["omitted"])
            self.assertEqual(representative | omitted, set(REGION_LOCAL_ROWS[region]))
            self.assertFalse(representative & omitted)

    def test_13_current_representative_rows_match_full_attention_exactly(self):
        q = torch.tensor([[[1.0, 0.0]], [[0.0, 1.0]], [[1.0, 1.0]], [[0.5, 0.25]]])
        k, v = q * 0.5, q * 0.25
        full = attention_core(q=q, k=k, v=v, q_indices=None, attention=TinyAttention(), optimized_attention=reference_attention, transformer_options={})
        indices = torch.tensor([0, 2, 3])
        subset = attention_core(q=q, k=k, v=v, q_indices=indices, attention=TinyAttention(), optimized_attention=reference_attention, transformer_options={})
        self.assertTrue(torch.allclose(subset, full.index_select(0, indices), atol=1e-6))

    def test_14_attention_core_keeps_full_global_kv(self):
        shapes = []

        def capture(q, k, v, heads, **kwargs):
            shapes.append((q.shape[-2], k.shape[-2], v.shape[-2]))
            return reference_attention(q, k, v, heads, **kwargs)

        q = torch.randn(5, 1, 2)
        attention_core(q=q, k=q, v=q, q_indices=torch.tensor([0, 3]), attention=TinyAttention(), optimized_attention=capture, transformer_options={})
        self.assertEqual(shapes, [(2, 5, 5)])

    def test_15_channel_mean_delta_is_deterministic(self):
        current = torch.tensor([[3.0, 5.0], [5.0, 9.0]])
        cached = torch.tensor([[1.0, 2.0], [3.0, 6.0]])
        omitted = torch.tensor([[10.0, 20.0], [30.0, 40.0]])
        delta1, corrected1 = correction_tensors(current_representative=current, cached_representative=cached, cached_omitted=omitted)
        delta2, corrected2 = correction_tensors(current_representative=current, cached_representative=cached, cached_omitted=omitted)
        self.assertTrue(torch.equal(delta1, torch.tensor([2.0, 3.0])))
        self.assertTrue(torch.equal(delta1, delta2))
        self.assertTrue(torch.equal(corrected1, corrected2))

    def test_16_correction_cannot_cross_region_or_time_without_explicit_rows(self):
        for region in range(4):
            rows = CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]
            representatives = set(rows["representative"])
            frame_stride = 15 * 27
            for omitted, neighbors in zip(rows["omitted"], rows["neighbors"]):
                self.assertTrue(set(neighbors).issubset(representatives))
                self.assertTrue(all(value // frame_stride == omitted // frame_stride for value in neighbors))

    def test_17_nonfinite_or_failed_runtime_guard_is_full_compute(self):
        self.assertFalse(representative_guard_from_scalars(cosine=float("nan"), normalized_l2=0.0, finite=False))
        cache = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=cache, runtime_guard_passed=False)[0], FULL_COMPUTE_ACTION)

    def test_18_layout_or_digest_mismatch_is_full_compute(self):
        cache = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=cache, runtime_guard_passed=True, layout_valid=False)[0], FULL_COMPUTE_ACTION)
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=cache, runtime_guard_passed=True, digest_valid=False)[0], FULL_COMPUTE_ACTION)

    def test_19_valid_model_free_metadata_path_can_express_reuse(self):
        cache = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertEqual(region_action(plan=selective_plan(), step=5, region=0, cache=cache, runtime_guard_passed=True)[0], REUSE_ACTION)

    def test_20_cache_budget_uses_actual_h3_core_shape_and_admits_twelve_blocks(self):
        self.assertEqual(ATTENTION_CORE_WIDTH, 7168)
        self.assertEqual(PER_BLOCK_WORST_CASE_CACHE_BYTES, 172390400)
        self.assertLessEqual(PER_BLOCK_GPU_STAGING_BYTES, 256 * 1024**2)
        plan = cache_budget_plan(available_host_bytes=64 * 1024**3, ranked_blocks=tuple(range(50)))
        self.assertEqual(plan.usable_cache_budget_bytes, MAX_HOST_CACHE_BYTES)
        self.assertEqual(len(plan.candidate_blocks), 12)
        self.assertTrue(plan.admitted)

    def test_21_a2_full_ranking_is_frozen_and_deterministic(self):
        rows = [
            {"block_index": index, "mean_normalized_l2": 1.0 + index / 100, "mean_cosine": 0.5, "p95_normalized_l2": 2.0}
            for index in range(50)
        ]
        rows[48]["mean_normalized_l2"] = 0.2
        self.assertEqual(a2_full_ranking(rows)[:2], (48, 0))
        self.assertEqual(a2_full_ranking(rows), a2_full_ranking(rows))

    def test_22_settings_digest_is_stable_and_mode_specific(self):
        self.assertEqual(settings_digest(mode=CONTROL_MODE), settings_digest(mode=CONTROL_MODE))
        self.assertNotEqual(settings_digest(mode=CONTROL_MODE), settings_digest(mode=SELECTIVE_MODE, candidate_blocks=(0, 1, 2)))

    def test_23_current_adapter_structural_gate_fails_before_generation(self):
        source = {
            "admitted": True,
            "checks": {
                "optimized_attention_boundary_present": True,
                "output_projection_separate": True,
                "attention_class_present": True,
            },
            "claim_boundary": {"attention_core_query_reduction": True, "global_kv_preserved": True},
        }
        cache = cache_budget_plan(available_host_bytes=64 * 1024**3, ranked_blocks=tuple(range(50)))
        admission = structural_admission(source_admission=source, cache_plan=cache, runtime_conditional_dispatch_available=False)
        self.assertFalse(admission["passed"])
        self.assertEqual(admission["decision"], "A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED")
        self.assertEqual(admission["generation_budget_consumed"], 0)
        self.assertEqual(admission["cuda_execution_count"], 0)

    def test_24_metric_tensor_contract_keeps_unsupported_out_of_scope(self):
        actual = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
        metrics = metric_tensors(actual, actual.clone(), torch)
        self.assertTrue(bool(metrics["finite"]))
        self.assertAlmostEqual(float(metrics["cosine"]), 1.0, places=6)
        self.assertAlmostEqual(float(metrics["normalized_l2"]), 0.0, places=6)

    def test_25_pipeline_default_is_disabled_and_standard_product_path_callable(self):
        config_path = Path(__file__).resolve().parents[2] / "configs" / "a3_h3_attention_output_reuse_correction.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertFalse(config["product_default_enabled"])
        backend = object.__new__(MiniMaxH3ComfyUIBackend)
        workflow = backend.build_api_workflow(
            {"content": [{"type": "text", "text": "private-test-placeholder"}]},
            output_prefix="hiveframe/a3-model-free",
        )
        self.assertEqual(workflow["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertNotIn("A3", json.dumps(workflow))
        capability = H3RegionalAttentionOutputReuseCapability()
        self.assertFalse(capability.enabled)
        self.assertFalse(capability.runtime_conditional_dispatch_available)
        state = MiniMaxH3ComfyUIBackend.experimental_capabilities["regional_attention_output_reuse_correction_v1"]
        self.assertFalse(state["default_enabled"])
        self.assertEqual(state["fallback"], "standard_full_compute")

    def test_26_config_freezes_guard_thresholds_budget_and_decision_matrix(self):
        config_path = Path(__file__).resolve().parents[2] / "configs" / "a3_h3_attention_output_reuse_correction.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["runtime_guard"]["mean_representative_cosine_min"], 0.97)
        self.assertEqual(config["runtime_guard"]["normalized_representative_l2_max"], 0.25)
        self.assertEqual(config["cache"]["maximum_host_bytes"], 2 * 1024**3)
        self.assertEqual(config["cache"]["host_safety_reserve_bytes"], 8 * 1024**3)
        self.assertEqual(config["opportunity"]["planned_attention_core_q_row_reduction_min"], 0.03)
        self.assertEqual(
            config["decision_matrix"]["structural_path_unavailable"],
            "A3_ATTENTION_OUTPUT_REUSE_STRUCTURALLY_NOT_ADMITTED",
        )


if __name__ == "__main__":
    unittest.main()
