from __future__ import annotations

from pathlib import Path
import inspect
import json
import os
import unittest

import torch

from hive_product.active_query_attention import MECHANISM_ID as A1_MECHANISM_ID, REGION_LOCAL_ROWS, VIDEO_TOKEN_COUNT
from hive_product.a2_h3_query_prototype_probe import NODE_CLASS, build_workflow
from hive_product.regional_query_prototype_attention import (
    BLOCK_REGION_OBSERVATIONS_MIN,
    CONTROL_MODE,
    CPU_PROTOTYPE_PLANS,
    GPUPrototypePlan,
    GPUPrototypePlanCache,
    H3RegionalQueryPrototypeController,
    MECHANISM_ID,
    SELECTIVE_MODE,
    attention_core,
    _project_qkv,
    build_cpu_prototype_plan,
    control_admission,
    fixed_contract,
    inspect_installed_attention_source,
    prototype_mapping_contract,
    prototype_settings_digest,
    reconstruct_full_core,
)


class IdentityNorm:
    def __init__(self, width):
        self.weight = torch.ones(width)
        self.eps = 1e-6

    def __call__(self, value):
        return value


class FakeQKV:
    def __call__(self, value):
        return torch.cat((value, value * 0.5, value * 0.25), dim=-1)


class IdentityProjection:
    def __call__(self, value):
        return value


class TinyAttention:
    heads = 1
    head_dim = 2

    def __init__(self):
        self.qkv_proj = FakeQKV()
        self.q_norm = IdentityNorm(2)
        self.k_norm = IdentityNorm(2)
        self.out_proj = IdentityProjection()


ATTENTION_SHAPES = []


def reference_attention(q, k, v, _heads, **_kwargs):
    ATTENTION_SHAPES.append({"q": tuple(q.shape), "k": tuple(k.shape), "v": tuple(v.shape)})
    scores = torch.matmul(q, k.transpose(-1, -2)) / (q.shape[-1] ** 0.5)
    return torch.matmul(scores.softmax(dim=-1), v).transpose(1, 2).reshape(q.shape[0], q.shape[2], -1)


class A2QueryPrototypeTests(unittest.TestCase):
    def test_fixed_contract_is_exact_q_full_kv_and_full_projection(self):
        contract = fixed_contract()
        self.assertEqual(contract["mechanism"], MECHANISM_ID)
        self.assertEqual(contract["prototype_source"], "EXACT_ORIGINAL_Q_AFTER_NORM_AND_ROPE")
        self.assertEqual(contract["spatial_stride"], [2, 2])
        self.assertEqual(contract["temporal_stride"], 1)
        self.assertEqual(contract["all_kv"], "GLOBAL_FULL")
        self.assertEqual(contract["qkv_projection"], "GLOBAL_FULL")
        self.assertEqual(contract["output_projection"], "GLOBAL_FULL")
        self.assertTrue(contract["full_compute_fallback"])

    def test_a1_historical_mechanism_remains_distinct(self):
        self.assertEqual(A1_MECHANISM_ID, "REGIONAL_ACTIVE_QUERY_GLOBAL_KV_ZERO_UPDATE_V1")
        self.assertNotEqual(A1_MECHANISM_ID, MECHANISM_ID)

    def test_all_semantic_masks_are_deterministic_and_partition_regions(self):
        self.assertEqual(len(CPU_PROTOTYPE_PLANS), 16)
        self.assertEqual(CPU_PROTOTYPE_PLANS, tuple(build_cpu_prototype_plan(mask) for mask in range(16)))
        mapping = prototype_mapping_contract()
        self.assertTrue(mapping["all_rows_in_range"])
        self.assertEqual(mapping["semantic_mask_count"], 16)
        for region in mapping["regions"]:
            self.assertTrue(region["exact_partition"])
            self.assertTrue(region["neighbor_rows_same_region"])
            self.assertGreater(region["representative_rows"], 0)
            self.assertGreater(region["omitted_rows"], 0)

    def test_representatives_are_exact_original_rows_and_no_time_or_region_crossing(self):
        frame_stride = 15 * 27
        for region in range(4):
            plan = CPU_PROTOTYPE_PLANS[1 << region]
            rows = plan.region_rows[region]
            local = set(REGION_LOCAL_ROWS[region])
            for omitted, neighbors in zip(rows["omitted"], rows["neighbors"]):
                self.assertTrue(set(neighbors).issubset(local))
                self.assertTrue(all(value // frame_stride == omitted // frame_stride for value in neighbors))
            for weights in rows["weights"]:
                self.assertAlmostEqual(sum(weights), 1.0)
            self.assertTrue(set(rows["representative"]).issubset(local))

    def test_only_selected_stable_interiors_are_omitted(self):
        plan = CPU_PROTOTYPE_PLANS[0b0001]
        omitted = set(plan.omitted_local_rows)
        self.assertTrue(omitted.issubset(set(REGION_LOCAL_ROWS[0])))
        for region in (1, 2, 3):
            self.assertTrue(set(REGION_LOCAL_ROWS[region]).issubset(set(plan.kernel_local_rows)))
        self.assertTrue(set(range(VIDEO_TOKEN_COUNT)) == set(plan.kernel_local_rows) | omitted)
        self.assertFalse(set(plan.kernel_local_rows) & omitted)

    def test_gpu_cache_materializes_all_masks_once_and_keeps_nonvideo_rows(self):
        cache = GPUPrototypePlanCache(torch)
        sequence = VIDEO_TOKEN_COUNT + 9
        cache.materialize_all(sequence_length=sequence, video_start=9, video_stop=sequence, device=torch.device("cpu"))
        first_bytes = cache.persistent_gpu_bytes
        cache.materialize_all(sequence_length=sequence, video_start=9, video_stop=sequence, device=torch.device("cpu"))
        self.assertEqual(cache.materialization_count, 16)
        self.assertEqual(cache.persistent_gpu_bytes, first_bytes)
        self.assertEqual(cache.hot_path_materialization_count, 0)
        plan = cache.get(0b0101)
        self.assertTrue(set(range(9)).issubset(set(plan.kernel_indices.tolist())))
        self.assertGreater(plan.persistent_bytes, 0)

    def test_bilinear_reconstruction_matches_known_field(self):
        core = torch.tensor([[0.0], [2.0], [0.0], [0.0], [4.0]])
        plan = GPUPrototypePlan(
            stable_region_mask=1,
            kernel_indices=torch.tensor([0, 1, 4]),
            representative_indices=torch.tensor([0, 1, 4]),
            omitted_indices=torch.tensor([2, 3]),
            neighbor_indices=torch.tensor([[0, 1, 0, 1], [1, 4, 1, 4]]),
            neighbor_weights=torch.tensor([[0.5, 0.5, 0.0, 0.0], [0.5, 0.5, 0.0, 0.0]]),
            region_rows={},
            persistent_bytes=0,
        )
        selected = core.index_select(0, plan.kernel_indices)
        rebuilt = reconstruct_full_core(selected, plan, 5)
        self.assertTrue(torch.equal(rebuilt.index_select(0, plan.kernel_indices), selected))
        self.assertTrue(torch.allclose(rebuilt.flatten(), torch.tensor([0.0, 2.0, 1.0, 3.0, 4.0])))

    def test_subset_exact_q_matches_full_attention_on_representatives(self):
        ATTENTION_SHAPES.clear()
        attention = TinyAttention()
        x = torch.tensor([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.25]])
        q, k, v = attention.qkv_proj(x).split(2, dim=-1)
        q = attention.q_norm(q.view(4, 1, 2))
        k = attention.k_norm(k.view(4, 1, 2))
        v = v.view(4, 1, 2)
        full = attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=None,
            attention=attention,
            optimized_attention=reference_attention,
            transformer_options={},
        )
        representatives = torch.tensor([0, 2, 3])
        subset = attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=representatives,
            attention=attention,
            optimized_attention=reference_attention,
            transformer_options={},
        )
        self.assertTrue(torch.allclose(subset, full.index_select(0, representatives), atol=1e-6))
        self.assertEqual(ATTENTION_SHAPES[1]["q"][-2], 3)
        self.assertEqual(ATTENTION_SHAPES[1]["k"][-2], 4)
        self.assertEqual(ATTENTION_SHAPES[1]["v"][-2], 4)

    def test_all_row_wrapper_matches_installed_attention_semantics(self):
        ATTENTION_SHAPES.clear()
        attention = TinyAttention()
        x = torch.tensor([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.25]])
        q, k, v = _project_qkv(
            attention,
            x,
            None,
            cast_to=lambda value, **_kwargs: value,
            in_training=False,
            rms_rope=lambda *args, **_kwargs: (args[0], args[1]),
            rms_rope_in_place=lambda *args, **_kwargs: None,
        )
        wrapped_core = attention_core(
            q=q,
            k=k,
            v=v,
            q_indices=None,
            attention=attention,
            optimized_attention=reference_attention,
            transformer_options={},
        )
        wrapped = attention.out_proj(wrapped_core)
        original_q = q.transpose(0, 1).unsqueeze(0)
        original_k = k.transpose(0, 1).unsqueeze(0)
        original_v = v.transpose(0, 1).unsqueeze(0)
        original = attention.out_proj(reference_attention(original_q, original_k, original_v, attention.heads).squeeze(0))
        self.assertTrue(torch.allclose(wrapped, original, atol=1e-6))

    def test_settings_digest_is_stable_and_mode_specific(self):
        self.assertEqual(prototype_settings_digest(mode=CONTROL_MODE), prototype_settings_digest(mode=CONTROL_MODE))
        self.assertNotEqual(
            prototype_settings_digest(mode=CONTROL_MODE),
            prototype_settings_digest(mode=SELECTIVE_MODE, admitted_blocks=(1, 2, 3)),
        )

    def test_control_gate_uses_inclusive_combined_callback_and_not_a1_rust_limit(self):
        execution = {
            "admitted_block_count": 3,
            "planned_query_reduction": 0.05,
            "affected_non_anchor_steps": [3, 4, 5],
            "stable_region_plan_event_count": 3,
            "explicit_cuda_synchronization_count": 0,
            "per_block_rust_call_count": 0,
            "per_token_rust_call_count": 0,
            "dynamic_per_block_gpu_plan_allocation_count": 0,
        }
        region = {"boundary_roundtrip": {"p95_ns": 500_000}, "tensor_bytes_to_rust": 0}
        c2 = {"total_shadow_callback": {"p95_ns": 2_900_000}, "full_tensor_host_copy_bytes": 0}
        gate = control_admission(
            execution=execution,
            region_plan=region,
            c2_shadow=c2,
            sampler_seconds=488.847320,
            output_integrity_passed=True,
            source_admitted=True,
        )
        self.assertTrue(gate["passed"])
        self.assertEqual(gate["a1_rust_boundary_p95_ns_record_only"], 500_000)
        self.assertIn("not added twice", gate["combined_measurement_method"])

    def test_control_gate_rejects_overhead_before_selective(self):
        execution = {
            "admitted_block_count": 20,
            "planned_query_reduction": 0.5,
            "affected_non_anchor_steps": [3, 5, 7],
            "stable_region_plan_event_count": 3,
            "explicit_cuda_synchronization_count": 0,
            "per_block_rust_call_count": 0,
            "per_token_rust_call_count": 0,
            "dynamic_per_block_gpu_plan_allocation_count": 0,
        }
        gate = control_admission(
            execution=execution,
            region_plan={"boundary_roundtrip": {"p95_ns": 1}, "tensor_bytes_to_rust": 0},
            c2_shadow={"total_shadow_callback": {"p95_ns": 1}, "full_tensor_host_copy_bytes": 0},
            sampler_seconds=520.0,
            output_integrity_passed=True,
            source_admitted=True,
        )
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["decision"], "A2_PROTOTYPE_CONTROL_OVERHEAD_TOO_HIGH")

    def test_hot_path_has_no_rust_call_host_copy_or_explicit_sync(self):
        source = inspect.getsource(H3RegionalQueryPrototypeController.instrumented_forward)
        for forbidden in ("evaluate_attention_region_plan", "cuda.synchronize", ".cpu(", ".numpy("):
            self.assertNotIn(forbidden, source)
        self.assertIn("block.attn.out_proj", source)
        self.assertIn("block.mlp(h)", source)

    def test_config_matches_frozen_profile_and_thresholds(self):
        path = Path(__file__).resolve().parents[2] / "configs" / "a2_h3_gpu_regional_query_prototype_attention.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["mechanism"], MECHANISM_ID)
        self.assertEqual(config["query_prototype"]["spatial_stride"], [2, 2])
        self.assertEqual(config["query_prototype"]["temporal_stride"], 1)
        self.assertFalse(config["profile"]["sage"])
        self.assertEqual(config["generation_budget"], 2)
        self.assertEqual(config["retry_budget"], 0)
        self.assertEqual(config["block_admission"]["regional_observations_min"], BLOCK_REGION_OBSERVATIONS_MIN)

    def test_workflow_is_mode_explicit_sage_free_and_does_not_mutate_input(self):
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0]}}}
        control = build_workflow(standard, mode=CONTROL_MODE, admitted_blocks=(), run_digest="11" * 32)
        selective = build_workflow(standard, mode=SELECTIVE_MODE, admitted_blocks=(1, 3, 5), run_digest="22" * 32)
        self.assertEqual(control["10"]["class_type"], NODE_CLASS)
        self.assertEqual(control["10"]["inputs"]["admitted_blocks_json"], "[]")
        self.assertEqual(selective["10"]["inputs"]["admitted_blocks_json"], "[1,3,5]")
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")

    def test_installed_source_contract_when_explicitly_configured(self):
        root = os.environ.get("HIVEFRAME_COMFYUI_ROOT")
        if not root:
            self.skipTest("installed source requires HIVEFRAME_COMFYUI_ROOT")
        source = Path(root)
        gate = inspect_installed_attention_source(
            source / "comfy/ldm/minimax/model.py",
            source / "comfy/ldm/modules/attention.py",
        )
        self.assertTrue(gate["admitted"], gate)
        self.assertTrue(gate["claim_boundary"]["attention_core_query_reduction"])
        self.assertTrue(gate["claim_boundary"]["global_kv_preserved"])


if __name__ == "__main__":
    unittest.main()
