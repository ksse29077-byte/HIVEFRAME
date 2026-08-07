from __future__ import annotations

import hashlib
import inspect
import math
import unittest

from hive_product.c3_r2_h3_residual_probe import QUALITY_GATE
from hive_product.c3_r4_h3_directional_probe import (
    NODE_CLASS,
    build_workflow,
    directional_memory_admission,
)
from hive_product.compact_residual_correction import CorrectionPlanContext
from hive_product.segment_residual_replay import FROZEN_CEILING
from hive_product.two_residual_directional_prediction import (
    ALPHA_GRID,
    CONTROL,
    MECHANISM,
    SELECTIVE,
    DirectionalPlanBridge,
    H3TwoResidualDirectionalController,
    direct_directional_metrics,
    directional_metrics_from_statistics,
    directional_settings_digest,
    select_global_alpha,
    sufficient_statistics_from_sequences,
    validate_calibrated_targets,
    validate_global_alpha,
)


class FakeTensor:
    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)


class FakeOps:
    def clone(self, tensor: FakeTensor) -> FakeTensor:
        return FakeTensor(tensor.value)

    def residualize(self, snapshot: FakeTensor, output: FakeTensor) -> FakeTensor:
        snapshot.value = output.value - snapshot.value
        return snapshot

    def metadata(self, tensor: FakeTensor):
        return {
            "shape": [1, 3072],
            "shape_digest": hashlib.sha256(repr((1, 3072)).encode()).hexdigest(),
            "dtype": "torch.bfloat16",
            "device": "cuda:0",
            "device_type": "cuda",
            "numel": 3072,
            "element_size": 2,
            "bytes": 6144,
        }

    def finite(self, tensor: FakeTensor) -> bool:
        return math.isfinite(tensor.value)

    def similarity(self, previous: FakeTensor, current: FakeTensor):
        return {
            "normalized_residual_l2": 0.15,
            "residual_cosine_similarity": 0.991,
            "finite": True,
        }

    def directional_grid(self, previous2, previous1, current):
        raw = self.similarity(previous1, current)
        candidates = [
            {
                "alpha": alpha,
                "normalized_residual_l2": 0.10,
                "residual_cosine_similarity": 0.995,
                "finite": True,
                "full_prediction_tensor_count": 0,
            }
            for alpha in ALPHA_GRID
        ]
        return {
            "statistics": {name: 1.0 for name in ("a2", "b2", "y2", "ab", "ay", "by")},
            "raw": raw,
            "candidates": candidates,
            "statistics_ns": 10,
            "alpha_evaluation_ns": 5,
            "full_prediction_tensor_count": 0,
        }

    def apply_directional(self, current, previous2, previous1, alpha):
        current.value += (1.0 + alpha) * previous1.value - alpha * previous2.value
        return current

    def cuda_memory(self, tensor):
        return {"memory_allocated_bytes": 1}


class FakeExtension:
    def __init__(self):
        self.calls = []

    def correction_plan_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 280,
            "directive_struct_size": 72,
            "max_rust_calls_per_callback": 1,
            "max_rust_calls_per_block": 0,
            "tensor_bytes_per_call": 0,
            "full_compute_seeds_required": 2,
        }

    def evaluate_correction_plan(self, **observation):
        self.calls.append(observation)
        admitted = (
            observation["calibrated_target"]
            and observation["cache_available"]
            and observation["predictor_available"]
            and observation["predictor_provenance_valid"]
            and observation["correction_metadata_valid"]
            and observation["full_compute_seed_count"] >= 2
            and not observation["reseed_required"]
            and observation["stable_count"] >= 2
            and observation["active_count"] == 0
            and not observation["global_invalidation"]
            and observation["overlap_conflict_mask"] == 0
            and observation["source_valid"]
            and observation["prediction_valid"]
            and observation["finite"]
        )
        return {
            "ffi_status": 0,
            "decision_code": 1 if admitted else 0,
            "reason_code": 0 if admitted else 6,
            "target_execution_step": observation["target_execution_step"],
            "first_source_execution_step": observation["first_source_execution_step"],
            "second_source_execution_step": observation["second_source_execution_step"],
            "decision_digest": hashlib.sha256(repr(sorted(observation.items())).encode()).digest(),
            "rust_policy_ns": 100,
        }


class FakePatcher:
    def __init__(self):
        self.model_options = {"transformer_options": {}}
        self.patches = {}

    def clone(self):
        return FakePatcher()

    def set_model_patch_replace(self, patch, name, block_name, number):
        self.patches[number] = patch


class FakeGuider:
    def __init__(self):
        self.model_patcher = FakePatcher()
        self.model_options = self.model_patcher.model_options


class DirectionalPredictionTests(unittest.TestCase):
    def bridge(self, targets=(), alpha=None):
        digest = "11" * 32
        return DirectionalPlanBridge(
            CorrectionPlanContext(digest, digest, digest, digest),
            targets,
            alpha,
            FakeExtension(),
        )

    def run_steps(self, controller, steps=20):
        for step in range(steps):
            tensor = FakeTensor(float(step))
            for block in range(50):
                wrapper = controller.block_wrapper(block)

                def original(args, block=block):
                    return {"img": FakeTensor(args["img"].value + (1.0 if block == 48 else 0.0))}

                tensor = wrapper({"img": tensor}, {"original_block": original})["img"]

    def test_exact_sufficient_statistics_match_direct_tensor_formula(self):
        a = [0.5, -1.0, 2.0, 3.5, -0.25]
        b = [0.6, -0.8, 2.2, 3.2, -0.1]
        y = [0.7, -0.7, 2.35, 3.0, 0.05]
        statistics = sufficient_statistics_from_sequences(a, b, y)
        for alpha in (0.0, *ALPHA_GRID):
            scalar = directional_metrics_from_statistics(statistics, alpha)
            direct = direct_directional_metrics(a, b, y, alpha)
            self.assertAlmostEqual(
                scalar["residual_cosine_similarity"], direct["residual_cosine_similarity"], places=12
            )
            self.assertAlmostEqual(
                scalar["normalized_residual_l2"], direct["normalized_residual_l2"], places=12
            )
            self.assertEqual(scalar["full_prediction_tensor_count"], 0)

    def test_fixed_alpha_grid_global_selection_spacing_and_tie_break(self):
        diagnostics = []
        for target in FROZEN_CEILING:
            alpha_records = []
            for alpha in ALPHA_GRID:
                admitted = alpha in {-0.25, 0.25} and target in {5, 8, 13}
                cosine = 0.995 if alpha == 0.25 else 0.994
                alpha_records.append({
                    "alpha": alpha,
                    "residual_cosine_similarity": cosine,
                    "normalized_residual_l2": 0.10,
                    "threshold_pass": admitted,
                    "raw_non_regression_pass": admitted,
                    "admitted": admitted,
                })
            diagnostics.append({"target_step": target, "alpha_diagnostics": alpha_records})
        selected = select_global_alpha(diagnostics)
        self.assertEqual(selected["global_alpha"], 0.25)
        self.assertEqual(selected["calibrated_targets"], [5, 8, 13])
        self.assertTrue(selected["selective_admitted"])

    def test_settings_digest_and_source_contract_are_deterministic(self):
        first = directional_settings_digest(
            actual_replay_enabled=False, global_alpha=None, calibrated_targets=()
        )
        second = directional_settings_digest(
            actual_replay_enabled=False, global_alpha=None, calibrated_targets=()
        )
        selective = directional_settings_digest(
            actual_replay_enabled=True, global_alpha=0.25, calibrated_targets=(5, 8)
        )
        self.assertEqual(first, second)
        self.assertNotEqual(first, selective)
        with self.assertRaisesRegex(ValueError, "frozen alpha"):
            validate_global_alpha(0.33, required=True)
        with self.assertRaisesRegex(ValueError, "re-seed"):
            validate_calibrated_targets((5, 6))

    def test_control_preserves_two_residual_memory_and_shadow_contract(self):
        controller = H3TwoResidualDirectionalController(
            CONTROL,
            self.bridge(),
            workflow_revision_digest="11" * 32,
            model_revision_digest="11" * 32,
            settings_digest="11" * 32,
            global_alpha=None,
            tensor_ops=FakeOps(),
        )
        self.run_steps(controller)
        receipt = controller.receipt()
        self.assertEqual(receipt["original_block_call_count"], 1000)
        self.assertEqual(receipt["actual_replay_steps"], 0)
        self.assertEqual(receipt["max_persistent_residual_count"], 2)
        self.assertEqual(receipt["persistent_direction_count"], 0)
        self.assertEqual(receipt["persistent_predicted_residual_count"], 0)
        self.assertEqual(receipt["shadow_full_prediction_tensor_count"], 0)
        self.assertLessEqual(receipt["max_live_residual_sized_buffers"], 3)
        self.assertEqual(receipt["full_size_fp32_materialization_count"], 0)
        self.assertEqual(receipt["tensor_bytes_to_rust"], 0)
        self.assertEqual(len(receipt["diagnostics"]), 6)
        self.assertEqual(len(receipt["diagnostics"][0]["alpha_diagnostics"]), 8)

    def test_selective_replay_skips_exact_segment_and_reseeds_two_steps(self):
        bridge = self.bridge((5,), 0.25)
        bridge.plans[5] = {
            "decision_code": 1,
            "decision": "REUSE_CORRECTED_TRANSFORM",
            "reason": "correction_admitted",
        }
        controller = H3TwoResidualDirectionalController(
            SELECTIVE,
            bridge,
            workflow_revision_digest="11" * 32,
            model_revision_digest="11" * 32,
            settings_digest="11" * 32,
            global_alpha=0.25,
            tensor_ops=FakeOps(),
        )
        self.run_steps(controller, 9)
        receipt = controller.receipt()
        self.assertEqual(receipt["actual_replay_steps"], 1)
        self.assertEqual(receipt["original_block_call_count"], 9 * 50 - 37)
        self.assertEqual(receipt["replayed_block_call_count"], 37)
        self.assertEqual(receipt["per_step"][5]["original_block_calls"], 13)
        self.assertEqual(receipt["per_step"][5]["replayed_block_calls"], 37)
        self.assertEqual(receipt["per_step"][6]["decision"], "FULL_COMPUTE")
        self.assertEqual(receipt["per_step"][7]["decision"], "FULL_COMPUTE")
        self.assertEqual(receipt["max_transient_prediction_count"], 1)

    def test_bridge_uses_existing_tensor_free_abi_and_fails_open(self):
        bridge = self.bridge((5,), 0.25)
        bridge.set_state_provider(lambda target: {
            "first_source_execution_step": target - 2,
            "second_source_execution_step": target - 1,
            "cache_available": True,
            "predictor_available": True,
            "predictor_provenance_valid": True,
            "correction_metadata_valid": True,
            "full_compute_seed_count": 2,
            "reseed_required": False,
            "finite": True,
        })
        event = {
            "predicted_execution_step": 5,
            "sketch_observed_step": 3,
            "total_steps": 20,
            "eye_states": ["STABLE", "STABLE", "STABLE", "UNCERTAIN", "UNCERTAIN"],
            "event_ready": True,
            "source_dtype": "torch.float32",
            "source_device_type": "cuda",
            "signal_adapter": "h3_nested_video_v1",
            "global_invalidation": 0,
            "overlap_conflict_mask": 0,
            "fallback_used": False,
            "reason": None,
        }
        plan = bridge.evaluate_event(event)
        self.assertEqual(plan["decision"], "REUSE_CORRECTED_TRANSFORM")
        active = dict(event)
        active["eye_states"] = ["STABLE", "STABLE", "ACTIVE", "UNCERTAIN", "UNCERTAIN"]
        self.assertEqual(bridge.evaluate_event(active)["decision"], "FULL_COMPUTE")
        bridge.extension = None
        bridge.extension_error = "unavailable"
        self.assertEqual(bridge.evaluate_event(event)["decision"], "ESCALATE_FULL_COMPUTE")
        receipt = bridge.receipt()
        self.assertEqual(receipt["tensor_bytes_to_rust"], 0)
        self.assertEqual(receipt["abi_reused_without_semantic_change"], "c3-r3.correction-plan.1")

    def test_workflow_memory_gate_and_guider_clone(self):
        digest = "11" * 32
        standard = {"10": {"class_type": "SamplerCustomAdvanced", "inputs": {}}}
        workflow = build_workflow(
            standard,
            run_digest=digest,
            workflow_revision_digest=digest,
            settings_digest=digest,
            model_revision_digest=digest,
            calibrated_targets=(),
            global_alpha=None,
            directional_replay_enabled=False,
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(QUALITY_GATE["mean_ssim_min"], 0.95)
        admitted = directional_memory_admission(
            device_total_memory_bytes=12_884_377_600,
            current_free_memory_bytes=12_000_000_000,
        )
        self.assertTrue(admitted["admitted"])
        self.assertEqual(admitted["expected_incremental_bytes"], 165_838_848)
        controller = H3TwoResidualDirectionalController(
            CONTROL,
            self.bridge(),
            workflow_revision_digest=digest,
            model_revision_digest=digest,
            settings_digest=digest,
            global_alpha=None,
            tensor_ops=FakeOps(),
        )
        guider = FakeGuider()
        patched = controller.install_on_guider_clone(guider)
        self.assertEqual(guider.model_patcher.patches, {})
        self.assertEqual(set(patched.model_patcher.patches), set(range(50)))
        source = inspect.getsource(H3TwoResidualDirectionalController.block_wrapper)
        self.assertNotIn(".cpu(", source)
        self.assertNotIn(".numpy(", source)
        self.assertNotIn("evaluate_correction_plan", source)

    def test_existing_pyo3_correction_abi_roundtrip_when_available(self):
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        contract = dict(boundary.correction_plan_contract())
        response = dict(boundary.evaluate_correction_plan(
            abi_version=1,
            struct_size=contract["observation_struct_size"],
            run_digest=bytes.fromhex("11" * 32),
            workflow_revision_digest=bytes.fromhex("22" * 32),
            settings_digest=bytes.fromhex("33" * 32),
            model_revision_digest=bytes.fromhex("44" * 32),
            segment_logical_digest=bytes.fromhex("55" * 32),
            target_execution_step=5,
            first_source_execution_step=3,
            second_source_execution_step=4,
            total_steps=20,
            cache_available=True,
            predictor_available=True,
            predictor_provenance_valid=True,
            corrected_similarity_admitted=True,
            correction_metadata_valid=True,
            calibrated_target=True,
            full_compute_seed_count=2,
            reseed_required=False,
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
        ))
        self.assertEqual(response["decision_code"], 1)
        self.assertEqual(contract["abi_version"], 1)
        self.assertEqual(MECHANISM, "TWO_RESIDUAL_LINEAR_DIRECTION_PREDICTION_V1")


if __name__ == "__main__":
    unittest.main()
