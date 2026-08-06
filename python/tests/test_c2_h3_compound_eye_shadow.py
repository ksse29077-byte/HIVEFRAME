from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import inspect
import unittest

from hive_product.compound_eye_shadow import (
    ASYNC_RING_SIZE,
    ESCALATE_FULL_COMPUTE,
    EYE_ACTIVE,
    EYE_STABLE,
    EYE_UNCERTAIN,
    FULL_COMPUTE,
    H3_AUDIO_SHAPE,
    H3_CALLBACK_VIDEO_DTYPE,
    H3_SIGNAL_ADAPTER,
    H3_VIDEO_SHAPE,
    PREDICTION_HORIZON_STEPS,
    QUANTIZATION_SCALE,
    SKETCH_VALUE_COUNT,
    AsyncCompoundEyeShadowPipeline,
    CompoundEyeShadowBridge,
    ShadowContext,
    ShadowSignalNotAdmitted,
    SketchResult,
    TorchAsyncSketchBackend,
    admit_h3_x0_video,
    wrap_async_shadow_callback,
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


class FakeDevice:
    def __init__(self, device_type: str, index: int = 0) -> None:
        self.type = device_type
        self.index = index

    def __eq__(self, other) -> bool:
        return isinstance(other, FakeDevice) and (self.type, self.index) == (other.type, other.index)


class FakeTensor:
    def __init__(
        self,
        shape: tuple[int, ...],
        *,
        dtype: str = H3_CALLBACK_VIDEO_DTYPE,
        device: FakeDevice | None = None,
    ) -> None:
        self.shape = shape
        self.ndim = len(shape)
        self.dtype = dtype
        self.device = device or FakeDevice("cuda")


class FakeTorch:
    Tensor = FakeTensor


class FakePinned:
    def is_pinned(self) -> bool:
        return True


class FakeEvent:
    def __init__(self, ready_sequence: list[bool] | None = None) -> None:
        self.ready_sequence = list(ready_sequence or [True])

    def query(self) -> bool:
        if len(self.ready_sequence) > 1:
            return self.ready_sequence.pop(0)
        return self.ready_sequence[0]


class FakeAsyncBackend:
    def __init__(self, readiness: list[list[bool]] | None = None) -> None:
        self.readiness = list(readiness or [])
        self.allocated: list[FakePinned] = []
        self.enqueue_calls = 0
        self.non_blocking_copy_requests = 0
        self.release_calls = 0

    def allocate_pinned(self) -> FakePinned:
        value = FakePinned()
        self.allocated.append(value)
        return value

    def admit(self, x0):
        return admit_h3_x0_video(x0, FakeTorch)

    def enqueue(self, slot, signal) -> int:
        sequence = self.readiness.pop(0) if self.readiness else [True]
        slot.completion_event = FakeEvent(sequence)
        slot.start_event = object()
        slot.device_sketch = object()
        self.enqueue_calls += 1
        self.non_blocking_copy_requests += 1
        return 1_000

    @staticmethod
    def ready(slot) -> bool:
        return slot.completion_event.query()

    @staticmethod
    def cuda_elapsed_ns(slot) -> int:
        return 50_000

    @staticmethod
    def host_values(slot) -> tuple[float, ...]:
        value = 1.0 + float(slot.observed_step or 0) / 100.0
        return (value,) * SKETCH_VALUE_COUNT

    def release(self, slot) -> None:
        slot.device_sketch = None
        slot.start_event = None
        slot.completion_event = None
        self.release_calls += 1


def h3_nested(video, audio):
    nested_type = type("NestedTensor", (), {})
    nested_type.__module__ = "comfy.nested_tensor"
    x0 = nested_type()
    x0.is_nested = True
    x0.tensors = [video, audio]
    return x0


def valid_x0(*, video_dtype=H3_CALLBACK_VIDEO_DTYPE, audio_dtype=H3_CALLBACK_VIDEO_DTYPE, device="cuda"):
    return h3_nested(
        FakeTensor(H3_VIDEO_SHAPE, dtype=video_dtype, device=FakeDevice(device)),
        FakeTensor(H3_AUDIO_SHAPE, dtype=audio_dtype, device=FakeDevice(device)),
    )


def sketch(value: int = 4096, step: int = 0) -> SketchResult:
    return SketchResult(
        values_q=(value,) * SKETCH_VALUE_COUNT,
        source_shape=H3_VIDEO_SHAPE,
        source_dtype=H3_CALLBACK_VIDEO_DTYPE,
        source_device_type="cuda",
        reduction_enqueue_ns=10,
        gpu_to_host_ns=20,
        host_quantization_ns=30,
        signal_adapter=H3_SIGNAL_ADAPTER,
        container_type="comfy.nested_tensor.NestedTensor",
        container_tensor_count=2,
        cuda_sketch_ns=20,
        sketch_observed_step=step,
        sketch_consumed_callback=step + 1,
        ready_lag_callbacks=1,
    )


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

    def pipeline(self, extension=None, backend=None) -> AsyncCompoundEyeShadowPipeline:
        return AsyncCompoundEyeShadowPipeline(
            self.bridge(extension or FakeC2Extension()), backend=backend or FakeAsyncBackend()
        )

    def test_exact_fp32_nested_contract_is_admitted_before_cuda_or_rust(self) -> None:
        admitted = admit_h3_x0_video(valid_x0(), FakeTorch)
        self.assertEqual(admitted.source_shape, H3_VIDEO_SHAPE)
        self.assertEqual(admitted.source_dtype, H3_CALLBACK_VIDEO_DTYPE)
        self.assertEqual(admitted.source_device_type, "cuda")
        self.assertEqual(admitted.signal_adapter, H3_SIGNAL_ADAPTER)

    def test_bf16_fp16_cpu_and_dtype_mismatch_are_rejected(self) -> None:
        cases = (
            valid_x0(video_dtype="torch.bfloat16"),
            valid_x0(video_dtype="torch.float16"),
            valid_x0(device="cpu"),
            valid_x0(audio_dtype="torch.float16"),
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ShadowSignalNotAdmitted):
                    admit_h3_x0_video(value, FakeTorch)

    def test_changed_container_length_shape_and_device_contracts_are_rejected(self) -> None:
        value = valid_x0()
        value.tensors = value.tensors[:1]
        with self.assertRaises(ShadowSignalNotAdmitted):
            admit_h3_x0_video(value, FakeTorch)
        value = valid_x0()
        value.tensors[0].shape = (1, 24, 36, 30, 54)
        with self.assertRaises(ShadowSignalNotAdmitted):
            admit_h3_x0_video(value, FakeTorch)
        value = valid_x0()
        value.tensors[1].device = FakeDevice("cuda", 1)
        with self.assertRaises(ShadowSignalNotAdmitted):
            admit_h3_x0_video(value, FakeTorch)

    def test_rejected_dtype_enqueues_nothing_and_calls_no_rust(self) -> None:
        backend = FakeAsyncBackend()
        extension = FakeC2Extension()
        pipeline = self.pipeline(extension, backend)
        pipeline.observe_callback(0, valid_x0(), 20)
        pipeline.observe_callback(1, valid_x0(video_dtype="torch.bfloat16"), 20)
        self.assertEqual(pipeline.sketch_enqueue_count, 1)
        self.assertEqual(pipeline.bridge.rust_call_count, 0)
        self.assertEqual(pipeline.dtype_rejection_count, 1)
        self.assertEqual(pipeline.rejected_dtype_rust_call_count, 0)

    def test_fixed_ring_is_pinned_nonblocking_and_consumes_in_order(self) -> None:
        backend = FakeAsyncBackend()
        extension = FakeC2Extension()
        pipeline = self.pipeline(extension, backend)
        self.assertEqual(len(pipeline.slots), ASYNC_RING_SIZE)
        self.assertTrue(all(slot.host_buffer.is_pinned() for slot in pipeline.slots))
        self.assertFalse(any(hasattr(slot, "source") for slot in pipeline.slots))
        with self.assertRaises(ValueError):
            AsyncCompoundEyeShadowPipeline(self.bridge(FakeC2Extension()), backend=backend, ring_size=4)
        for step in range(3):
            pipeline.observe_callback(step, valid_x0(), 20)
        pipeline.drain(timeout_seconds=0.1)
        self.assertEqual(backend.non_blocking_copy_requests, 3)
        self.assertEqual(pipeline.sketch_enqueue_count, 3)
        self.assertEqual(pipeline.sketch_consume_count, 3)
        self.assertEqual([event["sketch_observed_step"] for event in pipeline.bridge.events], [0, 1, 2])
        self.assertLessEqual(pipeline.bridge.rust_call_count, pipeline.callback_count + 1)
        self.assertEqual(pipeline.callback_synchronization_count, 0)
        self.assertEqual(pipeline.ring_overflow_count, 0)

    def test_event_not_ready_and_ring_overflow_fail_open_without_wait(self) -> None:
        backend = FakeAsyncBackend(readiness=[[False], [False], [False]])
        pipeline = self.pipeline(backend=backend)
        for step in range(4):
            pipeline.observe_callback(step, valid_x0(), 20)
        self.assertEqual(pipeline.sketch_enqueue_count, 3)
        self.assertEqual(pipeline.sketch_consume_count, 0)
        self.assertEqual(pipeline.ring_overflow_count, 1)
        self.assertGreaterEqual(pipeline.event_not_ready_count, 1)
        self.assertEqual(pipeline.bridge.rust_call_count, 0)
        self.assertEqual({event["actual_execution"] for event in pipeline.callback_events}, {"FULL_COMPUTE"})

    def test_slot_reuse_and_one_rust_call_per_callback(self) -> None:
        pipeline = self.pipeline()
        for step in range(6):
            before = pipeline.bridge.rust_call_count
            pipeline.observe_callback(step, valid_x0(), 20)
            self.assertLessEqual(pipeline.bridge.rust_call_count - before, 1)
        self.assertEqual(pipeline.sketch_enqueue_count, 6)
        self.assertEqual(pipeline.sketch_consume_count, 5)
        self.assertGreaterEqual(pipeline.backend.release_calls, 5)

    def test_bounded_drain_and_timeout_fail_open(self) -> None:
        backend = FakeAsyncBackend(readiness=[[False], [False], [False]])
        pipeline = self.pipeline(backend=backend)
        for step in range(3):
            pipeline.observe_callback(step, valid_x0(), 20)
        pipeline.drain(timeout_seconds=0)
        self.assertEqual(pipeline.drain_timeout_count, 3)
        self.assertEqual(pipeline.sketch_consume_count, 0)
        self.assertTrue(all(slot.state == "FREE" for slot in pipeline.slots))

    def test_callback_arguments_are_unchanged_and_full_compute_is_preserved(self) -> None:
        pipeline = self.pipeline()
        delegated: list[tuple] = []
        marker_x, marker_x0 = object(), valid_x0()
        callback = wrap_async_shadow_callback(lambda *args: delegated.append(args), pipeline)
        callback(3, marker_x0, marker_x, 20)
        self.assertEqual(delegated, [(3, marker_x0, marker_x, 20)])
        self.assertEqual(pipeline.callback_events[0]["actual_execution"], "FULL_COMPUTE")

    def test_callback_surface_contains_no_blocking_gpu_host_operations(self) -> None:
        source = inspect.getsource(AsyncCompoundEyeShadowPipeline.observe_callback)
        source += inspect.getsource(AsyncCompoundEyeShadowPipeline._query_and_consume_one)
        source += inspect.getsource(AsyncCompoundEyeShadowPipeline._consume)
        source += inspect.getsource(AsyncCompoundEyeShadowPipeline._consume_ready)
        source += inspect.getsource(wrap_async_shadow_callback)
        source += inspect.getsource(TorchAsyncSketchBackend.enqueue)
        source += inspect.getsource(TorchAsyncSketchBackend.host_values)
        for banned in (
            ".cpu(", ".numpy(", ".tolist(", ".item(", ".synchronize(",
            ".result(", ".join(", "sleep(",
        ):
            self.assertNotIn(banned, source)
        self.assertIn("non_blocking=True", inspect.getsource(TorchAsyncSketchBackend.enqueue))

    def test_lagged_two_step_candidate_is_validated_by_future_full_compute(self) -> None:
        extension = FakeC2Extension(
            [
                {"eye_state": [EYE_UNCERTAIN] * 5},
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_STABLE, EYE_ACTIVE, EYE_UNCERTAIN]},
                {"eye_state": [EYE_UNCERTAIN] * 5},
                {"eye_change_ppm": [0, 10000, 10000, 40000, 40000]},
            ]
        )
        bridge = self.bridge(extension)
        for step in range(4):
            bridge.evaluate(step, 20, sketch(step=step), consumed_callback=step + 1)
        event = bridge.events[-1]
        self.assertEqual(event["validation_of_lagged_prediction"]["validated"], 2)
        self.assertEqual(event["validation_of_lagged_prediction"]["prediction_sources"], [1])
        self.assertEqual(bridge.validated_stable_count, 2)
        self.assertEqual(bridge.contradicted_stable_count, 0)
        self.assertEqual(bridge.eligible_lagged_eye_steps, 16)
        self.assertEqual(event["prediction_horizon_steps"], PREDICTION_HORIZON_STEPS)

    def test_lagged_contradiction_missing_sketch_and_last_step_exclusion(self) -> None:
        extension = FakeC2Extension(
            [
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_UNCERTAIN, EYE_UNCERTAIN, EYE_UNCERTAIN]},
                {"eye_state": [EYE_UNCERTAIN] * 5},
                {"eye_change_ppm": [0, 50000, 0, 0, 0]},
                {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_STABLE, EYE_STABLE, EYE_STABLE]},
            ]
        )
        bridge = self.bridge(extension)
        bridge.evaluate(0, 4, sketch(step=0), consumed_callback=1)
        bridge.evaluate(1, 4, sketch(step=1), consumed_callback=2)
        bridge.evaluate(2, 4, sketch(step=2), consumed_callback=3)
        last = bridge.evaluate(3, 4, sketch(step=3), consumed_callback=4)
        self.assertEqual(bridge.contradicted_stable_count, 1)
        self.assertEqual(last["stable_regional_eyes"], [])

        missing = self.bridge(FakeC2Extension([
            {"eye_state": [EYE_UNCERTAIN] * 5},
            {"eye_state": [EYE_UNCERTAIN, EYE_STABLE, EYE_UNCERTAIN, EYE_UNCERTAIN, EYE_UNCERTAIN]},
        ]))
        missing.evaluate(0, 20, sketch(step=0), consumed_callback=1)
        missing.evaluate(1, 20, sketch(step=1), consumed_callback=2)
        missing.record_missing_observation(3, "missing_sketch")
        self.assertEqual(missing.not_validated_stable_count, 1)

    def test_receipt_records_async_boundary_and_no_selective_compute(self) -> None:
        pipeline = self.pipeline()
        pipeline.observe_callback(0, valid_x0(), 20)
        pipeline.observe_callback(1, valid_x0(), 20)
        pipeline.drain(timeout_seconds=0.1)
        receipt = pipeline.receipt()
        self.assertEqual(receipt["schema_version"], "c2.compound-eye-shadow.2")
        self.assertEqual(receipt["strict_signal_contract"]["video_dtype"], H3_CALLBACK_VIDEO_DTYPE)
        self.assertEqual(receipt["async_pipeline"]["ring_size"], 3)
        self.assertEqual(receipt["callback_synchronization_count"], 0)
        self.assertEqual(receipt["raw_tensor_bytes_to_rust"], 0)
        self.assertEqual(receipt["full_tensor_host_copy_bytes"], 0)
        for key in (
            "skipped_step_count", "skipped_block_count", "skipped_token_count",
            "skipped_latent_count", "reused_cache_count", "partial_compute_count",
            "region_skip_count",
        ):
            self.assertEqual(receipt[key], 0)

    def test_gate_and_adapter_share_fp32_contract_and_gate_is_final(self) -> None:
        events = [
            {
                "source_shape": list(H3_VIDEO_SHAPE),
                "source_dtype": H3_CALLBACK_VIDEO_DTYPE,
                "source_device_type": "cuda",
                "signal_adapter": H3_SIGNAL_ADAPTER,
            }
        ] * 20
        policy = {
            "callback_count": 20,
            "rust_call_count": 20,
            "full_compute_count": 20,
            "rust_full_compute_directive_count": 20,
            "escalate_full_compute_count": 0,
            "fallback_count": 0,
            "topology": "overlap_2x2",
            "eye_count": 5,
            "events": events,
            "strict_signal_contract": {
                "container_type": "comfy.nested_tensor.NestedTensor",
                "tensor_count": 2,
                "video_path": "x0.tensors[0]",
                "audio_path": "x0.tensors[1]",
                "video_shape": list(H3_VIDEO_SHAPE),
                "audio_shape": list(H3_AUDIO_SHAPE),
                "video_dtype": H3_CALLBACK_VIDEO_DTYPE,
                "audio_dtype": H3_CALLBACK_VIDEO_DTYPE,
                "device_type": "cuda",
                "axis_contract": "B,C,T,H,W",
                "admission_before_cuda_or_rust": True,
            },
            "async_pipeline": {
                "ring_size": 3,
                "pinned_buffer_count": 3,
                "sketch_enqueue_count": 20,
                "sketch_consume_count": 20,
                "non_blocking_copy_count": 20,
                "ring_overflow_count": 0,
                "callback_synchronization_count": 0,
                "signal_rejection_count": 0,
                "processing_failure_count": 0,
                "structural_admission_count": 20,
                "dtype_admission_count": 20,
                "dtype_rejection_count": 0,
                "rejected_dtype_rust_call_count": 0,
                "next_callback_verifiable_count": 19,
                "next_callback_event_ready_count": 19,
                "next_callback_event_ready_rate": 1.0,
                "deadline_miss_count": 0,
                "drain_timeout_count": 0,
            },
            "skipped_step_count": 0,
            "skipped_block_count": 0,
            "skipped_token_count": 0,
            "skipped_latent_count": 0,
            "reused_cache_count": 0,
            "partial_compute_count": 0,
            "tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "max_host_transfers_per_callback": 1,
            "sketch": {"value_count": 48},
            "lagged_stable_candidate_count": 2,
            "lagged_validated_stable_count": 2,
            "lagged_contradicted_stable_count": 0,
            "callback_shadow_cpu": {"p95_ns": 1_000_000},
            "cuda_async_sketch": {"p95_ns": 10_000_000},
            "boundary_roundtrip": {"p95_ns": 100_000},
            "cumulative_callback_shadow_cpu_ns": 20_000_000,
            "persistent_host_state_estimate_bytes": 576,
            "persistent_rust_state_bytes": 0,
            "persistent_gpu_state_bytes": 0,
            "max_in_flight_gpu_bytes": 576,
        }
        gate = _shadow_gate(policy, 600.0)
        self.assertEqual(gate["decision"], "C2_COMPOUND_EYE_SHADOW_READY")
        self.assertEqual(select_c3_hook(policy, gate)["selection"], "h3.transformer_block_wrapper")
        policy["async_pipeline"]["ring_overflow_count"] = 1
        failed = _shadow_gate(policy, 600.0)
        self.assertEqual(failed["decision"], "C2_SHADOW_FALLBACK_ONLY")
        self.assertEqual(select_c3_hook(policy, failed)["selection"], "no_c3_admission")
        probe_source = (ROOT / "python" / "hive_product" / "c2_h3_shadow_probe.py").read_text(encoding="utf-8")
        self.assertNotIn('event.get("source_dtype") == "torch.bfloat16"', probe_source)

    def test_workflow_and_c1_full_compute_paths_are_unchanged(self) -> None:
        standard = {
            "9": {"class_type": "BasicGuider", "inputs": {"value": 1}},
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["5", 0], "guider": ["9", 0], "sampler": ["7", 0],
                    "sigmas": ["6", 0], "latent_image": ["8", 1],
                },
            },
            "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0]}},
        }
        c2 = build_c2_workflow(standard, **DIGESTS)
        self.assertEqual(c2["10"]["class_type"], C2_NODE_CLASS)
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertFalse(any("sage" in node["class_type"].lower() for node in c2.values()))
        self.assertEqual(c2_settings_digest(), c2_settings_digest())
        c1_source = (ROOT / "python" / "hive_product" / "rust_step_policy.py").read_text(encoding="utf-8")
        c1_node = (
            ROOT / "python" / "hive_product" / "comfyui_nodes" / "hiveframe_c1_policy" / "__init__.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class RustStepPolicyBridge", c1_source)
        self.assertIn("class HIVEFRAMERustPolicySampler", c1_node)
        self.assertNotIn("CompoundEyeShadow", c1_source)
        self.assertNotIn("CompoundEyeShadow", c1_node)

    def test_actual_pyo3_c2_contract_roundtrip_when_extension_is_available(self) -> None:
        try:
            import _hive_retina_boundary as boundary
        except (ImportError, OSError):
            self.skipTest("built PyO3 extension unavailable")
        contract = dict(boundary.compound_eye_shadow_contract())
        self.assertEqual(contract["abi_version"], 1)
        self.assertEqual(contract["eye_count"], 5)
        self.assertEqual(contract["sketch_value_count"], 48)
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
                quantization_scale=QUANTIZATION_SCALE,
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
