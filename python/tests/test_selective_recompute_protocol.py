from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from hive_probes.compound_eye_v0 import make_synthetic_sequence, run_reference_simulation
from hive_visual_state.contracts import build_compute_plan, validate_compute_plan


class SelectiveRecomputeCounterexampleTests(unittest.TestCase):
    """Counterexamples that separate observation evidence from skip authority."""

    def setUp(self) -> None:
        sequence = make_synthetic_sequence(seed=101)
        self.state = run_reference_simulation(sequence, seed=101)[
            "shared_visual_state"
        ]

    def test_human_or_observed_movement_cannot_issue_backend_compute_authority(self) -> None:
        plan = build_compute_plan(self.state)
        dirty_units = [
            unit for unit in plan["execution_units"] if unit["observed_state"] == "dirty"
        ]
        self.assertTrue(dirty_units)
        for unit in dirty_units:
            self.assertEqual(
                unit["decision"],
                "candidate_active_requires_backend_admission",
            )
            self.assertEqual(unit["selectors"]["authority"], "none_observation_only")

    def test_pixel_stability_cannot_issue_backend_skip_authority(self) -> None:
        plan = build_compute_plan(self.state)
        stable_units = [
            unit for unit in plan["execution_units"] if unit["observed_state"] == "stable"
        ]
        self.assertTrue(stable_units)
        for unit in stable_units:
            self.assertEqual(
                unit["decision"],
                "candidate_frozen_requires_safe_reuse_evidence",
            )
            self.assertEqual(unit["selectors"]["authority"], "none_observation_only")

    def test_unsupported_backend_selector_cannot_schedule_skip(self) -> None:
        plan = build_compute_plan(self.state)
        stable = next(
            unit for unit in plan["execution_units"] if unit["observed_state"] == "stable"
        )
        stable["decision"] = "reuse_cache"
        stable["backend_capability"] = {
            "selector": "cache_reuse",
            "support_status": "unsupported",
        }
        with self.assertRaisesRegex(ValueError, "unsupported|authority|admission"):
            validate_compute_plan(plan)

    def test_scene_cut_cannot_preserve_prior_freeze_or_cache(self) -> None:
        plan = build_compute_plan(self.state)
        plan["global_invalidation"] = {
            "active": True,
            "reason": "scene_cut",
        }
        stable = next(
            unit for unit in plan["execution_units"] if unit["observed_state"] == "stable"
        )
        stable["decision"] = "reuse_cache"
        with self.assertRaisesRegex(ValueError, "global invalidation|scene cut"):
            validate_compute_plan(plan)

    def test_uncertain_region_requires_full_compute_fallback(self) -> None:
        plan = build_compute_plan(self.state)
        uncertain = next(
            unit
            for unit in plan["execution_units"]
            if unit["observed_state"] == "uncertain"
        )
        self.assertEqual(uncertain["decision"], "full_compute_fallback")
        self.assertEqual(uncertain["selectors"]["authority"], "full_compute_only")

    def test_receipt_cannot_omit_total_cost_components(self) -> None:
        from hive_visual_state.selective_protocol import validate_selective_compute_receipt

        incomplete = {
            "schema_version": "0.1.0",
            "receipt_id": "counterexample",
            "costs": {"active_compute": {"value": None}},
        }
        with self.assertRaisesRegex(ValueError, "missing|required"):
            validate_selective_compute_receipt(incomplete)

    def test_active_fraction_alone_cannot_claim_speedup(self) -> None:
        from hive_visual_state.selective_protocol import validate_selective_compute_receipt

        receipt = self._minimal_receipt()
        receipt["fractions"]["active"] = 0.1
        receipt["claims"]["speedup"] = {
            "value": 10.0,
            "status": "measured",
            "reason": "active fraction only",
            "method": "inferred from map",
        }
        with self.assertRaisesRegex(ValueError, "speedup|accepted|backend work"):
            validate_selective_compute_receipt(receipt)

    def test_gpu_savings_require_actual_backend_work_reduction(self) -> None:
        from hive_visual_state.selective_protocol import validate_selective_compute_receipt

        receipt = self._minimal_receipt()
        receipt["claims"]["gpu_savings"] = {
            "value": 0.5,
            "status": "measured",
            "reason": "none",
            "method": "backend profiler",
        }
        with self.assertRaisesRegex(ValueError, "backend work reduction"):
            validate_selective_compute_receipt(receipt)

    def test_frozen_active_uncertain_regions_cover_the_full_scope(self) -> None:
        from hive_visual_state.selective_protocol import validate_selective_state_map

        incomplete = {
            "coordinate_space": {"width": 16, "height": 16, "unit": "pixel"},
            "temporal_scope": {"start_frame": 0, "end_frame_exclusive": 1},
            "compute_unit_type": "unresolved",
            "frozen_regions": [[0, 0, 8, 16]],
            "active_regions": [],
            "uncertain_regions": [],
            "global_invalidation": False,
            "confidence": 0.5,
            "evidence_source": "auxiliary_observed_change_evidence",
            "boundary_closure": "full_compute_until_admitted",
            "promotion_policy": "backend_capability_required",
            "fallback_policy": "full_compute",
        }
        with self.assertRaisesRegex(ValueError, "cover|scope"):
            validate_selective_state_map(incomplete)

    def test_protocol_config_cannot_change_protected_evidence(self) -> None:
        from hive_visual_state.selective_protocol import validate_protocol_config

        config = {
            "protocol_status": "predeclared",
            "results_present": False,
            "model_runs": 0,
            "cuda_runs": 0,
            "protected_evidence_changes": ["M0", "M1-P0", "C01-C12"],
        }
        with self.assertRaisesRegex(ValueError, "protected evidence"):
            validate_protocol_config(config)

    @staticmethod
    def _minimal_receipt() -> dict:
        unavailable = {
            "value": None,
            "status": "unavailable",
            "reason": "protocol-only predeclaration",
            "method": "not measured",
        }
        cost_names = (
            "scout",
            "change_detection",
            "eye_observation",
            "map_compile",
            "scheduling",
            "active_compute",
            "frozen_reuse",
            "transfer",
            "synchronization",
            "merge",
            "boundary",
            "audit",
            "expected_repair_fallback",
            "output",
            "total_wall",
        )
        return {
            "schema_version": "0.1.0",
            "receipt_id": "counterexample",
            "run_status": "protocol_only",
            "results_present": False,
            "costs": {name: dict(unavailable) for name in cost_names},
            "resources": {
                "ram": dict(unavailable),
                "vram": dict(unavailable),
                "copied_bytes": dict(unavailable),
                "transferred_bytes": dict(unavailable),
            },
            "fractions": {"active": None, "frozen": None, "uncertain": None},
            "actual_backend_work_reduction": dict(unavailable),
            "quality_delta": dict(unavailable),
            "temporal_delta": dict(unavailable),
            "accepted_result": False,
            "claims": {},
        }


if __name__ == "__main__":
    unittest.main()
