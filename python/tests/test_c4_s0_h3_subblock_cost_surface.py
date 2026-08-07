from __future__ import annotations

from pathlib import Path
import json
import os
import unittest

from hive_product.c4_s0_h3_cost_probe import build_workflow, mapping_gate, settings_digest
from hive_product.h3_subblock_cost_surface import (
    BLOCK_COUNT,
    EXPECTED_BLOCK_CALLS,
    LOGICAL_GROUPS,
    MAX_EVENT_OBJECT_COUNT,
    MAX_EVENT_PAIR_COUNT,
    H3SubBlockTimingController,
    instrumentation_comparability,
    inspect_installed_source,
    rank_compute_levers,
)


class Box:
    def __init__(self, value: float) -> None:
        self.value = value


class Op:
    def __init__(self, name: str, fn, calls: list[str]) -> None:
        self.name = name
        self.fn = fn
        self.calls = calls

    def __call__(self, *args, **kwargs):
        self.calls.append(self.name)
        return self.fn(*args, **kwargs)


class FakeBlock:
    calls: list[str] = []
    mod_scale_shift = None
    mod_gate = None

    def __init__(self, *, fail_mlp: bool = False) -> None:
        calls = self.calls
        self.adaln_proj = Op("adaln", lambda _t: (1.0, 0.5, 0.25, 0.75, 0.25, 0.5), calls)
        self.norm1 = Op("norm1", lambda x: x.value + 1.0, calls)
        self.attn = Op("attn", lambda h, **_kwargs: h * 0.5, calls)
        self.norm2 = Op("norm2", lambda x: x.value + 2.0, calls)

        def mlp(value):
            if fail_mlp:
                raise RuntimeError("expected test failure")
            return value * 0.25

        self.mlp = Op("mlp", mlp, calls)

    def forward(self, x, t_emb, mod_segments, rope_freqs, transformer_options=None):
        shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = self.adaln_proj(t_emb)
        h = self.mod_scale_shift(self.norm1(x), shift_msa, scale_msa, mod_segments)
        x = self.mod_gate(
            x,
            gate_msa,
            self.attn(h, rope_freqs=rope_freqs, transformer_options=transformer_options or {}),
            mod_segments,
        )
        h = self.mod_scale_shift(self.norm2(x), shift_mlp, scale_mlp, mod_segments)
        return self.mod_gate(x, gate_mlp, self.mlp(h), mod_segments)


def fake_mod_scale_shift(value, shift, scale, _segments):
    FakeBlock.calls.append("mod_scale_shift")
    return (value * (1.0 + scale) + shift) % 101.0


def fake_mod_gate(x, gate, other, _segments):
    FakeBlock.calls.append("mod_gate")
    x.value = (x.value + gate * other) % 101.0
    return x


FakeBlock.mod_scale_shift = staticmethod(fake_mod_scale_shift)
FakeBlock.mod_gate = staticmethod(fake_mod_gate)


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
        self.timestamp = None

    def record(self):
        self.clock.value += 0.25
        self.timestamp = self.clock.value

    def elapsed_time(self, other):
        return other.timestamp - self.timestamp


def make_controller(clock: FakeClock, *, supported: bool = True):
    return H3SubBlockTimingController(
        event_factory=clock.event,
        synchronize=clock.synchronize,
        mod_scale_shift=fake_mod_scale_shift,
        mod_gate=fake_mod_gate,
        events_supported=supported,
        unsupported_reason=None if supported else "fake CUDA events unavailable",
    )


class C4S0SubBlockCostSurfaceTests(unittest.TestCase):
    def setUp(self):
        FakeBlock.calls = []

    def test_logical_groups_are_source_ordered_and_bounded(self):
        self.assertEqual(
            [group.group_id for group in LOGICAL_GROUPS],
            [
                "modulation_parameter_projection",
                "attention_norm_modulation",
                "attention_global_mixing",
                "attention_residual_update",
                "feed_forward_positionwise",
                "feed_forward_residual_update",
            ],
        )
        self.assertLessEqual(len(LOGICAL_GROUPS), 6)

    def test_instrumented_wrapper_preserves_original_result_and_order(self):
        original = FakeBlock.forward
        plain = FakeBlock()
        expected = plain.forward(Box(3.0), "t", [(0, 1, 0)], "rope", {}).value
        expected_order = list(FakeBlock.calls)
        FakeBlock.calls = []
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock)
        try:
            actual = FakeBlock().forward(Box(3.0), "t", [(0, 1, 0)], "rope", {}).value
        finally:
            controller.restore()
        self.assertEqual(actual, expected)
        self.assertEqual(FakeBlock.calls, expected_order)
        self.assertIs(FakeBlock.forward, original)
        self.assertEqual(controller.block_call_count, 1)
        self.assertEqual(controller.model_forward_count, 1)

    def test_deferred_events_have_one_final_synchronization_and_nested_accounting(self):
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock)
        controller.start_sampler()
        try:
            FakeBlock().forward(Box(1.0), "t", [], "rope", {})
            controller.end_sampler()
        finally:
            controller.restore()
        report = controller.finalize()
        self.assertEqual(report["synchronization_count"], 1)
        self.assertEqual(clock.synchronizations, 1)
        self.assertEqual(report["event_pair_creation_count"], 8)
        self.assertEqual(report["event_object_count"], 16)
        self.assertGreaterEqual(report["unattributed_within_dit_block_ms"], 0.0)
        self.assertEqual(len(report["logical_groups"]), 6)
        self.assertNotIn("gpu_kernel_seconds", report)
        self.assertEqual(report["kernel_profiler_support_status"], "not_collected")

    def test_full_contract_event_count_bound_and_serialization(self):
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock)
        controller.start_sampler()
        try:
            for _ in range(EXPECTED_BLOCK_CALLS):
                FakeBlock().forward(Box(1.0), "t", [], "rope", {})
            controller.end_sampler()
        finally:
            controller.restore()
        report = controller.finalize()
        self.assertEqual(report["model_forward_count"], 20)
        self.assertEqual(report["block_call_count"], 1000)
        self.assertEqual(report["event_pair_creation_count"], MAX_EVENT_PAIR_COUNT)
        self.assertEqual(report["event_object_count"], MAX_EVENT_OBJECT_COUNT)
        self.assertEqual(report["mapping_error_count"], 0)
        self.assertEqual(len(report["per_block"]), BLOCK_COUNT)
        self.assertEqual(len(report["per_step"]), 20)
        json.dumps(report, sort_keys=True)

    def test_exception_path_allows_explicit_restoration(self):
        original = FakeBlock.forward
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock)
        try:
            with self.assertRaisesRegex(RuntimeError, "expected test failure"):
                FakeBlock(fail_mlp=True).forward(Box(1.0), "t", [], "rope", {})
        finally:
            controller.restore()
        self.assertIs(FakeBlock.forward, original)
        self.assertEqual(controller.wrapper_failure_count, 1)

    def test_unsupported_event_path_preserves_original_and_uses_null(self):
        original = FakeBlock.forward
        clock = FakeClock()
        controller = make_controller(clock, supported=False)
        controller.install(FakeBlock)
        controller.start_sampler()
        result = FakeBlock().forward(Box(1.0), "t", [], "rope", {})
        controller.end_sampler()
        report = controller.finalize()
        self.assertIs(FakeBlock.forward, original)
        self.assertIsInstance(result, Box)
        self.assertEqual(report["support_status"], "unsupported")
        self.assertIsNone(report["value"])
        self.assertEqual(report["reason"], "fake CUDA events unavailable")
        self.assertEqual(report["synchronization_count"], 0)

    def test_installed_source_parser_matches_admitted_contract(self):
        root_value = os.environ.get("HIVEFRAME_COMFYUI_ROOT")
        if not root_value:
            self.skipTest("HIVEFRAME_COMFYUI_ROOT is not configured")
        source = Path(root_value) / "comfy" / "ldm" / "minimax" / "model.py"
        admission = inspect_installed_source(source)
        self.assertTrue(admission["admitted"], admission)
        self.assertEqual(admission["block_count"], 50)
        self.assertEqual(len(admission["logical_groups"]), 6)

    def test_workflow_mapping_is_full_compute_instrumentation_only(self):
        base = {
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["5", 0]},
            }
        }
        mapped = build_workflow(base, run_digest="r", settings_digest_value="s")
        self.assertEqual(mapped["10"]["class_type"], "HIVEFRAMEH3SubBlockCostSampler")
        self.assertNotIn("skip", mapped["10"]["inputs"])
        self.assertNotIn("reuse", mapped["10"]["inputs"])
        self.assertNotIn("selective", mapped["10"]["inputs"])
        self.assertEqual(base["10"]["class_type"], "SamplerCustomAdvanced")

    def test_settings_digest_and_comparability_are_stable(self):
        self.assertEqual(settings_digest(), settings_digest())
        self.assertTrue(instrumentation_comparability(488.584958)["passed"])
        self.assertFalse(instrumentation_comparability(514.0)["passed"])

    def test_ranking_keeps_global_attention_full_compute(self):
        groups = []
        for group in LOGICAL_GROUPS:
            share = 0.45 if group.group_id == "attention_global_mixing" else 0.01
            if group.group_id == "feed_forward_positionwise":
                share = 0.35
            groups.append({**group.public(), "share_of_sampler_cuda_event_span": share})
        ranking = rank_compute_levers({"logical_groups": groups})
        self.assertEqual(ranking["next_primary_compute_lever"], "MIXED_SUBBLOCK_SELECTIVE")
        self.assertEqual(ranking["selected_group_id"], "feed_forward_positionwise")

    def test_mapping_gate_requires_exact_full_compute_counts(self):
        groups = [
            {"group_id": group.group_id, "timing": {"count": 1000}}
            for group in LOGICAL_GROUPS
        ]
        callback = {
            "sampler_succeeded": True,
            "full_compute_only": True,
            "skip_count": 0,
            "reuse_count": 0,
            "prediction_count": 0,
            "regional_execution_count": 0,
            "token_omission_count": 0,
            "attention_omission_count": 0,
            "timing": {
                "support_status": "collected",
                "model_forward_count": 20,
                "block_call_count": 1000,
                "mapping_error_count": 0,
                "wrapper_failure_count": 0,
                "logical_groups": groups,
                "synchronization_count": 1,
                "event_pair_creation_count": 7001,
                "event_pair_bound": 7001,
                "event_object_count": 14002,
                "event_object_bound": 14002,
                "profiler_enabled": False,
                "skip_count": 0,
                "reuse_count": 0,
                "prediction_count": 0,
                "regional_execution_count": 0,
                "token_omission_count": 0,
                "attention_omission_count": 0,
            },
        }
        self.assertTrue(mapping_gate(callback)["passed"])
        callback["timing"]["skip_count"] = 1
        self.assertFalse(mapping_gate(callback)["passed"])


if __name__ == "__main__":
    unittest.main()
