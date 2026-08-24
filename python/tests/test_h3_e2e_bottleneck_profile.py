from __future__ import annotations

import json
import unittest

from hive_product.h3_e2e_bottleneck_profile import (
    EVENT_OBJECT_BOUND,
    EVENT_PAIR_BOUND,
    LEAF_CATEGORIES,
    H3AggregateTimingController,
    profile_mapping_gate,
)
from hive_product.h3_e2e_bottleneck_probe import _candidate_ranking, build_workflow


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


class FakeTensor:
    def __init__(self, value: float, shape=(4, 6)) -> None:
        self.value = value
        self.shape = shape
        self.device = "cuda"

    def split(self, _size, dim=-1):
        return tuple(FakeTensor(self.value + offset, self.shape) for offset in (1, 2, 3))

    def view(self, *shape):
        self.shape = tuple(shape)
        return self

    def transpose(self, _a, _b):
        return self

    def unsqueeze(self, _axis):
        return self

    def squeeze(self, _axis):
        return self

    def __getitem__(self, _index):
        return self


class Op:
    def __init__(self, name: str, calls: list[str], delta: float = 1.0) -> None:
        self.name = name
        self.calls = calls
        self.delta = delta

    def __call__(self, value, *args, **kwargs):
        self.calls.append(self.name)
        raw = value.value if isinstance(value, FakeTensor) else float(value)
        return FakeTensor(raw + self.delta)


class Norm(Op):
    weight = FakeTensor(1.0)
    eps = 1e-5


class FakeAttention:
    def __init__(self, calls: list[str]) -> None:
        self.heads = 2
        self.head_dim = 3
        self.qkv_proj = Op("qkv", calls)
        self.q_norm = Norm("q_norm", calls)
        self.k_norm = Norm("k_norm", calls)
        self.out_proj = Op("out", calls)


class FakeMLP:
    def __init__(self, calls: list[str]) -> None:
        self.fc1 = Op("fc1", calls)
        self.fc2 = Op("fc2", calls)


class FakeBlock:
    calls: list[str] = []

    def __init__(self) -> None:
        self.adaln_proj = self._adaln
        self.norm1 = Norm("norm1", self.calls)
        self.norm2 = Norm("norm2", self.calls)
        self.attn = FakeAttention(self.calls)
        self.mlp = FakeMLP(self.calls)

    def _adaln(self, _value):
        self.calls.append("adaln")
        return tuple(FakeTensor(float(index)) for index in range(6))

    def forward(self, x, t_emb, mod_segments, rope_freqs, transformer_options=None):
        raise AssertionError("original block forward should be wrapped in this fixture")


class FakeModel:
    blocks: list[FakeBlock] = []

    def _forward(self, x):
        for block in self.blocks:
            x = block.forward(x, FakeTensor(1.0), [], None, {})
        return x


def make_controller(clock: FakeClock, *, supported: bool = True):
    def mod_scale(value, *_args):
        FakeBlock.calls.append("mod_scale")
        return value

    def mod_gate(x, _gate, other, _segments):
        FakeBlock.calls.append("mod_gate")
        return FakeTensor(x.value + other.value)

    def attention(q, _k, _v, _heads, **_kwargs):
        FakeBlock.calls.append("attention")
        return q

    def linear_input_act(fc2, value, _activation):
        FakeBlock.calls.append("swiglu")
        return fc2(value)

    return H3AggregateTimingController(
        event_factory=clock.event,
        synchronize=clock.synchronize,
        mod_scale_shift=mod_scale,
        mod_gate=mod_gate,
        optimized_attention=attention,
        cast_to=lambda value, **_kwargs: value,
        in_training=lambda: False,
        rms_rope=lambda q, k, *_args, **_kwargs: (q, k),
        rms_rope_in_place=lambda *_args, **_kwargs: None,
        linear_input_act=linear_input_act,
        events_supported=supported,
        unsupported_reason=None if supported else "CUDA unavailable",
    )


class H3EndToEndBottleneckProfileTests(unittest.TestCase):
    def setUp(self):
        FakeBlock.calls = []
        FakeModel.blocks = []

    def test_leaf_categories_cover_requested_transformer_boundaries(self):
        self.assertEqual(len(LEAF_CATEGORIES), 11)
        self.assertIn("attention_qkv_projection", LEAF_CATEGORIES)
        self.assertIn("attention_kernel", LEAF_CATEGORIES)
        self.assertIn("mlp_activation_fc2_projection", LEAF_CATEGORIES)

    def test_wrappers_preserve_result_and_restore_classes(self):
        original_block = FakeBlock.forward
        original_model = FakeModel._forward
        FakeModel.blocks = [FakeBlock()]
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock, FakeModel)
        controller.start_sampler()
        try:
            result = FakeModel()._forward(FakeTensor(1.0))
            controller.end_sampler()
            report = controller.finalize()
        finally:
            controller.restore()
        self.assertIsInstance(result, FakeTensor)
        self.assertIs(FakeBlock.forward, original_block)
        self.assertIs(FakeModel._forward, original_model)
        self.assertEqual(report["model_forward_count"], 1)
        self.assertEqual(report["block_call_count"], 1)
        self.assertEqual(report["synchronization_count"], 1)
        self.assertEqual(clock.synchronizations, 1)
        self.assertEqual(set(report["leaf_categories"]), set(LEAF_CATEGORIES))

    def test_full_shape_is_bounded_and_aggregate_only(self):
        FakeModel.blocks = [FakeBlock() for _ in range(50)]
        clock = FakeClock()
        controller = make_controller(clock)
        controller.install(FakeBlock, FakeModel)
        controller.start_sampler()
        try:
            for _ in range(20):
                FakeModel()._forward(FakeTensor(1.0))
            controller.end_sampler()
            report = controller.finalize()
        finally:
            controller.restore()
        self.assertEqual(report["model_forward_count"], 20)
        self.assertEqual(report["block_call_count"], 1000)
        self.assertEqual(report["event_pair_creation_count"], EVENT_PAIR_BOUND)
        self.assertEqual(report["event_object_count"], EVENT_OBJECT_BOUND)
        self.assertEqual(report["per_call_cpu_sync_count"], 0)
        self.assertEqual(report["tensor_payload_d2h_bytes"], 0)
        self.assertNotIn("per_block", report)
        self.assertNotIn("per_step", report)
        json.dumps(report, sort_keys=True)

    def test_mapping_gate_rejects_v4_transfer_or_incomplete_counts(self):
        leaves = {
            category: {"count": 1000, "support_status": "collected"}
            for category in LEAF_CATEGORIES
        }
        timing = {
            "support_status": "collected",
            "model_forward_count": 20,
            "block_call_count": 1000,
            "leaf_categories": leaves,
            "mapping_error_count": 0,
            "wrapper_failure_count": 0,
            "synchronization_count": 1,
            "per_call_cpu_sync_count": 0,
            "event_pair_creation_count": EVENT_PAIR_BOUND,
            "event_object_count": EVENT_OBJECT_BOUND,
            "sampler_accounting_ratio": 1.0,
            "model_other_raw_signed_ms": 1.0,
            "sampler_non_model_raw_signed_ms": 1.0,
            "tensor_payload_d2h_bytes": 0,
            "v4_observer_enabled": False,
            "v4_evidence_transfer_bytes": 0,
            "full_compute_only": True,
            "skip_count": 0,
            "reuse_count": 0,
            "prediction_count": 0,
            "regional_execution_count": 0,
            "token_omission_count": 0,
            "attention_omission_count": 0,
        }
        callback = {"sampler_succeeded": True, "timing": timing}
        self.assertTrue(profile_mapping_gate(callback)["passed"])
        timing["v4_evidence_transfer_bytes"] = 1
        self.assertFalse(profile_mapping_gate(callback)["passed"])

    def test_workflow_changes_only_sampler_and_adds_fixed_first_frame(self):
        base = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"prompt": "fixed"}},
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["5", 0]},
            },
        }
        mapped = build_workflow(base, run_digest="run", first_frame_name="first.png")
        self.assertEqual(mapped["10"]["class_type"], "HIVEFRAMEH3EndToEndProfileSampler")
        self.assertEqual(mapped["8"]["inputs"]["first_frame"], ["16", 0])
        self.assertEqual(mapped["16"]["inputs"]["image"], "first.png")
        self.assertEqual(base["10"]["class_type"], "SamplerCustomAdvanced")
        serialized = json.dumps(mapped, sort_keys=True).lower()
        for forbidden in ("selective", "partial_q", "skip", "reuse", "observer"):
            self.assertNotIn(forbidden, serialized)

    def test_amdahl_ranking_requires_ten_percent_expected_e2e(self):
        leaves = {
            category: {"total_ms": 0.0}
            for category in LEAF_CATEGORIES
        }
        leaves["attention_kernel"]["total_ms"] = 700_000.0
        ranking = _candidate_ranking(
            {
                "accounted_seconds": 1_000.0,
                "non_overlapping_phases_seconds": {
                    "vae_video_decode": 10.0,
                    "vae_audio_decode": 10.0,
                    "frame_video_encode_mux_save": 10.0,
                },
                "transformer_nested_gpu": {
                    "leaf_categories": leaves,
                    "model_other_prepost_offload_ms": 20_000.0,
                },
            }
        )
        self.assertEqual(
            ranking["selected_next_task"]["candidate"],
            "attention_backend_qkv_rope_out_fusion_ab",
        )
        self.assertEqual(ranking["selected_next_task"]["tier"], "TIER_B")
        self.assertEqual(ranking["v4_state"], "EXPERIMENTAL_AUXILIARY_FROZEN")

    def test_unsupported_path_installs_nothing_and_never_synchronizes(self):
        original_block = FakeBlock.forward
        original_model = FakeModel._forward
        clock = FakeClock()
        controller = make_controller(clock, supported=False)
        controller.install(FakeBlock, FakeModel)
        controller.start_sampler()
        report = controller.finalize()
        controller.restore()
        self.assertIs(FakeBlock.forward, original_block)
        self.assertIs(FakeModel._forward, original_model)
        self.assertEqual(report["support_status"], "unsupported")
        self.assertEqual(clock.synchronizations, 0)


if __name__ == "__main__":
    unittest.main()
