from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from hive_benchmarks.m1_corpus_summary import (
    ALLOWED_DECISIONS,
    ARTIFACTS,
    build_reports,
    validate_measurement_contract,
    validate_topologies,
    write_reports,
)
from hive_benchmarks.m1_corpus_validator import summarize_manifest, validate_manifest
from hive_benchmarks.m1_oracle_validator import validate_oracle_document
from hive_benchmarks.m1_protocol import public_sanitation_errors, sha256_json, tracked_binary_errors
from hive_benchmarks.m1_rights_validator import validate_rights_document


ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def derivative_contract() -> dict:
    return copy.deepcopy(json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))["derivative_contract"])


def valid_clip(clip_id: str = "clip-001", digest: str = SHA_A, scene: str = "slow_pan") -> dict:
    return {
        "clip_id": clip_id,
        "neutral_description": "A reviewed short real-video clip.",
        "scene_classes": [scene],
        "stress_labels": [],
        "source_class": "eligible_self_recorded",
        "source_provenance": "Creator-controlled recording with preserved capture receipt.",
        "rights_status": "admitted",
        "rights_holder": "recording creator",
        "source_authority": "creator capture receipt",
        "license_identifier": "self-recorded-explicit-rights-v1",
        "license_terms_digest": SHA_B,
        "attribution_required": False,
        "attribution_text": "not required",
        "permissions": {"research": True, "commercial": True, "copy": True, "derivative": True, "redistribution": True},
        "identifiable_people": False,
        "consent_required": False,
        "consent_status": "not_required",
        "sensitive_content_status": "none_observed",
        "original_sha256": digest,
        "original_bytes": 1024,
        "width": 4,
        "height": 2,
        "fps": 16.0,
        "frame_count": 2,
        "duration_seconds": 0.125,
        "codec": "h264",
        "container": "mp4",
        "audio_present": False,
        "derivative_sha256": SHA_C,
        "oracle_sha256": SHA_D,
        "storage_class": "external_digest_store",
        "storage_reference": f"m1-a/{clip_id}/{digest}",
        "admission_status": "eligible",
        "rejection_reason": {"value": None, "status": "unavailable", "reason": "The clip is eligible.", "method": "admission review"},
        "reviewed_at": "2026-08-02T00:00:00Z",
        "review_method": "human provenance and rights review",
        "evidence_notes": ["No binary is stored in Git."],
    }


def valid_manifest(clips: list[dict] | None = None) -> dict:
    base = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))
    base["clips"] = clips if clips is not None else [valid_clip()]
    return base


def valid_rights(clip_id: str = "clip-001", digest: str = SHA_A, source_class: str = "eligible_self_recorded") -> dict:
    receipt = {
        "clip_id": clip_id,
        "original_sha256": digest,
        "source_class": source_class,
        "rights_basis": "creator ownership and explicit admission receipt",
        "rights_holder": "recording creator",
        "license_identifier": "self-recorded-explicit-rights-v1",
        "official_source_reference": f"creator-receipt:{clip_id}",
        "terms_digest": SHA_B,
        "attribution_obligation": {"required": False, "text": "not required"},
        "permissions": {"research": True, "commercial": True, "copy": True, "derivative": True, "redistribution": True},
        "identifiable_people": False,
        "consent_basis": "no identifiable people",
        "consent_status": "not_required",
        "restrictions": [],
        "review_status": "admitted",
        "reviewed_at": "2026-08-02T00:00:00Z",
        "review_method": "human source, terms, consent, and evidence review",
        "evidence_digest": SHA_C,
    }
    return {"schema_version": "0.1.0", "receipts": [receipt]}


def region(region_id: str, state: str, box: list[int], semantic_ref: str = "base", object_ids: list[str] | None = None) -> dict:
    payload = {"label": semantic_ref}
    return {
        "region_id": region_id,
        "state": state,
        "geometry": {"type": "bbox", "xywh": box},
        "object_ids": object_ids or [],
        "change_causes": ["object_motion"] if state == "dirty" else [],
        "confidence": 1.0,
        "semantic_ref": semantic_ref,
        "semantic_hash": sha256_json(payload),
    }


def valid_annotation(clip_id: str = "clip-001", source_digest: str = SHA_A, *, cut: bool = False) -> dict:
    semantic_payloads = {"base": {"label": "base"}}
    regions = [region("r-dirty", "dirty", [0, 0, 2 if not cut else 4, 2])]
    if not cut:
        regions.append(region("r-stable", "stable", [2, 0, 2, 2]))
    annotation = {
        "clip_id": clip_id,
        "source_sha256": source_digest,
        "derivative_sha256": SHA_C,
        "canvas": [4, 2],
        "frame_count": 2,
        "object_catalog": [],
        "semantic_payloads": semantic_payloads,
        "transitions": [{
            "transition_id": "t-0-1",
            "frame_interval": [0, 1],
            "scene_cut": cut,
            "camera_motion": "none",
            "full_reobserve": cut,
            "invalidated_object_ids": [],
            "regions": regions,
        }],
        "annotation_provenance": "human annotation protocol",
        "annotation_method": "initial annotation followed by independent review",
        "review_protocol": "independent_multi_reviewer",
        "review_status": "verified",
        "confidence": 1.0,
        "disagreement": [],
    }
    annotation["artifact_digest"] = sha256_json(annotation)
    return annotation


def oracle_document(annotation: dict | None = None) -> dict:
    return {"schema_version": "0.1.0", "annotation_version": "m1-a-v0", "annotations": [annotation or valid_annotation()]}


class M1RealVideoProtocolTests(unittest.TestCase):
    def test_schemas_and_predeclared_configs_parse(self) -> None:
        for path in [
            ROOT / "schemas" / "m1-real-video-corpus-manifest.schema.json",
            ROOT / "schemas" / "m1-video-rights-receipt.schema.json",
            ROOT / "schemas" / "m1-oracle-annotation.schema.json",
            ROOT / "configs" / "m1-real-video-corpus.json",
            ROOT / "configs" / "m1-topology-candidates.json",
            ROOT / "configs" / "m1-measurement-contract.json",
        ]:
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)
        self.assertEqual(validate_manifest(json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))), [])

    def test_valid_self_recorded_public_domain_explicit_and_consent_receipts(self) -> None:
        for source_class in ("eligible_self_recorded", "eligible_public_domain", "eligible_explicit_license"):
            document = valid_rights(source_class=source_class)
            self.assertEqual(validate_rights_document(document), [])
        consent = valid_rights()
        consent["receipts"][0].update({"identifiable_people": True, "consent_basis": "signed appearance release", "consent_status": "verified"})
        self.assertEqual(validate_rights_document(consent), [])

    def test_valid_manifest_derivative_digest_and_unknown_semantics(self) -> None:
        clip = valid_clip()
        clip["audio_present"] = {"value": None, "status": "unavailable", "reason": "No audio probe was run.", "method": "metadata-only review"}
        self.assertEqual(validate_manifest(valid_manifest([clip])), [])

    def test_compact_rle_and_polygon_are_accepted(self) -> None:
        annotation = valid_annotation()
        dirty = annotation["transitions"][0]["regions"][0]
        stable = annotation["transitions"][0]["regions"][1]
        dirty["geometry"] = {"type": "rle", "size": [2, 4], "counts": [0, 2, 2, 2, 2], "starts_with": 0}
        stable["geometry"] = {"type": "polygon", "points": [[2, 0], [4, 0], [4, 2], [2, 2]]}
        annotation["artifact_digest"] = sha256_json({key: value for key, value in annotation.items() if key != "artifact_digest"})
        self.assertEqual(validate_oracle_document(oracle_document(annotation)), [])

    def test_valid_hard_cut_requires_full_dirty_reobserve(self) -> None:
        self.assertEqual(validate_oracle_document(oracle_document(valid_annotation(cut=True))), [])

    def test_coverage_gate_needs_twelve_distinct_actual_clips_and_all_classes(self) -> None:
        base = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))
        clips = [valid_clip(f"clip-{index:03d}", hashlib.sha256(f"clip-{index}".encode()).hexdigest(), scene) for index, scene in enumerate(base["required_scene_classes"], 1)]
        summary = summarize_manifest(valid_manifest(clips))
        self.assertEqual(summary["counts"]["eligible"], 12)
        self.assertEqual(summary["missing_scene_classes"], [])
        clips[1]["original_sha256"] = clips[0]["original_sha256"]
        self.assertTrue(any("distinct actual videos" in error for error in validate_manifest(valid_manifest(clips))))

    def test_missing_source_commercial_permission_derivative_and_consent_are_rejected(self) -> None:
        rights = valid_rights()
        rights["receipts"][0]["official_source_reference"] = ""
        rights["receipts"][0]["permissions"]["commercial"] = False
        self.assertTrue(validate_rights_document(rights))
        clip = valid_clip()
        clip["derivative_sha256"] = {"value": None, "status": "pending", "reason": "Derivative not prepared.", "method": "pending workflow"}
        clip["identifiable_people"] = True
        clip["consent_required"] = True
        clip["consent_status"] = "pending"
        self.assertTrue(validate_manifest(valid_manifest([clip])))

    def test_digest_frame_mask_bounds_and_object_failures_are_detected(self) -> None:
        annotation = valid_annotation()
        annotation["transitions"][0]["regions"][0]["semantic_hash"] = SHA_A
        annotation["transitions"][0]["regions"][1]["geometry"]["xywh"] = [1, 0, 4, 2]
        annotation["transitions"][0]["regions"][0]["object_ids"] = ["missing-object"]
        annotation["frame_count"] = 3
        annotation["artifact_digest"] = SHA_A
        errors = validate_oracle_document(oracle_document(annotation))
        self.assertTrue(any("digest mismatch" in error for error in errors))
        self.assertTrue(any("outside canvas" in error for error in errors))
        self.assertTrue(any("unknown ids" in error for error in errors))
        self.assertTrue(any("transition mapping" in error for error in errors))

    def test_mask_overlap_rle_length_and_polygon_self_intersection_are_detected(self) -> None:
        annotation = valid_annotation()
        annotation["transitions"][0]["regions"][1]["geometry"] = {"type": "rle", "size": [2, 4], "counts": [0, 8, 1], "starts_with": 0}
        annotation["transitions"][0]["regions"][0]["geometry"] = {"type": "polygon", "points": [[0, 0], [3, 2], [0, 2], [3, 0]]}
        annotation["artifact_digest"] = SHA_A
        errors = validate_oracle_document(oracle_document(annotation))
        self.assertTrue(any("run lengths" in error for error in errors))
        self.assertTrue(any("self-intersects" in error for error in errors))

    def test_missing_cut_and_preserved_pre_cut_state_are_detected(self) -> None:
        annotation = valid_annotation(cut=True)
        transition = annotation["transitions"][0]
        transition["full_reobserve"] = False
        transition["regions"].append(region("stable-after-cut", "stable", [0, 0, 1, 1]))
        annotation["artifact_digest"] = SHA_A
        errors = validate_oracle_document(oracle_document(annotation))
        self.assertTrue(any("full_reobserve" in error for error in errors))
        self.assertTrue(any("scene cut invalidates" in error for error in errors))

    def test_missing_annotation_and_cross_document_digest_mismatch_are_not_admitted(self) -> None:
        manifest = valid_manifest()
        rights = valid_rights()
        empty_oracle = {"schema_version": "0.1.0", "annotation_version": "m1-a-v0", "annotations": []}
        topologies = json.loads((ROOT / "configs" / "m1-topology-candidates.json").read_text(encoding="utf-8"))
        measurement = json.loads((ROOT / "configs" / "m1-measurement-contract.json").read_text(encoding="utf-8"))
        reports = build_reports(manifest, rights, empty_oracle, topologies, measurement, [])
        self.assertIn("ORACLE_PROTOCOL_REVISE", reports["admission-report.json"])

    def test_public_sanitation_rejects_paths_credentials_and_tracked_binary(self) -> None:
        self.assertTrue(public_sanitation_errors({"path": "C:\\Users\\someone\\clip.mp4"}))
        self.assertTrue(public_sanitation_errors({"path": "/home/someone/clip.mp4"}))
        self.assertTrue(public_sanitation_errors({"token": "api_key=abcdefghijklmnop"}))
        self.assertEqual(tracked_binary_errors(["benchmarks/clip.mp4"]), ["tracked binary media is forbidden: benchmarks/clip.mp4"])

    def test_repeated_full_mask_or_semantic_payload_is_rejected_without_autofix(self) -> None:
        annotation = valid_annotation()
        annotation["transitions"][0]["regions"][0]["mask"] = [1, 1, 1, 1]
        annotation["transitions"][0]["regions"][0]["semantic_payload"] = {"label": "base"}
        before = copy.deepcopy(annotation)
        self.assertTrue(validate_oracle_document(oracle_document(annotation)))
        self.assertEqual(annotation, before)

    def test_topology_and_measurement_contracts_are_fixed_and_result_free(self) -> None:
        topologies = json.loads((ROOT / "configs" / "m1-topology-candidates.json").read_text(encoding="utf-8"))
        measurement = json.loads((ROOT / "configs" / "m1-measurement-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_topologies(topologies), [])
        self.assertEqual(validate_measurement_contract(measurement), [])
        self.assertEqual([item["topology_id"] for item in topologies["candidates"]], [f"T{index}" for index in range(8)])
        self.assertFalse(measurement["results_present"])
        self.assertEqual(measurement["m1_a_gate_decisions"], list(ALLOWED_DECISIONS))

    def test_empty_admitted_corpus_yields_acquisition_required_and_zero_run_counts(self) -> None:
        manifest = json.loads((ROOT / "configs" / "m1-real-video-corpus.json").read_text(encoding="utf-8"))
        rights = {"schema_version": "0.1.0", "receipts": []}
        oracle = {"schema_version": "0.1.0", "annotation_version": "m1-a-v0", "annotations": []}
        topologies = json.loads((ROOT / "configs" / "m1-topology-candidates.json").read_text(encoding="utf-8"))
        measurement = json.loads((ROOT / "configs" / "m1-measurement-contract.json").read_text(encoding="utf-8"))
        reports = build_reports(manifest, rights, oracle, topologies, measurement, [])
        admission = json.loads(reports["admission-report.json"])
        self.assertEqual(admission["decision"], "CORPUS_ACQUISITION_REQUIRED")
        self.assertEqual(admission["counts"]["eligible"], 0)
        self.assertTrue(all(value == 0 for value in admission["execution_counts"].values()))

    def test_report_writer_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "target") as temporary:
            output = Path(temporary)
            (output / ARTIFACTS[0]).write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_reports(output, {name: "test" for name in ARTIFACTS})


if __name__ == "__main__":
    unittest.main()
