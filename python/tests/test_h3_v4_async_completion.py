from __future__ import annotations

import inspect
import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import (
    SOURCE_SLOT_EMPTY,
    SourceSlotLifecycle,
)
from hive_product.h3_observer_v4 import H3ObserverControllerV4
from hive_product.h3_v4_async_completion_fixture import (
    ROOT_CAUSE,
    replay_async_completion_trace,
    replay_late_event_and_abort_cleanup,
    replay_release_zero_prefix,
)


class FakeEvent:
    def __init__(self, ready: bool = False) -> None:
        self.ready = ready
        self.query_count = 0

    def query(self) -> bool:
        self.query_count += 1
        return self.ready


class H3V4AsyncCompletionTests(unittest.TestCase):
    def test_root_cause_is_callback_ordering_gap(self) -> None:
        self.assertEqual(ROOT_CAUSE, "CALLBACK_ORDERING_GAP")
        source = inspect.getsource(H3ObserverControllerV4)
        self.assertIn("self._pump_completions(\"callback_entry\")", source)
        self.assertIn("self._pump_completions(\"callback_exit\")", source)
        self.assertIn("self._pump_completions(\"generation_finalize\")", source)
        self.assertIn("self._pump_completions(\"abort_cleanup\")", source)

    def test_lifecycle_returns_released_slot_to_empty_without_resetting_counts(self) -> None:
        slot = SourceSlotLifecycle()
        identity = {
            "generation_digest": "1",
            "source_step_ordinal": 1,
            "source_scheduler_timestep": "2",
            "source_block": 0,
            "source_region": 0,
            "source_capture_sequence": 1,
            "source_slot_index": 0,
            "source_slot_version": 1,
            "source_tensor_shape": (1, 1),
            "source_dtype": "torch.bfloat16",
            "source_device_layout_identity": "cuda",
        }
        slot.begin_capture(identity)
        slot.mark_ready()
        slot.begin_consume(identity)
        slot.release()
        slot.return_empty()
        self.assertEqual(slot.state, SOURCE_SLOT_EMPTY)
        self.assertEqual((slot.capture_count, slot.consume_count, slot.release_count), (1, 1, 1))

    def test_full_trace_varies_completion_latency_and_drains_every_slot(self) -> None:
        receipt = replay_async_completion_trace()
        self.assertTrue(receipt["passed"])
        self.assertEqual(receipt["full_attention_calls"], 1000)
        self.assertEqual(
            (receipt["capture_count"], receipt["consume_count"], receipt["release_count"]),
            (208, 199, 199),
        )
        self.assertGreater(receipt["completion_not_ready_count"], 0)
        self.assertEqual(len(receipt["delay_classes"]), 6)
        self.assertLessEqual(receipt["peak_live_slots"], 13)
        for field in (
            "lineage_mismatch_count",
            "overwrite_count",
            "stale_admission_count",
            "duplicate_release_count",
            "incomplete_evidence_count",
            "unread_overwrite_count",
            "final_live_slots",
            "final_live_tensor_references",
        ):
            self.assertEqual(receipt[field], 0, field)

    def test_retained_failure_prefix_releases_only_after_completion(self) -> None:
        receipt = replay_release_zero_prefix()
        self.assertTrue(receipt["passed"])
        self.assertEqual(
            receipt["before_completion"],
            {"capture": 13, "consume": 13, "release": 0, "consuming": 13},
        )
        self.assertEqual(receipt["early_release_count"], 0)
        self.assertEqual(
            receipt["after_completion"],
            {"capture": 13, "consume": 13, "release": 13, "empty": 13},
        )

    def test_late_version_and_abort_cleanup_are_fail_closed(self) -> None:
        receipt = replay_late_event_and_abort_cleanup()
        self.assertTrue(receipt["passed"])
        self.assertTrue(receipt["stale_completion_rejected"])
        self.assertEqual(receipt["generation_event_mix_count"], 0)
        self.assertEqual(receipt["state_after_abort"], SOURCE_SLOT_EMPTY)

    def test_hot_path_uses_query_without_blocking_synchronization(self) -> None:
        source = inspect.getsource(H3ObserverControllerV4._pump_completions)
        self.assertIn("oracle_completion_event.query()", source)
        for forbidden in (
            "torch.cuda.synchronize",
            "event.synchronize",
            "stream.synchronize",
            ".result(",
            ".join(",
        ):
            self.assertNotIn(forbidden, source)

    def test_completion_signal_event_is_not_timing_enabled(self) -> None:
        source = inspect.getsource(H3ObserverControllerV4._observe_full_compute_control)
        self.assertIn("Event(enable_timing=False, blocking=False)", source)

    def test_evidence_commit_precedes_release_and_no_immediate_release_remains(self) -> None:
        observe = inspect.getsource(H3ObserverControllerV4._observe_full_compute_control)
        commit = inspect.getsource(H3ObserverControllerV4._commit_completion)
        self.assertNotIn("slot.release()", observe)
        self.assertLess(commit.index("self._pending_records.append"), commit.index("slot.complete_release"))


if __name__ == "__main__":
    unittest.main()
