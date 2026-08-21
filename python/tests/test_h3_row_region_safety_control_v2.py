from __future__ import annotations

import inspect
import unittest

import torch

from hive_product.h3_hybrid_cache_staging import (
    CONTROL_ORACLE_D2H_BYTES,
    HOST_SOURCE_CACHE_BYTES,
    PINNED_HOST_TOTAL_BYTES,
)
from hive_product.h3_row_region_safety import FULL_Q_ROWS, generation_candidates, generation_identity
from hive_product.h3_row_region_safety_control_v2_probe import (
    ADMISSION_BLOCKED,
    FAILED,
    NODE_CLASS,
    READY,
    _cardinality_receipt,
    build_workflow,
)
from hive_product.h3_row_region_safety_v2 import (
    CANDIDATE_BLOCKS,
    D2HEventFinalizer,
    EXPECTED_ENQUEUE_COUNT,
    EXPECTED_RECORD_COUNT,
    HOLDOUT_LABEL,
    H3RowRegionSafetyControllerV2,
    HybridControlOracleWorker,
    OMITTED_POSITIONS,
    PinnedSlot,
    REPRESENTATIVE_POSITIONS,
    SLOT_SHAPE,
    VETO_BLOCKS,
    _chunked_metrics,
    _evidence_integrity_checks,
    evidence_design_receipt,
    settings_digest,
)


class FakeCompletionEvent:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.query_count = 0
        self.elapsed_time_count = 0

    def query(self):
        self.query_count += 1
        return self.ready

    def elapsed_time(self, _other):
        self.elapsed_time_count += 1
        raise AssertionError("completion event must never be used for timing")


class FakeTimingStart:
    def __init__(self, value: float | None = 0.25) -> None:
        self.value = value
        self.calls = 0

    def elapsed_time(self, _end):
        self.calls += 1
        if self.value is None:
            raise ValueError("injected timing failure")
        return self.value


class H3RowRegionSafetyControlV2Tests(unittest.TestCase):
    def test_formal_control_cardinality_contract_is_exact(self):
        writes = [
            {"step": step, "block": block}
            for step in range(20)
            for block in range(30)
        ]
        records = [
            {"step": step, "block": block, "region": 0}
            for step in range(2, 18)
            for block in range(30)
        ]
        receipt = _cardinality_receipt(writes, records)
        self.assertTrue(receipt["passed"])
        records.pop()
        self.assertFalse(_cardinality_receipt(writes, records)["passed"])

    def test_balanced_holdout_shape_and_budgets_are_exact(self):
        design = evidence_design_receipt()
        self.assertEqual(CANDIDATE_BLOCKS, tuple(range(30)))
        self.assertEqual(VETO_BLOCKS, frozenset({30, 31, 48, 49}))
        self.assertEqual(EXPECTED_ENQUEUE_COUNT, 600)
        self.assertEqual(EXPECTED_RECORD_COUNT, 480)
        self.assertEqual(design["label"], HOLDOUT_LABEL)
        self.assertEqual(design["expected_d2h_bytes"], CONTROL_ORACLE_D2H_BYTES)
        self.assertEqual(design["source_cache_bytes"], HOST_SOURCE_CACHE_BYTES)
        self.assertEqual(design["pinned_ring_bytes"], PINNED_HOST_TOTAL_BYTES)
        self.assertEqual(design["h2d_bytes"], 0)
        self.assertEqual(SLOT_SHAPE, (3367, 7168))

    def test_hot_path_has_no_host_read_or_forced_sync(self):
        source = inspect.getsource(HybridControlOracleWorker.enqueue)
        for forbidden in (".cpu(", ".numpy(", ".item(", ".tolist(", ".synchronize("):
            self.assertNotIn(forbidden, source)
        self.assertIn("non_blocking=True", source)
        self.assertIn("wait_event", source)

    def test_completion_and_timing_events_have_separate_roles(self):
        enqueue = inspect.getsource(HybridControlOracleWorker.enqueue)
        consume = inspect.getsource(HybridControlOracleWorker._consume)
        finalizer = inspect.getsource(D2HEventFinalizer.try_finalize)
        self.assertIn("completion_event", enqueue)
        self.assertIn("timing_start_event", enqueue)
        self.assertIn("timing_end_event", enqueue)
        self.assertNotIn(".synchronize(", consume)
        self.assertIn("completion_event.query()", finalizer)
        self.assertIn("timing_start_event.elapsed_time(slot.timing_end_event)", finalizer)
        self.assertNotIn("completion_event.elapsed_time", finalizer)

    def test_incomplete_completion_blocks_record_admission(self):
        completion = FakeCompletionEvent(ready=False)
        timing = FakeTimingStart()
        slot = PinnedSlot(
            payload=object(),
            completion_event=completion,
            timing_start_event=timing,
            timing_end_event=object(),
            state="D2H_IN_FLIGHT",
            metadata={"source_identity": "pending"},
        )
        result = D2HEventFinalizer().try_finalize(slot)
        self.assertFalse(result["admitted"])
        self.assertEqual(result["completion"], "PENDING")
        self.assertEqual(timing.calls, 0)
        self.assertEqual(completion.elapsed_time_count, 0)

    def test_timing_failure_is_unknown_without_discarding_completion(self):
        completion = FakeCompletionEvent(ready=True)
        timing = FakeTimingStart(value=None)
        slot = PinnedSlot(
            payload=object(),
            completion_event=completion,
            timing_start_event=timing,
            timing_end_event=object(),
            state="D2H_IN_FLIGHT",
            metadata={"source_identity": "complete"},
        )
        finalizer = D2HEventFinalizer()
        result = finalizer.try_finalize(slot)
        self.assertTrue(result["admitted"])
        self.assertEqual(result["timing"]["status"], "UNKNOWN")
        self.assertIsNone(result["timing"]["value"])
        receipt = finalizer.receipt()
        self.assertEqual(receipt["timing_status"], "UNKNOWN")
        self.assertFalse(receipt["host_wall_time_substituted_for_cuda_time"])
        self.assertEqual(completion.elapsed_time_count, 0)

    def test_timing_uses_only_enabled_start_end_contract(self):
        completion = FakeCompletionEvent(ready=True)
        timing = FakeTimingStart(value=0.5)
        slot = PinnedSlot(
            payload=object(),
            completion_event=completion,
            timing_start_event=timing,
            timing_end_event=object(),
            state="D2H_IN_FLIGHT",
            metadata={"source_identity": "complete"},
        )
        result = D2HEventFinalizer().try_finalize(slot)
        self.assertTrue(result["admitted"])
        self.assertEqual(slot.state, "CPU_READY")
        self.assertEqual(result["timing"]["status"], "MEASURED_CUDA_EVENT")
        self.assertEqual(result["timing"]["value"], 0.5)
        self.assertEqual(timing.calls, 1)
        self.assertEqual(completion.elapsed_time_count, 0)

    def test_event_and_slot_cleanup_clears_finalization_state(self):
        slot = PinnedSlot(
            payload=object(),
            completion_event=object(),
            timing_start_event=object(),
            timing_end_event=object(),
            state="FINALIZED",
            metadata={"source_identity": "complete"},
        )
        finalizer = D2HEventFinalizer()
        finalizer.cleanup_slot(slot)
        self.assertEqual(slot.state, "FREE")
        self.assertIsNone(slot.metadata)
        self.assertIsNone(slot.completion_event)
        self.assertIsNone(slot.timing_start_event)
        self.assertIsNone(slot.timing_end_event)
        self.assertEqual(finalizer.receipt()["cleaned_event_count"], 3)

    def test_incomplete_drop_and_overwrite_fail_integrity(self):
        sequence = [{"ordinal": 1}]
        valid = {
            "enqueue_count": 1,
            "record_count": 1,
            "incomplete_record_count": 0,
            "ring_backpressure_count": 0,
            "ring_overflow_count": 0,
            "ring_overwrite_count": 0,
            "evidence_drop_count": 0,
            "duplicate_d2h_count": 0,
            "lineage_mismatch_count": 0,
            "d2h_bytes": 64,
            "h2d_bytes": 0,
            "ring_write_sequence": sequence,
            "ring_read_sequence": sequence,
            "event_and_slot_cleanup_pass": True,
            "hot_path_forced_sync_count": 0,
        }
        self.assertTrue(
            all(
                _evidence_integrity_checks(
                    valid,
                    expected_enqueue_count=1,
                    expected_record_count=1,
                    expected_d2h_bytes=64,
                ).values()
            )
        )
        for field in (
            "incomplete_record_count",
            "evidence_drop_count",
            "ring_overwrite_count",
        ):
            corrupted = dict(valid)
            corrupted[field] = 1
            checks = _evidence_integrity_checks(
                corrupted,
                expected_enqueue_count=1,
                expected_record_count=1,
                expected_d2h_bytes=64,
            )
            self.assertFalse(all(checks.values()), field)

    def test_controller_is_full_compute_observer_only(self):
        refresh = inspect.getsource(H3RowRegionSafetyControllerV2._refresh_cache)
        observe = inspect.getsource(H3RowRegionSafetyControllerV2._observe_full_compute_control)
        for source in (refresh, observe):
            self.assertNotIn("attention_core(", source)
            self.assertNotIn("_prepare_direct_reuse", source)

    def test_cpu_metric_uses_real_representative_and_omitted_rows(self):
        self.assertEqual(len(REPRESENTATIVE_POSITIONS), 1036)
        self.assertEqual(len(OMITTED_POSITIONS), 2331)
        source = torch.zeros((3367, 8), dtype=torch.bfloat16)
        current = source.clone()
        current[list(REPRESENTATIVE_POSITIONS)] = 0.5
        current[list(OMITTED_POSITIONS)] = 0.5
        metrics = _chunked_metrics(torch, source, current)
        self.assertAlmostEqual(metrics["corrected"]["cosine"], 1.0, places=6)
        self.assertAlmostEqual(metrics["corrected"]["normalized_l2"], 0.0, places=6)
        self.assertTrue(metrics["corrected"]["finite"])

    def test_workflow_remains_standard_i2v_full_compute(self):
        standard = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
            "10": {"class_type": "SamplerCustomAdvanced", "inputs": {}},
        }
        workflow = build_workflow(
            standard, run_digest="55" * 32, first_frame_name="reference.png"
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(workflow["10"]["inputs"]["settings_digest"], settings_digest())
        self.assertEqual(workflow["8"]["inputs"]["first_frame"], ["16", 0])

    def test_decisions_and_full_q_baseline_are_frozen(self):
        self.assertEqual(READY, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_READY_FOR_EXECUTOR_INTEGRATION")
        self.assertEqual(FAILED, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_FAILED")
        self.assertEqual(ADMISSION_BLOCKED, "H3_ROW_REGION_SAFETY_EVIDENCE_CONTROL_V2_ADMISSION_BLOCKED")
        self.assertEqual(FULL_Q_ROWS, 15_424_000)

    def test_v2_record_maps_to_complete_tensor_free_rust_candidate(self):
        identity = generation_identity(
            run_digest_hex="11" * 32,
            workflow_digest_hex="22" * 32,
            model_digest_hex="33" * 32,
            settings_digest_hex=settings_digest(),
            input_identity_digest_hex="44" * 32,
        )
        evidence = {
            "step": 2,
            "source_step": 1,
            "block": 0,
            "region": 0,
            "predicted_state": "STABLE",
            "uncertainty_ppm": 1000,
            "motion_ppm": 2000,
            "payload_bytes": 48_269_312,
            "corrected": {"cosine": 0.999, "normalized_l2": 0.01, "finite": True},
            "actual_safety": "SAFE",
            "false_safe": False,
            "false_unsafe": False,
        }
        candidate = generation_candidates(identity, [evidence])[0]
        self.assertEqual(candidate["admission_eligible"], 1)
        self.assertEqual(candidate["planned_q_rows"], 2331)
        self.assertEqual(len(candidate["lineage_digest"]), 32)
        self.assertTrue(all(not isinstance(value, torch.Tensor) for value in candidate.values()))


if __name__ == "__main__":
    unittest.main()
