from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

import numpy as np

from hive_benchmarks.m1_b0_contract import (
    CONFIG_PATH,
    SCHEMA_PATH,
    public_sanitation_errors,
    unavailable,
    validate_config,
    validate_result_document,
)
from hive_benchmarks.m1_b0_locality import (
    _activate,
    _dilate_tiles,
    _run_summary,
    _tile_counts,
    analyze_gray_sequence,
    analyze_rgb_sequence,
    compensated_difference,
    estimate_global_translation,
)
from hive_benchmarks.m1_b0_runner import _compare_values, _profile_stats, _write_json_new


ROOT = Path(__file__).resolve().parents[2]


def test_config(width: int = 19, height: int = 18) -> dict:
    config = deepcopy(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    config["allow_test_shape"] = True
    config["input_contract"]["width"] = width
    config["input_contract"]["height"] = height
    config["surface"]["gray8_thresholds"] = [0, 2]
    config["surface"]["rgb24_thresholds"] = [0, 2]
    config["surface"]["tile_sizes"] = [8]
    config["surface"]["activation_rules"] = [
        {"id": "any", "minimum_changed_numerator": 1, "minimum_changed_denominator": None},
        {"id": "10_percent", "minimum_changed_numerator": 10, "minimum_changed_denominator": 100},
    ]
    config["surface"]["halo_tiles"] = [0, 1]
    config["translation"]["downsample_width"] = width // 8
    config["translation"]["downsample_height"] = height // 8
    config["translation"]["search_min"] = -1
    config["translation"]["search_max"] = 1
    return config


class M1B0LocalityTests(unittest.TestCase):
    def test_official_config_and_schema_parse_and_are_public_safe(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(validate_config(config), [])
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(public_sanitation_errors(config), [])
        self.assertEqual([clip["clip_id"] for clip in config["input_contract"]["clips"]], [f"c{i:02d}" for i in range(1, 13)])

    def test_exact_equality_fixture_is_fully_frozen_candidate(self) -> None:
        config = test_config()
        frame = np.arange(18 * 19, dtype=np.uint16).reshape(18, 19).astype(np.uint8)
        summary = analyze_gray_sequence(np.stack([frame, frame]), config)
        raw_zero = next(item for item in summary["pixel_surface"] if item["source"] == "raw" and item["threshold"] == 0)
        self.assertEqual(raw_zero["changed_pixels"], 0)
        any_tiles = next(item for item in summary["tile_surface"] if item["source"] == "raw" and item["threshold"] == 0 and item["activation_rule"] == "any" and item["halo_tiles"] == 0)
        self.assertEqual(any_tiles["active_tiles"], 0)
        self.assertEqual(any_tiles["frozen_candidate_ratio"], 1.0)

    def test_low_amplitude_noise_respects_strict_threshold(self) -> None:
        config = test_config()
        first = np.zeros((18, 19), dtype=np.uint8)
        second = np.ones_like(first)
        summary = analyze_gray_sequence(np.stack([first, second]), config)
        threshold_zero = next(item for item in summary["pixel_surface"] if item["source"] == "raw" and item["threshold"] == 0)
        threshold_two = next(item for item in summary["pixel_surface"] if item["source"] == "raw" and item["threshold"] == 2)
        self.assertEqual(threshold_zero["changed_pixels"], 18 * 19)
        self.assertEqual(threshold_two["changed_pixels"], 0)

    def test_partial_edge_tiles_use_actual_pixel_area(self) -> None:
        changed = np.ones((18, 19), dtype=bool)
        counts, areas = _tile_counts(changed, 8)
        self.assertEqual(counts.shape, (3, 3))
        self.assertEqual(int(np.count_nonzero(areas != 64)), 5)
        self.assertEqual(int(counts[-1, -1]), 2 * 3)
        active = _activate(counts, areas, {"minimum_changed_numerator": 100, "minimum_changed_denominator": 100})
        self.assertTrue(bool(active.all()))

    def test_local_motion_and_halo_expansion_are_deterministic(self) -> None:
        config = test_config()
        first = np.zeros((18, 19), dtype=np.uint8)
        second = first.copy()
        second[1:3, 1:3] = 255
        one = analyze_gray_sequence(np.stack([first, second]), config)
        two = analyze_gray_sequence(np.stack([first, second]), config)
        self.assertEqual(one["summary_digest"], two["summary_digest"])
        base = next(item for item in one["tile_surface"] if item["source"] == "raw" and item["threshold"] == 0 and item["activation_rule"] == "any" and item["halo_tiles"] == 0)
        halo = next(item for item in one["tile_surface"] if item["source"] == "raw" and item["threshold"] == 0 and item["activation_rule"] == "any" and item["halo_tiles"] == 1)
        self.assertEqual(base["active_tiles"], 1)
        self.assertGreater(halo["active_tiles"], base["active_tiles"])
        self.assertEqual(halo["additional_closure_tiles"], halo["active_tiles"] - base["active_tiles"])

    def test_full_frame_change_records_full_pressure(self) -> None:
        config = test_config()
        first = np.zeros((18, 19), dtype=np.uint8)
        second = np.full_like(first, 255)
        summary = analyze_gray_sequence(np.stack([first, second]), config)
        item = next(value for value in summary["tile_surface"] if value["source"] == "raw" and value["threshold"] == 2 and value["activation_rule"] == "any" and value["halo_tiles"] == 0)
        self.assertEqual(item["full_pressure_pairs"], 1)
        self.assertEqual(item["pairs_at_or_above_90_percent"], 1)

    def test_translation_and_newly_exposed_border(self) -> None:
        width, height = 832, 480
        config = deepcopy(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        y, x = np.indices((height, width))
        previous = ((x * 3 + y * 5) % 251).astype(np.uint8)
        current = np.zeros_like(previous)
        current[:, 8:] = previous[:, :-8]
        estimate = estimate_global_translation(previous, current, config["translation"])
        self.assertEqual((estimate.dx_full, estimate.dy_full), (8, 0))
        difference, exposed = compensated_difference(previous, current, estimate)
        self.assertEqual(exposed, 8 * height)
        self.assertTrue(bool(np.all(difference[:, :8] == 255)))
        self.assertEqual(int(np.count_nonzero(difference[:, 8:])), 0)

    def test_hard_cut_like_fixture_is_only_global_invalidation_candidate(self) -> None:
        config = test_config()
        first = np.zeros((18, 19), dtype=np.uint8)
        second = np.full((18, 19), 200, dtype=np.uint8)
        summary = analyze_gray_sequence(np.stack([first, second]), config)
        self.assertEqual(summary["frame_pairs"], 1)
        full = [item for item in summary["tile_surface"] if item["source"] == "raw" and item["full_pressure_pairs"] == 1]
        self.assertTrue(full)
        self.assertNotIn("safe_skip", json.dumps(summary, sort_keys=True))

    def test_temporal_persistence_fixture_reports_runs_and_transitions(self) -> None:
        states = np.array([[False, True], [False, True], [True, False], [True, False]], dtype=bool)
        summary = _run_summary(states)
        self.assertEqual(summary["active_run_count"], 2)
        self.assertEqual(summary["active_run_median"], 2)
        self.assertEqual(summary["active_to_frozen_transitions"], 1)
        self.assertEqual(summary["frozen_to_active_transitions"], 1)
        self.assertEqual(summary["one_frame_only_activity_ratio"], 0.0)

    def test_rgb_secondary_pass_reports_luma_disagreement(self) -> None:
        config = test_config()
        gray = np.zeros((2, 18, 19), dtype=np.uint8)
        rgb = np.zeros((2, 18, 19, 3), dtype=np.uint8)
        rgb[1, 0, 0, 2] = 4
        summary = analyze_rgb_sequence(rgb, config, gray)
        threshold_two = next(item for item in summary["pixel_surface"] if item["threshold"] == 2)
        disagreement = next(item for item in summary["luma_rgb_disagreement"] if item["threshold"] == 2)
        self.assertEqual(threshold_two["changed_pixels"], 1)
        self.assertEqual(disagreement["disagreement_pixels"], 1)

    def test_unavailable_semantics_are_null_and_explained(self) -> None:
        value = unavailable("Backend tensor shape is not admitted in M1-B0.")
        self.assertIsNone(value["value"])
        self.assertEqual(value["status"], "unavailable")
        self.assertTrue(value["reason"])
        self.assertEqual(value["method"], "not measured")

    def test_tile_dilation_does_not_create_out_of_canvas_tiles(self) -> None:
        active = np.zeros((2, 3), dtype=bool)
        active[0, 0] = True
        expanded = _dilate_tiles(active, 1)
        self.assertEqual(expanded.shape, active.shape)
        self.assertEqual(int(expanded.sum()), 4)

    def test_result_schema_invariants_accept_positive_and_reject_negative_fixture(self) -> None:
        result_path = ROOT / "reports" / "m1_b0" / "locality_opportunity_summary.json"
        if result_path.exists():
            positive = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            positive = {
                "schema_version": "0.1.0",
                "protocol_revision": "m1-b0-v1",
                "run_kind": "m1_b0_model_free_locality_opportunity",
                "decision": "M1_B0_LOCALITY_SURFACE_MEASURED",
                "inputs": [
                    {
                        "clip_id": f"c{index:02d}", "width": 832, "height": 480, "fps": 16,
                        "hash_verified": True, "derivative_sha256": f"{index:064x}",
                    }
                    for index in range(1, 13)
                ],
                "parity": {"passed": True, "clip_format_pairs": 24, "mismatches": []},
                "claim_boundary": {field: 0 for field in (
                    "model_runs", "cuda_runs", "gpu_runs", "backend_integration_runs",
                    "selective_compute_runs", "vram_measurement_runs", "product_speedup_results",
                    "safe_skip_truth_count", "verified_compute_relevance_oracles",
                )},
                "unavailable_memory_metrics": {"actual_peak_vram_reduction": unavailable("No GPU run.")},
                "local_artifact_bundle": {"bytes": 1, "sha256": "a" * 64, "tracked_by_git": False},
                "summary_digest": "b" * 64,
            }
        self.assertEqual(validate_result_document(positive), [])
        negative = deepcopy(positive)
        negative["claim_boundary"]["model_runs"] = 1
        self.assertIn("claim_boundary.model_runs", validate_result_document(negative))

    def test_parity_comparison_preserves_integer_exactness_and_float_tolerance(self) -> None:
        mismatches: list[str] = []
        _compare_values({"count": 3, "ratio": 0.5}, {"count": 3, "ratio": 0.5 + 1e-13}, "root", mismatches, 1e-12)
        self.assertEqual(mismatches, [])
        _compare_values({"count": 3}, {"count": 4}, "root", mismatches, 1e-12)
        self.assertTrue(mismatches)

    def test_profile_statistics_use_nearest_rank(self) -> None:
        self.assertEqual(_profile_stats([3.0, 1.0, 2.0]), {"minimum": 1.0, "p50": 2.0, "p95": 3.0, "maximum": 3.0})

    def test_output_collision_is_blocked_before_overwrite(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            _write_json_new(target, {"attempt": 1})
            with self.assertRaisesRegex(RuntimeError, "OUTPUT_COLLISION"):
                _write_json_new(target, {"attempt": 2})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"attempt": 1})


if __name__ == "__main__":
    unittest.main()
