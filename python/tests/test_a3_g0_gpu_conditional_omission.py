from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

from hive_product.gpu_conditional_omission import (
    DECISION_READY,
    GPUConditionalOmissionCapability,
    REPLAY_SEQUENCE,
    fixed_contract,
    settings_digest,
)
from hive_product.comfyui_backend import MiniMaxH3ComfyUIBackend


class A3G0ContractTests(unittest.TestCase):
    def test_fixed_topology_and_claim_boundary(self):
        contract = fixed_contract()
        self.assertEqual(contract["graph_topology"]["conditional_nodes"], 2)
        self.assertEqual(contract["graph_topology"]["conditional_type"], "IF")
        self.assertEqual(tuple(contract["graph_topology"]["replay_sequence"]), REPLAY_SEQUENCE)
        self.assertEqual(contract["synchronization_contract"]["guard_d2h_bytes"], 0)
        self.assertEqual(contract["synchronization_contract"]["explicit_hot_path_cpu_sync_count"], 0)
        self.assertEqual(contract["synchronization_contract"]["final_evidence_sync_count"], 1)
        self.assertFalse(contract["claim_boundary"]["body_counters_are_kernel_launch_counts"])
        self.assertFalse(contract["claim_boundary"]["actual_h3_attention_omission"])

    def test_settings_digest_is_stable(self):
        self.assertEqual(settings_digest(), settings_digest())

    def test_capability_is_experimental_disabled_and_fail_open(self):
        capability = GPUConditionalOmissionCapability()
        self.assertEqual(capability.state, "experimental")
        self.assertFalse(capability.default_enabled)
        self.assertFalse(capability.actual_h3_attention_connected)
        self.assertEqual(capability.fallback, "standard_full_compute")
        adapter = MiniMaxH3ComfyUIBackend.experimental_capabilities["gpu_conditional_omission_v1"]
        self.assertEqual(adapter["state"], "synthetic_verified_once")
        self.assertFalse(adapter["default_enabled"])
        self.assertFalse(adapter["actual_h3_attention_connected"])
        self.assertEqual(adapter["fallback"], "standard_full_compute")

    def test_decision_matrix_keeps_ready_and_fail_closed_outcomes(self):
        decisions = fixed_contract()["decisions"]
        self.assertIn(DECISION_READY, decisions)
        self.assertIn("A3_G0_EXACT_FALLBACK_PARITY_FAILED", decisions)
        self.assertIn("A3_G0_PYTORCH_NATIVE_DISPATCH_NOT_ADMITTED", decisions)


class A3G0NativeFocusedTests(unittest.TestCase):
    def test_fixed_gpu_sequence_proves_omission_and_exact_fallback(self):
        try:
            import torch
        except ImportError as error:
            self.skipTest(f"PyTorch unavailable: {error}")
        if not torch.cuda.is_available():
            self.skipTest("CUDA unavailable")
        from hive_product.a3_g0_gpu_conditional_probe import run_probe

        configured_root = os.environ.get("HIVEFRAME_A3_G0_BUILD_ROOT")
        if configured_root:
            result = run_probe(build_root=Path(configured_root))
        else:
            with tempfile.TemporaryDirectory(prefix="hiveframe-a3-g0-test-") as temp_root:
                result = run_probe(build_root=Path(temp_root))
        self.assertEqual(result["decision"], DECISION_READY)
        self.assertEqual(result["replay"]["reuse_body_execution_count"], 2)
        self.assertEqual(result["replay"]["exact_body_execution_count"], 2)
        self.assertEqual(result["replay"]["branch_history"], [0, 1, 0, 1])
        self.assertFalse(result["replay"]["branch_state_leak"])
        self.assertTrue(result["parity"]["safe_reference_bit_exact"])
        self.assertTrue(result["parity"]["unsafe_exact_control_bit_exact"])
        self.assertEqual(result["synchronization"]["guard_d2h_bytes"], 0)
        self.assertEqual(result["synchronization"]["host_guard_read_count"], 0)
        self.assertEqual(result["synchronization"]["explicit_hot_path_cpu_sync_count"], 0)
        self.assertEqual(result["synchronization"]["final_evidence_sync_count"], 1)
        self.assertEqual(result["memory"]["conditional_body_allocation_count"], 0)
        self.assertEqual(result["integration"]["redundant_tensor_copy_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
