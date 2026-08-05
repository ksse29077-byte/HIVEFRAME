from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs" / "m1_b0_model_free_locality.json"
SCHEMA_PATH = ROOT / "schemas" / "m1_b0_locality_opportunity.schema.json"

EXPECTED_GRAY_THRESHOLDS = [0, 1, 2, 4, 8, 16]
EXPECTED_RGB_THRESHOLDS = [0, 2, 4, 8, 16]
EXPECTED_TILE_SIZES = [8, 16, 32, 64]
EXPECTED_ACTIVATION_IDS = ["any", "1_percent", "5_percent", "10_percent"]
EXPECTED_HALOS = [0, 1, 2]
ZERO_CLAIMS = (
    "safe_skip_truth_count",
    "verified_compute_relevance_oracles",
    "backend_selective_compute_results",
    "model_runs",
    "cuda_runs",
    "gpu_runs",
    "backend_integration_runs",
    "selective_compute_runs",
    "vram_measurement_runs",
    "product_speedup_results",
)
ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:home|Users)/[^/]+/)")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def unavailable(reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "status": "unavailable",
        "reason": reason,
        "method": "not measured",
    }


def validate_protocol_contract(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    claims = document.get("claim_boundary", {})
    if claims.get("backend_selective_compute_results") != 0:
        errors.append("backend_claim_forbidden")
    if document.get("guided_oracle_usage") != "excluded_from_measurement_truth":
        errors.append("guided_oracle_truth_forbidden")
    streaming = document.get("cost_profiles", {}).get("streaming_decode_compare", [])
    if not {"decode", "transfer", "compare", "tile_aggregation"}.issubset(streaming):
        errors.append("streaming_decode_scope_incomplete")
    if document.get("pure_python_pixel_loop_performance_baseline") is not False:
        errors.append("python_pixel_loop_baseline_forbidden")
    partial = document.get("partial_edge_tiles", {})
    if partial.get("included") is not True:
        errors.append("partial_edge_tiles_required")
    if document.get("surface", {}).get("protocol_revision_on_change") is not True:
        errors.append("protocol_revision_required")
    if document.get("translation", {}).get("exposed_border_policy") != "active_or_uncertain":
        errors.append("exposed_border_cannot_freeze")
    if document.get("global_invalidation", {}).get("hard_cut_pressure_recorded") is not True:
        errors.append("global_invalidation_pressure_required")
    if document.get("halo", {}).get("closure_cost_reported") is not True:
        errors.append("halo_cost_required")
    metric = document.get("unavailable_metric", {})
    if metric.get("value") is not None:
        errors.append("unavailable_value_must_be_null")
    workers = document.get("workers", {})
    logical = int(workers.get("logical_threads", 0))
    oversubscribed = [value for value in workers.get("requested", []) if value > logical // 2]
    if oversubscribed and not set(oversubscribed).issubset(workers.get("oversubscription_diagnostics", [])):
        errors.append("oversubscription_label_required")
    if ABSOLUTE_PATH.search(json.dumps(document.get("public_artifact", {}), sort_keys=True)):
        errors.append("public_absolute_path_forbidden")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document.get("result_digest", ""))):
        errors.append("result_digest_required")
    if document.get("parity", {}).get("continue_benchmark_on_mismatch") is not False:
        errors.append("parity_mismatch_must_block")
    if claims.get("product_speedup_results") != 0:
        errors.append("product_speedup_forbidden")
    if document.get("input", {}).get("hash_verified") is not True:
        errors.append("input_hash_verification_required")
    if partial.get("denominator") != "actual_tile_pixel_count":
        errors.append("partial_edge_denominator_invalid")
    if document.get("surface", {}).get("report_all_configurations") is not True:
        errors.append("surface_cherry_pick_forbidden")
    if document.get("translation", {}).get("raw_results_reported") is not True:
        errors.append("raw_translation_surface_required")
    if document.get("backend_capability_auto_admit") is not False:
        errors.append("backend_auto_admission_forbidden")
    return errors


def validate_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if config.get("schema_version") != "0.1.0":
        errors.append("schema_version")
    if config.get("protocol_revision") != "m1-b0-v1":
        errors.append("protocol_revision")
    input_contract = config.get("input_contract", {})
    clips = input_contract.get("clips", [])
    expected_ids = [f"c{index:02d}" for index in range(1, 13)]
    if [clip.get("clip_id") for clip in clips] != expected_ids:
        errors.append("clip_ids")
    if len({clip.get("sha256") for clip in clips}) != 12:
        errors.append("clip_hashes")
    if (input_contract.get("width"), input_contract.get("height"), input_contract.get("fps")) != (
        832,
        480,
        16,
    ):
        errors.append("input_shape")
    surface = config.get("surface", {})
    if surface.get("gray8_thresholds") != EXPECTED_GRAY_THRESHOLDS:
        errors.append("gray8_thresholds")
    if surface.get("rgb24_thresholds") != EXPECTED_RGB_THRESHOLDS:
        errors.append("rgb24_thresholds")
    if surface.get("tile_sizes") != EXPECTED_TILE_SIZES:
        errors.append("tile_sizes")
    if [item.get("id") for item in surface.get("activation_rules", [])] != EXPECTED_ACTIVATION_IDS:
        errors.append("activation_rules")
    if surface.get("halo_tiles") != EXPECTED_HALOS:
        errors.append("halo_tiles")
    translation = config.get("translation", {})
    if (
        translation.get("profile") != "global_translation_v1"
        or translation.get("downsample_width") != 104
        or translation.get("downsample_height") != 60
        or translation.get("search_min") != -4
        or translation.get("search_max") != 4
        or translation.get("exposed_border_policy") != "active_or_uncertain"
    ):
        errors.append("translation_contract")
    benchmark = config.get("benchmark", {})
    if benchmark.get("required_worker_sweep") != [1, 2, 3, 4, 6]:
        errors.append("worker_sweep")
    if benchmark.get("cold_disk_benchmark") is not False or benchmark.get("os_file_cache_flushed") is not False:
        errors.append("cache_claim")
    claims = config.get("claim_boundary", {})
    for field in ZERO_CLAIMS:
        if claims.get(field) != 0:
            errors.append(f"claim_boundary.{field}")
    return errors


def public_sanitation_errors(value: Any) -> list[str]:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return ["public_absolute_path"] if ABSOLUTE_PATH.search(rendered) else []


def validate_result_document(document: dict[str, Any]) -> list[str]:
    """Dependency-free validation for the strict M1-B0 public receipt contract.

    Full Draft 2020-12 validation is performed when an optional validator is
    available; this invariant layer remains executable in the pinned, no-new-
    dependency M1-B0 environment.
    """

    errors: list[str] = []
    if document.get("schema_version") != "0.1.0":
        errors.append("schema_version")
    if document.get("protocol_revision") != "m1-b0-v1":
        errors.append("protocol_revision")
    if document.get("run_kind") != "m1_b0_model_free_locality_opportunity":
        errors.append("run_kind")
    if document.get("decision") not in {
        "M1_B0_LOCALITY_SURFACE_MEASURED",
        "M1_B0_REFINEMENT_REQUIRED",
        "M1_B0_BLOCKED",
    }:
        errors.append("decision")
    inputs = document.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 12:
        errors.append("inputs")
    else:
        expected_ids = [f"c{index:02d}" for index in range(1, 13)]
        if [item.get("clip_id") for item in inputs] != expected_ids:
            errors.append("input_clip_ids")
        for item in inputs:
            if (
                item.get("width") != 832
                or item.get("height") != 480
                or item.get("fps") != 16
                or item.get("hash_verified") is not True
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("derivative_sha256", "")))
            ):
                errors.append(f"input:{item.get('clip_id', 'unknown')}")
    parity = document.get("parity", {})
    if parity.get("passed") is not True or parity.get("clip_format_pairs") != 24 or parity.get("mismatches") != []:
        errors.append("parity")
    claims = document.get("claim_boundary", {})
    for field in (
        "model_runs",
        "cuda_runs",
        "gpu_runs",
        "backend_integration_runs",
        "selective_compute_runs",
        "vram_measurement_runs",
        "product_speedup_results",
        "safe_skip_truth_count",
        "verified_compute_relevance_oracles",
    ):
        if claims.get(field) != 0:
            errors.append(f"claim_boundary.{field}")
    for name, metric in document.get("unavailable_memory_metrics", {}).items():
        if not isinstance(metric, dict) or metric.get("value") is not None or metric.get("status") != "unavailable":
            errors.append(f"unavailable_memory_metrics.{name}")
        elif not metric.get("reason") or metric.get("method") != "not measured":
            errors.append(f"unavailable_memory_metrics.{name}")
    artifact = document.get("local_artifact_bundle", {})
    if (
        artifact.get("tracked_by_git") is not False
        or not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256", "")))
        or not isinstance(artifact.get("bytes"), int)
        or artifact.get("bytes", 0) < 1
    ):
        errors.append("local_artifact_bundle")
    if not re.fullmatch(r"[0-9a-f]{64}", str(document.get("summary_digest", ""))):
        errors.append("summary_digest")
    errors.extend(public_sanitation_errors(document))
    return errors
