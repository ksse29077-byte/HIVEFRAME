from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from hive_benchmarks.m1_b0_contract import public_sanitation_errors, validate_result_document


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit(repository: Path, local_root: Path) -> dict[str, Any]:
    failures: list[str] = []
    summary_path = repository / "reports/m1_b0/locality_opportunity_summary.json"
    csv_path = repository / "reports/m1_b0/locality_opportunity_summary.csv"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    failures.extend(validate_result_document(summary))

    digest = summary.pop("summary_digest")
    if _canonical_digest(summary) != digest:
        failures.append("summary_digest")
    summary["summary_digest"] = digest
    tile_rows = sum(len(clip["tile_surface"]) for clip in summary["surface"]["clip_results"])
    temporal_rows = sum(len(clip["temporal_persistence"]) for clip in summary["surface"]["clip_results"])
    if tile_rows != 6912 or temporal_rows != 6912:
        failures.append("surface_row_count")
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        csv_rows = sum(1 for _ in csv.DictReader(stream))
    if csv_rows != 6912:
        failures.append("csv_row_count")

    tracked = subprocess.check_output(
        ["git", "ls-files", "*.json"], cwd=repository, text=True, encoding="utf-8"
    ).splitlines()
    json_files = [repository / path for path in tracked]
    for required in (
        repository / "reports/m1_b0/input_integrity_report.json",
        repository / "reports/m1_b0/benchmark_receipt.json",
        summary_path,
    ):
        if required not in json_files:
            json_files.append(required)
    for path in json_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            failures.append(f"json:{path.relative_to(repository).as_posix()}:{error}")

    bundle_path = local_root / "bundle-manifest.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    expected_files = bundle["files"]
    if _canonical_digest(expected_files) != bundle["sha256"]:
        failures.append("bundle_inventory_digest")
    actual_bytes = 0
    for item in expected_files:
        path = local_root / item["relative_name"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
            failures.append(f"bundle_file:{item['relative_name']}")
        else:
            actual_bytes += item["bytes"]
    if actual_bytes != bundle["bytes"] or bundle["bytes"] != summary["local_artifact_bundle"]["bytes"]:
        failures.append("bundle_bytes")
    if bundle["sha256"] != summary["local_artifact_bundle"]["sha256"]:
        failures.append("bundle_summary_digest")

    public_documents = [summary]
    for name in ("benchmark_receipt.json", "input_integrity_report.json"):
        public_documents.append(json.loads((repository / "reports/m1_b0" / name).read_text(encoding="utf-8")))
    for document in public_documents:
        failures.extend(public_sanitation_errors(document))

    return {
        "passed": not failures,
        "failures": failures,
        "repository_json_files_parsed": len(json_files),
        "tile_surface_rows": tile_rows,
        "temporal_surface_rows": temporal_rows,
        "csv_rows": csv_rows,
        "bundle_files": len(expected_files),
        "bundle_bytes": bundle["bytes"],
        "bundle_sha256": bundle["sha256"],
        "summary_sha256": _sha256(summary_path),
        "summary_digest": digest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit M1-B0 public and local evidence")
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    arguments = parser.parse_args()
    result = audit(arguments.repository.resolve(), arguments.local_root.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
