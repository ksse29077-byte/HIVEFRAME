from __future__ import annotations

from pathlib import Path
import inspect
import json
import os
import unittest

import torch

from hive_product.c4_s1_h3_ff_token_probe import (
    CONTROL_MODE,
    SELECTIVE_MODE,
    build_workflow,
    instrumentation_comparability,
    policy_admission,
    settings_digest,
)
from hive_product.ff_token_selective import (
    ANCHOR_STEPS,
    H3FFTokenSelectiveController,
    MIN_BLOCK_VIDEO_SKIP_RATIO,
    MODEL_SOURCE_SHA256,
    POLICIES,
    SCALAR_METADATA_BUDGET_BYTES,
    SELECTOR_ID,
    VIDEO_TOKEN_COUNT,
    causal_candidate_mask,
    execute_active_rows,
    fixed_contract,
    inspect_installed_ff_source,
    scalar_metadata_bytes,
)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.synchronizations = 0

    def event(self):
        return FakeEvent(self)

    def synchronize(self):
        self.synchronizations += 1


class FakeEvent:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.timestamp = 0.0

    def record(self):
        self.clock.value += 0.25
        self.timestamp = self.clock.value

    def elapsed_time(self, other):
        return other.timestamp - self.timestamp


class Identity:
    def __call__(self, x):
        return x


class Attention:
    def __call__(self, h, **_kwargs):
        return torch.zeros_like(h)


class CountingMLP:
    def __init__(self) -> None:
        self.calls = 0
        self.rows: list[int] = []

    def __call__(self, h):
        self.calls += 1
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
    clock = FakeClock()
    controller = H3FFTokenSelectiveController(
        mode=mode,
        selected_policy=selected_policy,
        event_factory=clock.event,
        synchronize=clock.synchronize,
        mod_scale_shift=mod_scale_shift,
        mod_gate=mod_gate,
        torch_module=torch,
    )
    return controller, clock


class C4S1FFTokenSelectiveTests(unittest.TestCase):
    def test_frozen_contract_and_three_exact_policies(self):
        self.assertEqual(SELECTOR_ID, "FF_POSITIONWISE_LOW_IMPACT_TOKEN_SKIP_V1")
        self.assertEqual(ANCHOR_STEPS, (0, 1, 18, 19))
        self.assertEqual(
            [(p.policy_id, p.prev_ff_delta_ratio_max, p.h_norm_change_max, p.gate_norm_change_max) for p in POLICIES],
            [("P0", 0.0025, 0.005, 0.005), ("P1", 0.005, 0.01, 0.01), ("P2", 0.01, 0.02, 0.02)],
        )
        self.assertEqual(MIN_BLOCK_VIDEO_SKIP_RATIO, 0.10)

    def test_scalar_history_is_under_fixed_budget_and_has_no_tensor_cache(self):
        contract = fixed_contract()
        self.assertLess(scalar_metadata_bytes(), SCALAR_METADATA_BUDGET_BYTES)
        self.assertEqual(contract["persistent_scalar_metadata_bytes"], scalar_metadata_bytes())
        self.assertFalse(contract["full_tensor_cache"])
        self.assertEqual(contract["tensor_bytes_to_rust"], 0)
        self.assertEqual(contract["host_full_tensor_copy_bytes"], 0)

    def test_source_hash_layout_order_and_positionwise_mlp_are_admitted(self):
        root = os.environ.get("HIVEFRAME_COMFYUI_ROOT")
        if not root:
            self.skipTest("HIVEFRAME_COMFYUI_ROOT is not configured")
        source = Path(root) / "comfy" / "ldm" / "minimax" / "model.py"
        result = inspect_installed_ff_source(source)
        self.assertTrue(result["admitted"], result)
        self.assertEqual(result["source_sha256"], MODEL_SOURCE_SHA256)
        self.assertEqual(result["video_segment"]["expected_token_count"], VIDEO_TOKEN_COUNT)
        self.assertIn("nthw", result["token_order"])
        self.assertIn("Linear-SwiGLU-Linear", result["mlp_row_execution"])

    def test_live_selector_has_no_current_mlp_or_oracle_parameter(self):
        parameters = set(inspect.signature(causal_candidate_mask).parameters)
        self.assertNotIn("current_mlp_output", parameters)
        self.assertNotIn("current_ff_delta", parameters)
        self.assertNotIn("oracle_impact", parameters)
        self.assertEqual(
            parameters,
            {"policy", "history_valid", "prev_h_norm", "prev_ff_delta_ratio", "prev_gate_norm", "current_h_norm", "current_gate_norm"},
        )

    def test_causal_mask_invalid_nonfinite_and_thresholds_fail_open(self):
        p0 = POLICIES[0]
        ones = torch.ones(4)
        mask = causal_candidate_mask(
            policy=p0,
            history_valid=torch.tensor([True, False, True, True]),
            prev_h_norm=ones,
            prev_ff_delta_ratio=torch.tensor([0.002, 0.001, float("nan"), 0.003]),
            prev_gate_norm=ones,
            current_h_norm=ones,
            current_gate_norm=ones,
        )
        self.assertEqual(mask.tolist(), [True, False, False, False])

    def test_active_row_execution_is_one_call_scatter_correct_and_skips_zero_update(self):
        x = torch.zeros((6, 2))
        h = torch.arange(12, dtype=torch.float32).reshape(6, 2)
        mlp = CountingMLP()
        gates = torch.tensor([[2.0, 2.0], [3.0, 3.0], [4.0, 4.0]])
        segments = [(0, 2, 1), (2, 4, 2), (4, 6, 0)]
        active = torch.tensor([0, 1, 2, 3, 5])
        result, output = execute_active_rows(x=x, h=h, mlp=mlp, gate_mlp=gates, mod_segments=segments, active_indices=active)
        self.assertEqual(mlp.calls, 1)
        self.assertEqual(output.shape[0], 5)
        self.assertTrue(torch.equal(result[4], torch.zeros(2)))
        self.assertTrue(torch.allclose(result[5], h[5] * 0.001 * gates[0]))

    def test_control_wrapper_preserves_full_path_and_restores(self):
        original = FakeBlock.forward
        controller, clock = make_controller()
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
        self.assertIs(FakeBlock.forward, original)
        self.assertEqual(clock.synchronizations, 1)
        self.assertEqual(report["attention_omission_count"], 0)
        self.assertEqual(report["omitted_video_row_count"], 0)

    def test_anchor_invalidates_skip_and_skipped_history_requires_refresh(self):
        controller, _ = make_controller(SELECTIVE_MODE, "P2")
        current = torch.ones(4)
        first = controller._candidate_masks(block_index=0, step_index=0, current_h_norm=current, current_gate_norm=current)
        self.assertFalse(first["P2"].any())
        controller._update_history(
            block_index=0,
            current_h_norm=current,
            current_gate_norm=current,
            actual_ratio=torch.full((4,), 0.001),
            computed_mask=torch.ones(4, dtype=torch.bool),
            counterfactual_masks=first,
        )
        candidate = controller._candidate_masks(block_index=0, step_index=2, current_h_norm=current, current_gate_norm=current)
        self.assertTrue(candidate["P2"].all())
        controller._update_history(
            block_index=0,
            current_h_norm=current,
            current_gate_norm=current,
            actual_ratio=torch.zeros(4),
            computed_mask=torch.zeros(4, dtype=torch.bool),
            counterfactual_masks=candidate,
        )
        next_mask = controller._candidate_masks(block_index=0, step_index=3, current_h_norm=current, current_gate_norm=current)
        self.assertFalse(next_mask["P2"].any())

    def test_under_ten_percent_candidate_uses_full_mlp(self):
        controller, _ = make_controller(SELECTIVE_MODE, "P2")
        block = FakeBlock()
        controller.block_call_count = 2 * 50
        current = torch.ones(20)
        history = controller._new_history(current, current)
        history.prev_h_norm.fill_(1.0)
        history.prev_ff_delta_ratio.fill_(1.0)
        history.prev_ff_delta_ratio[0] = 0.001
        history.prev_gate_norm.fill_(2 ** 0.5)
        history.valid_by_policy["P2"].fill_(True)
        controller.history[0] = history
        segments = [(0, 2, 1), (2, 4, 2), (4, 24, 0)]
        controller.instrumented_forward(block, torch.ones((24, 2)), None, segments, None, {})
        self.assertEqual(block.mlp.rows, [24])
        self.assertEqual(controller.omitted_video_row_count, 0)

    def test_segment_or_shape_mismatch_fails_open_to_full_mlp(self):
        controller, _ = make_controller(SELECTIVE_MODE, "P2")
        block = FakeBlock()
        bad_segments = [(0, 4, 1), (4, 7, 0)]
        controller.instrumented_forward(block, torch.ones((8, 2)), None, bad_segments, None, {})
        self.assertEqual(block.mlp.rows, [8])
        self.assertEqual(controller.fail_open_count, 1)
        self.assertEqual(controller.omitted_video_row_count, 0)

    def test_workflow_mapping_preserves_standard_and_exposes_one_mode(self):
        base = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0]}}}
        mapped = build_workflow(base, mode=CONTROL_MODE, selected_policy=None, run_digest="r")
        self.assertEqual(mapped["10"]["class_type"], "HIVEFRAMEH3FFTokenSelectiveSampler")
        self.assertEqual(mapped["10"]["inputs"]["mode"], CONTROL_MODE)
        self.assertEqual(base["10"]["class_type"], "SamplerCustomAdvanced")

    def test_settings_hashes_are_stable_and_mode_distinct(self):
        control = settings_digest(mode=CONTROL_MODE, selected_policy=None)
        selective = settings_digest(mode=SELECTIVE_MODE, selected_policy="P0")
        self.assertEqual(control, settings_digest(mode=CONTROL_MODE, selected_policy=None))
        self.assertNotEqual(control, selective)

    def test_control_comparability_uses_immutable_c4_s0_reference(self):
        self.assertTrue(instrumentation_comparability(488.847320)["passed"])
        self.assertFalse(instrumentation_comparability(514.0)["passed"])

    def test_policy_admission_uses_all_fixed_gates_and_conservative_tie_break(self):
        shadow = {}
        for policy in POLICIES:
            shadow[policy.policy_id] = {
                "all_token_mlp_row_reduction": 0.11,
                "video_token_skip_ratio": 0.21,
                "affected_step_count": 3,
                "affected_block_count": 10,
                "actual_impact": {"mean": 0.002, "p99": 0.009, "over_0_010_rate": 0.001, "max": 0.02, "nonfinite_count": 0},
            }
        result = policy_admission({"instrumentation": {"policy_shadow": shadow}})
        self.assertTrue(result["passed"])
        self.assertEqual(result["selected_policy"], "P0")

    def test_json_config_matches_code_contract(self):
        config = json.loads((Path(__file__).resolve().parents[2] / "configs" / "c4_s1_ff_token_selective.json").read_text(encoding="utf-8"))
        self.assertEqual(config["selector_id"], SELECTOR_ID)
        self.assertEqual(config["anchors"], list(ANCHOR_STEPS))
        self.assertEqual(config["generation_budget"], 2)
        self.assertEqual(config["retry_budget"], 0)


if __name__ == "__main__":
    unittest.main()
