from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import importlib.util
import unittest

from hive_product.compound_eye_shadow import (
    ESCALATE_FULL_COMPUTE,
    EYE_ACTIVE,
    EYE_STABLE,
    EYE_UNCERTAIN,
    FULL_COMPUTE,
    H3_AUDIO_SHAPE,
    H3_SIGNAL_ADAPTER,
    H3_VIDEO_SHAPE,
    QUANTIZATION_SCALE,
    SKETCH_VALUE_COUNT,
    CompoundEyeShadowBridge,
    ShadowContext,
    ShadowSignalNotAdmitted,
    SketchResult,
    extract_x0_sketch,
    wrap_shadow_callback,
)
from hive_product.c2_h3_shadow_probe import (
    C2_NODE_CLASS,
    _shadow_gate,
    build_c2_workflow,
    c2_settings_digest,
    select_c3_hook,
)


ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "run_digest": "11" * 32,
    "workflow_revision_digest": "22" * 32,
    "settings_digest": "33" * 32,
}


def sketch(value: int = 4096) -> SketchResult:
    return SketchResult(
        values_q=(value,) * SKETCH_VALUE_COUNT,
        source_shape=(1, 16, 31, 60, 108),
        source_dtype="torch.bfloat16",
        source_device_type="cpu",
        reduction_enqueue_ns=10,
        gpu_to_host_ns=20,
        host_quantization_ns=30,
    )


def h3_nested(video, audio):
    nested_type = type("NestedTensor", (), {})
    nested_type.__module__ = "comfy.nested_tensor"
    x0 = nested_type()
    x0.is_nested = True
    x0.tensors = [video, audio]
    return x0


class FakeC2Extension:
    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[dict] = []
        self.responses = responses or []

    def compound_eye_shadow_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 536,
            "directive_struct_size": 240,
            "eye_count": 5,
            "sketch_value_count": 48,
            "max_rust_calls_per_callback": 1,
            "host_scalar_bytes_per_callback": 192,
            "stable_validation_limit_ppm": 30000,
            "tensor_bytes_per_callback": 0,
        }

    def evaluate_compound_eye_shadow_policy(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        override = self.responses[index] if index < len(self.responses) else {}
        eye_state = override.get("eye_state", [EYE_UNCERTAIN] * 5)
        eye_change = override.get("eye_change_ppm", [0] * 5)
        stable = sum(value == EYE_STABLE for value in eye_state[1:])
        active = sum(value == EYE_ACTIVE for value in eye_state[1:])
        uncertain = 4 - stable - active
        digest = sha256(str(index).encode()).digest()
        return {
            "ffi_status": 0,
            "abi_version": 1,
            "struct_size": 240,
            "decision_code": override.get("decision_code", FULL_COMPUTE),
            "reason_code": 0,
            "unsupported_flags": 0,
            "eye_state": eye_state,
            "eye_confidence_ppm": [500000] * 5,
            "eye_change_ppm": eye_change,
            "stable_eye_count": stable,
            "active_eye_count": active,
            "uncertain_eye_count": uncertain,
            "candidate_generate_count": active,
            "candidate_reuse_count": stable,
            "candidate_reconcile_count": uncertain,
            "global_invalidation": override.get("global_invalidation", 0),
            "overlap_conflict_mask": override.get("overlap_conflict_mask", 0),
            "shared_visual_state_digest": digest,
            "compute_plan_digest": digest,
            "decision_digest": digest,
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "rust_policy_ns": 100,
        }


class CompoundEyeShadowTests(unittest.TestCase):
    def bridge(self, extension=None) -> CompoundEyeShadowBridge:
        return CompoundEyeShadowBridge(ShadowContext(**DIGESTS), extension=extension)

    def test_fixed_sketch_is_48_values_with_predeclared_quantization(self) -> None:
        if importlib.util.find_spec("torch") is None:
            self.skipTest("torch unavailable in focused model-free test environment")
        import torch

        x0 = h3_nested(
            torch.ones(H3_VIDEO_SHAPE, dtype=torch.float32),
            torch.zeros(H3_AUDIO_SHAPE, dtype=torch.float32),
        )
        result = extract_x0_sketch(x0)
        self.assertEqual(len(result.values_q), 48)
        self.assertEqual(set(result.values_q), {QUANTIZATION_SCALE})
        self.assertEqual(result.host_transfer_count, 1)
        self.assertEqual(result.host_transfer_bytes, 192)
        self.assertEqual(result.persistent_gpu_bytes, 0)

    def test_non_tensor_and_unsafe_axes_are_not_admitted(self) -> None:
        with self.assertRaises(ShadowSignalNotAdmitted):
            extract_x0_sketch(object())
        if importlib.util.find_spec("torch") is None:
            return
        import torch

        with self.assertRaises(ShadowSignalNotAdmitted):
            extract_x0_sketch(torch.ones((1, 2, 8, 8)))
        with self.assertRaises(ShadowSignalNotAdmitted):
            extract_x0_sketch(torch.ones(H3_VIDEO_SHAPE))

    def test_exact_h3_nested_video_adapter_uses_only_video_slot(self) -> None:
        if importlib.util.find_spec("torch") is None:
            self.skipTest("torch unavailable in focused model-free test environment")
        import torch

        x0 = h3_nested(
            torch.ones(H3_VIDEO_SHAPE, dtype=torch.float32),
            torch.zeros(H3_AUDIO_SHAPE, dtype=torch.float32),
        )
        result = extract_x0_sketch(x0)
        self.assertEqual(result.signal_adapter, H3_SIGNAL_ADAPTER)
        self.assertEqual(result.container_type, "comfy.nested_tensor.NestedTensor")
        self.assertEqual(result.container_tensor_count, 2)
        self.assertEqual(result.source_shape, H3_VIDEO_SHAPE)
        self.assertEqual(set(result.values_q), {QUANTIZATION_SCALE})

    def test_h3_nested_adapter_rejects_ambiguous_or_changed_contracts(self) -> None:
        if importlib.util.find_spec("torch") is None:
            self.skipTest("torch unavailable in focused model-free test environment")
        import torch

        valid_video = torch.ones(H3_VIDEO_SHAPE)
        valid_audio = torch.ones(H3_AUDIO_SHAPE)
        for tensors in (
            [valid_video],
            [valid_video, valid_audio, valid_audio],
            [torch.ones((1, 24, 36, 30, 54)), valid_audio],
            [valid_video, torch.ones((1, 32, 2, 206))],
        ):
            x0 = h3_nested(tensors[0], tensors[1]) if len(tensors) == 2 else h3_nested(valid_video, valid_audio)
            x0.tensors = tensors
            with self.assertRaises(ShadowSignalNotAdmitted):
                extract_x0_sketch(x0)

        wrong_type = type("NestedTensor", (), {})
        wrong_type.__module__ = "unapproved.container"
        x0 = wrong_type()
        x0.is_nested = True
        x0.tensors = [valid_video, valid_audio]
        with self.assertRaises(ShadowSignalNotAdmitted):
            extract_x0_sketch(x0)

    def test_no_full_cpu_copy_numpy_or_raw_tensor_ffi(self) -> None:
        source = (ROOT / "python" / "hive_product" / "compound_eye_shadow.py").read_text(encoding="utf-8")
        self.assertNotIn("x0.cpu(", source)
        self.assertNotIn("x0.numpy(", source)
        extension = FakeC2Extension()
        bridge = self.bridge(extension)
        bridge.evaluate(0, 20, sketch())
        call = extension.calls[0]
        self.assertEqual(len(call["current_sketch_q"]), 48)
        self.assertFalse(any("tensor" in name or "cuda" in name or name in {"x", "x0"} for name in call))

    def test_one_rust_call_per_callback_and_original_arguments_unchanged(self) -> None:
        extension = FakeC2Extension()
        bridge = self.bridge(extension)
        delegated: list[tuple] = []
        marker_x0, marker_x = object(), object()
        callback = wrap_shadow_callback(
            lambda *args: delegated.append(args), bridge, extractor=lambda value: sketch()
        )
        callback(3, marker_x0, marker_x, 20)
        self.assertEqual(delegated, [(3, marker_x0, marker_x, 20)])
        self.assertEqual(bridge.callback_count, 1)
        self.assertEqual(bridge.rust_call_count, 1)
        self.assertEqual(len(extension.calls), 1)

    def test_previous_state_validates_at_next_callback_and_excludes_last(self) -> None:
        extension = FakeC2Extension(
            [
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_STABLE, EYE_UNCERTAIN, EYE_UNCERTAIN]},
                {"eye_change_ppm": [10000, 10000, 10000, 40000, 40000]},
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_STABLE, EYE_STABLE, EYE_STABLE]},
            ]
        )
        bridge = self.bridge(extension)
        bridge.evaluate(2, 4, sketch())
        second = bridge.evaluate(3, 4, sketch())
        self.assertEqual(second["validation_of_previous"]["validated"], 2)
        self.assertEqual(bridge.validated_stable_count, 2)
        self.assertEqual(bridge.stable_candidate_count, 2)
        # Step 3 is the last callback and its four candidates are not admitted.
        self.assertEqual(second["stable_regional_eyes"], [])

    def test_contradiction_and_missing_observation_are_not_silently_validated(self) -> None:
        extension = FakeC2Extension(
            [
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_UNCERTAIN, EYE_UNCERTAIN, EYE_UNCERTAIN]},
                {"eye_change_ppm": [10000, 50000, 0, 0, 0]},
            ]
        )
        bridge = self.bridge(extension)
        bridge.evaluate(2, 20, sketch())
        event = bridge.evaluate(3, 20, sketch())
        self.assertEqual(event["validation_of_previous"]["contradicted"], 1)
        self.assertEqual(bridge.contradicted_stable_count, 1)

        missing = self.bridge(FakeC2Extension([
            {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_UNCERTAIN, EYE_UNCERTAIN, EYE_UNCERTAIN]}
        ]))
        missing.evaluate(2, 20, sketch())
        missing.record_signal_failure(3, 20, "x0_not_tensor")
        self.assertEqual(missing.not_validated_stable_count, 1)
        self.assertEqual(missing.escalate_count, 1)

    def test_fail_open_receipt_keeps_all_actual_selective_counters_zero(self) -> None:
        bridge = self.bridge(extension=object())
        event = bridge.evaluate(0, 20, sketch())
        self.assertEqual(event["decision"], "ESCALATE_FULL_COMPUTE")
        receipt = bridge.receipt()
        for key in (
            "skipped_step_count",
            "skipped_block_count",
            "skipped_token_count",
            "skipped_latent_count",
            "reused_cache_count",
            "partial_compute_count",
            "tensor_bytes_to_rust",
        ):
            self.assertEqual(receipt[key], 0)
        self.assertIsNone(receipt["gpu_kernel_seconds"]["value"])
        self.assertEqual(receipt["gpu_kernel_seconds"]["support_status"], "not_collected")

    def test_c1_contract_and_node_remain_unchanged(self) -> None:
        c1_source = (ROOT / "python" / "hive_product" / "rust_step_policy.py").read_text(encoding="utf-8")
        c1_node = (
            ROOT / "python" / "hive_product" / "comfyui_nodes" / "hiveframe_c1_policy" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class RustStepPolicyBridge", c1_source)
        self.assertIn("class HIVEFRAMERustPolicySampler", c1_node)
        self.assertNotIn("CompoundEyeShadow", c1_source)
        self.assertNotIn("CompoundEyeShadow", c1_node)

    def test_workflow_changes_only_sampler_wrapper_and_keeps_sage_zero(self) -> None:
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
        c2 = build_c2_workflow(standard, **DIGESTS)
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertEqual(c2["10"]["class_type"], C2_NODE_CLASS)
        self.assertEqual(c2["9"], standard["9"])
        self.assertEqual(c2["11"], standard["11"])
        self.assertFalse(any("sage" in node["class_type"].lower() for node in c2.values()))
        self.assertEqual(c2_settings_digest(), c2_settings_digest())

    def test_gate_requires_real_stable_validation_and_zero_actual_compute(self) -> None:
        policy = {
            "callback_count": 20,
            "rust_call_count": 20,
            "full_compute_count": 20,
            "escalate_full_compute_count": 0,
            "fallback_count": 0,
            "topology": "overlap_2x2",
            "eye_count": 5,
            "events": [
                {
                    "source_shape": list(H3_VIDEO_SHAPE),
                    "source_dtype": "torch.bfloat16",
                    "source_device_type": "cuda",
                    "signal_adapter": H3_SIGNAL_ADAPTER,
                }
            ] * 20,
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "tensor_bytes_to_rust": 0,
            "max_host_transfers_per_callback": 1,
            "sketch": {"value_count": 48},
            "stable_candidate_count": 2,
            "validated_stable_count": 2,
            "contradicted_stable_count": 0,
            "total_shadow_callback": {"p95_ns": 1_000_000},
            "boundary_roundtrip": {"p95_ns": 100_000},
            "cumulative_shadow_overhead_ns": 20_000_000,
            "persistent_host_state_estimate_bytes": 32_000,
            "persistent_rust_state_bytes": 0,
            "persistent_gpu_state_bytes": 0,
        }
        self.assertEqual(_shadow_gate(policy, 600.0)["decision"], "C2_COMPOUND_EYE_SHADOW_READY")
        policy["contradicted_stable_count"] = 1
        self.assertEqual(_shadow_gate(policy, 600.0)["decision"], "C2_SHADOW_FALSE_STABLE_DETECTED")
        policy["contradicted_stable_count"] = 0
        policy["validated_stable_count"] = 1
        self.assertEqual(_shadow_gate(policy, 600.0)["decision"], "C2_SHADOW_NO_STABLE_ADMISSION")

    def test_c3_selection_is_exactly_one_candidate(self) -> None:
        candidate = select_c3_hook({"validated_stable_count": 2, "contradicted_stable_count": 0, "events": []})
        self.assertEqual(candidate["candidate"], "B")
        none = select_c3_hook({"validated_stable_count": 0, "contradicted_stable_count": 0, "events": []})
        self.assertEqual(none["candidate"], "C")

    def test_actual_pyo3_c2_contract_roundtrip_when_extension_is_available(self) -> None:
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        contract = dict(boundary.compound_eye_shadow_contract())
        self.assertEqual(contract["abi_version"], 1)
        self.assertEqual(contract["eye_count"], 5)
        self.assertEqual(contract["sketch_value_count"], 48)
        self.assertEqual(contract["max_rust_calls_per_callback"], 1)
        self.assertEqual(contract["tensor_bytes_per_callback"], 0)
        response = dict(
            boundary.evaluate_compound_eye_shadow_policy(
                abi_version=1,
                struct_size=contract["observation_struct_size"],
                run_digest=bytes.fromhex(DIGESTS["run_digest"]),
                workflow_revision_digest=bytes.fromhex(DIGESTS["workflow_revision_digest"]),
                settings_digest=bytes.fromhex(DIGESTS["settings_digest"]),
                step_index=0,
                total_steps=20,
                topology_id=1,
                sketch_source_id=1,
                quantization_scale=4096,
                previous_available=False,
                uncertainty_flags=0,
                invalidation_flags=0,
                full_compute_supported=True,
                fallback_supported=True,
                receipt_required=True,
                unsupported_flags=0,
                current_sketch_q=[4096] * 48,
                previous_sketch_q=[0] * 48,
            )
        )
        self.assertEqual(response["ffi_status"], 0)
        self.assertEqual(response["decision_code"], FULL_COMPUTE)
        self.assertEqual(list(response["eye_state"]), [EYE_UNCERTAIN] * 5)
        self.assertEqual(response["skipped_step_count"], 0)


if __name__ == "__main__":
    unittest.main()
