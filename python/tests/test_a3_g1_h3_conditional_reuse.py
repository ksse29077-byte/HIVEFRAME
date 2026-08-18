from __future__ import annotations

from pathlib import Path
import inspect
import json
import unittest

import torch

import hive_product.a3_g1_conditional_reuse as g1
from hive_product.active_query_attention import (
    REGION_LOCAL_ROWS,
    REGION_MASK,
    REGIONAL_ACTIVE_QUERY,
    VIDEO_TOKEN_COUNT,
)
from hive_product.a3_g1_h3_conditional_probe import NODE_CLASS, build_workflow
from hive_product.attention_output_reuse import make_cache_lineage
from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend
from hive_product.regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


def plan(*, step=5, stable=1, active=0, uncertain=0, refresh=0, **overrides):
    payload = {
        "target_step": step,
        "decision_code": REGIONAL_ACTIVE_QUERY,
        "stable_region_mask": stable,
        "full_compute_region_mask": REGION_MASK ^ stable,
        "active_mask": active,
        "uncertain_mask": uncertain,
        "refresh_region_mask": refresh,
        "global_invalidation": False,
        "overlap_conflict_mask": 0,
        "source_valid": True,
        "prediction_valid": True,
        "fallback_used": False,
    }
    payload.update(overrides)
    return payload


def directive(payload):
    return g1.rust_directive(
        plan=payload,
        step=5,
        block_index=0,
        candidate_blocks=(0, 1, 2),
        cache_ready=True,
    )[0]


def admitted_control_execution():
    return {
        "mixed_state_mapping_admitted": True,
        "invalid_mask_count": 0,
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
            "cache_refresh_count": 192,
            "full_size_gpu_staging_count": 0,
            "max_region_staging_bytes": g1.MAX_REGION_STAGING_BYTES,
        },
        "memory": {"correction_temp_peak": g1.MAX_CORRECTION_TEMP_BYTES},
    }


class A3G1DMixedStateContractTests(unittest.TestCase):
    def test_01_stable_only_selects_regional(self):
        self.assertEqual(directive(plan(stable=1)), g1.REGIONAL_SELECTIVE)
        contract = g1.fixed_contract()
        self.assertTrue(contract["mixed_state_enabled"])
        self.assertFalse(contract["product_default_enabled"])
        self.assertEqual(contract["rust_directives"], [g1.FORCE_FULL, g1.REGIONAL_SELECTIVE])

    def test_02_stable_plus_uncertain_selects_regional(self):
        payload = plan(stable=1, uncertain=2)
        self.assertEqual(g1.regional_masks(payload), (1, 0, 2, 0))
        self.assertEqual(directive(payload), g1.REGIONAL_SELECTIVE)

    def test_03_stable_plus_active_selects_regional(self):
        payload = plan(stable=1, active=4)
        self.assertEqual(g1.regional_masks(payload), (1, 4, 0, 0))
        self.assertEqual(directive(payload), g1.REGIONAL_SELECTIVE)

    def test_04_uncertain_only_forces_full(self):
        self.assertEqual(directive(plan(stable=0, uncertain=2)), g1.FORCE_FULL)

    def test_05_active_only_forces_full(self):
        self.assertEqual(directive(plan(stable=0, active=4)), g1.FORCE_FULL)

    def test_06_no_stable_forces_full(self):
        self.assertEqual(directive(plan(stable=0)), g1.FORCE_FULL)

    def test_07_stable_uncertain_overlap_forces_full(self):
        self.assertEqual(directive(plan(stable=1, uncertain=1)), g1.FORCE_FULL)

    def test_08_stable_active_or_active_uncertain_overlap_forces_full(self):
        self.assertEqual(directive(plan(stable=1, active=1)), g1.FORCE_FULL)
        self.assertEqual(directive(plan(stable=1, active=2, uncertain=2)), g1.FORCE_FULL)
        malformed = plan(stable=1)
        malformed.pop("full_compute_region_mask")
        self.assertEqual(directive(malformed), g1.FORCE_FULL)
        self.assertEqual(directive(plan(stable=16)), g1.FORCE_FULL)
        self.assertEqual(directive(plan(stable=1, global_invalidation=True)), g1.FORCE_FULL)

    def test_09_active_rows_are_in_exact_kernel(self):
        safety = g1.mixed_state_row_safety(
            sequence_length=VIDEO_TOKEN_COUNT + 9,
            stable_mask=1,
            active_mask=2,
            uncertain_mask=0,
        )
        self.assertTrue(safety["mapping_safe"])
        self.assertEqual(safety["active_exact_rows"], len(REGION_LOCAL_ROWS[1]))

    def test_10_uncertain_rows_are_in_exact_kernel(self):
        safety = g1.mixed_state_row_safety(
            sequence_length=VIDEO_TOKEN_COUNT,
            stable_mask=1,
            active_mask=0,
            uncertain_mask=4,
        )
        self.assertTrue(safety["mapping_safe"])
        self.assertEqual(safety["uncertain_exact_rows"], len(REGION_LOCAL_ROWS[2]))

    def test_11_halo_rows_are_exact(self):
        safety = g1.mixed_state_row_safety(
            sequence_length=VIDEO_TOKEN_COUNT,
            stable_mask=1,
            active_mask=0,
            uncertain_mask=0,
        )
        expected = VIDEO_TOKEN_COUNT - len({row for rows in REGION_LOCAL_ROWS for row in rows})
        self.assertGreater(expected, 0)
        self.assertEqual(safety["halo_exact_rows"], expected)

    def test_12_nonvideo_rows_are_exact(self):
        safety = g1.mixed_state_row_safety(
            sequence_length=VIDEO_TOKEN_COUNT + 17,
            stable_mask=1,
            active_mask=0,
            uncertain_mask=0,
        )
        self.assertEqual(safety["nonvideo_exact_rows"], 17)
        self.assertEqual(
            safety["kernel_q_rows"],
            len(CPU_PROTOTYPE_PLANS[1].kernel_local_rows) + 17,
        )

    def test_13_only_stable_interior_rows_are_omitted(self):
        prototype = CPU_PROTOTYPE_PLANS[1]
        omitted = set(prototype.omitted_local_rows)
        stable = set(REGION_LOCAL_ROWS[0])
        other = {row for rows in REGION_LOCAL_ROWS[1:] for row in rows}
        self.assertTrue(omitted)
        self.assertTrue(omitted.issubset(stable))
        self.assertFalse(omitted & other)

    def test_14_stable_representatives_remain_exact(self):
        prototype = CPU_PROTOTYPE_PLANS[1]
        kernel = set(prototype.kernel_local_rows)
        representatives = set(prototype.representative_local_rows)
        self.assertTrue(representatives)
        self.assertTrue(representatives.issubset(kernel))
        self.assertFalse(representatives & set(prototype.omitted_local_rows))

    def test_15_full_and_partial_execution_is_xor(self):
        self.assertTrue(g1.attention_path_is_xor(full_calls=1, partial_calls=0))
        self.assertTrue(g1.attention_path_is_xor(full_calls=0, partial_calls=1))
        self.assertFalse(g1.attention_path_is_xor(full_calls=1, partial_calls=1))
        source = inspect.getsource(g1.H3A3G1Controller._prepare_direct_reuse)
        self.assertEqual(source.count("attention_core("), 1)
        self.assertNotIn("_exact_full(", source)

    def test_16_consecutive_approximation_is_prohibited(self):
        self.assertIsNone(
            make_cache_lineage(
                block_index=0,
                source_step=4,
                source_kind="CORRECTED_ATTENTION_CORE_OUTPUT",
            )
        )
        lineage = make_cache_lineage(
            block_index=0,
            source_step=4,
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        )
        self.assertTrue(lineage.eligible(target_step=5, region=0))
        self.assertFalse(lineage.eligible(target_step=6, region=0))

    def test_17_missing_or_stale_cache_forces_full(self):
        result = g1.rust_directive(
            plan=plan(),
            step=5,
            block_index=0,
            candidate_blocks=(0, 1, 2),
            cache_ready=False,
        )
        self.assertEqual(result, (g1.FORCE_FULL, "cache_missing_stale_or_not_ready"))

    def test_18_source_steps_1_through_16_are_cache_eligible(self):
        self.assertEqual(g1.ELIGIBLE_CACHE_SOURCE_STEPS, tuple(range(1, 17)))
        self.assertTrue(all(g1.source_step_cache_eligible(step) for step in range(1, 17)))

    def test_19_source_steps_0_17_18_19_skip_cache(self):
        self.assertTrue(all(not g1.source_step_cache_eligible(step) for step in (0, 17, 18, 19)))

    def test_20_h2d_uploads_only_target_stable_regions(self):
        self.assertEqual(g1.stable_region_ids(0b0101), (0, 2))
        source = inspect.getsource(g1.H3A3G1Controller._prepare_direct_reuse)
        self.assertIn("for region in stable_region_ids(stable_mask)", source)
        self.assertEqual(source.count("_upload_region("), 1)

    def test_21_region_staging_remains_bounded_and_full_size_zero(self):
        maximum_rows = max(
            len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["representative"])
            + len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["omitted"])
            for region in range(4)
        )
        self.assertEqual(maximum_rows * 7168 * 2, g1.MAX_REGION_STAGING_BYTES)
        self.assertLess(g1.MAX_REGION_STAGING_BYTES, 172_390_400)
        peak = g1.correction_temp_bytes(rows=g1.CORRECTION_CHUNK_ROWS, width=7168, float_buffers=8)
        self.assertLessEqual(peak, g1.MAX_CORRECTION_TEMP_BYTES)

    def test_22_callback_latency_is_diagnostic_and_e2e_is_the_gate(self):
        c2 = {
            "total_shadow_callback": {"p95_ns": 349_114_868},
            "callback_shadow_cpu": {"p95_ns": 1000},
            "cuda_async_sketch": {"p95_ns": 2000},
            "gpu_to_host": {"p95_ns": 3000},
        }
        region = {
            "tensor_bytes_to_rust": 0,
            "boundary_roundtrip": {"p95_ns": 90_000},
            "rust_policy": {"p95_ns": 10_000},
        }
        result = g1.control_opportunity_gate(
            execution=admitted_control_execution(),
            region_plan=region,
            c2_shadow=c2,
            output_integrity=True,
            cache_capacity=3,
            control_sampler_seconds=g1.IMMUTABLE_STANDARD_SAMPLER_SECONDS * 1.01,
            control_submit_seconds=g1.IMMUTABLE_STANDARD_SUBMIT_SECONDS * 1.01,
        )
        self.assertTrue(result["passed"])
        self.assertFalse(result["latency_diagnostics"]["total_shadow_callback_is_admission_gate"])
        result = g1.control_opportunity_gate(
            execution=admitted_control_execution(),
            region_plan=region,
            c2_shadow=c2,
            output_integrity=True,
            cache_capacity=3,
            control_sampler_seconds=g1.IMMUTABLE_STANDARD_SAMPLER_SECONDS * 1.051,
            control_submit_seconds=g1.IMMUTABLE_STANDARD_SUBMIT_SECONDS,
        )
        self.assertEqual(result["decision"], g1.DECISION_CONTROL_OVERHEAD)

        root = Path(__file__).resolve().parents[2]
        config = json.loads(
            (root / "configs" / "a3_g1_h3_conditional_attention_reuse.json").read_text(encoding="utf-8")
        )
        self.assertFalse(config["product_default_enabled"])
        capability = MiniMaxH3ComfyUIBackend.experimental_capabilities[
            "real_h3_preplan_direct_selective_reuse_v1"
        ]
        self.assertFalse(capability["default_enabled"])
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {}}}
        workflow = build_workflow(
            standard,
            mode=g1.CONTROL_MODE,
            candidate_blocks=g1.A2_RANKED_BLOCKS[:3],
            run_digest="model-free-run-digest",
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(NODE_CLASS, "HIVEFRAMEH3MixedStateRegionalReuseSampler")


if __name__ == "__main__":
    unittest.main()
