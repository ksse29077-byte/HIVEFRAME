from __future__ import annotations

from pathlib import Path
import inspect
import json
import unittest

import torch

from hive_product.c4_s1_r1_h3_ff_minimal_probe import (
    CONTROL_MODE,
    SELECTIVE_MODE,
    build_workflow,
    instrumentation_comparability,
    instrumentation_gate,
    minimal_telemetry_contract,
    policy_admission,
    settings_digest,
)
from hive_product.ff_token_minimal import (
    H3FFTokenMinimalController,
    _BoundedImpactAggregate,
    tail_gate_implies_p99,
)
from hive_product.ff_token_selective import (
    ANCHOR_STEPS,
    MIN_BLOCK_VIDEO_SKIP_RATIO,
    POLICIES,
    SELECTOR_ID,
)


class Identity:
    def __call__(self, x):
        return x


class Attention:
    def __call__(self, h, **_kwargs):
        return torch.zeros_like(h)


class CountingMLP:
    def __init__(self) -> None:
        self.rows: list[int] = []

    def __call__(self, h):
        self.rows.append(int(h.shape[0]))
        return h * 0.001


class FakeBlock:
    forward = None

    def __init__(self) -> None:
        self.norm1 = Identity()
        self.norm2 = Identity()
        self.attn = Attention()
        self.mlp = CountingMLP()

    def adaln_proj(self, _t):
        zero = torch.zeros((3, 2), dtype=torch.float32)
        one = torch.ones((3, 2), dtype=torch.float32)
        return zero, zero, one, zero, zero, one


def mod_scale_shift(h, shift, scale, segments):
    out = h.clone()
    for start, stop, row in segments:
        out[start:stop].mul_(1.0 + scale[row]).add_(shift[row])
    return out


def mod_gate(x, gate, other, segments):
    for start, stop, row in segments:
        x[start:stop].add_(other[start:stop] * gate[row])
    return x


def original_forward(block, x, t_emb, segments, rope, transformer_options=None):
    shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = block.adaln_proj(t_emb)
    h = mod_scale_shift(block.norm1(x), shift_msa, scale_msa, segments)
    x = mod_gate(x, gate_msa, block.attn(h, rope_freqs=rope, transformer_options=transformer_options or {}), segments)
    h = mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, segments)
    return mod_gate(x, gate_mlp, block.mlp(h), segments)


FakeBlock.forward = original_forward


def make_controller(mode=CONTROL_MODE, selected_policy=None):
    return H3FFTokenMinimalController(
        mode=mode,
        selected_policy=selected_policy,
        mod_scale_shift=mod_scale_shift,
        mod_gate=mod_gate,
        torch_module=torch,
    )


class C4S1R1MinimalTelemetryTests(unittest.TestCase):
    def test_selector_policies_and_safety_contract_are_unchanged(self):
        self.assertEqual(SELECTOR_ID, "FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1")
        self.assertEqual(ANCHOR_STEPS, (0, 1, 18, 19))
        self.assertEqual(MIN_BLOCK_VIDEO_SKIP_RATIO, 0.10)
        self.assertEqual(
            [(p.policy_id, p.prev_ff_delta_ratio_max, p.h_norm_change_max, p.gate_norm_change_max) for p in POLICIES],
            [("P0", 0.0025, 0.005, 0.005), ("P1", 0.005, 0.01, 0.01), ("P2", 0.01, 0.02, 0.02)],
        )

    def test_minimal_contract_removes_measurement_only_hot_path_work(self):
        contract = minimal_telemetry_contract()["measurement_only_work"]
        self.assertEqual(contract["per_block_cuda_event_pairs"], 0)
        self.assertEqual(contract["explicit_hot_path_cuda_synchronizations"], 0)
        self.assertEqual(contract["control_hot_path_item_reads"], 0)
        self.assertEqual(contract["hot_path_tensor_to_cpu"], 0)
        self.assertEqual(contract["histogram_bins"], 0)
        self.assertFalse(contract["resource_sampler_enabled"])

    def test_control_hot_path_source_has_no_event_sync_histogram_or_host_transfer(self):
        source = inspect.getsource(H3FFTokenMinimalController.instrumented_forward)
        for forbidden in ("cuda.Event", "synchronize(", ".cpu(", ".numpy(", ".tolist(", "histc("):
            self.assertNotIn(forbidden, source)
        self.assertIn("if not self.is_control", source)

    def test_bounded_aggregate_is_exact_and_p99_is_derived_not_invented(self):
        aggregate = _BoundedImpactAggregate(torch, torch.device("cpu"))
        values = torch.tensor([0.001, 0.011, 0.020, float("nan"), 0.009])
        mask = torch.tensor([True, True, False, True, True])
        aggregate.add_masked(values, mask)
        result = aggregate.result()
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["impact_sum"], 0.021, places=6)
        self.assertAlmostEqual(result["mean"], 0.007, places=6)
        self.assertAlmostEqual(result["max"], 0.011, places=6)
        self.assertEqual(result["over_0_010_count"], 1)
        self.assertEqual(result["nonfinite_count"], 1)
        self.assertIsNone(result["p99"])
        self.assertEqual(result["p99_support_status"], "derived_from_stricter_tail_gate")

    def test_tail_rate_gate_logically_implies_p99_gate(self):
        self.assertTrue(tail_gate_implies_p99(count=1000, over_threshold_count=5))
        self.assertFalse(tail_gate_implies_p99(count=1000, over_threshold_count=6))
        self.assertFalse(tail_gate_implies_p99(count=0, over_threshold_count=0))

    def test_control_execution_preserves_full_compute_and_reports_zero_hot_path_telemetry(self):
        controller = make_controller()
        original = FakeBlock.forward
        controller.install(FakeBlock)
        controller.start_sampler()
        block = FakeBlock()
        x = torch.ones((8, 2))
        segments = [(0, 2, 1), (2, 4, 2), (4, 8, 0)]
        actual = block.forward(x.clone(), None, segments, None, {})
        controller.end_sampler()
        report = controller.finalize()
        controller.restore()
        expected = original(FakeBlock(), x.clone(), None, segments, None, {})
        self.assertTrue(torch.allclose(actual, expected))
        self.assertEqual(report["actual_mlp_row_count"], report["full_mlp_row_count"])
        self.assertEqual(report["omitted_video_row_count"], 0)
        self.assertEqual(report["synchronization_count"], 0)
        audit = report["minimal_telemetry_audit"]
        self.assertEqual(audit["per_block_cuda_event_pair_count"], 0)
        self.assertEqual(audit["control_hot_path_item_count"], 0)
        self.assertEqual(audit["hot_path_host_tensor_transfer_count"], 0)
        self.assertEqual(audit["histogram_bin_count"], 0)
        for name in ("full_ff_group", "actual_mlp", "gather_mask", "scatter_residual"):
            self.assertIsNone(report["timing"][name]["value"])
            self.assertEqual(report["timing"][name]["support_status"], "not_collected")

    def test_fail_open_and_wrapper_restore_are_preserved(self):
        controller = make_controller(SELECTIVE_MODE, "P2")
        original = FakeBlock.forward
        controller.install(FakeBlock)
        block = FakeBlock()
        block.forward(torch.ones((8, 2)), None, [(0, 4, 1), (4, 7, 0)], None, {})
        controller.restore()
        self.assertEqual(block.mlp.rows, [8])
        self.assertEqual(controller.fail_open_count, 1)
        self.assertIs(FakeBlock.forward, original)

    def test_workflow_mapping_and_settings_hash_are_mode_explicit(self):
        base = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0]}}}
        control = build_workflow(base, mode=CONTROL_MODE, selected_policy=None, run_digest="r")
        selective = build_workflow(base, mode=SELECTIVE_MODE, selected_policy="P0", run_digest="r")
        self.assertEqual(control["10"]["class_type"], "HIVEFRAMEH3FFTokenMinimalSampler")
        self.assertEqual(control["10"]["inputs"]["mode"], CONTROL_MODE)
        self.assertEqual(base["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertNotEqual(control["10"]["inputs"]["settings_digest"], selective["10"]["inputs"]["settings_digest"])
        self.assertEqual(settings_digest(mode=CONTROL_MODE, selected_policy=None), settings_digest(mode=CONTROL_MODE, selected_policy=None))

    def test_comparability_gate_remains_fixed(self):
        self.assertTrue(instrumentation_comparability(488.847320)["passed"])
        self.assertFalse(instrumentation_comparability(514.0)["passed"])
        self.assertEqual(instrumentation_comparability(488.847320)["relative_limit"], 0.05)

    def test_policy_admission_uses_derived_p99_and_all_frozen_gates(self):
        shadow = {}
        for policy in POLICIES:
            shadow[policy.policy_id] = {
                "all_token_mlp_row_reduction": 0.11,
                "video_token_skip_ratio": 0.21,
                "affected_step_count": 3,
                "affected_block_count": 10,
                "actual_impact": {
                    "mean": 0.002,
                    "p99": None,
                    "p99_support_status": "derived_from_stricter_tail_gate",
                    "p99_gate_pass": True,
                    "over_0_010_rate": 0.001,
                    "max": 0.02,
                    "nonfinite_count": 0,
                },
            }
        result = policy_admission({"instrumentation": {"policy_shadow": shadow}})
        self.assertTrue(result["passed"])
        self.assertEqual(result["selected_policy"], "P0")

    def test_instrumentation_gate_rejects_any_reintroduced_measurement_path(self):
        timing = {
            name: {"value": None, "support_status": "not_collected"}
            for name in ("full_ff_group", "actual_mlp", "gather_mask", "scatter_residual")
        }
        data = {
            "model_forward_count": 20,
            "block_call_count": 1000,
            "mapping_error_count": 0,
            "wrapper_failure_count": 0,
            "observed_video_token_count": 14985,
            "observed_hidden_width": 5376,
            "attention_omission_count": 0,
            "non_video_omission_count": 0,
            "mlp_call_count": 1000,
            "actual_mlp_row_count": 100000,
            "full_mlp_row_count": 100000,
            "omitted_video_row_count": 0,
            "synchronization_count": 0,
            "profiler_enabled": False,
            "timing": timing,
            "minimal_telemetry_audit": {
                "per_block_cuda_event_pair_count": 0,
                "control_hot_path_item_count": 0,
                "hot_path_host_tensor_transfer_count": 0,
                "histogram_bin_count": 0,
                "resource_sampler_enabled": False,
            },
            "memory_contract": {
                "budget_passed": True,
                "full_tensor_cache_count": 0,
                "host_full_tensor_copy_bytes": 0,
                "tensor_bytes_to_rust": 0,
            },
        }
        callback = {"sampler_succeeded": True, "mode": CONTROL_MODE, "attention_execution": "ALWAYS_FULL_COMPUTE", "instrumentation": data}
        self.assertTrue(instrumentation_gate(callback, mode=CONTROL_MODE)["passed"])
        data["minimal_telemetry_audit"]["per_block_cuda_event_pair_count"] = 1
        self.assertFalse(instrumentation_gate(callback, mode=CONTROL_MODE)["passed"])

    def test_json_config_matches_predeclared_contract(self):
        config_path = Path(__file__).resolve().parents[2] / "configs" / "c4_s1_r1_ff_minimal_telemetry.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["selector_id"], SELECTOR_ID)
        self.assertEqual(config["anchors"], list(ANCHOR_STEPS))
        self.assertEqual(config["minimal_telemetry"]["histogram_bins"], 0)
        self.assertEqual(config["generation_budget"], 2)
        self.assertEqual(config["retry_budget"], 0)


if __name__ == "__main__":
    unittest.main()
