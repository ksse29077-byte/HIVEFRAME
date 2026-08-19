import json
import importlib.util
import unittest

from hive_product.rust_cache_plan_v2 import (
    CACHE_PLAN_ABI_V2,
    CANDIDATE_FIELDS,
    FULL_COMPUTE,
    PLAN_READY,
    GenerationIdentity,
    RustCachePlanV2Bridge,
    cache_lineage_v2_digest,
    stable_digest,
)


ROWS = (3_367, 3_108, 2_886, 2_664)
OMITTED = (2_331, 2_072, 1_850, 1_628)
PAYLOAD = (48_269_312, 44_556_288, 41_373_696, 38_191_104)
FULL_Q_ROWS = 15_424_000


def identity(generation_id=101):
    return GenerationIdentity(
        run_digest=stable_digest("run"),
        workflow_digest=stable_digest("workflow"),
        model_digest=stable_digest("h3"),
        model_revision_digest=stable_digest("h3-revision"),
        settings_digest=stable_digest("settings"),
        source_plan_digest=stable_digest("pr101-plan"),
        layout_digest=stable_digest("h3-layout"),
        input_identity_digest=stable_digest("non-identifying-input"),
        generation_id=generation_id,
        scheduler_id=1,
        total_steps=20,
        width=864,
        height=480,
        frame_count=124,
        fps_numerator=24,
        fps_denominator=1,
    ).as_dict()


def candidate(identity_value, block, region, source_step=1, **changes):
    value = {
        "target_step": source_step + 1,
        "source_step": source_step,
        "block_index": block,
        "region": region,
        "packed_row_start": region * 3_500,
        "packed_row_count": ROWS[region],
        "state": 1,
        "actual_safety_state": 1,
        "safety_evidence_present": 1,
        "uncertainty_ppm": 10_000,
        "motion_ppm": 20_000,
        "cosine_ppm": 990_000,
        "corrected_nl2_ppm": 100_000,
        "false_safe_count": 0,
        "nonfinite_count": 0,
        "cache_age": 1,
        "source_kind": 1,
        "shape_rows": ROWS[region],
        "shape_width": 7_168,
        "dtype": 1,
        "device_class": 1,
        "precision": 1,
        "quantization": 1,
        "admission_eligible": 1,
        "rejection_reason": 0,
        "planned_q_rows": OMITTED[region],
        "full_q_rows": 100_000,
        "payload_bytes": PAYLOAD[region],
        "effect_numerator": OMITTED[region],
        "effect_denominator": PAYLOAD[region],
        "planned_d2h_bytes": PAYLOAD[region],
        "planned_h2d_bytes": OMITTED[region] * 7_168 * 2,
        "shape_digest": stable_digest(f"shape-{region}"),
        "packed_row_digest": stable_digest(f"rows-{region}"),
        "lineage_digest": bytes(32),
    }
    value.update(changes)
    value["lineage_digest"] = cache_lineage_v2_digest(identity_value, value)
    assert frozenset(value) == CANDIDATE_FIELDS
    return value


def records_for(identity_value, blocks, regions=(0,), event_count=7):
    return [
        candidate(identity_value, block, region, source_step=source_step)
        for block in blocks
        for region in regions
        for source_step in range(event_count)
    ]


class CachePlanV2FakeExtension:
    def __init__(self, raises=False):
        self.raises = raises
        self.calls = 0

    def cache_plan_v2_contract(self):
        return {
            "abi_version": 2,
            "request_struct_size": 56,
            "identity_struct_size": 304,
            "profile_struct_size": 112,
            "batch_header_struct_size": 56,
            "candidate_struct_size": 248,
            "inventory_struct_size": 72,
            "maximum_records": 4096,
            "maximum_batch_bytes": 4 * 1024 * 1024,
            "balanced_12gb": {
                "maximum_candidates": 4096,
                "maximum_batch_bytes": 2 * 1024 * 1024,
            },
        }

    def compile_cache_plan_v2(self, request, identity_value, profile, header, candidates, inventory):
        self.calls += 1
        if self.raises:
            raise RuntimeError("boundary failure")
        fallback = bool(header["overflowed"])
        return {
            "ffi_status": 0,
            "abi_version": 2,
            "decision_code": FULL_COMPUTE if fallback else PLAN_READY,
            "reason_code": 5 if fallback else 0,
            "fallback_required": fallback,
            "selected": [],
            "rejected": [],
            "eviction_order": [],
            "total_selected_bytes": 0,
            "total_planned_q_rows": 0,
            "total_full_q_rows": request["total_full_q_rows"],
            "planned_reduction_ppm": 0,
            "total_planned_d2h_bytes": 0,
            "total_planned_h2d_bytes": 0,
            "plan_digest": stable_digest("plan"),
            "lineage_digest": stable_digest("lineage"),
            "performance_receipt": {
                "ffi_total_time_ns": {"value": 1, "status": "MEASURED"}
            },
        }


class H3RustRegionSparseCachePlanV2Tests(unittest.TestCase):
    def test_model_free_bridge_is_one_generation_call_and_tensor_free(self):
        extension = CachePlanV2FakeExtension()
        bridge = RustCachePlanV2Bridge(extension)
        identity_value = identity()
        records = records_for(identity_value, (0,), event_count=1)
        first = bridge.compile_generation(
            identity=identity_value,
            candidates=records,
            total_full_q_rows=FULL_Q_ROWS,
        )
        second = bridge.compile_generation(
            identity=identity_value,
            candidates=records,
            total_full_q_rows=FULL_Q_ROWS,
        )
        self.assertEqual(extension.calls, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["bridge_contract"]["existing_a1_step_policy_calls"], 18)
        for field in ("calls_per_block", "calls_per_region", "calls_per_row", "tensor_bytes_per_call"):
            self.assertEqual(first["bridge_contract"][field], 0)

    def test_overflow_is_not_truncated_into_safe_evidence(self):
        extension = CachePlanV2FakeExtension()
        extension.cache_plan_v2_contract = lambda: {
            **CachePlanV2FakeExtension().cache_plan_v2_contract(),
            "maximum_records": 1,
            "balanced_12gb": {"maximum_candidates": 1, "maximum_batch_bytes": 4096},
        }
        bridge = RustCachePlanV2Bridge(extension)
        identity_value = identity()
        result = bridge.compile_generation(
            identity=identity_value,
            candidates=records_for(identity_value, (0, 1), event_count=1),
            total_full_q_rows=FULL_Q_ROWS,
        )
        self.assertEqual(result["decision_code"], FULL_COMPUTE)
        self.assertTrue(result["fallback_required"])

    def test_exception_and_tensor_like_field_fail_open(self):
        identity_value = identity()
        result = RustCachePlanV2Bridge(CachePlanV2FakeExtension(raises=True)).compile_generation(
            identity=identity_value,
            candidates=records_for(identity_value, (0,), event_count=1),
            total_full_q_rows=FULL_Q_ROWS,
        )
        self.assertEqual(result["decision_code"], FULL_COMPUTE)
        malformed = records_for(identity_value, (0,), event_count=1)
        malformed[0]["q_tensor"] = object()
        rejected = RustCachePlanV2Bridge(CachePlanV2FakeExtension()).compile_generation(
            identity=identity_value,
            candidates=malformed,
            total_full_q_rows=FULL_Q_ROWS,
        )
        self.assertEqual(rejected["decision_code"], FULL_COMPUTE)

    def test_unknown_is_distinct_from_structural_zero_and_receipt_serializes(self):
        bridge = RustCachePlanV2Bridge(extension=None)
        bridge.extension = None
        bridge.contract = None
        result = bridge.compile_generation(
            identity=identity(), candidates=[], total_full_q_rows=FULL_Q_ROWS
        )
        receipt = result["performance_receipt"]
        self.assertEqual(receipt["rust_transfer_bytes"], {"value": 0, "status": "STRUCTURAL_ZERO"})
        self.assertEqual(receipt["rust_plan_time_ns"], {"value": None, "status": "UNKNOWN"})
        json.dumps(receipt)

    def test_cache_lineage_changes_for_every_identity_dimension(self):
        identity_value = identity()
        base = candidate(identity_value, 0, 0)
        base_digest = base["lineage_digest"]
        for field in (
            "run_digest",
            "workflow_digest",
            "model_digest",
            "model_revision_digest",
            "settings_digest",
            "source_plan_digest",
            "layout_digest",
            "input_identity_digest",
            "scheduler_id",
            "total_steps",
            "width",
            "height",
            "frame_count",
            "fps_numerator",
            "fps_denominator",
        ):
            changed = dict(identity_value)
            changed[field] = stable_digest(f"changed-{field}") if field.endswith("digest") else changed[field] + 1
            self.assertNotEqual(cache_lineage_v2_digest(changed, base), base_digest, field)

    @unittest.skipUnless(importlib.util.find_spec("_hive_retina_boundary"), "PyO3 extension not built")
    def test_real_pyo3_round_trip_and_pr101_frozen_fixture(self):
        import _hive_retina_boundary as boundary

        identity_value = identity()
        frozen = records_for(identity_value, (0, 4, 10, 11, 12, 13), regions=(0, 1, 2), event_count=1)
        event_counts = {0: 7, 1: 3, 2: 2}
        frozen = [
            candidate(identity_value, block, region, source_step=step)
            for block in (0, 4, 10, 11, 12, 13)
            for region, count in event_counts.items()
            for step in range(count)
        ]
        result = RustCachePlanV2Bridge(boundary).compile_generation(
            identity=identity_value,
            candidates=frozen,
            total_full_q_rows=FULL_Q_ROWS,
        )
        self.assertEqual(result["abi_version"], CACHE_PLAN_ABI_V2)
        self.assertEqual(result["decision_code"], FULL_COMPUTE)
        self.assertEqual(result["reason_code"], 9)
        self.assertEqual(result["total_planned_q_rows"], 157_398)
        self.assertEqual(result["planned_reduction_ppm"], 10_204)
        receipt = result["performance_receipt"]
        self.assertEqual(receipt["rust_process_spawn_count"]["value"], 0)
        self.assertEqual(receipt["calls_per_generation"]["value"], 1)
        self.assertEqual(receipt["calls_per_block"]["value"], 0)
        self.assertEqual(receipt["gpu_to_cpu_tensor_bytes"]["status"], "NOT_EXECUTED")

    @unittest.skipUnless(importlib.util.find_spec("_hive_retina_boundary"), "PyO3 extension not built")
    def test_real_pyo3_three_percent_fixture_is_plan_ready(self):
        import _hive_retina_boundary as boundary

        identity_value = identity(102)
        records = records_for(identity_value, tuple(range(29)), event_count=7)
        result = RustCachePlanV2Bridge(boundary).compile_generation(
            identity=identity_value,
            candidates=records,
            total_full_q_rows=FULL_Q_ROWS,
            profile_name="quality_24gb_plus",
        )
        self.assertEqual(result["decision_code"], PLAN_READY)
        self.assertGreaterEqual(result["planned_reduction_ppm"], 30_000)
        self.assertLessEqual(
            result["total_selected_bytes"],
            dict(boundary.cache_plan_v2_contract())["quality_24gb_plus"]["host_cache_budget_bytes"],
        )

    @unittest.skipUnless(importlib.util.find_spec("_hive_retina_boundary"), "PyO3 extension not built")
    def test_real_pyo3_panic_is_contained_as_full_compute(self):
        import _hive_retina_boundary as boundary

        result = dict(boundary.cache_plan_v2_panic_boundary_probe())
        self.assertEqual(result["decision_code"], FULL_COMPUTE)
        self.assertEqual(result["reason_code"], 10)
        self.assertTrue(result["fallback_required"])


if __name__ == "__main__":
    unittest.main()
