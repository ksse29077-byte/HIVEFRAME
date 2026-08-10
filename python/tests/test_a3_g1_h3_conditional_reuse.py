from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import unittest

import torch

from hive_product.active_query_attention import REGIONAL_ACTIVE_QUERY
from hive_product.a3_g1_conditional_reuse import (
    A2_RANKED_BLOCKS,
    CONTROL_MODE,
    DECISION_GUARD_NOT_SAFE,
    EXECUTION_AUTHORITY,
    EXECUTION_ISLAND,
    FORCE_FULL,
    GPU_CHECK,
    GPUConditionalAttentionIsland,
    SELECTIVE_MODE,
    aggregate_all_safe,
    control_opportunity_gate,
    execution_island_source_admission,
    fixed_contract,
    gpu_guard_metrics,
    rust_directive,
    settings_digest,
    work_accounting,
)
from hive_product.a3_g1_h3_conditional_probe import NODE_CLASS, build_workflow
from hive_product.attention_output_reuse import (
    MAX_GPU_STAGING_BYTES,
    cache_budget_plan,
    make_cache_lineage,
)
from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend


def plan(*, stable=1, uncertain=0, refresh=0):
    return {
        "decision_code": REGIONAL_ACTIVE_QUERY,
        "stable_region_mask": stable,
        "active_mask": 0,
        "uncertain_mask": uncertain,
        "refresh_region_mask": refresh,
    }


class FakeAttention:
    __name__ = "attention_pytorch"


class FakeGraph:
    begin_capture_to_if_node = object()
    end_capture_to_conditional_node = object()


class A3G1ContractTests(unittest.TestCase):
    def test_01_contract_reuses_g0_authority_but_remains_disabled(self):
        contract = fixed_contract()
        self.assertEqual(contract["execution_authority"], EXECUTION_AUTHORITY)
        self.assertEqual(contract["execution_island"], EXECUTION_ISLAND)
        self.assertFalse(contract["product_default_enabled"])
        self.assertEqual(contract["rust_directives"], [FORCE_FULL, GPU_CHECK])
        self.assertFalse(contract["conditional_graph"]["host_predicate_read"])

    def test_02_settings_digest_is_stable_and_mode_specific(self):
        candidates = A2_RANKED_BLOCKS[:3]
        self.assertEqual(
            settings_digest(mode=CONTROL_MODE, candidate_blocks=candidates),
            settings_digest(mode=CONTROL_MODE, candidate_blocks=candidates),
        )
        self.assertNotEqual(
            settings_digest(mode=CONTROL_MODE, candidate_blocks=candidates),
            settings_digest(mode=SELECTIVE_MODE, candidate_blocks=candidates),
        )

    def test_03_rust_force_full_cases_are_fail_open(self):
        candidates = (0, 1, 2)
        self.assertEqual(
            rust_directive(plan=plan(), step=0, block_index=0, candidate_blocks=candidates, cache_ready=True)[0],
            FORCE_FULL,
        )
        self.assertEqual(
            rust_directive(plan=None, step=5, block_index=0, candidate_blocks=candidates, cache_ready=True)[0],
            FORCE_FULL,
        )
        self.assertEqual(
            rust_directive(plan=plan(uncertain=1), step=5, block_index=0, candidate_blocks=candidates, cache_ready=True)[0],
            FORCE_FULL,
        )
        self.assertEqual(
            rust_directive(plan=plan(), step=5, block_index=0, candidate_blocks=candidates, cache_ready=False)[0],
            FORCE_FULL,
        )

    def test_04_only_valid_stable_cache_candidate_requests_gpu_check(self):
        directive, reason = rust_directive(
            plan=plan(stable=3),
            step=5,
            block_index=0,
            candidate_blocks=(0, 1, 2),
            cache_ready=True,
        )
        self.assertEqual((directive, reason), (GPU_CHECK, "stable_cache_candidate"))

    def test_05_block_guard_requires_all_regions(self):
        self.assertTrue(bool(aggregate_all_safe([torch.tensor(True), torch.tensor(True)], torch)))
        self.assertFalse(bool(aggregate_all_safe([torch.tensor(True), torch.tensor(False)], torch)))
        with self.assertRaises(ValueError):
            aggregate_all_safe([], torch)

    def test_06_gpu_guard_threshold_and_nonfinite_are_fixed(self):
        current = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
        passed = gpu_guard_metrics(current, current.clone(), torch)
        self.assertTrue(bool(passed["safe"]))
        rejected = gpu_guard_metrics(current, torch.full_like(current, float("nan")), torch)
        self.assertFalse(bool(rejected["safe"]))

    def test_07_cache_lineage_prohibits_chaining_and_age_two(self):
        self.assertIsNone(make_cache_lineage(block_index=0, source_step=4, source_kind="CORRECTED_ATTENTION_CORE_OUTPUT"))
        lineage = make_cache_lineage(block_index=0, source_step=4, source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT")
        self.assertTrue(lineage.eligible(target_step=5, region=0))
        self.assertFalse(lineage.eligible(target_step=6, region=0))

    def test_08_cache_budget_preserves_three_block_minimum_and_staging_limit(self):
        cache = cache_budget_plan(available_host_bytes=64 * 1024**3, ranked_blocks=A2_RANKED_BLOCKS)
        self.assertGreaterEqual(len(cache.candidate_blocks), 3)
        self.assertTrue(cache.admitted)
        self.assertLessEqual(cache.per_block_gpu_staging_bytes, MAX_GPU_STAGING_BYTES)

    def test_09_actual_work_accounting_does_not_hide_unsafe_duplicate_q(self):
        result = work_accounting(
            full_q_rows_theoretical=1000,
            forced_full_q_rows=600,
            representative_and_required_q_rows=200,
            conditional_full_q_rows=100,
            reused_omitted_rows=100,
        )
        self.assertEqual(result["actual_current_q_rows"], 900)
        self.assertAlmostEqual(result["actual_q_reduction_ratio"], 0.1)

    def test_10_source_admission_requires_exact_pytorch_backend_and_cuda_if_api(self):
        fake = SimpleNamespace(
            __version__="2.12.1+cu130",
            version=SimpleNamespace(cuda="13.0"),
            cuda=SimpleNamespace(is_available=lambda: True, CUDAGraph=FakeGraph),
        )
        admitted = execution_island_source_admission(fake, FakeAttention())
        self.assertTrue(admitted["admitted"])
        rejected = execution_island_source_admission(fake, lambda: None)
        self.assertFalse(rejected["admitted"])

    def test_11_control_gate_rejects_false_safe_without_relaxing_other_checks(self):
        execution = {
            "execution_island": {"native_full_parity_bit_exact": True},
            "admitted_block_count": 3,
            "planned_q_reduction_ratio": 0.04,
            "affected_non_anchor_steps": [4, 5, 6],
            "stable_plan_event_count": 3,
            "false_safe_count": 1,
            "full_compute_fallback_preserved": True,
            "rust": {"per_block_calls": 0, "per_token_calls": 0},
        }
        result = control_opportunity_gate(
            execution=execution,
            region_plan={"tensor_bytes_to_rust": 0},
            c2_shadow={"total_shadow_callback": {"p95_ns": 10}},
            output_integrity=True,
            cache_capacity=3,
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["decision"], DECISION_GUARD_NOT_SAFE)

    def test_12_config_matches_contract_and_fixed_candidate_prefix(self):
        root = Path(__file__).resolve().parents[2]
        payload = json.loads((root / "configs" / "a3_g1_h3_conditional_attention_reuse.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["mechanism"], fixed_contract()["mechanism"])
        self.assertEqual(payload["execution_island"], EXECUTION_ISLAND)
        self.assertEqual(tuple(payload["candidate_blocks_from_a2_frozen_ranking"]), A2_RANKED_BLOCKS)
        self.assertEqual(payload["runtime_guard"]["representative_cosine_min"], 0.97)
        self.assertEqual(payload["opportunity"]["actual_q_reduction_min"], 0.03)

    def test_13_backend_capability_is_experimental_and_full_fallback(self):
        capability = MiniMaxH3ComfyUIBackend.experimental_capabilities["real_h3_conditional_attention_reuse_v1"]
        self.assertFalse(capability["default_enabled"])
        self.assertEqual(capability["fallback"], "standard_full_compute")

    def test_14_workflow_freezes_profile_digest_and_repository_node(self):
        standard = {
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["1", 0], "sampler": ["2", 0]},
            }
        }
        candidates = A2_RANKED_BLOCKS[:3]
        workflow = build_workflow(
            standard,
            mode=CONTROL_MODE,
            candidate_blocks=candidates,
            run_digest="model-free-run-digest",
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(json.loads(workflow["10"]["inputs"]["candidate_blocks_json"]), list(candidates))
        self.assertEqual(
            workflow["10"]["inputs"]["settings_digest"],
            settings_digest(mode=CONTROL_MODE, candidate_blocks=candidates),
        )
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")


@unittest.skipUnless(
    os.environ.get("HIVEFRAME_A3_G1_CUDA_FOCUSED") == "1" and torch.cuda.is_available(),
    "A3-G1 focused native CUDA proof is opt-in",
)
class A3G1CUDAFocusedTests(unittest.TestCase):
    def test_exact_sdpa_conditional_body_omission_and_parity(self):
        import torch.nn.functional as functional

        packed = torch.randn((3, 1, 4, 128, 64), device="cuda", dtype=torch.bfloat16)
        q, k, v = packed[0], packed[1], packed[2]
        safe = torch.randn_like(q)
        reference = functional.scaled_dot_product_attention(q, k, v, dropout_p=0.0, is_causal=False)
        island = GPUConditionalAttentionIsland(torch)
        island.capture(
            q=q,
            k=k,
            v=v,
            safe_core=safe,
            full_callable=lambda qt, kt, vt: functional.scaled_dot_product_attention(
                qt, kt, vt, dropout_p=0.0, is_causal=False
            ),
            parity_reference=reference,
        )
        unsafe = torch.tensor(False, device="cuda")
        output = island.dispatch(unsafe=unsafe, omitted_rows=17, q=q, k=k, v=v, safe_core=safe)
        torch.cuda.synchronize()
        self.assertTrue(torch.equal(output, safe))
        receipt = island.receipt()
        self.assertTrue(receipt["native_full_parity_bit_exact"])
        self.assertEqual(receipt["counters"]["full_body_executions"], 1)
        self.assertEqual(receipt["counters"]["reuse_body_executions"], 1)
        self.assertEqual(receipt["counters"]["reused_omitted_rows"], 17)


if __name__ == "__main__":
    unittest.main()
