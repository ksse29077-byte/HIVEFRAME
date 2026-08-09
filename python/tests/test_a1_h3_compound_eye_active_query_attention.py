from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import inspect
import json
import os
import unittest

import torch

from hive_product.active_query_attention import (
    ABI_VERSION,
    ANCHOR_STEPS,
    BLOCK_COUNT,
    CALLBACK_P95_NS_MAX,
    CONTROL_MODE,
    ESCALATE_FULL_COMPUTE,
    FULL_COMPUTE,
    HALO_PATCHES,
    MECHANISM_ID,
    REGION_LOCAL_ROWS,
    REGION_MASK,
    REGIONAL_ACTIVE_QUERY,
    SELECTIVE_MODE,
    VIDEO_TOKEN_COUNT,
    ActiveQueryShadowPipeline,
    AttentionRegionPlanBridge,
    H3ActiveQueryAttentionController,
    RegionPlanContext,
    active_query_row_indices,
    active_query_settings_digest,
    control_admission,
    fixed_contract,
    inspect_installed_attention_source,
    region_mapping_contract,
    subset_query_attention,
)
from hive_product.a1_h3_active_query_probe import NODE_CLASS, build_workflow


DIGESTS = {
    "run_digest": "11" * 32,
    "workflow_revision_digest": "22" * 32,
    "settings_digest": "33" * 32,
    "model_revision_digest": "44" * 32,
}


class FakeExtension:
    def __init__(self) -> None:
        self.calls = []

    def attention_region_plan_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 312,
            "directive_struct_size": 144,
            "eye_count": 5,
            "region_count": 4,
            "max_rust_calls_per_ready_observation": 1,
            "max_rust_calls_per_block": 0,
            "max_rust_calls_per_token": 0,
            "tensor_bytes_per_call": 0,
            "prediction_horizon_steps": 2,
        }

    def evaluate_attention_region_plan(self, **observation):
        self.calls.append(observation)
        invalid = not observation["source_valid"] or not observation["prediction_valid"]
        stable = int(observation["stable_mask"])
        blocked = (
            int(observation["active_mask"])
            | int(observation["uncertain_mask"])
            | int(observation["overlap_conflict_mask"])
            | int(observation["cooldown_mask"])
            | int(observation["refresh_required_mask"])
        )
        admitted = stable & ~blocked & REGION_MASK
        if invalid:
            decision, reason, admitted = ESCALATE_FULL_COMPUTE, 6, 0
        elif observation["anchor_step"] or observation["global_invalidation"] or observation["overlap_conflict_mask"]:
            decision, reason, admitted = FULL_COMPUTE, 10, 0
        elif admitted:
            decision, reason = REGIONAL_ACTIVE_QUERY, 0
        else:
            decision, reason = FULL_COMPUTE, 12
        payload = repr(sorted(observation.items())).encode()
        digest = sha256(payload).digest()
        return {
            "ffi_status": 0,
            "abi_version": 1,
            "struct_size": 144,
            "decision_code": decision,
            "reason_code": reason,
            "target_step": observation["predicted_execution_step"],
            "stable_region_mask": admitted,
            "full_compute_region_mask": REGION_MASK & ~admitted,
            "refresh_region_mask": observation["refresh_required_mask"],
            "fallback_required": int(invalid),
            "unsupported_flags": 0,
            "shared_visual_state_digest": digest,
            "compute_plan_digest": digest,
            "decision_digest": digest,
            "rust_policy_ns": 100,
        }


def c2_event(target: int, states=None, *, conflict=0, ready=True):
    states = states or ["UNCERTAIN", "STABLE", "ACTIVE", "UNCERTAIN", "STABLE"]
    return {
        "predicted_execution_step": target,
        "sketch_observed_step": target - 2,
        "total_steps": 20,
        "eye_states": states,
        "eye_confidence_ppm": [500000, 900000, 900000, 500000, 850000],
        "eye_change_ppm": [40000, 5000, 90000, 30000, 7000],
        "global_invalidation": 0,
        "overlap_conflict_mask": conflict,
        "fallback_used": False,
        "reason": None,
        "event_ready": ready,
        "deadline_missed": False,
        "source_dtype": "torch.float32",
        "source_device_type": "cuda",
        "signal_adapter": "h3_nested_video_v1",
    }


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


class A1ActiveQueryTests(unittest.TestCase):
    def bridge(self):
        extension = FakeExtension()
        return AttentionRegionPlanBridge(RegionPlanContext(**DIGESTS), extension=extension), extension

    def test_fixed_contract_preserves_global_kv_anchors_halo_and_full_ff(self):
        contract = fixed_contract()
        self.assertEqual(contract["mechanism"], MECHANISM_ID)
        self.assertEqual(contract["anchors"], list(ANCHOR_STEPS))
        self.assertEqual(contract["all_kv"], "GLOBAL_FULL")
        self.assertEqual(contract["non_video_queries"], "FULL_COMPUTE")
        self.assertEqual(contract["uncertain_queries"], "FULL_COMPUTE")
        self.assertEqual(contract["feed_forward"], "FULL_COMPUTE")
        self.assertEqual(contract["halo_patches"], HALO_PATCHES)

    def test_plan_uses_one_rust_call_and_refreshes_after_selective(self):
        bridge, extension = self.bridge()
        first = bridge.evaluate_event(c2_event(5))
        second = bridge.evaluate_event(c2_event(6))
        third = bridge.evaluate_event(c2_event(7))
        self.assertEqual(first["decision_code"], REGIONAL_ACTIVE_QUERY)
        self.assertEqual(first["stable_region_mask"], 0b1001)
        self.assertEqual(second["decision_code"], FULL_COMPUTE)
        self.assertEqual(second["stable_region_mask"], 0)
        self.assertEqual(third["decision_code"], REGIONAL_ACTIVE_QUERY)
        self.assertEqual(len(extension.calls), 3)
        self.assertEqual(bridge.receipt()["rust_calls_per_block"], 0)
        self.assertEqual(bridge.receipt()["tensor_bytes_to_rust"], 0)

    def test_anchor_conflict_missing_and_late_plan_are_full_compute(self):
        bridge, _ = self.bridge()
        anchor = bridge.evaluate_event(c2_event(18))
        conflict = bridge.evaluate_event(c2_event(5, conflict=1))
        late = bridge.evaluate_event(c2_event(7, ready=False))
        self.assertEqual(anchor["decision_code"], FULL_COMPUTE)
        self.assertEqual(conflict["decision_code"], FULL_COMPUTE)
        self.assertEqual(late["decision_code"], ESCALATE_FULL_COMPUTE)
        self.assertIsNone(bridge.plans.get(3), "missing execution-step plan must remain unavailable")

    def test_region_mapping_is_exclusive_in_range_and_keeps_one_patch_seam(self):
        contract = region_mapping_contract()
        self.assertTrue(contract["exclusive"])
        self.assertTrue(contract["in_range"])
        self.assertEqual(len(REGION_LOCAL_ROWS), 4)
        self.assertGreater(contract["boundary_rows_full_compute"], 0)
        rows = [row for region in REGION_LOCAL_ROWS for row in region]
        self.assertEqual(len(rows), len(set(rows)))

    def test_only_stable_video_query_rows_are_omitted(self):
        nonvideo = 7
        active, omitted = active_query_row_indices(
            sequence_length=nonvideo + VIDEO_TOKEN_COUNT,
            video_start=nonvideo,
            video_stop=nonvideo + VIDEO_TOKEN_COUNT,
            stable_region_mask=0b0001,
            torch_module=torch,
            device=torch.device("cpu"),
        )
        active_set = set(active.tolist())
        self.assertTrue(set(range(nonvideo)).issubset(active_set))
        self.assertEqual(omitted, len(REGION_LOCAL_ROWS[0]))
        self.assertEqual(len(active_set), nonvideo + VIDEO_TOKEN_COUNT - omitted)

    def test_subset_q_full_kv_matches_full_attention_rows(self):
        ATTENTION_SHAPES.clear()
        attention = TinyAttention()
        x = torch.tensor([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.25]])
        all_rows = torch.arange(4)
        subset_rows = torch.tensor([0, 2, 3])
        kwargs = dict(
            rope_freqs=None,
            transformer_options={},
            optimized_attention=reference_attention,
            cast_to=lambda value, **_kwargs: value,
            in_training=False,
            rms_rope=lambda *args, **kwargs: (args[0], args[1]),
            rms_rope_in_place=lambda *args, **kwargs: None,
        )
        full = subset_query_attention(attention, x, active_indices=all_rows, **kwargs)
        subset = subset_query_attention(attention, x, active_indices=subset_rows, **kwargs)
        self.assertTrue(torch.allclose(subset, full.index_select(0, subset_rows), atol=1e-6))
        self.assertEqual(ATTENTION_SHAPES[0]["q"][-2], 4)
        self.assertEqual(ATTENTION_SHAPES[1]["q"][-2], 3)
        self.assertEqual(ATTENTION_SHAPES[1]["k"][-2], 4)
        self.assertEqual(ATTENTION_SHAPES[1]["v"][-2], 4)

    def test_full_q_wrapper_matches_original_attention_contract(self):
        ATTENTION_SHAPES.clear()
        attention = TinyAttention()
        x = torch.tensor([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [0.5, 0.25]])
        kwargs = dict(
            rope_freqs=None,
            transformer_options={},
            optimized_attention=reference_attention,
            cast_to=lambda value, **_kwargs: value,
            in_training=False,
            rms_rope=lambda *args, **kwargs: (args[0], args[1]),
            rms_rope_in_place=lambda *args, **kwargs: None,
        )
        wrapped = subset_query_attention(attention, x, active_indices=torch.arange(4), **kwargs)
        q, k, v = attention.qkv_proj(x).split(attention.heads * attention.head_dim, dim=-1)
        q = attention.q_norm(q.view(4, 1, 2)).transpose(0, 1).unsqueeze(0)
        k = attention.k_norm(k.view(4, 1, 2)).transpose(0, 1).unsqueeze(0)
        v = v.view(4, 1, 2).transpose(0, 1).unsqueeze(0)
        original = attention.out_proj(reference_attention(q, k, v, attention.heads).squeeze(0))
        self.assertTrue(torch.allclose(wrapped, original, atol=1e-6))

    def test_settings_digest_is_stable_and_mode_specific(self):
        self.assertEqual(
            active_query_settings_digest(mode=CONTROL_MODE),
            active_query_settings_digest(mode=CONTROL_MODE),
        )
        self.assertNotEqual(
            active_query_settings_digest(mode=CONTROL_MODE),
            active_query_settings_digest(mode=SELECTIVE_MODE, admitted_blocks=(1, 2, 3)),
        )

    def test_control_gate_enforces_opportunity_overhead_and_comparability(self):
        execution = {
            "admitted_block_count": 3,
            "planned_query_reduction": 0.05,
            "affected_non_anchor_steps": [3, 4, 5],
            "stable_region_plan_event_count": 3,
            "explicit_cuda_synchronization_count": 0,
        }
        region = {"boundary_roundtrip": {"p95_ns": 90_000}, "tensor_bytes_to_rust": 0}
        c2 = {"total_shadow_callback": {"p95_ns": CALLBACK_P95_NS_MAX}, "full_tensor_host_copy_bytes": 0}
        gate = control_admission(
            execution=execution,
            region_plan=region,
            c2_shadow=c2,
            sampler_seconds=488.847320,
            output_integrity_passed=True,
            source_admitted=True,
        )
        self.assertTrue(gate["passed"])
        execution["planned_query_reduction"] = 0.049
        rejected = control_admission(
            execution=execution,
            region_plan=region,
            c2_shadow=c2,
            sampler_seconds=488.847320,
            output_integrity_passed=True,
            source_admitted=True,
        )
        self.assertEqual(rejected["decision"], "A1_REGIONAL_QUERY_OPPORTUNITY_TOO_LOW")

    def test_hot_path_source_has_no_rust_call_cuda_sync_or_full_host_copy(self):
        source = inspect.getsource(H3ActiveQueryAttentionController.instrumented_forward)
        for forbidden in ("evaluate_attention_region_plan", "cuda.synchronize", ".cpu(", ".numpy("):
            self.assertNotIn(forbidden, source)
        self.assertIn("block.mlp(h)", source)

    def test_config_matches_frozen_product_question(self):
        path = Path(__file__).resolve().parents[2] / "configs" / "a1_h3_compound_eye_active_query_attention.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(config["mechanism"], MECHANISM_ID)
        self.assertEqual(config["execution"]["key"], "global_full")
        self.assertEqual(config["execution"]["value"], "global_full")
        self.assertFalse(config["profile"]["sage"])
        self.assertEqual(config["generation_budget"], 2)
        self.assertEqual(config["retry_budget"], 0)

    def test_workflow_is_mode_explicit_and_sage_free(self):
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0]}}}
        control = build_workflow(standard, mode=CONTROL_MODE, admitted_blocks=(), run_digest="11" * 32)
        selective = build_workflow(
            standard,
            mode=SELECTIVE_MODE,
            admitted_blocks=(1, 3, 5),
            run_digest="22" * 32,
        )
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
        self.assertTrue(gate["claim_boundary"]["global_kv_preserved"])

    def test_actual_pyo3_a1_roundtrip_when_extension_is_available(self):
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        contract = dict(boundary.attention_region_plan_contract())
        self.assertEqual(contract["abi_version"], ABI_VERSION)
        result = dict(
            boundary.evaluate_attention_region_plan(
                abi_version=ABI_VERSION,
                struct_size=contract["observation_struct_size"],
                run_digest=bytes.fromhex(DIGESTS["run_digest"]),
                workflow_revision_digest=bytes.fromhex(DIGESTS["workflow_revision_digest"]),
                settings_digest=bytes.fromhex(DIGESTS["settings_digest"]),
                model_revision_digest=bytes.fromhex(DIGESTS["model_revision_digest"]),
                observed_step=3,
                predicted_execution_step=5,
                total_steps=20,
                topology_id=1,
                eye_state=[2, 0, 1, 2, 0],
                eye_confidence_ppm=[500000, 900000, 1000000, 500000, 850000],
                eye_change_ppm=[40000, 5000, 90000, 30000, 7000],
                stable_mask=0b1001,
                stable_count=2,
                active_mask=0b0010,
                active_count=1,
                uncertain_mask=0b0100,
                uncertain_count=1,
                global_invalidation=False,
                overlap_conflict_mask=0,
                anchor_step=False,
                cooldown_mask=0,
                refresh_required_mask=0,
                source_valid=True,
                prediction_valid=True,
                selective_supported=True,
                fallback_supported=True,
                fatal_flags=0,
                unsupported_flags=0,
            )
        )
        self.assertEqual(result["ffi_status"], 0)
        self.assertEqual(result["decision_code"], REGIONAL_ACTIVE_QUERY)
        self.assertEqual(result["stable_region_mask"], 0b1001)


if __name__ == "__main__":
    unittest.main()
