from __future__ import annotations

from hashlib import sha256
import inspect
import math
import unittest

from hive_product.c3_r2_h3_residual_probe import NODE_CLASS, QUALITY_GATE, build_c3_r2_workflow
from hive_product.segment_residual_replay import (
    BLOCK_COUNT,
    CONTROL,
    ESCALATE_FULL_COMPUTE,
    FROZEN_CEILING,
    FULL_COMPUTE,
    MAX_REUSE_STEPS,
    MAX_THEORETICAL_REDUCTION,
    REUSE_TRANSFORM,
    SEGMENT_BLOCKS,
    SELECTIVE,
    H3SegmentResidualController,
    ReusePlanBridge,
    ReusePlanContext,
    residual_settings_digest,
    select_maximum_safe_targets,
)


DIGESTS = {
    "run_digest": "11" * 32,
    "workflow_revision_digest": "22" * 32,
    "settings_digest": "33" * 32,
    "model_revision_digest": "44" * 32,
}


class FakeExtension:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reuse_plan_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 260,
            "directive_struct_size": 64,
            "max_rust_calls_per_callback": 1,
            "max_rust_calls_per_block": 0,
            "tensor_bytes_per_call": 0,
            "cache_age_required": 1,
        }

    def evaluate_reuse_plan(self, **observation):
        self.calls.append(observation)
        admitted = (
            observation["calibrated_target"]
            and observation["cache_available"]
            and observation["cache_age"] == 1
            and observation["cache_provenance_valid"]
            and observation["residual_similarity_admitted"]
            and observation["stable_count"] >= 2
            and observation["active_count"] == 0
            and not observation["global_invalidation"]
            and observation["overlap_conflict_mask"] == 0
            and observation["source_valid"]
            and observation["prediction_valid"]
            and observation["finite"]
            and not observation["prior_step_reused"]
        )
        return {
            "ffi_status": 0,
            "abi_version": 1,
            "struct_size": 64,
            "decision_code": REUSE_TRANSFORM if admitted else FULL_COMPUTE,
            "reason_code": 0 if admitted else 6,
            "target_execution_step": observation["target_execution_step"],
            "source_execution_step": observation["source_execution_step"],
            "fallback_required": int(not admitted),
            "unsupported_flags": 0,
            "decision_digest": sha256(repr(sorted(observation.items())).encode()).digest(),
            "rust_policy_ns": 100,
        }


def event_for_target(target: int, *, active: bool = False) -> dict:
    states = ["UNCERTAIN", "STABLE", "STABLE", "UNCERTAIN", "UNCERTAIN"]
    if active:
        states[2] = "ACTIVE"
    return {
        "total_steps": 20,
        "predicted_execution_step": target,
        "sketch_observed_step": target - 2,
        "eye_states": states,
        "global_invalidation": 0,
        "overlap_conflict_mask": 0,
        "fallback_used": False,
        "reason": None,
        "event_ready": True,
        "deadline_missed": False,
        "source_dtype": "torch.float32",
        "source_device_type": "cuda",
        "signal_adapter": "h3_nested_video_v1",
    }


class FakeTensor:
    def __init__(self, values):
        self.values = [float(value) for value in values]


class FakeTensorOps:
    def clone(self, tensor):
        return FakeTensor(tensor.values)

    def residualize(self, snapshot, output):
        snapshot.values = [right - left for left, right in zip(snapshot.values, output.values)]
        return snapshot

    def apply(self, current, residual):
        current.values = [left + right for left, right in zip(current.values, residual.values)]
        return current

    def metadata(self, tensor):
        return {
            "shape": [len(tensor.values)],
            "shape_digest": sha256(repr((len(tensor.values),)).encode()).hexdigest(),
            "dtype": "torch.bfloat16",
            "device": "cuda:0",
            "device_type": "cuda",
            "numel": len(tensor.values),
            "element_size": 2,
            "bytes": len(tensor.values) * 2,
        }

    def finite(self, tensor):
        return all(math.isfinite(value) for value in tensor.values)

    def similarity(self, previous, current):
        dot = sum(a * b for a, b in zip(previous.values, current.values))
        norm_a = math.sqrt(sum(value * value for value in previous.values))
        norm_b = math.sqrt(sum(value * value for value in current.values))
        difference = math.sqrt(sum((a - b) ** 2 for a, b in zip(previous.values, current.values)))
        return {
            "normalized_residual_l2": difference / norm_a,
            "residual_cosine_similarity": dot / (norm_a * norm_b),
            "finite": True,
            "method": "fake scalar reduction",
            "full_tensor_host_copy_bytes": 0,
        }

    def cuda_memory(self, tensor):
        return {
            "memory_allocated_bytes": 100,
            "memory_reserved_bytes": 200,
            "max_memory_allocated_bytes": 300,
            "max_memory_reserved_bytes": 400,
            "device_total_memory_bytes": 1_000,
        }


class FakePatcher:
    def __init__(self) -> None:
        self.model_options = {"transformer_options": {}}
        self.patches = {}

    def clone(self):
        return FakePatcher()

    def set_model_patch_replace(self, patch, name, block_name, number):
        self.patches[number] = patch


class FakeGuider:
    def __init__(self) -> None:
        self.model_patcher = FakePatcher()
        self.model_options = self.model_patcher.model_options


class SegmentResidualReplayTests(unittest.TestCase):
    def bridge(self, targets=()):
        extension = FakeExtension()
        bridge = ReusePlanBridge(ReusePlanContext(**DIGESTS), tuple(targets), extension=extension)
        return bridge, extension

    def controller(self, mode=CONTROL, targets=()):
        bridge, extension = self.bridge(targets)
        controller = H3SegmentResidualController(
            mode,
            bridge,
            workflow_revision_digest=DIGESTS["workflow_revision_digest"],
            model_revision_digest=DIGESTS["model_revision_digest"],
            settings_digest=DIGESTS["settings_digest"],
            tensor_ops=FakeTensorOps(),
        )
        return controller, bridge, extension

    @staticmethod
    def run_step(controller, value=0.0):
        tensor = FakeTensor([value, value + 1])
        block_calls = []
        for block in range(BLOCK_COUNT):
            def original(args, block=block):
                block_calls.append(block)
                args["img"].values = [value + 1.0 for value in args["img"].values]
                return {"img": args["img"]}

            tensor = controller.block_wrapper(block)(
                {"img": tensor}, {"original_block": original}
            )["img"]
        return tensor, block_calls

    def test_fixed_segment_ceiling_and_one_shot_maximum(self):
        self.assertEqual(SEGMENT_BLOCKS, tuple(range(12, 49)))
        self.assertEqual(FROZEN_CEILING, (5, 6, 8, 13, 16, 17))
        self.assertEqual(MAX_REUSE_STEPS, 4)
        self.assertAlmostEqual(MAX_THEORETICAL_REDUCTION, 0.148)

    def test_bridge_admits_only_calibrated_age_one_cache(self):
        bridge, extension = self.bridge((5,))
        bridge.set_cache_state_provider(
            lambda target: {
                "source_execution_step": target - 1,
                "cache_age": 1,
                "cache_available": True,
                "cache_provenance_valid": True,
                "finite": True,
                "prior_step_reused": False,
            }
        )
        admitted = bridge.evaluate_event(event_for_target(5))
        rejected = bridge.evaluate_event(event_for_target(8))
        self.assertEqual(admitted["decision_code"], REUSE_TRANSFORM)
        self.assertEqual(rejected["decision_code"], FULL_COMPUTE)
        self.assertEqual(len(extension.calls), 2)
        self.assertEqual(bridge.receipt()["tensor_bytes_to_rust"], 0)

    def test_live_active_veto_and_missing_cache_fail_open(self):
        bridge, _ = self.bridge((5,))
        bridge.set_cache_state_provider(lambda target: {"source_execution_step": target - 1})
        missing = bridge.evaluate_event(event_for_target(5))
        self.assertEqual(missing["decision_code"], FULL_COMPUTE)
        bridge.set_cache_state_provider(
            lambda target: {
                "source_execution_step": target - 1,
                "cache_age": 1,
                "cache_available": True,
                "cache_provenance_valid": True,
                "finite": True,
            }
        )
        active = bridge.evaluate_event(event_for_target(5, active=True))
        self.assertEqual(active["decision_code"], FULL_COMPUTE)

    def test_control_captures_residual_and_never_reuses(self):
        controller, _, _ = self.controller(CONTROL)
        _, calls = self.run_step(controller)
        self.assertEqual(len(calls), 50)
        self.assertEqual(controller.residual_capture_count, 1)
        self.assertEqual(controller.residual_application_count, 0)
        self.assertIsNotNone(controller.cache)
        self.assertEqual(controller.cache.tensor.values, [37.0, 37.0])
        self.assertEqual(controller.max_concurrent_residual_sized_buffers, 1)

    def test_control_similarity_uses_previous_full_residual_and_fixed_gate(self):
        controller, _, _ = self.controller(CONTROL)
        for _ in range(6):
            self.run_step(controller)
        diagnostic = controller.similarity_diagnostics
        self.assertEqual(len(diagnostic), 1)
        self.assertEqual(diagnostic[0]["target_step"], 5)
        self.assertTrue(diagnostic[0]["admitted"])
        self.assertEqual(diagnostic[0]["normalized_residual_l2"], 0.0)
        self.assertAlmostEqual(diagnostic[0]["residual_cosine_similarity"], 1.0)
        self.assertEqual(controller.max_concurrent_residual_sized_buffers, 2)

    def test_selective_applies_delta_once_omits_37_calls_and_runs_block49(self):
        controller, bridge, _ = self.controller(SELECTIVE, (5,))
        for _ in range(5):
            self.run_step(controller)
        bridge.plans[5] = {
            "decision_code": REUSE_TRANSFORM,
            "decision": "REUSE_TRANSFORM",
            "reason": "reuse_admitted",
        }
        _, calls = self.run_step(controller)
        self.assertEqual(len(calls), 13)
        self.assertIn(49, calls)
        self.assertTrue(all(block not in calls for block in SEGMENT_BLOCKS))
        self.assertEqual(controller.residual_application_count, 1)
        self.assertEqual(controller.replayed_block_call_count, 37)
        self.assertIsNone(controller.cache)

    def test_reuse_step_does_not_create_cache_and_next_full_does(self):
        controller, bridge, _ = self.controller(SELECTIVE, (5,))
        for _ in range(5):
            self.run_step(controller)
        captures = controller.residual_capture_count
        bridge.plans[5] = {"decision_code": REUSE_TRANSFORM, "decision": "REUSE_TRANSFORM", "reason": "ok"}
        self.run_step(controller)
        self.assertEqual(controller.residual_capture_count, captures)
        self.assertIsNone(controller.cache)
        self.run_step(controller)
        self.assertEqual(controller.residual_capture_count, captures + 1)
        self.assertIsNotNone(controller.cache)

    def test_provenance_shape_dtype_or_device_mismatch_vetoes(self):
        controller, bridge, _ = self.controller(SELECTIVE, (5,))
        for _ in range(5):
            self.run_step(controller)
        bridge.plans[5] = {"decision_code": REUSE_TRANSFORM, "decision": "REUSE_TRANSFORM", "reason": "ok"}
        controller.cache.settings_digest = "bad"
        _, calls = self.run_step(controller)
        self.assertEqual(len(calls), 50)
        self.assertEqual(controller.residual_application_count, 0)

    def test_no_per_block_cache_host_copy_or_rust_call(self):
        source = inspect.getsource(H3SegmentResidualController.block_wrapper)
        self.assertNotIn(".cpu(", source)
        self.assertNotIn(".numpy(", source)
        self.assertNotIn("evaluate_reuse_plan", source)
        controller, _, _ = self.controller(CONTROL)
        self.run_step(controller)
        receipt = controller.receipt()
        self.assertEqual(receipt["per_block_cache_count"], 0)
        self.assertEqual(receipt["tensor_bytes_to_rust"], 0)
        self.assertEqual(receipt["full_tensor_host_copy_bytes"], 0)

    def test_guider_clone_installs_wrappers_without_mutating_original(self):
        controller, _, _ = self.controller(CONTROL)
        guider = FakeGuider()
        patched = controller.install_on_guider_clone(guider)
        self.assertEqual(guider.model_patcher.patches, {})
        self.assertEqual(set(patched.model_patcher.patches), set(range(50)))

    def test_maximum_safe_selection_is_deterministic_and_nonconsecutive(self):
        diagnostics = [{"target_step": step, "admitted": True} for step in FROZEN_CEILING]
        selected = select_maximum_safe_targets(diagnostics)
        self.assertEqual(selected, (5, 8, 13, 16))
        self.assertTrue(all(right != left + 1 for left, right in zip(selected, selected[1:])))

    def test_workflow_and_settings_digests_separate_control_selective(self):
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {}}}
        control = build_c3_r2_workflow(
            standard,
            **DIGESTS,
            calibrated_targets=(),
            actual_residual_replay_enabled=False,
        )
        selective = build_c3_r2_workflow(
            standard,
            **DIGESTS,
            calibrated_targets=(5, 8),
            actual_residual_replay_enabled=True,
        )
        self.assertEqual(control["10"]["class_type"], NODE_CLASS)
        self.assertFalse(control["10"]["inputs"]["actual_residual_replay_enabled"])
        self.assertEqual(selective["10"]["inputs"]["calibrated_targets_csv"], "5,8")
        self.assertNotEqual(
            residual_settings_digest(actual_residual_replay_enabled=False, calibrated_targets=()),
            residual_settings_digest(actual_residual_replay_enabled=True, calibrated_targets=(5, 8)),
        )

    def test_quality_gate_is_fixed_before_runtime(self):
        self.assertEqual(
            QUALITY_GATE,
            {
                "mean_ssim_min": 0.95,
                "p05_ssim_min": 0.90,
                "min_ssim_min": 0.85,
                "low_ssim_frame_rate_max": 0.02,
                "normalized_mae_max": 0.03,
                "motion_energy_ratio_min": 0.90,
                "motion_energy_ratio_max": 1.10,
                "gradient_energy_ratio_min": 0.90,
                "gradient_energy_ratio_max": 1.10,
            },
        )

    def test_actual_pyo3_contracts_roundtrip_when_extension_is_available(self):
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        self.assertEqual(boundary.step_policy_contract()["abi_version"], 1)
        self.assertEqual(boundary.compound_eye_shadow_contract()["abi_version"], 1)
        self.assertEqual(boundary.c3_frozen_block_plan_contract()["abi_version"], 1)
        contract = dict(boundary.reuse_plan_contract())
        response = dict(
            boundary.evaluate_reuse_plan(
                abi_version=1,
                struct_size=contract["observation_struct_size"],
                run_digest=bytes.fromhex(DIGESTS["run_digest"]),
                workflow_revision_digest=bytes.fromhex(DIGESTS["workflow_revision_digest"]),
                settings_digest=bytes.fromhex(DIGESTS["settings_digest"]),
                model_revision_digest=bytes.fromhex(DIGESTS["model_revision_digest"]),
                segment_logical_digest=bytes.fromhex("55" * 32),
                target_execution_step=5,
                source_execution_step=4,
                total_steps=20,
                cache_age=1,
                cache_available=True,
                cache_provenance_valid=True,
                residual_similarity_admitted=True,
                calibrated_target=True,
                prior_step_reused=False,
                stable_mask=3,
                stable_count=2,
                active_mask=0,
                active_count=0,
                uncertain_mask=12,
                uncertain_count=2,
                global_invalidation=False,
                overlap_conflict_mask=0,
                prediction_valid=True,
                source_valid=True,
                finite=True,
                fallback_supported=True,
                fatal_flags=0,
                unsupported_flags=0,
            )
        )
        self.assertEqual(response["decision_code"], REUSE_TRANSFORM)
        self.assertEqual(response["ffi_status"], 0)


if __name__ == "__main__":
    unittest.main()
