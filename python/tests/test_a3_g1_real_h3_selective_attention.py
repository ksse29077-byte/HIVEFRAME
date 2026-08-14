from __future__ import annotations

from pathlib import Path
import unittest

from hive_product.a3_g1_real_h3_selective_attention import (
    BLOCKER,
    DECISION_NOT_CONNECTABLE,
    fixed_contract,
    inspect_source_texts,
    settings_digest,
)


ROOT = Path(__file__).resolve().parents[2]


class A3G1ContractTests(unittest.TestCase):
    def test_profile_and_budget_are_frozen(self):
        contract = fixed_contract()
        self.assertEqual(contract["base_commit"], "f5d2bf8c2f80612909eef21c555d764a116f7062")
        self.assertEqual(contract["profile"]["width"], 864)
        self.assertEqual(contract["profile"]["height"], 480)
        self.assertEqual(contract["profile"]["steps"], 20)
        self.assertFalse(contract["profile"]["sage"])
        self.assertEqual(contract["generation_budget"], {
            "control_max": 1,
            "selective_max": 1,
            "retry_max": 0,
            "requires_structural_gate": True,
        })
        self.assertEqual(contract["selective_gate"]["actual_q_reduction_min"], 0.03)
        self.assertTrue(contract["selective_gate"]["post_compute_masking_forbidden"])
        self.assertFalse(contract["quality_gate"]["threshold_change_allowed"])

    def test_settings_digest_is_stable(self):
        self.assertEqual(settings_digest(), settings_digest())

    def test_current_g0_topology_fails_before_generation(self):
        g0 = ROOT / "python" / "hive_product" / "native" / "a3_g0_gpu_conditional"
        result = inspect_source_texts(
            h3_model=(
                "class Attention\noptimized_attention(q, k, v\n"
                "class DiTBlock\nself.attn(h, rope_freqs=rope_freqs"
            ),
            comfy_attention=(
                "def attention_pytorch\nscaled_dot_product_attention(q, k, v\n"
                "optimized_attention = attention_pytorch"
            ),
            g0_cuda=(g0 / "conditional_omission.cu").read_text(encoding="utf-8"),
            g0_binding=(g0 / "binding.cpp").read_text(encoding="utf-8"),
            g0_header=(g0 / "conditional_omission.h").read_text(encoding="utf-8"),
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["decision"], DECISION_NOT_CONNECTABLE)
        self.assertEqual(result["blocker"], BLOCKER)
        self.assertTrue(result["stop_required"])
        self.assertEqual(result["generation_attempt_count"], 0)
        self.assertEqual(result["model_load_count"], 0)
        self.assertTrue(result["claim_boundary"]["full_compute_fallback_preserved"])

    def test_gate_is_not_hard_coded_to_fail(self):
        result = inspect_source_texts(
            h3_model=(
                "class Attention\noptimized_attention(q, k, v\n"
                "class DiTBlock\nself.attn(h, rope_freqs=rope_freqs"
            ),
            comfy_attention=(
                "def attention_pytorch\nscaled_dot_product_attention(q, k, v\n"
                "optimized_attention = attention_pytorch"
            ),
            g0_cuda=(
                "cudaGraphSetConditional cudaGraphCondTypeIf reuse_body_kernel exact_body_kernel "
                "cudaGraphAddChildGraphNode register_h3_attention_child_graph accepts_float_qkv "
                "scaled_dot_product_attention"
            ),
            g0_binding="register_h3_attention_child_graph accepts_float_qkv",
            g0_header="register_h3_attention_child_graph accepts_float_qkv",
        )
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
