from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import inspect
import unittest

from hive_product.c3_r1_h3_frozen_probe import NODE_CLASS, build_c3_r1_workflow
from hive_product.frozen_block_selective import (
    BLOCK_COUNT,
    CANDIDATE_BLOCKS,
    CANDIDATE_BLOCK_MASK,
    CONTROL,
    ESCALATE_FULL_COMPUTE,
    FROZEN_SCHEDULE,
    FULL_COMPUTE,
    FULL_COMPUTE_ANCHORS,
    SELECTIVE,
    SELECTIVE_BLOCK_BYPASS,
    THEORETICAL_OPPORTUNITY,
    FrozenBlockPlanBridge,
    FrozenPlanContext,
    H3BlockExecutionController,
    frozen_settings_digest,
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

    def c3_frozen_block_plan_contract(self):
        return {
            "abi_version": 1,
            "observation_struct_size": 224,
            "directive_struct_size": 72,
            "total_steps": 20,
            "block_count": 50,
            "frozen_schedule": list(FROZEN_SCHEDULE),
            "candidate_block_start": 12,
            "candidate_block_end": 48,
            "candidate_block_count": 37,
            "max_rust_calls_per_callback": 1,
            "max_rust_calls_per_block": 0,
            "tensor_bytes_per_call": 0,
        }

    def evaluate_c3_frozen_block_plan(self, **observation):
        self.calls.append(observation)
        frozen = bool(observation["frozen_schedule_member"])
        admitted = (
            frozen
            and observation["source_valid"]
            and observation["prediction_valid"]
            and observation["stable_count"] >= 2
            and observation["active_count"] == 0
            and not observation["global_invalidation"]
            and observation["overlap_conflict_mask"] == 0
            and observation["fatal_flags"] == 0
        )
        decision = SELECTIVE_BLOCK_BYPASS if admitted else FULL_COMPUTE
        reason = 0 if admitted else 11 if not frozen else 15
        mask = CANDIDATE_BLOCK_MASK if admitted else 0
        return {
            "ffi_status": 0,
            "abi_version": 1,
            "struct_size": 72,
            "decision_code": decision,
            "reason_code": reason,
            "target_step": observation["predicted_execution_step"],
            "bypass_mask": mask,
            "bypass_count": mask.bit_count(),
            "fallback_required": int(not admitted),
            "unsupported_flags": 0,
            "decision_digest": sha256(repr(sorted(observation.items())).encode()).digest(),
            "rust_policy_ns": 100,
        }


def event_for_target(target: int, *, active: bool = False) -> dict:
    states = ["UNCERTAIN", "STABLE", "STABLE", "UNCERTAIN", "UNCERTAIN"]
    if active:
        states[3] = "ACTIVE"
    return {
        "total_steps": 20,
        "predicted_execution_step": target,
        "sketch_observed_step": target - 2,
        "eye_states": states,
        "candidate_reuse_count": 2,
        "candidate_generate_count": int(active),
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


class FakePatcher:
    def __init__(self) -> None:
        self.model_options = {"transformer_options": {}}
        self.patches: dict[int, object] = {}

    def clone(self):
        return FakePatcher()

    def set_model_patch_replace(self, patch, name, block_name, number):
        if (name, block_name) != ("dit", "double_block"):
            raise AssertionError("unexpected patch namespace")
        self.patches[number] = patch


class FakeGuider:
    def __init__(self) -> None:
        self.model_patcher = FakePatcher()
        self.model_options = self.model_patcher.model_options


class FrozenBlockSelectiveTests(unittest.TestCase):
    def bridge(self):
        extension = FakeExtension()
        return FrozenBlockPlanBridge(FrozenPlanContext(**DIGESTS), extension=extension), extension

    def test_frozen_schedule_candidate_blocks_and_opportunity_are_exact(self) -> None:
        self.assertEqual(FROZEN_SCHEDULE, (5, 6, 8, 13, 16, 17))
        self.assertEqual(FULL_COMPUTE_ANCHORS, (0, 1, 18, 19))
        self.assertEqual(CANDIDATE_BLOCKS, tuple(range(12, 49)))
        self.assertEqual(len(CANDIDATE_BLOCKS), 37)
        self.assertAlmostEqual(THEORETICAL_OPPORTUNITY, 0.222)
        self.assertTrue(set(FROZEN_SCHEDULE).isdisjoint(FULL_COMPUTE_ANCHORS))

    def test_plan_admits_member_and_never_adds_nonmember(self) -> None:
        bridge, extension = self.bridge()
        admitted = bridge.evaluate_event(event_for_target(5))
        rejected = bridge.evaluate_event(event_for_target(7))
        self.assertEqual(admitted["decision_code"], SELECTIVE_BLOCK_BYPASS)
        self.assertEqual(admitted["bypass_count"], 37)
        self.assertEqual(rejected["decision_code"], FULL_COMPUTE)
        self.assertEqual(rejected["bypass_count"], 0)
        self.assertEqual(len(extension.calls), 2)

    def test_live_active_veto_keeps_original_forward(self) -> None:
        bridge, _ = self.bridge()
        veto = bridge.evaluate_event(event_for_target(5, active=True))
        self.assertEqual(veto["decision_code"], FULL_COMPUTE)
        controller = H3BlockExecutionController(SELECTIVE, bridge)
        marker = object()
        called = []
        result = controller.block_wrapper(12)(
            {"img": marker}, {"original_block": lambda args: called.append(args) or {"img": marker}}
        )
        self.assertEqual(result["img"], marker)
        self.assertEqual(len(called), 1)

    def test_control_always_calls_original_and_selective_omits_candidate(self) -> None:
        bridge, extension = self.bridge()
        bridge.evaluate_event(event_for_target(5))
        control = H3BlockExecutionController(CONTROL, bridge)
        selective = H3BlockExecutionController(SELECTIVE, bridge)
        marker = object()

        def run_through_step_five(controller):
            originals = 0
            for step in range(6):
                for block in range(BLOCK_COUNT):
                    def original(args, marker=marker):
                        return {"img": marker}
                    before = controller.original_block_call_count
                    result = controller.block_wrapper(block)(
                        {"img": marker}, {"original_block": original}
                    )
                    originals += controller.original_block_call_count - before
                    self.assertIs(result["img"], marker)
            return originals

        self.assertEqual(run_through_step_five(control), 300)
        self.assertEqual(control.bypass_block_call_count, 0)
        self.assertEqual(run_through_step_five(selective), 263)
        self.assertEqual(selective.bypass_block_call_count, 37)
        self.assertEqual(len(extension.calls), 1, "block wrappers must not call Rust")

    def test_first_last_anchors_and_outside_schedule_are_full_compute(self) -> None:
        bridge, _ = self.bridge()
        for step in (*FULL_COMPUTE_ANCHORS, 7):
            plan = bridge.evaluate_event(event_for_target(step))
            self.assertEqual(plan["decision_code"], FULL_COMPUTE)
            self.assertEqual(plan["bypass_mask"], 0)

    def test_guider_clone_installs_all_wrappers_and_preserves_original(self) -> None:
        bridge, _ = self.bridge()
        guider = FakeGuider()
        controller = H3BlockExecutionController(CONTROL, bridge)
        patched = controller.install_on_guider_clone(guider)
        self.assertIsNot(patched, guider)
        self.assertIsNot(patched.model_patcher, guider.model_patcher)
        self.assertEqual(guider.model_patcher.patches, {})
        self.assertEqual(set(patched.model_patcher.patches), set(range(50)))

    def test_identity_bypass_contains_no_copy_or_per_block_boundary(self) -> None:
        source = inspect.getsource(H3BlockExecutionController.block_wrapper)
        for banned in (".clone(", ".cpu(", ".numpy(", "evaluate_c3_frozen_block_plan"):
            self.assertNotIn(banned, source)
        self.assertIn('{"img": args["img"]}', source)

    def test_workflow_control_selective_difference_and_settings_hash(self) -> None:
        standard = {
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["5", 0], "guider": ["9", 0]},
            }
        }
        control = build_c3_r1_workflow(
            standard,
            **DIGESTS,
            actual_block_bypass_enabled=False,
        )
        selective = build_c3_r1_workflow(
            standard,
            **DIGESTS,
            actual_block_bypass_enabled=True,
        )
        self.assertEqual(control["10"]["class_type"], NODE_CLASS)
        self.assertFalse(control["10"]["inputs"]["actual_block_bypass_enabled"])
        self.assertTrue(selective["10"]["inputs"]["actual_block_bypass_enabled"])
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertNotEqual(
            frozen_settings_digest(actual_block_bypass_enabled=False),
            frozen_settings_digest(actual_block_bypass_enabled=True),
        )

    def test_actual_pyo3_contracts_roundtrip_when_extension_is_available(self) -> None:
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        c1 = dict(boundary.step_policy_contract())
        c2 = dict(boundary.compound_eye_shadow_contract())
        c3 = dict(boundary.c3_frozen_block_plan_contract())
        self.assertEqual(c1["abi_version"], 1)
        self.assertEqual(c2["abi_version"], 1)
        self.assertEqual(c3["abi_version"], 1)
        self.assertEqual(c3["frozen_schedule"], list(FROZEN_SCHEDULE))
        response = dict(
            boundary.evaluate_c3_frozen_block_plan(
                abi_version=1,
                struct_size=c3["observation_struct_size"],
                run_digest=bytes.fromhex(DIGESTS["run_digest"]),
                workflow_revision_digest=bytes.fromhex(DIGESTS["workflow_revision_digest"]),
                settings_digest=bytes.fromhex(DIGESTS["settings_digest"]),
                model_revision_digest=bytes.fromhex(DIGESTS["model_revision_digest"]),
                predicted_execution_step=5,
                total_steps=20,
                block_count=50,
                frozen_schedule_member=True,
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
                selective_supported=True,
                fallback_supported=True,
                fatal_flags=0,
                unsupported_flags=0,
            )
        )
        self.assertEqual(response["ffi_status"], 0)
        self.assertEqual(response["decision_code"], SELECTIVE_BLOCK_BYPASS)
        self.assertEqual(response["bypass_count"], 37)


if __name__ == "__main__":
    unittest.main()
