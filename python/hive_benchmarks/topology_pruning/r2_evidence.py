"""Lossless public-evidence transforms for M1-P0-R2 artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from hive_benchmarks.topology_pruning.r2_runner import (
    normalize_python_semantic_evidence,
    sanitize_rust_public_evidence,
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_python_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return normalize_python_semantic_evidence(copy.deepcopy(value))


def canonical_rust_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return sanitize_rust_public_evidence(copy.deepcopy(value))


def canonical_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def rewrite_pair(python_path: Path, rust_path: Path) -> dict[str, Any]:
    python_before = _load(python_path)
    rust_before = _load(rust_path)
    python_after = canonical_python_evidence(python_before)
    rust_after = canonical_rust_evidence(rust_before)
    _write(python_path, python_after)
    _write(rust_path, rust_after)
    return {
        "python_logical_digest": canonical_digest(python_after),
        "rust_logical_digest": canonical_digest(rust_after),
        "python_samples": len(python_after["samples"]),
        "rust_samples": len(rust_after["samples"]),
        "semantic_payloads": len(python_after["semantic_evidence"]),
    }


def compare_pairs(
    before_python: Path,
    after_python: Path,
    before_rust: Path,
    after_rust: Path,
) -> dict[str, Any]:
    before_python_value = canonical_python_evidence(_load(before_python))
    after_python_value = canonical_python_evidence(_load(after_python))
    before_rust_value = canonical_rust_evidence(_load(before_rust))
    after_rust_value = canonical_rust_evidence(_load(after_rust))
    before_python_digest = canonical_digest(before_python_value)
    after_python_digest = canonical_digest(after_python_value)
    before_rust_digest = canonical_digest(before_rust_value)
    after_rust_digest = canonical_digest(after_rust_value)
    return {
        "equivalent": (
            before_python_digest == after_python_digest
            and before_rust_digest == after_rust_digest
        ),
        "python": {
            "before": before_python_digest,
            "after": after_python_digest,
            "equivalent": before_python_digest == after_python_digest,
        },
        "rust": {
            "before": before_rust_digest,
            "after": after_rust_digest,
            "equivalent": before_rust_digest == after_rust_digest,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize or compare existing R2 public evidence."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    rewrite = subparsers.add_parser("rewrite")
    rewrite.add_argument("python_evidence", type=Path)
    rewrite.add_argument("rust_evidence", type=Path)
    compare = subparsers.add_parser("compare")
    compare.add_argument("before_python", type=Path)
    compare.add_argument("after_python", type=Path)
    compare.add_argument("before_rust", type=Path)
    compare.add_argument("after_rust", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.operation == "rewrite":
        result = rewrite_pair(args.python_evidence, args.rust_evidence)
    else:
        result = compare_pairs(
            args.before_python,
            args.after_python,
            args.before_rust,
            args.after_rust,
        )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
