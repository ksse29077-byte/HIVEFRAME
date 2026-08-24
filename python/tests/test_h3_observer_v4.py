from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from hive_product.h3_bounded_host_source_oracle_v4 import (
    FROZEN_EVENTS,
    HOST_SOURCE_BUDGET_BYTES,
    HOST_SOURCE_RESIDENT_BYTES,
    MINIMUM_EXACT_RECORDS,
    MINIMUM_PLANNED_Q_RATIO,
    SOURCE_BLOCKS,
    SOURCE_SLOT_EMPTY,
    SOURCE_SLOT_READY,
    SOURCE_SLOT_RELEASED,
    SOURCE_SLOT_IDENTITY_FIELDS,
    SOURCE_STEPS,
    SourceSlotLifecycle,
    V4ContractError,
)
from hive_product.h3_bounded_host_source_oracle_v4_cuda import (
    gpu_compressed_fingerprint,
    gpu_exact_oracle_metrics,
    gpu_exact_oracle_metrics_indexed,
    gpu_indexed_compressed_fingerprint,
)
from hive_product.a3_g1_conditional_reuse import CONTROL_MODE
from hive_product.c0_h3_phase_probe import EventTimeline
from hive_product.h3_observer_v4 import (
    H3ObserverControllerV4,
    PROFILE_DIGEST,
    SOURCE_CAPTURE_COUNT,
    V4ObserverAbort,
)
from hive_product.h3_observer_v4_control_probe import (
    ADMISSION_BLOCKED,
    NODE_CLASS,
    NOT_VIABLE,
    VALIDATED,
    _p1_a2_profile_receipt,
    _performance_receipt,
    build_workflow,
)
from hive_product.h3_v4_lineage_diagnostic import (
    CAUSE_UNKNOWN,
    LINEAGE_FIELDS,
    build_source_components,
    build_target_components,
    compare_lineage,
    replay_frozen_event_trace,
    replay_retained_failure_prefix,
)
from hive_product.h3_v4_economics import (
    DECISION as ECONOMICS_NOT_VIABLE,
    build_precontrol_economics_gate,
)


class H3ObserverV4Tests(unittest.TestCase):
    def test_abort_uses_ordinary_runtime_exception_boundary(self) -> None:
        self.assertTrue(issubclass(V4ObserverAbort, Exception))
        self.assertFalse(issubclass(V4ObserverAbort, RuntimeError))

        timeline = EventTimeline({"10": {"class_type": NODE_CLASS}})
        timeline.prompt_id = "prompt-id"
        try:
            raise V4ObserverAbort("lineage mismatch")
        except Exception as error:
            terminal = timeline.ingest(
                {
                    "type": "execution_error",
                    "data": {
                        "prompt_id": "prompt-id",
                        "node_id": "10",
                        "node_type": NODE_CLASS,
                        "exception_type": type(error).__name__,
                    },
                },
                1.0,
            )
        self.assertTrue(terminal)
        self.assertEqual(timeline.terminal_event, "execution_error")

    def test_v4_abort_bypasses_parent_native_fallback_and_fails_closed(self) -> None:
        error = V4ObserverAbort("target processing failed")
        native_fallback_types = (IndexError, RuntimeError, TypeError, ValueError)
        self.assertNotIsInstance(error, native_fallback_types)

        parent_source = inspect.getsource(
            H3ObserverControllerV4.__mro__[1].instrumented_forward
        )
        self.assertIn(
            "except (IndexError, RuntimeError, TypeError, ValueError)", parent_source
        )
        self.assertIn("except BaseException", parent_source)

    @staticmethod
    def _lineage_components():
        scheduler = tuple(float(20 - index).hex() for index in range(20))
        source = build_source_components(
            generation_digest="1" * 64,
            profile_digest="2" * 64,
            model_digest="3" * 64,
            inventory_digest="4" * 64,
            layout_digest="5" * 64,
            scheduler_timesteps=scheduler,
            block=0,
            source_step=1,
            tensor_shape=(3367, 7168),
            tensor_dtype="torch.bfloat16",
            completion_state="EVENT_RECORDED",
            legacy_lineage_digest="6" * 64,
        )
        target = build_target_components(
            scheduler_timesteps=scheduler,
            target_step=2,
            expected_source_step=1,
            block=0,
            target_sequence=1,
        )
        return source, target

    def test_frozen_runtime_inventory_is_exact(self):
        self.assertEqual(len(FROZEN_EVENTS), MINIMUM_EXACT_RECORDS)
        self.assertEqual(MINIMUM_EXACT_RECORDS, 199)
        self.assertEqual(SOURCE_CAPTURE_COUNT, 208)
        self.assertEqual(SOURCE_CAPTURE_COUNT, len(SOURCE_BLOCKS) * len(SOURCE_STEPS))
        self.assertGreaterEqual(MINIMUM_PLANNED_Q_RATIO, 0.03)
        self.assertLessEqual(HOST_SOURCE_RESIDENT_BYTES, HOST_SOURCE_BUDGET_BYTES)

    def test_lifecycle_is_generation_scoped_and_fail_closed(self):
        controller = H3ObserverControllerV4.__new__(H3ObserverControllerV4)
        controller.state = "created"
        controller.lifecycle = ["created"]
        controller._transition("admitted")
        controller.start_observing()
        controller._transition("finalizing")
        controller._transition("complete")
        self.assertEqual(
            controller.lifecycle,
            ["created", "admitted", "observing", "finalizing", "complete"],
        )
        with self.assertRaises(V4ObserverAbort):
            controller._transition("observing")

    def test_full_model_free_event_trace_has_1000_calls_and_199_candidates(self):
        scheduler = tuple(float(20 - index).hex() for index in range(20))
        receipt = replay_frozen_event_trace(scheduler)
        self.assertTrue(receipt["passed"])
        self.assertFalse(receipt["runtime_evidence"])
        self.assertEqual(receipt["full_attention_trace_calls"], 1000)
        self.assertEqual(receipt["source_capture_count"], 208)
        self.assertEqual(receipt["frozen_candidates_encountered"], 199)
        self.assertEqual(receipt["exact_candidate_admissions"], 199)
        self.assertEqual(receipt["lineage_mismatch_count"], 0)
        self.assertEqual(receipt["source_slot_overwrite_count"], 0)
        self.assertEqual(receipt["incomplete_source_admission_count"], 0)
        self.assertEqual(receipt["target_lookup_count"], 199)
        self.assertEqual(receipt["target_consume_completed_count"], 199)
        self.assertEqual(receipt["source_release_count"], 199)
        self.assertEqual(receipt["duplicate_consume_count"], 0)
        self.assertEqual(receipt["stale_slot_admission_count"], 0)
        self.assertEqual(receipt["unread_slot_overwrite_count"], 0)
        self.assertLessEqual(receipt["peak_simultaneous_live_slots"], 13)

    def test_source_slot_lifecycle_versions_capture_consume_and_release(self) -> None:
        scheduler = tuple(float(20 - index).hex() for index in range(20))
        first = build_source_components(
            generation_digest="1" * 64,
            profile_digest="2" * 64,
            model_digest="3" * 64,
            inventory_digest="4" * 64,
            layout_digest="5" * 64,
            scheduler_timesteps=scheduler,
            block=3,
            source_step=1,
            tensor_shape=(3367, 7168),
            tensor_dtype="torch.bfloat16",
            completion_state="EVENT_RECORDED",
            legacy_lineage_digest="6" * 64,
        )
        identity = {field: first[field] for field in SOURCE_SLOT_IDENTITY_FIELDS}
        slot = SourceSlotLifecycle()
        self.assertEqual(slot.state, SOURCE_SLOT_EMPTY)
        slot.begin_capture(identity)
        slot.mark_ready()
        self.assertEqual(slot.state, SOURCE_SLOT_READY)
        self.assertEqual(slot.version, 1)
        slot.begin_consume(identity)
        slot.release()
        self.assertEqual(slot.state, SOURCE_SLOT_RELEASED)
        self.assertEqual((slot.capture_count, slot.consume_count, slot.release_count), (1, 1, 1))

    def test_retained_step1_sequence4_cannot_satisfy_step16_sequence199(self) -> None:
        scheduler = tuple(float(20 - index).hex() for index in range(20))

        def identity(source_step: int) -> dict[str, object]:
            components = build_source_components(
                generation_digest="1" * 64,
                profile_digest="2" * 64,
                model_digest="3" * 64,
                inventory_digest="4" * 64,
                layout_digest="5" * 64,
                scheduler_timesteps=scheduler,
                block=3,
                source_step=source_step,
                tensor_shape=(3367, 7168),
                tensor_dtype="torch.bfloat16",
                completion_state="EVENT_RECORDED",
                legacy_lineage_digest="6" * 64,
            )
            return {
                field: components[field] for field in SOURCE_SLOT_IDENTITY_FIELDS
            }

        slot = SourceSlotLifecycle()
        stored = identity(1)
        requested = identity(16)
        self.assertEqual(stored["source_capture_sequence"], 4)
        self.assertEqual(requested["source_capture_sequence"], 199)
        slot.begin_capture(stored)
        slot.mark_ready()
        with self.assertRaisesRegex(V4ContractError, "source_step_ordinal"):
            slot.begin_consume(requested)
        self.assertEqual(slot.state, SOURCE_SLOT_READY)
        self.assertEqual(slot.identity, stored)

    def test_retained_151_13_0_prefix_is_not_reproducible_from_frozen_order(self):
        receipt = replay_retained_failure_prefix(
            full_attention_calls=151,
            source_capture_count=13,
            exact_record_count=0,
        )
        self.assertFalse(receipt["reproduced_from_frozen_order"])
        self.assertEqual(receipt["expected_first_target_full_attention_call"], 101)
        self.assertEqual(receipt["unexplained_full_attention_call_delta"], 50)
        self.assertEqual(receipt["classification"], CAUSE_UNKNOWN)

    def test_lineage_component_receipt_identifies_each_negative_field(self):
        expected, target = self._lineage_components()
        mutations = {
            "generation_digest": "a" * 64,
            "profile_digest": "b" * 64,
            "model_digest": "c" * 64,
            "source_step_ordinal": 7,
            "source_scheduler_timestep": float(7).hex(),
            "source_block": 9,
            "source_region": 3,
            "source_capture_sequence": 99,
            "source_completion_state": "INCOMPLETE",
            "inventory_digest": "d" * 64,
            "layout_digest": "e" * 64,
        }
        for field, changed in mutations.items():
            with self.subTest(field=field):
                actual = dict(expected)
                actual[field] = changed
                receipt = compare_lineage(
                    expected=expected, actual=actual, target=target
                )
                self.assertFalse(receipt["matched"])
                self.assertEqual(receipt["first_mismatch_field"], field)
                self.assertIn(field, receipt["mismatched_fields"])
                self.assertGreater(receipt["mismatch_count"], 0)
                self.assertNotEqual(receipt["mismatch_mask"], 0)
                self.assertNotEqual(
                    receipt["expected_identity_digest"],
                    receipt["actual_identity_digest"],
                )

    def test_lineage_classification_is_derived_from_first_proven_component(self):
        expected, target = self._lineage_components()
        cases = {
            "generation_digest": "GENERATION_DIGEST_DRIFT",
            "profile_digest": "PROFILE_DIGEST_DRIFT",
            "model_digest": "MODEL_DIGEST_DRIFT",
            "inventory_digest": "INVENTORY_OR_LAYOUT_DIGEST_DRIFT",
            "layout_digest": "INVENTORY_OR_LAYOUT_DIGEST_DRIFT",
            "source_block": "BLOCK_OR_REGION_IDENTITY_MISMATCH",
            "source_region": "BLOCK_OR_REGION_IDENTITY_MISMATCH",
            "source_slot_index": "SOURCE_SLOT_REUSE_OR_OVERWRITE",
            "source_step_ordinal": "CAPTURE_TARGET_ORDERING_ERROR",
            "source_scheduler_timestep": "STEP_ORDINAL_VS_SCHEDULER_TIMESTEP",
        }
        for field, classification in cases.items():
            with self.subTest(field=field):
                actual = dict(expected)
                actual[field] = "changed"
                receipt = compare_lineage(
                    expected=expected, actual=actual, target=target
                )
                self.assertEqual(receipt["classification"], classification)

    def test_lineage_receipt_covers_every_contract_field_without_payload(self):
        expected, target = self._lineage_components()
        receipt = compare_lineage(expected=expected, actual=expected, target=target)
        self.assertTrue(receipt["matched"])
        self.assertEqual(set(receipt["matched_fields"]), set(LINEAGE_FIELDS))
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("tensor_payload", serialized)

    def test_runtime_lineage_gate_precedes_candidate_h2d_and_exact_oracle(self):
        source = inspect.getsource(H3ObserverControllerV4._observe_full_compute_control)
        lineage_gate = source.index("compare_lineage(")
        abort = source.index("raise V4ObserverAbort(", lineage_gate)
        candidate_h2d = source.index("staging.copy_(")
        exact_oracle = source.index("gpu_exact_oracle_metrics_indexed(")
        self.assertLess(lineage_gate, abort)
        self.assertLess(abort, candidate_h2d)
        self.assertLess(abort, exact_oracle)

    def test_indexed_gpu_helpers_match_packed_helpers_on_small_tensor(self):
        import torch

        generator = torch.Generator().manual_seed(101)
        current = torch.randn((12, 8), generator=generator)
        packed_indices = torch.tensor([1, 3, 4, 7, 8, 10], dtype=torch.long)
        source = current.index_select(0, packed_indices).clone()
        source[2] += 0.125
        representative = torch.tensor([0, 2, 5], dtype=torch.long)
        omitted = torch.tensor([1, 3, 4], dtype=torch.long)
        packed_current = current.index_select(0, packed_indices)

        expected_fingerprint = gpu_compressed_fingerprint(
            torch, packed_current, representative
        )
        indexed_fingerprint = gpu_indexed_compressed_fingerprint(
            torch, current, packed_indices, representative
        )
        self.assertTrue(torch.equal(expected_fingerprint, indexed_fingerprint))

        expected = gpu_exact_oracle_metrics(
            torch, source, packed_current, representative, omitted
        )
        indexed = gpu_exact_oracle_metrics_indexed(
            torch, source, current, packed_indices, representative, omitted
        )
        self.assertTrue(torch.equal(expected, indexed))

    def test_hot_path_has_no_host_read_or_forced_cuda_sync(self):
        source = "\n".join(
            inspect.getsource(function)
            for function in (
                H3ObserverControllerV4._observe_full_compute_control,
                H3ObserverControllerV4._refresh_cache,
                gpu_indexed_compressed_fingerprint,
                gpu_exact_oracle_metrics_indexed,
            )
        )
        for forbidden in (
            ".cpu(",
            ".item(",
            ".tolist(",
            ".numpy(",
            ".synchronize(",
        ):
            self.assertNotIn(forbidden, source)

    def test_controller_observes_after_exact_full_without_partial_execution(self):
        source = inspect.getsource(H3ObserverControllerV4)
        exact_position = source.index("result = super()._exact_full")
        observe_position = source.index("def _observe_full_compute_control")
        self.assertLess(exact_position, observe_position)
        self.assertIn('"selective_execution_count": 0', source)
        self.assertIn('"partial_q_execution_count": 0', source)
        self.assertIn('"attention_omission_count": 0', source)
        self.assertIn('"output_mutation_zero"', source)
        self.assertIn("self._inventory_digest", source)

    def test_comfy_node_is_isolated_and_explicit_control_only(self):
        repository = Path(__file__).resolve().parents[2]
        node_path = (
            repository
            / "python"
            / "hive_product"
            / "comfyui_v4_nodes"
            / "hiveframe_h3_observer_v4"
            / "__init__.py"
        )
        common_node_path = (
            repository
            / "python"
            / "hive_product"
            / "comfyui_nodes"
            / "hiveframe_h3_observer_v4"
            / "__init__.py"
        )
        source = node_path.read_text(encoding="utf-8")
        self.assertTrue(node_path.is_file())
        self.assertFalse(common_node_path.exists())
        self.assertIn("mode != CONTROL_MODE", source)
        self.assertIn("observer_profile_digest != PROFILE_DIGEST", source)
        self.assertNotIn("h3_row_region_safety_v2", source)
        self.assertNotIn("H3V2PinnedRingResources", source)
        self.assertEqual(len(PROFILE_DIGEST), 64)

    def test_workflow_replaces_only_standard_sampler_and_adds_first_frame(self):
        standard = {
            "8": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {}},
            "10": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {
                    "noise": ["5", 0],
                    "guider": ["9", 0],
                    "sampler": ["7", 0],
                    "sigmas": ["6", 0],
                    "latent_image": ["8", 1],
                },
            },
        }
        workflow = build_workflow(
            standard, run_digest="a" * 64, first_frame_name="frame.png"
        )
        self.assertEqual(workflow["10"]["class_type"], NODE_CLASS)
        self.assertEqual(workflow["10"]["inputs"]["mode"], CONTROL_MODE)
        self.assertEqual(
            workflow["10"]["inputs"]["observer_profile_digest"], PROFILE_DIGEST
        )
        self.assertEqual(workflow["8"]["inputs"]["first_frame"], ["16", 0])
        self.assertEqual(standard["10"]["class_type"], "SamplerCustomAdvanced")

    def test_p1_a2_profile_accepts_frame_count_alias_only(self):
        profile = {
            "width": 864,
            "height": 480,
            "frame_count": 124,
            "fps": 24,
            "steps": 20,
            "seed": 101,
            "sampler": "res_multistep",
            "scheduler": "simple",
            "sage_enabled": False,
        }
        receipt = {
            "status": "succeeded",
            "backend": "minimax_h3_comfyui_local",
            "model_contract": "MiniMax-H3",
            "workflow_sha256": (
                "31ab33fdb053a7834cc866bd7aa08b887518fc656e4a796c89779c6b5e1786e6"
            ),
            "metrics": {"retry_count": 0},
            "reference_sha256": "a" * 64,
            "nested": {"profile": profile},
        }
        repository = Path(__file__).resolve().parents[2]
        temporary_root = repository / ".test-tmp"
        temporary_root.mkdir(exist_ok=True)
        path = temporary_root / "observer-v4-p1-a2-receipt.json"
        try:
            path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertTrue(_p1_a2_profile_receipt(path)["passed"])
        finally:
            path.unlink(missing_ok=True)

    def test_performance_decision_excludes_control_only_exact_oracle(self):
        callback = {
            "attention_execution": {
                "v4_oracle": {
                    "timing_ms": {
                        "full_attention": 100_000.0,
                        "observer": 3_500.0,
                        "exact_gpu_oracle": 3_000.0,
                        "source_d2h": 500.0,
                        "candidate_h2d": 400.0,
                    }
                }
            }
        }
        performance = _performance_receipt(
            callback=callback, sampler_seconds=490.0, submit_seconds=590.0
        )
        self.assertEqual(performance["projected_production_observer_cost_ms"], 1_000.0)
        self.assertGreater(performance["projected_production_net_ms"], 0.0)

    def test_precontrol_economics_separates_costs_and_blocks_unknown_runtime(self):
        gate = build_precontrol_economics_gate()
        classes = {item["cost_id"]: item["classification"] for item in gate["costs"]}
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["decision"], ECONOMICS_NOT_VIABLE)
        self.assertEqual(
            gate["measurement_comparability"]["direct_comparison"],
            "NOT_COMPARABLE",
        )
        self.assertEqual(classes["source_capture_d2h"], "CONTROL_ONLY")
        self.assertEqual(classes["candidate_source_h2d"], "CONTROL_ONLY")
        self.assertEqual(
            classes["compound_eye_scalar_d2h"], "SELECTIVE_RUNTIME_REQUIRED"
        )
        self.assertEqual(
            classes["rust_live_plan_compile"], "SELECTIVE_RUNTIME_REQUIRED"
        )
        self.assertEqual(classes["rust_deterministic_replay"], "CONTROL_ONLY")
        self.assertEqual(classes["artifact_serialization"], "CONTROL_ONLY")
        self.assertEqual(classes["confusion_matrix_calculation"], "CONTROL_ONLY")
        self.assertGreater(len(gate["unknown_selective_runtime_costs"]), 0)
        self.assertIsNone(gate["predicted_net_saving_seconds"])
        self.assertGreater(gate["avoided_q_compute_upper_bound_seconds"], 0.0)

        optimistic = build_precontrol_economics_gate(
            {name: 0.0 for name in gate["unknown_selective_runtime_costs"]}
        )
        self.assertTrue(optimistic["passed"])
        self.assertGreaterEqual(optimistic["predicted_net_saving_ratio"], 0.01)

    def test_runner_source_enforces_single_submission_and_terminal_decisions(self):
        import hive_product.h3_observer_v4_control_probe as runner

        source = inspect.getsource(runner.run_control)
        self.assertEqual(source.count('receipt["submission_count"] = 1'), 1)
        self.assertEqual(source.count("_collect_websocket_run("), 1)
        self.assertNotIn("lineage_diagnostic", source)
        self.assertIn("custom_nodes_root=repository", source)
        self.assertIn("comfyui_v4_nodes", source)
        self.assertIn("_shutdown_owned_runtime(", source)
        self.assertIn('if callback_path.is_file()', source)
        self.assertIn('root / "private-receipt.json"', source)
        self.assertIn("build_precontrol_economics_gate", source)
        self.assertIn("production_economics_viable", source)
        self.assertEqual(VALIDATED, "H3_V4_OBSERVER_RUNTIME_AND_FORMAL_CONTROL_VALIDATED")
        self.assertEqual(NOT_VIABLE, "H3_COMPOUND_EYE_PATH_NOT_YET_PRODUCT_VIABLE")
        self.assertEqual(ADMISSION_BLOCKED, "H3_V4_FORMAL_CONTROL_ADMISSION_BLOCKED")


if __name__ == "__main__":
    unittest.main()
