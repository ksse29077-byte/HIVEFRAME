from __future__ import annotations

from dataclasses import replace
import inspect
from types import SimpleNamespace
import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import SOURCE_SLOT_EMPTY
from hive_product.h3_observer_v4 import H3ObserverControllerV4, V4HostSourceSlot
from hive_product.h3_v4_tensor_identity import (
    INFERENCE_NO_VERSION_COUNTER,
    NORMAL_VERSION_COUNTER,
    TensorIdentityError,
    capture_tensor_identity,
    tensor_identity_matches,
)


def _lineage(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "generation_digest": "1" * 64,
        "profile_digest": "2" * 64,
        "model_digest": "3" * 64,
        "inventory_digest": "4" * 64,
        "layout_digest": "5" * 64,
        "source_step_ordinal": 1,
        "source_scheduler_timestep": "0x1.0p+0",
        "source_block": 0,
        "source_region": 0,
        "source_capture_sequence": 1,
        "source_slot_index": 0,
        "source_slot_version": 1,
    }
    value.update(changes)
    return value


class H3V4TensorIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        import torch

        self.torch = torch

    def snapshot(self, tensor, **changes: object):
        return capture_tensor_identity(
            self.torch,
            tensor,
            lineage_identity=_lineage(**changes),
            workflow_digest="6" * 64,
        )

    def test_inference_tensor_never_reads_a_version_counter(self) -> None:
        with self.torch.inference_mode():
            tensor = self.torch.zeros((4, 8), dtype=self.torch.bfloat16)
        snapshot = self.snapshot(tensor)
        self.assertEqual(snapshot.version_semantics, INFERENCE_NO_VERSION_COUNTER)
        self.assertFalse(snapshot.version_counter_available)
        self.assertIsNone(snapshot.version_counter_value)

    def test_normal_tensor_version_change_is_detected(self) -> None:
        tensor = self.torch.zeros((4, 8), dtype=self.torch.bfloat16)
        before = self.snapshot(tensor)
        tensor.add_(1)
        after = self.snapshot(tensor)
        self.assertEqual(before.version_semantics, NORMAL_VERSION_COUNTER)
        self.assertFalse(tensor_identity_matches(before, after))

    def test_same_pointer_with_changed_capture_sequence_is_rejected(self) -> None:
        tensor = self.torch.zeros((4, 8))
        self.assertFalse(
            tensor_identity_matches(
                self.snapshot(tensor), self.snapshot(tensor, source_capture_sequence=2)
            )
        )

    def test_same_shape_with_changed_step_is_rejected(self) -> None:
        tensor = self.torch.zeros((4, 8))
        self.assertFalse(
            tensor_identity_matches(
                self.snapshot(tensor), self.snapshot(tensor, source_step_ordinal=2)
            )
        )

    def test_changed_block_or_region_is_rejected(self) -> None:
        tensor = self.torch.zeros((4, 8))
        before = self.snapshot(tensor)
        self.assertFalse(
            tensor_identity_matches(before, self.snapshot(tensor, source_block=1))
        )
        self.assertFalse(
            tensor_identity_matches(before, self.snapshot(tensor, source_region=1))
        )

    def test_changed_slot_version_is_rejected(self) -> None:
        tensor = self.torch.zeros((4, 8))
        self.assertFalse(
            tensor_identity_matches(
                self.snapshot(tensor), self.snapshot(tensor, source_slot_version=2)
            )
        )

    def test_changed_storage_offset_is_rejected(self) -> None:
        storage = self.torch.zeros((5, 8))
        first = storage[0:4]
        second = storage[1:5]
        self.assertEqual(first.shape, second.shape)
        self.assertFalse(
            tensor_identity_matches(self.snapshot(first), self.snapshot(second))
        )

    def test_changed_dtype_device_or_layout_is_rejected(self) -> None:
        tensor = self.torch.zeros((4, 8), dtype=self.torch.float32)
        before = self.snapshot(tensor)
        changed_dtype = self.snapshot(tensor.to(dtype=self.torch.bfloat16))
        changed_layout = self.snapshot(
            self.torch.empty_strided((4, 8), (1, 4), dtype=tensor.dtype)
        )
        changed_device_identity = dict(before.logical_identity)
        changed_device_identity["tensor_device"] = "cuda:1"
        changed_device = replace(before, logical_identity=changed_device_identity)
        self.assertFalse(tensor_identity_matches(before, changed_dtype))
        self.assertFalse(tensor_identity_matches(before, changed_layout))
        self.assertFalse(tensor_identity_matches(before, changed_device))

    def test_previous_generation_inference_tensor_is_rejected(self) -> None:
        with self.torch.inference_mode():
            tensor = self.torch.zeros((4, 8), dtype=self.torch.bfloat16)
        self.assertFalse(
            tensor_identity_matches(
                self.snapshot(tensor),
                self.snapshot(tensor, generation_digest="9" * 64),
            )
        )

    def test_bounded_receipt_excludes_storage_pointers_and_object_id(self) -> None:
        receipt = self.snapshot(self.torch.zeros((4, 8))).bounded_receipt()
        serialized = repr(receipt)
        self.assertNotIn("data_ptr", serialized)
        self.assertNotIn("python_object_id", serialized)

    def test_identity_failure_precedes_consume_transition(self) -> None:
        source = inspect.getsource(H3ObserverControllerV4._observe_full_compute_control)
        self.assertLess(
            source.index("identity_before = self._capture_full_core_identity"),
            source.index("slot.begin_consume"),
        )
        self.assertNotIn("getattr(full_core, \"_version\"", source)
        self.assertNotIn("full_core._version", source)

    def test_identity_helper_exception_leaves_ready_slot_unchanged(self) -> None:
        slot = V4HostSourceSlot(payload=object())
        identity = {
            **_lineage(),
            "source_tensor_shape": (1, 1),
            "source_dtype": "torch.bfloat16",
            "source_device_layout_identity": "cpu-pinned",
        }
        slot.begin_capture(identity)
        slot.mark_ready(
            lineage_digest="7" * 64,
            lineage_components=identity,
            completion_event=object(),
        )

        class BrokenTorch:
            @staticmethod
            def is_inference(_tensor):
                raise RuntimeError("fixture identity failure")

        with self.assertRaises(TensorIdentityError):
            capture_tensor_identity(
                BrokenTorch(),
                object(),
                lineage_identity=identity,
                workflow_digest="8" * 64,
            )
        self.assertEqual(slot.state, "READY")
        self.assertEqual(slot.lifecycle.consume_count, 0)

    def test_abort_cleanup_removes_orphan_state_and_event_reference(self) -> None:
        slot = V4HostSourceSlot(payload=object())
        identity = {
            **_lineage(),
            "source_tensor_shape": (1, 1),
            "source_dtype": "torch.bfloat16",
            "source_device_layout_identity": "cpu-pinned",
        }
        slot.begin_capture(identity)
        slot.mark_ready(
            lineage_digest="7" * 64,
            lineage_components=identity,
            completion_event=object(),
        )
        slot.begin_consume(identity)
        slot.abort_cleanup()
        self.assertEqual(slot.state, SOURCE_SLOT_EMPTY)
        self.assertIsNone(slot.lifecycle.identity)
        self.assertIsNone(slot.completion_event)
        self.assertEqual(slot.lifecycle.abort_cleanup_count, 1)

    def test_already_aborted_controller_still_runs_cleanup_once(self) -> None:
        slot = V4HostSourceSlot(payload=object())
        identity = {
            **_lineage(),
            "source_tensor_shape": (1, 1),
            "source_dtype": "torch.bfloat16",
            "source_device_layout_identity": "cpu-pinned",
        }
        slot.begin_capture(identity)
        slot.mark_ready(
            lineage_digest="7" * 64,
            lineage_components=identity,
            completion_event=object(),
        )
        slot.begin_consume(identity)
        controller = object.__new__(H3ObserverControllerV4)
        controller.state = "aborted"
        controller._abort_cleanup_completed = False
        controller.abort_reason = None
        controller.finalization_sync_count = 0
        controller.completion_commit_failure_count = 0
        controller.torch = SimpleNamespace(
            cuda=SimpleNamespace(synchronize=lambda: None)
        )
        controller.resources = SimpleNamespace(slots={0: slot})
        controller._pump_completions = lambda _position: 0
        controller._pending_completions = [object()]
        controller._deferred_captures = {0: object()}
        controller._scheduled_targets = {(0, 1)}
        controller._scheduled_sources = {(0, 0)}
        controller.abort("fixture")
        self.assertTrue(controller._abort_cleanup_completed)
        self.assertEqual(slot.state, SOURCE_SLOT_EMPTY)
        self.assertEqual(controller._pending_completions, [])
        controller.abort("duplicate")
        self.assertEqual(slot.lifecycle.abort_cleanup_count, 1)


if __name__ == "__main__":
    unittest.main()
