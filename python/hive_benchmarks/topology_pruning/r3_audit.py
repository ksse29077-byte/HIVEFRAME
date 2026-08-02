"""Independent arithmetic and evidence audit for committed M1-P0-R3 results."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from hive_benchmarks.topology_pruning.r3_runner import (
    CONFIG_PATH,
    ROOT,
    _implementation_order,
    _summaries,
    decide,
    load_json,
    validate_config,
    validate_immutable_r2,
)
from hive_benchmarks.topology_pruning.paired_normalization import (
    deterministic_case_b_order,
    sha256_file,
)


EVIDENCE = ROOT / "reports" / "topology_pruning" / "r3"


def audit(root: Path = ROOT) -> dict[str, Any]:
    config_path = root / CONFIG_PATH.relative_to(ROOT)
    evidence = root / EVIDENCE.relative_to(ROOT)
    config = load_json(config_path)
    result = load_json(evidence / "inprocess-boundary-results.json")
    parity = load_json(evidence / "parity-report.json")
    copies = load_json(evidence / "copy-accounting.json")
    predeclared = load_json(evidence / "predeclared-boundary-contract.json")
    decision_text = (evidence / "decision-report.md").read_text(encoding="utf-8")

    assertions = 0

    def require(condition: bool, message: str) -> None:
        nonlocal assertions
        assertions += 1
        if not condition:
            raise AssertionError(message)

    validate_config(config)
    validate_immutable_r2(config)
    require(predeclared["source_config_sha256"] == sha256_file(config_path), "config hash")
    require(result["run_kind"] == config["run_kind"], "run kind")
    require(result["warmups"] == 5 and result["repetitions"] == 30, "run counts")
    require(result["profile"] == config["profile"], "profile")
    require(result["topologies"] == ["T0", "T1", "T2"], "topologies")
    require(result["model_loaded"] is False and result["cuda_used"] is False, "model boundary")
    require(len(result["samples"]) == 90, "sample count")

    counts = Counter(sample["candidate_id"] for sample in result["samples"])
    require(counts == Counter({"T0": 30, "T1": 30, "T2": 30}), "candidate counts")
    by_block: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sample in result["samples"]:
        by_block[int(sample["block_index"])].append(sample)
        candidate = sample["candidate_id"]
        require(
            sample["implementation_order"]
            == list(_implementation_order(101, "measured", sample["block_index"], candidate)),
            "implementation order",
        )
        require(
            sample["paired_boundary_delta_ns"]
            == sample["rust"]["wrapper_total_ns"] - sample["python"]["outer_total_ns"],
            "paired delta",
        )
        require(sample["rust"]["ffi_calls"] == 1, "one FFI call")
        require(sample["rust"]["subprocess_count"] == 0, "no subprocess")
        require(sample["rust"]["temporary_file_count"] == 0, "no temp file")
        require(sample["rust"]["input_copy_bytes"] == 0, "zero input copy")
        require(sample["rust"]["input_borrowed"] is True, "borrowed input")
        require(sample["rust"]["input_readonly"] is True, "read-only input")
        require(sample["rust"]["input_c_contiguous"] is True, "C input")
        require(
            sample["rust"]["ffi_enter_exit_residual_ns"]
            == sample["rust"]["wrapper_total_ns"] - sample["rust"]["rust_function_span_ns"],
            "FFI residual",
        )
        require(sample["python"]["semantic_hash"] == sample["rust"]["semantic_hash"], "parity")
        require("semantic_result" not in sample, "no repeated semantic payload")
        require(sample["semantic_ref"] in result["semantic_evidence"], "semantic ref")
        require(
            result["semantic_evidence"][sample["semantic_ref"]]["semantic_hash"]
            == sample["rust"]["semantic_hash"],
            "semantic ref hash",
        )

    require(set(by_block) == set(range(30)), "block indices")
    for block, samples in sorted(by_block.items()):
        require({sample["candidate_id"] for sample in samples} == {"T0", "T1", "T2"}, "block members")
        ordered = [
            sample["candidate_id"]
            for sample in sorted(samples, key=lambda item: item["candidate_order_index"])
        ]
        require(ordered == list(deterministic_case_b_order(101, "measured", block)), "candidate order")

    recomputed = _summaries(result["samples"])
    require(recomputed == result["summaries"], "summary arithmetic")
    require(parity["pairs"] == 90, "parity pairs")
    require(parity["semantic_parity_rate"] == 1.0, "semantic parity rate")
    require(parity["deterministic_hashes"] is True, "determinism")
    require(parity["input_hash_stable"] is True, "input stability")
    require(parity["r1_hash_parity"] is True, "R1 parity")
    require(copies["input_copy_bytes"] == 0, "copy report")
    require(copies["subprocess_count"] == 0, "subprocess report")
    require(copies["temporary_file_count"] == 0, "temporary-file report")
    require(copies["ffi_calls_per_candidate"] == 1, "FFI report")
    require(copies["per_eye_ffi_calls"] == 0, "per-Eye report")
    require(copies["allocation_count"]["value"] is None, "allocation null")
    require(copies["unavailable_values_are_null"] is True, "unavailable semantics")

    decision = decide(config, recomputed, parity, copies)
    require(decision["decision"] == "RUST_CONTROL_PLANE_ADMITTED", "Gate")
    require("Decision: **RUST_CONTROL_PLANE_ADMITTED**" in decision_text, "decision report")
    require("MONO_FIRST" not in decision_text, "no Mono-first decision")

    public = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(evidence.iterdir())
        if path.is_file()
    )
    private_path = re.compile(
        r"(?i)(?:[A-Z]:[\\/]|/(?:home|Users)/[^/\s]+/|AppData[\\/]|OneDrive[\\/])"
    )
    require(private_path.search(public) is None, "private path scan")
    require("pointer_address" not in public, "address scan")
    require(len(result["semantic_evidence"]) == 3, "one semantic identity per candidate")

    return {
        "assertions": assertions,
        "failures": 0,
        "decision": decision["decision"],
        "samples": len(result["samples"]),
        "pairs_per_candidate": dict(sorted(counts.items())),
    }


def main() -> int:
    print(json.dumps(audit(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
