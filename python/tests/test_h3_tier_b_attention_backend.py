from __future__ import annotations

import unittest

from hive_product.h3_tier_b_attention_backend import (
    AttentionBackendCapabilityRegistry,
    AttentionBackendRequest,
    BASELINE_BACKEND,
    CANDIDATE_BACKEND,
    H3ExactAttentionBackendAdapter,
    PRODUCT_HEAD_DIM,
    PRODUCT_HEADS,
    PRODUCT_SEQUENCE_ROWS,
)


class FakeDevice:
    type = "cuda"


class FakeTensor:
    shape = (1, PRODUCT_HEADS, PRODUCT_SEQUENCE_ROWS, PRODUCT_HEAD_DIM)
    dtype = "torch.bfloat16"
    device = FakeDevice()

    def transpose(self, _first, _second):
        return self

    def reshape(self, *_shape):
        return self


class FakeFunctional:
    @staticmethod
    def scaled_dot_product_attention(*_args, **_kwargs):
        return FakeTensor()


class FakeNN:
    functional = FakeFunctional()


class FakeTorch:
    nn = FakeNN()


def request(**overrides):
    values = {
        "name": CANDIDATE_BACKEND,
        "device_type": "cuda",
        "dtype": "torch.bfloat16",
        "sequence_rows": PRODUCT_SEQUENCE_ROWS,
        "heads": PRODUCT_HEADS,
        "head_dim": PRODUCT_HEAD_DIM,
        "layout": "BHSD",
        "mask_present": False,
        "causal": False,
        "dropout_p": 0.0,
    }
    values.update(overrides)
    return AttentionBackendRequest(**values)


class H3TierBAttentionBackendTests(unittest.TestCase):
    def test_manifest_is_full_compute_and_does_not_claim_false_fusion(self):
        manifest = AttentionBackendCapabilityRegistry().manifest(CANDIDATE_BACKEND)
        self.assertEqual(manifest.full_q_percent, 100)
        self.assertEqual(manifest.full_kv_percent, 100)
        self.assertFalse(manifest.omission_enabled)
        self.assertFalse(manifest.fusion_claimed)
        self.assertFalse(manifest.compile_required)
        self.assertFalse(manifest.cache_required)
        self.assertEqual(manifest.fallback_backend, BASELINE_BACKEND)

    def test_exact_product_shape_is_admitted(self):
        selection = AttentionBackendCapabilityRegistry().resolve(request())
        self.assertTrue(selection.admitted)
        self.assertEqual(selection.selected, CANDIDATE_BACKEND)
        self.assertIsNone(selection.fallback_reason)

    def test_unsupported_contracts_fail_closed_to_standard(self):
        registry = AttentionBackendCapabilityRegistry()
        cases = (
            (request(device_type="cpu"), "UNSUPPORTED_DEVICE"),
            (request(dtype="torch.float16"), "UNSUPPORTED_DTYPE"),
            (request(sequence_rows=1), "UNSUPPORTED_SEQUENCE"),
            (request(mask_present=True), "MASK_UNSUPPORTED"),
            (request(causal=True), "CAUSAL_UNSUPPORTED"),
            (request(dropout_p=0.1), "DROPOUT_UNSUPPORTED"),
        )
        for candidate, reason in cases:
            with self.subTest(reason=reason):
                selection = registry.resolve(candidate)
                self.assertFalse(selection.admitted)
                self.assertEqual(selection.selected, BASELINE_BACKEND)
                self.assertEqual(selection.fallback_reason, reason)

    def test_unknown_backend_falls_back_without_silent_execution(self):
        selection = AttentionBackendCapabilityRegistry().resolve(request(name="unknown"))
        self.assertFalse(selection.admitted)
        self.assertEqual(selection.selected, BASELINE_BACKEND)
        self.assertEqual(selection.fallback_reason, "BACKEND_NOT_REGISTERED")

    def test_adapter_fallback_records_reason_and_preserves_full_compute(self):
        calls = []

        def baseline(q, *_args, **_kwargs):
            calls.append("baseline")
            return q

        adapter = H3ExactAttentionBackendAdapter(
            torch_module=FakeTorch(), baseline=baseline
        )
        tensor = FakeTensor()
        tensor.device = type("Cpu", (), {"type": "cpu"})()
        output, receipt = adapter.execute(
            CANDIDATE_BACKEND, tensor, tensor, tensor, PRODUCT_HEADS
        )
        self.assertIs(output, tensor)
        self.assertEqual(calls, ["baseline"])
        self.assertEqual(receipt["fallback_reason"], "UNSUPPORTED_DEVICE")
        self.assertEqual(receipt["fallback_count"], 1)
        self.assertEqual(receipt["attention_omission_count"], 0)
        self.assertEqual(receipt["full_q_percent"], 100)

    def test_capability_manifest_is_extensible_and_mutually_named(self):
        manifest = AttentionBackendCapabilityRegistry().capability_manifest()
        self.assertEqual(set(manifest), {BASELINE_BACKEND, CANDIDATE_BACKEND})
        self.assertNotEqual(
            manifest[BASELINE_BACKEND]["implementation_digest"],
            manifest[CANDIDATE_BACKEND]["implementation_digest"],
        )

    def test_native_error_falls_back_once_and_never_returns_partial_result(self):
        calls = []

        def baseline(q, *_args, **_kwargs):
            calls.append("baseline")
            return q

        def fail_candidate(*_args):
            calls.append("candidate")
            raise RuntimeError("forced")

        tensor = FakeTensor()
        adapter = H3ExactAttentionBackendAdapter(
            torch_module=FakeTorch(), baseline=baseline, candidate=fail_candidate
        )
        output, receipt = adapter.execute(
            CANDIDATE_BACKEND, tensor, tensor, tensor, PRODUCT_HEADS
        )
        self.assertIs(output, tensor)
        self.assertEqual(calls, ["candidate", "baseline"])
        self.assertEqual(adapter.candidate_call_count, 0)
        self.assertEqual(adapter.baseline_call_count, 1)
        self.assertEqual(receipt["fallback_count"], 1)
        self.assertEqual(receipt["fallback_reason"], "NATIVE_ERROR:RuntimeError")


if __name__ == "__main__":
    unittest.main()
