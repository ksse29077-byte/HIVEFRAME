from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import unittest

from hive_product.c1_h3_policy_probe import (
    C1_NODE_CLASS,
    _policy_gate,
    build_c1_workflow,
    c1_settings_digest,
)
from hive_product.comfyui_backend import ComfyUIH3Config
from hive_product.rust_step_policy import (
    ESCALATE_FULL_COMPUTE,
    FULL_COMPUTE,
    PolicyContext,
    RustStepPolicyBridge,
    wrap_progress_callback,
)


ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "run_digest": "01" * 32,
    "workflow_revision_digest": "02" * 32,
    "settings_digest": "03" * 32,
}


class FakeExtension:
    def __init__(self, decision: int = FULL_COMPUTE, *, malformed: bool = False) -> None:
        self.decision = decision
        self.malformed = malformed
        self.calls: list[dict] = []

    def step_policy_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 184,
            "directive_struct_size": 76,
            "max_rust_calls_per_callback": 1,
            "tensor_bytes_per_callback": 0,
        }

    def evaluate_step_policy(self, **kwargs):
        self.calls.append(kwargs)
        if self.malformed:
            return {"ffi_status": 0}
        return {
            "ffi_status": 0,
            "abi_version": 1,
            "struct_size": 76,
            "decision_code": self.decision,
            "reason_code": 0 if self.decision == FULL_COMPUTE else 6,
            "unsupported_flags": 0,
            "decision_digest": sha256(str(kwargs["step_index"]).encode()).digest(),
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "rust_policy_ns": 100,
        }


class C1StepPolicyTests(unittest.TestCase):
    def bridge(self, extension=None) -> RustStepPolicyBridge:
        return RustStepPolicyBridge(PolicyContext(**DIGESTS), extension=extension)

    def test_full_compute_roundtrip_is_metadata_only_and_one_call_per_callback(self) -> None:
        extension = FakeExtension()
        bridge = self.bridge(extension)
        for step in range(20):
            event = bridge.evaluate(step, 20)
            self.assertEqual(event["decision"], "FULL_COMPUTE")
        receipt = bridge.receipt()
        self.assertEqual(receipt["callback_count"], 20)
        self.assertEqual(receipt["rust_call_count"], 20)
        self.assertEqual(receipt["full_compute_count"], 20)
        self.assertEqual(receipt["tensor_bytes_transferred"], 0)
        self.assertEqual(receipt["metadata_bytes_transferred"], 20 * (184 + 76))
        for call in extension.calls:
            self.assertEqual(len(call["run_digest"]), 32)
            self.assertFalse(any("tensor" in key or "prompt" in key or "path" in key for key in call))

    def test_unavailable_malformed_and_unknown_responses_fail_open(self) -> None:
        unavailable = self.bridge(extension=object())
        self.assertEqual(unavailable.evaluate(0, 20)["decision"], "ESCALATE_FULL_COMPUTE")
        self.assertEqual(unavailable.receipt()["fallback_count"], 1)

        malformed = self.bridge(FakeExtension(malformed=True))
        self.assertEqual(malformed.evaluate(0, 20)["decision"], "ESCALATE_FULL_COMPUTE")
        self.assertEqual(malformed.events[0]["reason"], "malformed_response")

        unknown = self.bridge(FakeExtension(decision=99))
        self.assertEqual(unknown.evaluate(0, 20)["decision"], "ESCALATE_FULL_COMPUTE")
        self.assertEqual(unknown.events[0]["reason"], "unknown_decision")

    def test_explicit_escalation_remains_full_compute_without_fallback(self) -> None:
        bridge = self.bridge(FakeExtension(decision=ESCALATE_FULL_COMPUTE))
        event = bridge.evaluate(0, 20)
        self.assertEqual(event["decision"], "ESCALATE_FULL_COMPUTE")
        self.assertFalse(event["fallback_used"])

    def test_progress_wrapper_delegates_original_arguments_after_policy(self) -> None:
        bridge = self.bridge(FakeExtension())
        delegated = []
        callback = wrap_progress_callback(lambda *args: delegated.append(args), bridge)
        marker_a, marker_b = object(), object()
        callback(3, marker_a, marker_b, 20)
        self.assertEqual(delegated, [(3, marker_a, marker_b, 20)])
        self.assertEqual(bridge.callback_count, 1)
        self.assertEqual(bridge.rust_call_count, 1)

    def test_c1_workflow_changes_only_sampler_class_and_fixed_digests(self) -> None:
        standard = {
            "9": {"class_type": "BasicGuider", "inputs": {"value": 1}},
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["5", 0],
                    "guider": ["9", 0],
                    "sampler": ["7", 0],
                    "sigmas": ["6", 0],
                    "latent_image": ["8", 1],
                },
            },
            "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0]}},
        }
        c1 = build_c1_workflow(standard, **DIGESTS)
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertEqual(c1["10"]["class_type"], C1_NODE_CLASS)
        self.assertEqual(c1["9"], standard["9"])
        self.assertEqual(c1["11"], standard["11"])
        for name, value in DIGESTS.items():
            self.assertEqual(c1["10"]["inputs"][name], value)

    def test_custom_node_root_is_repository_owned_and_settings_digest_stable(self) -> None:
        config = ComfyUIH3Config(
            asset_root=None,
            comfyui_root=None,
            base_url="http://127.0.0.1:8191",
            workflow=None,
            output_root=None,
            custom_nodes_root=ROOT / "python" / "hive_product" / "comfyui_nodes",
        )
        config.validate()
        self.assertEqual(c1_settings_digest(), c1_settings_digest())

    def test_custom_node_guard_is_module_local_for_locked_comfyui_classes(self) -> None:
        source = (
            ROOT / "python" / "hive_product" / "comfyui_nodes" / "hiveframe_c1_policy" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_ACTIVE = False", source)
        self.assertNotIn("cls._active", source)

    def test_gate_uses_predeclared_limits_and_requires_twenty_full_compute_calls(self) -> None:
        policy = {
            "callback_count": 20,
            "rust_call_count": 20,
            "full_compute_count": 20,
            "escalate_full_compute_count": 0,
            "fallback_count": 0,
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "tensor_bytes_transferred": 0,
            "boundary_roundtrip": {"p95_ns": 1_000_000},
            "cumulative_policy_overhead_ns": 10_000_000,
        }
        self.assertTrue(_policy_gate(policy, 600.0)["passed"])
        policy["full_compute_count"] = 19
        self.assertFalse(_policy_gate(policy, 600.0)["passed"])


if __name__ == "__main__":
    unittest.main()
