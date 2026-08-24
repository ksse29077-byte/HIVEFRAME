from __future__ import annotations

from dataclasses import replace
import inspect
import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import REGION_ROWS
from hive_product.h3_v4_executor_hot_path import (
    FULL_SEQUENCE_ROWS,
    H3_DTYPE,
    H3_HEAD_DIM,
    H3_HEADS,
    V4_EXECUTOR_BENCHMARK,
    V4_SELECTIVE_FUTURE,
    V4CacheHandle,
    V4ExecutorAdapter,
    V4ExecutorContractError,
    V4ExecutorPlan,
    V4GenerationContext,
    V4GpuPlan,
)


class TinyTensor:
    def __init__(self, rows, *, width=H3_HEADS, dtype=H3_DTYPE, device="cuda:0"):
        self.rows = list(rows)
        self.shape = (len(self.rows), width, H3_HEAD_DIM) if width == H3_HEADS else (len(self.rows), width)
        self.dtype = dtype
        self.device = device

    def index_select(self, _dimension, indices):
        values = indices.rows if isinstance(indices, TinyIndices) else indices
        width = self.shape[1]
        return TinyTensor([self.rows[index] for index in values], width=width, dtype=self.dtype, device=self.device)

    def new_empty(self, shape):
        return TinyTensor([None] * shape[0], width=shape[1], dtype=self.dtype, device=self.device)

    def index_copy_(self, _dimension, indices, source):
        values = indices.rows if isinstance(indices, TinyIndices) else indices
        for target, value in zip(values, source.rows, strict=True):
            self.rows[target] = value
        return self


class TinyIndices:
    def __init__(self, rows):
        self.rows = list(rows)


def context():
    return V4GenerationContext(
        generation_digest="1" * 64,
        model_digest="2" * 64,
        settings_digest="3" * 64,
        scheduler_digest="4" * 64,
        input_digest="5" * 64,
    )


def plan(value, *, block=0):
    return V4ExecutorPlan.frozen_region_zero(
        value, lineage_digest="6" * 64, step=1, block=block
    )


def gpu_plan(value):
    return V4GpuPlan(
        cpu=value,
        computed_indices=TinyIndices(value.computed_rows),
        reused_indices=TinyIndices(value.reused_rows),
        cache_region_indices=TinyIndices(value.cache_region_rows),
        cache_reused_positions=TinyIndices(value.cache_reused_positions),
    )


def qkv():
    rows = range(FULL_SEQUENCE_ROWS)
    return tuple(TinyTensor(rows) for _ in range(3))


def backend(q, _k, _v):
    return TinyTensor(q.rows, width=H3_HEADS * H3_HEAD_DIM)


class H3V4ExecutorHotPathTests(unittest.TestCase):
    def test_frozen_plan_is_exact_disjoint_partition(self):
        value = context()
        frozen = plan(value)
        frozen.validate_partition(FULL_SEQUENCE_ROWS)
        self.assertEqual(len(frozen.reused_rows), 2331)
        self.assertEqual(len(frozen.computed_rows), 13093)
        self.assertEqual(len(frozen.computed_rows) + len(frozen.reused_rows), FULL_SEQUENCE_ROWS)
        self.assertFalse(set(frozen.computed_rows).intersection(frozen.reused_rows))

    def test_invalid_partition_and_future_profile_are_rejected(self):
        value = context()
        frozen = plan(value)
        with self.assertRaises(V4ExecutorContractError):
            replace(frozen, reused_rows=frozen.reused_rows[:-1]).validate_partition(FULL_SEQUENCE_ROWS)
        with self.assertRaises(V4ExecutorContractError):
            V4ExecutorAdapter(
                torch_module=object(),
                profile=V4_SELECTIVE_FUTURE,
                context=value,
                full_attention=backend,
            )

    def test_release_cache_plan_selection_is_the_only_selective_authority(self):
        value = context()
        rust_plan = {
            "decision_code": 1,
            "fallback_required": False,
            "planned_reduction_ppm": 30_074,
            "selected": [
                {
                    "block_index": 0,
                    "region": 0,
                    "planned_q_rows": 2331,
                    "payload_bytes": 48_269_312,
                }
            ],
        }
        decoded = V4ExecutorPlan.from_rust_cache_plan(
            value,
            rust_plan,
            lineage_digest="6" * 64,
            step=1,
            block=0,
        )
        self.assertEqual(len(decoded.reused_rows), 2331)
        with self.assertRaises(V4ExecutorContractError):
            V4ExecutorPlan.from_rust_cache_plan(
                value,
                {**rust_plan, "selected": []},
                lineage_digest="6" * 64,
                step=1,
                block=0,
            )

    def test_selective_branch_reconstructs_every_row_once(self):
        value = context()
        frozen = plan(value)
        prepared = gpu_plan(frozen)
        q, k, v = qkv()
        full = backend(q, k, v)
        cache = V4CacheHandle(
            context_digest=value.digest(),
            lineage_digest=frozen.lineage_digest,
            tensor=full.index_select(0, TinyIndices(REGION_ROWS)),
        )
        executor = V4ExecutorAdapter(
            torch_module=object(),
            profile=V4_EXECUTOR_BENCHMARK,
            context=value,
            full_attention=backend,
        )
        result = executor.execute(q=q, k=k, v=v, gpu_plan=prepared, cache=cache)
        self.assertEqual(result.mode, "SELECTIVE")
        self.assertEqual(result.actual_computed_rows, 13093)
        self.assertEqual(result.actual_reused_rows, 2331)
        self.assertEqual(result.actual_computed_rows + result.actual_reused_rows, FULL_SEQUENCE_ROWS)
        self.assertEqual(result.output.rows, full.rows)

    def test_lineage_mismatch_and_veto_use_only_full_branch(self):
        value = context()
        q, k, v = qkv()
        calls = []

        def counted_backend(query, key, item):
            calls.append(len(query.rows))
            return backend(query, key, item)

        executor = V4ExecutorAdapter(
            torch_module=object(),
            profile=V4_EXECUTOR_BENCHMARK,
            context=value,
            full_attention=counted_backend,
        )
        for frozen, reason in (
            (plan(value), "CACHE_LINEAGE_MISMATCH"),
            (plan(value, block=30), "CALIBRATION_VETO_BLOCK"),
        ):
            cache = V4CacheHandle(
                context_digest=value.digest(),
                lineage_digest="f" * 64,
                tensor=TinyTensor(REGION_ROWS, width=H3_HEADS * H3_HEAD_DIM),
            )
            result = executor.execute(
                q=q, k=k, v=v, gpu_plan=gpu_plan(frozen), cache=cache
            )
            self.assertEqual(result.mode, "FULL")
            self.assertEqual(result.fallback_reason, reason)
            self.assertEqual(result.actual_reused_rows, 0)
        self.assertEqual(calls, [FULL_SEQUENCE_ROWS, FULL_SEQUENCE_ROWS])

    def test_executor_consumes_plan_without_observer_decision_dependency(self):
        source = inspect.getsource(V4ExecutorAdapter)
        self.assertNotIn("Observer", source)
        self.assertNotIn("predicted_state", source)
        self.assertIn("validate_runtime_contract", source)
        self.assertIn("self.full_attention(selected_q, k, v)", source)
        self.assertIn("self.full_attention(q, k, v)", source)


if __name__ == "__main__":
    unittest.main()
