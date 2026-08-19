import math
import unittest

import torch

from hive_product.a3_g1_cache_density import (
    CACHE_HARD_CAP_BYTES,
    FrozenBlockEvidence,
    REGION_INTERIOR_ROWS,
    REGION_OMITTED_ROWS,
    RegionCacheAdmissionDirectory,
    RegionCacheRecord,
    admit_by_effect_per_byte,
    build_safe_region_candidates,
    cache_byte_ledger,
    full_block_payload_bytes,
    region_payload_bytes,
    replay_frozen_control,
    validate_cache_access,
)
from hive_product.a3_g1_conditional_reuse import attention_path_is_xor
from hive_product.a3_g1_conditional_reuse import reconstruct_selected_core
from hive_product.attention_output_reuse import make_cache_lineage
from hive_product.regional_query_prototype_attention import CPU_PROTOTYPE_PLANS


FROZEN_BLOCKS = (
    FrozenBlockEvidence(0, 12, 0, 0, True),
    FrozenBlockEvidence(48, 12, 1, 0, False),
    FrozenBlockEvidence(16, 12, 0, 0, False),
    FrozenBlockEvidence(10, 12, 0, 0, True),
    FrozenBlockEvidence(4, 12, 0, 0, True),
    FrozenBlockEvidence(11, 12, 0, 0, True),
    FrozenBlockEvidence(17, 12, 0, 0, False),
    FrozenBlockEvidence(13, 12, 0, 0, True),
    FrozenBlockEvidence(49, 12, 1, 0, False),
    FrozenBlockEvidence(15, 12, 0, 0, False),
    FrozenBlockEvidence(12, 12, 0, 0, True),
    FrozenBlockEvidence(14, 12, 0, 0, False),
)
STABLE_REGION_EVENTS = {0: 7, 1: 3, 2: 2, 3: 0}


class H3CacheDensityRemediationTests(unittest.TestCase):
    def test_byte_ledger_matches_frozen_control(self):
        self.assertEqual(region_payload_bytes(0), 48_269_312)
        self.assertEqual(region_payload_bytes(1), 44_556_288)
        self.assertEqual(region_payload_bytes(2), 41_373_696)
        self.assertEqual(region_payload_bytes(3), 38_191_104)
        self.assertEqual(full_block_payload_bytes(), 172_390_400)
        self.assertEqual(cache_byte_ledger(12)["total_tensor_payload"], 2_068_684_800)
        self.assertEqual(cache_byte_ledger(18)["total_tensor_payload"], 3_103_027_200)
        self.assertTrue(all(cache_byte_ledger(12)[name] == 0 for name in (
            "q", "k", "v", "residual", "ff_output", "metadata_tensor",
            "lineage_tensor", "mask_index_tensor",
        )))
        self.assertIsNone(cache_byte_ledger(12)["python_metadata_overhead"])
        self.assertIsNone(cache_byte_ledger(12)["cuda_event_overhead"])
        self.assertIsNone(cache_byte_ledger(12)["pinned_allocator_overhead"])

    def test_two_gib_hard_cap_cannot_be_raised(self):
        candidates, _ = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        with self.assertRaises(ValueError):
            admit_by_effect_per_byte(
                candidates=candidates,
                hard_cap_bytes=CACHE_HARD_CAP_BYTES + 1,
            )

    def test_admission_excludes_false_safe_and_quality_failed_blocks(self):
        candidates, rejected = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        self.assertEqual({item.block_index for item in candidates}, {0, 4, 10, 11, 12, 13})
        self.assertEqual(set(rejected), {14, 15, 16, 17, 48, 49})
        self.assertNotIn(3, {item.region for item in candidates})

    def test_effect_per_byte_admission_is_deterministic_and_under_cap(self):
        candidates, _ = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        first = admit_by_effect_per_byte(candidates=candidates)
        second = admit_by_effect_per_byte(candidates=reversed(candidates))
        self.assertEqual(first, second)
        self.assertEqual(first.payload_bytes, 805_195_776)
        self.assertLessEqual(first.payload_bytes, CACHE_HARD_CAP_BYTES)
        self.assertEqual(first.planned_omitted_q_rows, 157_398)
        self.assertEqual(first.false_safe_count, 0)

    def test_eviction_removes_lowest_effect_per_byte_and_honors_cap(self):
        candidates, _ = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        by_region = {item.region: item for item in candidates if item.block_index == 0}
        directory = RegionCacheAdmissionDirectory(
            hard_cap_bytes=by_region[0].payload_bytes + by_region[1].payload_bytes,
        )
        lineage = make_cache_lineage(
            block_index=0,
            source_step=4,
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        )
        self.assertIsNotNone(lineage)
        directory.admit(RegionCacheRecord(by_region[0], lineage))
        directory.admit(RegionCacheRecord(by_region[1], lineage))
        evicted = directory.admit(RegionCacheRecord(by_region[2], lineage))
        self.assertEqual(evicted, ((0, 2),))
        self.assertLessEqual(directory.payload_bytes, directory.hard_cap_bytes)
        self.assertEqual(directory.keys, ((0, 0), (0, 1)))

    def test_interrupted_execution_cleanup_clears_directory(self):
        candidates, _ = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        item = candidates[0]
        lineage = make_cache_lineage(
            block_index=item.block_index,
            source_step=4,
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        )
        self.assertIsNotNone(lineage)
        directory = RegionCacheAdmissionDirectory()
        directory.admit(RegionCacheRecord(item, lineage))
        self.assertGreater(directory.payload_bytes, 0)
        directory.clear()
        self.assertEqual(directory.payload_bytes, 0)
        self.assertEqual(directory.keys, ())

    def test_shape_dtype_and_device_contract(self):
        candidates, _ = build_safe_region_candidates(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        for item in candidates:
            self.assertEqual(item.shape, (REGION_INTERIOR_ROWS[item.region], 7_168))
            self.assertEqual(item.dtype, "bfloat16")
            self.assertEqual(item.device, "cpu:pinned")

    def test_lineage_age_and_region_validation(self):
        lineage = make_cache_lineage(
            block_index=0,
            source_step=4,
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        )
        hit = validate_cache_access(
            lineage=lineage,
            block_index=0,
            region=0,
            target_step=5,
            shape=(REGION_INTERIOR_ROWS[0], 7_168),
            dtype="bfloat16",
            device="cpu:pinned",
        )
        self.assertEqual(hit.action, "REGIONAL_SELECTIVE")
        stale = validate_cache_access(
            lineage=lineage,
            block_index=0,
            region=0,
            target_step=6,
            shape=(REGION_INTERIOR_ROWS[0], 7_168),
            dtype="bfloat16",
            device="cpu:pinned",
        )
        self.assertEqual(stale.action, "FULL_COMPUTE")

    def test_every_invalid_cache_state_falls_back_exactly(self):
        lineage = make_cache_lineage(
            block_index=0,
            source_step=4,
            source_kind="ACTUAL_FULL_ATTENTION_CORE_OUTPUT",
        )
        base = dict(
            lineage=lineage,
            block_index=0,
            region=0,
            target_step=5,
            shape=(REGION_INTERIOR_ROWS[0], 7_168),
            dtype="bfloat16",
            device="cpu:pinned",
        )
        mutations = (
            {"lineage": None},
            {"block_index": 1},
            {"scene_cut": True},
            {"interrupted": True},
            {"cache_error": True},
            {"finite": False},
            {"shape": (1, 7_168)},
            {"dtype": "float8_e4m3fn"},
            {"device": "cuda:0"},
        )
        for mutation in mutations:
            args = {**base, **mutation}
            with self.subTest(mutation=mutation):
                self.assertEqual(validate_cache_access(**args).action, "FULL_COMPUTE")

    def test_partial_full_execution_remains_xor(self):
        self.assertTrue(attention_path_is_xor(full_calls=1, partial_calls=0))
        self.assertTrue(attention_path_is_xor(full_calls=0, partial_calls=1))
        self.assertFalse(attention_path_is_xor(full_calls=1, partial_calls=1))

    def test_row_mapping_reconstructs_only_frozen_omitted_rows(self):
        for region in range(4):
            plan = CPU_PROTOTYPE_PLANS[1 << region]
            rows = plan.region_rows[region]
            self.assertEqual(len(rows["omitted"]), REGION_OMITTED_ROWS[region])
            self.assertEqual(
                len(rows["representative"]) + len(rows["omitted"]),
                REGION_INTERIOR_ROWS[region],
            )
            self.assertFalse(set(rows["representative"]) & set(rows["omitted"]))

    def test_selected_and_cached_rows_reconstruct_full_core_shape(self):
        selected_indices = torch.tensor([0, 2, 4], dtype=torch.long)
        selected = torch.tensor([[1.0], [2.0], [3.0]], dtype=torch.bfloat16)
        full = reconstruct_selected_core(selected, selected_indices, 5)
        omitted_indices = torch.tensor([1, 3], dtype=torch.long)
        cached = torch.tensor([[10.0], [20.0]], dtype=torch.bfloat16)
        full.index_copy_(0, omitted_indices, cached)
        self.assertEqual(tuple(full.shape), (5, 1))
        self.assertEqual(full.flatten().float().tolist(), [1.0, 10.0, 2.0, 20.0, 3.0])

    def test_nan_and_inf_evidence_cannot_be_admitted(self):
        bad = (FrozenBlockEvidence(0, 12, 0, 1, True),)
        candidates, rejected = build_safe_region_candidates(
            blocks=bad,
            stable_region_event_counts=STABLE_REGION_EVENTS,
        )
        self.assertEqual(candidates, ())
        self.assertEqual(rejected, (0,))

    def test_frozen_control_replay_fails_closed_below_three_percent(self):
        replay = replay_frozen_control(
            blocks=FROZEN_BLOCKS,
            stable_region_event_counts=STABLE_REGION_EVENTS,
            raw_false_safe_cases_replayable=False,
        )
        self.assertEqual(replay.admission.false_safe_count, 0)
        self.assertTrue(replay.byte_ledger_pass)
        self.assertTrue(replay.lineage_validation_pass)
        self.assertTrue(replay.partial_full_xor_pass)
        self.assertTrue(replay.exact_fallback_pass)
        self.assertFalse(replay.raw_false_safe_cases_replayable)
        self.assertTrue(math.isclose(float(replay.admission.planned_q_reduction), 0.010204745850622407))
        self.assertLess(float(replay.admission.planned_q_reduction), 0.03)
        self.assertFalse(replay.ready_for_real_gpu_proof)
        self.assertEqual(replay.decision, "H3_COMPOUND_EYE_CACHE_DENSITY_REMEDIATION_FAILED")


if __name__ == "__main__":
    unittest.main()
