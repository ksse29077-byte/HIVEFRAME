from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import json
import unittest

import torch

from hive_product.h3_background_oracle_lineage import (
    CAPSULE_MAX_BYTES,
    LineageDiagnosticAbort,
    LineageDiagnosticCapsuleWriteError,
    LineageDiagnosticContext,
    LineageDiagnosticError,
    LineageDiagnosticRecorder,
    replay_ring_backpressure_capsule,
    scheduler_timestep_trace,
    validate_diagnostic_pair,
    validate_diagnostic_trace,
)
from hive_product.h3_row_region_safety_v2 import ControlV2EvidenceError


TEST_TEMP_ROOT = Path(__file__).resolve().parents[2] / ".test-tmp"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def TemporaryDirectory():
    path = TEST_TEMP_ROOT / f"case-{uuid4().hex}"
    path.mkdir()
    try:
        yield str(path)
    finally:
        for child in path.iterdir():
            child.unlink()
        path.rmdir()


def context(root: Path, timesteps: tuple[str, ...] | None = None):
    return LineageDiagnosticContext.create(
        run_digest="11" * 32,
        workflow_digest="22" * 32,
        model_digest="33" * 32,
        settings_digest="44" * 32,
        scheduler_timesteps=timesteps or tuple(float(20 - i).hex() for i in range(20)),
        capsule_path=root / "capsule.json",
    )


def metadata(ordinal: int, block: int = 0, region: int = 0):
    return {
        "block": block,
        "step": ordinal,
        "current_step_raw": ordinal,
        "current_denoise_ordinal": ordinal,
        "current_scheduler_timestep": float(20 - ordinal).hex(),
        "model_forward_ordinal": ordinal,
        "attention_call_ordinal": ordinal * 50 + block,
        "block_id": block,
        "region_id": region,
        "current_shape_dtype_device": "shape=(4, 8)|dtype=torch.bfloat16|device=cuda",
        "oracle_lineage_digest": f"oracle-{block}",
        "source_identity": f"source-{ordinal}-{block}-{region}",
        "lineage_base": "lineage",
    }


def enriched(recorder: LineageDiagnosticRecorder, ordinal: int, block: int = 0):
    return recorder.enrich_enqueue(
        metadata(ordinal, block),
        enqueue_sequence=ordinal * 2 + block + 1,
        ring_slot_id=ordinal % 2,
        ring_slot_generation=ordinal // 2 + 1,
        ring_write_sequence=ordinal * 2 + block + 1,
    )


class H3BackgroundOracleLineageTests(unittest.TestCase):
    def test_integrity_errors_bypass_runtime_error_full_compute_fallback(self):
        self.assertTrue(issubclass(ControlV2EvidenceError, Exception))
        self.assertFalse(issubclass(ControlV2EvidenceError, RuntimeError))
        self.assertTrue(issubclass(LineageDiagnosticAbort, Exception))

    def test_actual_h3_ring_backpressure_trace_replays_fail_closed(self):
        fixture = Path(__file__).parent / "fixtures" / "h3_oracle_ring_backpressure_trace.json"
        capsule = json.loads(fixture.read_text(encoding="utf-8"))
        first = replay_ring_backpressure_capsule(capsule)
        second = replay_ring_backpressure_capsule(capsule)
        self.assertEqual(first, second)
        self.assertEqual(first["cause"], "DUPLICATE_OR_MISSING_RECORD")
        self.assertEqual(first["occupied_slot_count"], 2)
        self.assertEqual(first["pending_sequences"], [31, 32])
        self.assertTrue(first["source_age_one_at_failure"])
        self.assertFalse(first["native_full_fallback_allowed"])
        self.assertFalse(first["missing_record_created"])
        self.assertTrue(first["later_false_age_mismatch_prevented"])

    def test_decreasing_raw_scheduler_timestep_is_preserved(self):
        values = torch.tensor([20.0 - i for i in range(21)])
        trace = scheduler_timestep_trace(values)
        self.assertEqual(len(trace), 20)
        self.assertEqual(trace[0], float(20).hex())
        self.assertEqual(trace[-1], float(1).hex())

    def test_noncontiguous_scheduler_timestep_is_not_normalized(self):
        values = [1000.0, 731.5, 100.25, 0.5] + [0.25 / (i + 1) for i in range(17)]
        trace = scheduler_timestep_trace(values)
        self.assertEqual(trace[1], float(731.5).hex())
        self.assertNotEqual(float.fromhex(trace[0]) - float.fromhex(trace[1]), 1.0)

    def test_cuda_scheduler_tensor_is_rejected_before_capture(self):
        class FakeSigmas:
            device = type("Device", (), {"type": "cuda"})()

        with self.assertRaises(LineageDiagnosticError):
            scheduler_timestep_trace(FakeSigmas())

    def test_forced_mismatch_writes_atomic_capsule_with_actual_values(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            source = enriched(recorder, 1)
            current = enriched(recorder, 3)
            recorder.capture_failure(
                rejection_reason="SOURCE_DENOISE_ORDINAL_NOT_AGE_ONE",
                source=source,
                current=current,
            )
            capsule = json.loads((Path(temp) / "capsule.json").read_text())
            self.assertEqual(capsule["mismatch"]["source_denoise_ordinal"], 1)
            self.assertEqual(capsule["mismatch"]["current_denoise_ordinal"], 3)
            self.assertFalse((Path(temp) / "capsule.json.partial").exists())
            self.assertLessEqual((Path(temp) / "capsule.json").stat().st_size, CAPSULE_MAX_BYTES)

    def test_failure_signal_blocks_new_enqueue(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            recorder.capture_failure(
                rejection_reason="INJECTED", source=None, current=enriched(recorder, 0)
            )
            with self.assertRaises(LineageDiagnosticAbort):
                enriched(recorder, 1)

    def test_capsule_write_failure_is_explicit_and_fail_closed(self):
        def fail(_path, _content):
            raise OSError("injected")

        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)), writer=fail)
            with self.assertRaises(LineageDiagnosticCapsuleWriteError):
                recorder.capture_failure(
                    rejection_reason="INJECTED", source=None, current=enriched(recorder, 0)
                )
            self.assertTrue(recorder.failed)
            self.assertEqual(
                recorder.capsule_write_failure_reason,
                "CAPSULE_ATOMIC_WRITE_FAILED:OSError",
            )

    def test_mismatch_history_is_bounded_to_sixteen(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            previous = None
            for ordinal in range(20):
                current = enriched(recorder, ordinal)
                recorder.mark_completion(current)
                recorder.mark_finalizer(current, ring_read_sequence=ordinal + 1)
                recorder.record_valid_pair(source=previous, current=current)
                previous = current
            recorder.capture_failure(
                rejection_reason="INJECTED", source=previous, current=enriched(recorder, 19, 1)
            )
            capsule = json.loads((Path(temp) / "capsule.json").read_text())
            self.assertEqual(len(capsule["normal_records_before_mismatch"]), 16)
            self.assertEqual(capsule["normal_record_count_before_mismatch"], 20)

    def test_post_mismatch_completed_records_are_bounded_to_four(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            post = [enriched(recorder, index, index % 2) for index in range(6)]
            recorder.capture_failure(
                rejection_reason="INJECTED",
                source=None,
                current=enriched(recorder, 0),
                completed_after_mismatch=post,
            )
            capsule = json.loads((Path(temp) / "capsule.json").read_text())
            self.assertEqual(len(capsule["completed_records_after_mismatch"]), 4)

    def test_completion_and_finalizer_sequences_are_independent(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            first = enriched(recorder, 0)
            second = enriched(recorder, 1)
            recorder.mark_completion(second)
            recorder.mark_completion(first)
            recorder.mark_finalizer(first, ring_read_sequence=1)
            recorder.mark_finalizer(second, ring_read_sequence=2)
            self.assertEqual(second["oracle_completion_sequence"], 1)
            self.assertEqual(first["oracle_completion_sequence"], 2)
            self.assertEqual(first["finalizer_sequence"], 1)
            self.assertEqual(second["finalizer_sequence"], 2)

    def test_first_denoise_without_source_is_full_compute(self):
        with TemporaryDirectory() as temp:
            current = enriched(LineageDiagnosticRecorder(context(Path(temp))), 0)
            self.assertEqual(
                validate_diagnostic_pair(None, current),
                ("FULL_COMPUTE", "FIRST_DENOISE_HAS_NO_SOURCE"),
            )

    def test_missing_noninitial_source_is_rejected(self):
        with TemporaryDirectory() as temp:
            current = enriched(LineageDiagnosticRecorder(context(Path(temp))), 1)
            self.assertEqual(validate_diagnostic_pair(None, current)[0], "REJECT")

    def test_age_two_source_falls_back_to_full_compute(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            self.assertEqual(
                validate_diagnostic_pair(enriched(recorder, 1), enriched(recorder, 3)),
                ("FULL_COMPUTE", "CACHE_AGE_NOT_ONE"),
            )

    def test_future_source_is_rejected(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            self.assertEqual(
                validate_diagnostic_pair(enriched(recorder, 3), enriched(recorder, 2))[0],
                "REJECT",
            )

    def test_cross_generation_scheduler_workflow_model_and_settings_fail(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            for field in (
                "generation_id_digest",
                "workflow_digest",
                "model_digest",
                "scheduler_digest",
                "settings_digest",
            ):
                source = enriched(recorder, 1)
                current = enriched(recorder, 2)
                source[field] = "different"
                self.assertEqual(validate_diagnostic_pair(source, current)[0], "REJECT", field)

    def test_block_region_mismatch_is_rejected(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            source = enriched(recorder, 1)
            current = enriched(recorder, 2, 1)
            self.assertEqual(validate_diagnostic_pair(source, current)[0], "REJECT")

    def test_stale_ring_generation_is_rejected(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            source = enriched(recorder, 1)
            source["ring_slot_generation"] = 0
            self.assertEqual(
                validate_diagnostic_pair(source, enriched(recorder, 2))[1],
                "STALE_RING_SLOT_GENERATION",
            )

    def test_duplicate_record_and_enqueue_sequence_are_rejected(self):
        with TemporaryDirectory() as temp:
            recorder = LineageDiagnosticRecorder(context(Path(temp)))
            item = enriched(recorder, 1)
            with self.assertRaises(LineageDiagnosticError):
                validate_diagnostic_trace([item, dict(item)])

    def test_complete_trace_digest_is_deterministic(self):
        with TemporaryDirectory() as first_temp, TemporaryDirectory() as second_temp:
            contents = []
            for temp in (first_temp, second_temp):
                recorder = LineageDiagnosticRecorder(context(Path(temp)))
                prior = None
                for ordinal in range(3):
                    current = enriched(recorder, ordinal)
                    recorder.mark_completion(current)
                    recorder.mark_finalizer(current, ring_read_sequence=ordinal + 1)
                    recorder.record_valid_pair(source=prior, current=current)
                    prior = current
                recorder.write_complete_trace()
                contents.append((Path(temp) / "capsule.json").read_bytes())
            self.assertEqual(contents[0], contents[1])


if __name__ == "__main__":
    unittest.main()
