from __future__ import annotations

import inspect
import unittest

from hive_product.h3_cuda_fixture_teardown_v4 import (
    FixtureLifecycleError,
    FixtureOwnershipRegistry,
    LIFECYCLE,
    ROOT_CAUSE,
    final_memory_gate,
)
from hive_product.h3_bounded_host_source_oracle_v4_cuda import (
    run_bounded_cuda_preflight,
)


class FakeTensor:
    def __init__(self, *, cuda: bool = False, pinned: bool = False, size: int = 8):
        self.is_cuda = cuda
        self._pinned = pinned
        self._size = size

    def is_pinned(self):
        return self._pinned

    def numel(self):
        return self._size

    def element_size(self):
        return 2


class FakeTorch:
    pass


def snapshot(*, allocated=0, active=0, cuda=0, pinned=0, future=0, event=0, stream=0):
    return {
        "allocated_bytes": allocated,
        "active_bytes": active,
        "released_fixture_cuda_tensor_count": cuda,
        "released_fixture_pinned_tensor_count": pinned,
        "worker_owner_count": 0,
        "outstanding_future_count": future,
        "future_cuda_result_count": future,
        "worker_thread_count": 0,
        "outstanding_event_count": event,
        "outstanding_stream_count": stream,
    }


class H3CudaFixtureTeardownV4Tests(unittest.TestCase):
    def test_root_cause_is_specific_and_lifecycle_is_complete(self):
        self.assertEqual(ROOT_CAUSE, "LIVE_TENSOR_REFERENCE_LEAK")
        self.assertEqual(
            LIFECYCLE,
            (
                "RUNNING",
                "STOP_ACCEPTING",
                "DRAINING",
                "CUDA_COMPLETION_CONFIRMED",
                "WORKERS_JOINED",
                "REFERENCES_RELEASED",
                "ALLOCATOR_CLEANED",
                "CLOSED",
            ),
        )

    def test_registry_rejects_post_close_enqueue(self):
        registry = FixtureOwnershipRegistry(FakeTorch())
        registry.cuda("tensor", FakeTensor(cuda=True))
        registry.pinned("host", FakeTensor(pinned=True))
        self.assertEqual(registry.counts()["fixture_owned_cuda_tensor_bytes"], 16)
        self.assertEqual(registry.counts()["fixture_owned_pinned_bytes"], 16)
        registry.release_strong_references()
        with self.assertRaises(FixtureLifecycleError):
            registry.cuda("late", FakeTensor(cuda=True))

    def test_memory_gate_detects_each_owner_category(self):
        warm = snapshot()
        self.assertTrue(all(final_memory_gate(snapshot(), warm).values()))
        for changed in (
            snapshot(allocated=2, active=2),
            snapshot(cuda=1),
            snapshot(pinned=1),
            snapshot(future=1),
            snapshot(event=1),
            snapshot(stream=1),
        ):
            self.assertFalse(all(final_memory_gate(changed, warm).values()))

    def test_v4_entrypoint_uses_explicit_ownership_remediation(self):
        source = inspect.getsource(run_bounded_cuda_preflight)
        self.assertIn("run_teardown_remediation", source)
        self.assertNotIn("del source", source)
        self.assertNotIn("final_allocated <= baseline_allocated", source)


if __name__ == "__main__":
    unittest.main()
