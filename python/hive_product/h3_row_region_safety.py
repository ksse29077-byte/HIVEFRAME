"""Bounded row/region safety evidence for one Full Compute H3 CONTROL."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping, Sequence
import json
import struct

from .a3_g1_conditional_reuse import (
    CONTROL_MODE,
    ELIGIBLE_CACHE_SOURCE_STEPS,
    H3A3G1Controller,
    HostCacheEntry,
    source_step_cache_eligible,
)
from .active_query_attention import AttentionRegionPlanBridge, REGION_COUNT
from .attention_output_reuse import (
    CATASTROPHIC_COSINE_MIN,
    CATASTROPHIC_NORMALIZED_L2_MAX,
)
from .regional_query_prototype_attention import CPU_PROTOTYPE_PLANS
from .rust_cache_plan_v2 import (
    CANDIDATE_FIELDS,
    GenerationIdentity,
    cache_lineage_v2_digest,
    stable_digest,
)


SCHEMA_VERSION = "h3.row-region-safety-evidence.1"
MAX_EVIDENCE_RECORDS = 640
CACHE_HARD_CAP_BYTES = 2 * 1024**3
TRANSFER_BUDGET_BYTES = 40 * 1024**3
SHAPE_WIDTH = 7_168
FULL_Q_ROWS = 15_424_000
SOURCE_PLAN_DIGEST_LABEL = "h3-rust-cache-plan-abi-v2@8455f479"
LAYOUT_DIGEST_LABEL = "h3-packed-video-15424x7168-regions-v1"

EVIDENCE_KEYS = tuple(
    (block, region)
    for block in (*range(32), 48, 49)
    for region in (range(REGION_COUNT) if block in {48, 49} else (0,))
)
EVIDENCE_BLOCKS = tuple(dict.fromkeys(block for block, _ in EVIDENCE_KEYS))
FALSE_UNSAFE_PROBE_BLOCKS = frozenset({48, 49})

STATE_TO_ABI = {"STABLE": 1, "ACTIVE": 2, "UNCERTAIN": 3}


class EvidenceBudgetError(Exception):
    """Stop the one-shot CONTROL instead of retaining truncated evidence."""


def _region_rows(region: int) -> tuple[int, ...]:
    details = CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]
    return tuple(sorted((*details["representative"], *details["omitted"])))


def _row_digest(region: int) -> bytes:
    hasher = sha256(b"hiveframe-h3-packed-row-region-v1")
    for row in _region_rows(region):
        hasher.update(struct.pack("<I", int(row)))
    return hasher.digest()


def _shape_digest(region: int) -> bytes:
    rows = len(_region_rows(region))
    return sha256(f"bf16:{rows}:{SHAPE_WIDTH}:cpu-pinned".encode()).digest()


def evidence_design_receipt() -> dict[str, Any]:
    payloads = {
        region: len(_region_rows(region)) * SHAPE_WIDTH * 2
        for region in range(REGION_COUNT)
    }
    cache_bytes = sum(payloads[region] for _, region in EVIDENCE_KEYS)
    maximum_records = len(EVIDENCE_KEYS) * len(ELIGIBLE_CACHE_SOURCE_STEPS)
    return {
        "key_count": len(EVIDENCE_KEYS),
        "candidate_block_count": len(EVIDENCE_BLOCKS),
        "maximum_records": maximum_records,
        "record_limit": MAX_EVIDENCE_RECORDS,
        "cache_bytes": cache_bytes,
        "cache_hard_cap_bytes": CACHE_HARD_CAP_BYTES,
        "cache_admitted": cache_bytes <= CACHE_HARD_CAP_BYTES,
        "transfer_budget_bytes": TRANSFER_BUDGET_BYTES,
        "payload_bytes_by_region": payloads,
    }


def settings_digest() -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": CONTROL_MODE,
        "evidence_keys": EVIDENCE_KEYS,
        "maximum_records": MAX_EVIDENCE_RECORDS,
        "cache_hard_cap_bytes": CACHE_HARD_CAP_BYTES,
        "transfer_budget_bytes": TRANSFER_BUDGET_BYTES,
        "cosine_min": CATASTROPHIC_COSINE_MIN,
        "corrected_nl2_max": CATASTROPHIC_NORMALIZED_L2_MAX,
        "full_compute_only": True,
        "partial_q_execution": False,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SafetyEvidencePlanBridge(AttentionRegionPlanBridge):
    """Retain only bounded confidence/change metadata beside the Rust V1 plan."""

    def evaluate_event(self, event: Mapping[str, Any]) -> dict[str, Any] | None:
        plan = super().evaluate_event(event)
        if plan is not None:
            confidence = event.get("eye_confidence_ppm")
            change = event.get("eye_change_ppm")
            plan["eye_confidence_ppm"] = (
                [int(value) for value in confidence]
                if isinstance(confidence, list) and len(confidence) == 5
                else [0] * 5
            )
            plan["eye_change_ppm"] = (
                [int(value) for value in change]
                if isinstance(change, list) and len(change) == 5
                else [1_000_000] * 5
            )
        return plan


class H3RowRegionSafetyController(H3A3G1Controller):
    """Observe bounded regional drift while preserving exact Full Attention."""

    def __init__(self, *, plan_bridge: Any, h3_model: Any, torch_module: Any) -> None:
        super().__init__(
            mode=CONTROL_MODE,
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch_module,
            candidate_blocks=EVIDENCE_BLOCKS,
        )
        self._key_regions = {
            block: tuple(region for key_block, region in EVIDENCE_KEYS if key_block == block)
            for block in EVIDENCE_BLOCKS
        }
        self._evidence_gpu: list[dict[str, Any]] = []
        self.evidence_metadata_d2h_bytes = 0
        self.evidence_metadata_d2h_calls = 0

    def _check_transfer(self, additional_bytes: int) -> None:
        if self.d2h_bytes + self.h2d_bytes + int(additional_bytes) > TRANSFER_BUDGET_BYTES:
            raise EvidenceBudgetError("bounded evidence transfer budget would be exceeded")

    def _cache_entry(self, block_index: int, full_core: Any) -> HostCacheEntry:
        entry = self._host_cache.get(block_index)
        if entry is None:
            tensors = {
                region: self.torch.empty(
                    (int(self._region_cache_indices[region].numel()), int(full_core.shape[-1])),
                    dtype=full_core.dtype,
                    device="cpu",
                    pin_memory=True,
                )
                for region in self._key_regions[block_index]
            }
            added = sum(int(value.numel()) * int(value.element_size()) for value in tensors.values())
            if self.host_cache_bytes + added > CACHE_HARD_CAP_BYTES:
                raise EvidenceBudgetError("observation cache hard cap would be exceeded")
            entry = HostCacheEntry(tensors=tensors, event=self.torch.cuda.Event(blocking=False))
            self._host_cache[block_index] = entry
            self.host_cache_bytes += added
        return entry

    def _refresh_cache(self, *, block_index: int, step: int, full_core: Any) -> None:
        if not source_step_cache_eligible(step):
            self.skipped_ineligible_source_refreshes += 1
            return
        entry = self._cache_entry(block_index, full_core)
        refresh_bytes = sum(
            int(target.numel()) * int(target.element_size()) for target in entry.tensors.values()
        )
        self._check_transfer(refresh_bytes)
        for region, target in entry.tensors.items():
            indices = self._region_cache_indices[region]
            staging = self._region_staging[: int(indices.numel())]
            self.torch.index_select(full_core, 0, indices, out=staging)
            target.copy_(staging, non_blocking=True)
            self.d2h_bytes += int(target.numel()) * int(target.element_size())
        entry.event.record(self.torch.cuda.current_stream(device=full_core.device))
        entry.source_step = step
        entry.source_kind = "ACTUAL_FULL_ATTENTION_CORE_OUTPUT"
        entry.valid = True
        self.full_refreshes += 1
        self.eligible_source_steps_seen.add(step)

    @staticmethod
    def _predicted_state(plan: Mapping[str, Any] | None, region: int) -> str:
        if not isinstance(plan, Mapping) or bool(plan.get("global_invalidation", True)):
            return "UNCERTAIN"
        bit = 1 << region
        stable = plan.get("stable_region_mask", 0)
        active = plan.get("active_mask", 0)
        uncertain = plan.get("uncertain_mask", 0)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (stable, active, uncertain)):
            return "UNCERTAIN"
        if stable & bit and not ((active | uncertain) & bit):
            return "STABLE"
        if active & bit and not (uncertain & bit):
            return "ACTIVE"
        return "UNCERTAIN"

    def _observe_full_compute_control(
        self,
        *,
        block_index: int,
        step: int,
        plan: Mapping[str, Any] | None,
        directive: str,
        stable_mask: int,
        full_core: Any,
    ) -> None:
        del directive, stable_mask
        entry = self._host_cache.get(block_index)
        if entry is None or not entry.ready_for(target_step=step):
            return
        confidence = plan.get("eye_confidence_ppm", [0] * 5) if isinstance(plan, Mapping) else [0] * 5
        motion = plan.get("eye_change_ppm", [1_000_000] * 5) if isinstance(plan, Mapping) else [1_000_000] * 5
        for region in self._key_regions[block_index]:
            state = self._predicted_state(plan, region)
            if state != "STABLE" and block_index not in FALSE_UNSAFE_PROBE_BLOCKS:
                continue
            if len(self._evidence_gpu) >= MAX_EVIDENCE_RECORDS:
                raise EvidenceBudgetError("bounded evidence record limit would be exceeded")
            source = entry.tensors[region]
            payload_bytes = int(source.numel()) * int(source.element_size())
            self._check_transfer(payload_bytes)
            staging = self._upload_region(entry=entry, region=region)
            rows = self.plan_cache.get(1 << region).region_rows[region]
            positions = self._region_cache_positions[region]
            delta = self._channel_mean_delta(
                full_core=full_core, staging=staging, rows=rows, positions=positions
            )
            raw, corrected = self._bounded_region_metrics(
                full_core=full_core,
                staging=staging,
                rows=rows,
                positions=positions,
                delta=delta,
            )
            unsafe = (
                (~corrected["finite"])
                | (corrected["cosine"] < CATASTROPHIC_COSINE_MIN)
                | (corrected["normalized_l2"] > CATASTROPHIC_NORMALIZED_L2_MAX)
            )
            self._evidence_gpu.append(
                {
                    "step": step,
                    "source_step": entry.source_step,
                    "block": block_index,
                    "region": region,
                    "predicted_state": state,
                    "uncertainty_ppm": max(0, 1_000_000 - int(confidence[region + 1])),
                    "motion_ppm": int(motion[region + 1]),
                    "payload_bytes": payload_bytes,
                    "raw": raw,
                    "corrected": corrected,
                    "unsafe": unsafe,
                }
            )

    def _materialize_evidence(self) -> list[dict[str, Any]]:
        if not self._evidence_gpu:
            return []
        scalar_rows = []
        for item in self._evidence_gpu:
            values = []
            for group in ("raw", "corrected"):
                metrics = item[group]
                values.extend(
                    (
                        metrics["cosine"],
                        metrics["normalized_l2"],
                        metrics["normalized_mae"],
                        metrics["energy_ratio"],
                        metrics["finite"].to(dtype=self.torch.float32),
                    )
                )
            values.append(item["unsafe"].to(dtype=self.torch.float32))
            scalar_rows.append(self.torch.stack(tuple(values)).float())
        matrix = self.torch.stack(tuple(scalar_rows)).cpu()
        self.evidence_metadata_d2h_calls = 1
        self.evidence_metadata_d2h_bytes = int(matrix.numel()) * int(matrix.element_size())
        values = matrix.tolist()
        result = []
        names = ("cosine", "normalized_l2", "normalized_mae", "energy_ratio", "finite")
        for item, row in zip(self._evidence_gpu, values):
            record = {name: value for name, value in item.items() if name not in {"raw", "corrected", "unsafe"}}
            record["raw"] = {name: float(row[index]) for index, name in enumerate(names)}
            record["corrected"] = {
                name: float(row[5 + index]) for index, name in enumerate(names)
            }
            record["raw"]["finite"] = bool(record["raw"]["finite"])
            record["corrected"]["finite"] = bool(record["corrected"]["finite"])
            record["actual_safety"] = "UNSAFE" if bool(row[10]) else "SAFE"
            record["false_safe"] = (
                record["predicted_state"] == "STABLE" and record["actual_safety"] == "UNSAFE"
            )
            record["false_unsafe"] = (
                record["predicted_state"] != "STABLE" and record["actual_safety"] == "SAFE"
            )
            result.append(record)
        return result

    def finalize(self) -> dict[str, Any]:
        base = super().finalize()
        evidence = self._materialize_evidence()
        confusion = {
            "true_safe": sum(item["predicted_state"] == "STABLE" and item["actual_safety"] == "SAFE" for item in evidence),
            "false_safe": sum(item["false_safe"] for item in evidence),
            "true_unsafe": sum(item["predicted_state"] != "STABLE" and item["actual_safety"] == "UNSAFE" for item in evidence),
            "false_unsafe": sum(item["false_unsafe"] for item in evidence),
        }
        nonstable = sum(item["predicted_state"] != "STABLE" for item in evidence)
        base["safety_evidence"] = {
            "schema_version": SCHEMA_VERSION,
            "records": evidence,
            "record_count": len(evidence),
            "record_limit": MAX_EVIDENCE_RECORDS,
            "overflow": False,
            "confusion_matrix": confusion,
            "false_unsafe_status": "COLLECTED" if nonstable > 0 else "NOT_COLLECTED",
            "nonstable_probe_count": nonstable,
            "metadata_d2h_calls": self.evidence_metadata_d2h_calls,
            "metadata_d2h_bytes": self.evidence_metadata_d2h_bytes,
            "rust_tensor_transfer_bytes": 0,
        }
        base["cache"]["transfer_total_bytes"] = self.d2h_bytes + self.h2d_bytes
        base["cache"]["transfer_budget_bytes"] = TRANSFER_BUDGET_BYTES
        base["cache"]["cache_hard_cap_bytes"] = CACHE_HARD_CAP_BYTES
        base["partial_attention_calls"] = 0
        return base

    def close(self) -> None:
        for entry in self._host_cache.values():
            entry.invalidate()
            entry.tensors.clear()
        self._host_cache.clear()
        self._region_staging = None
        self._evidence_gpu.clear()


def generation_identity(
    *,
    run_digest_hex: str,
    workflow_digest_hex: str,
    model_digest_hex: str,
    settings_digest_hex: str,
    input_identity_digest_hex: str,
) -> dict[str, Any]:
    run_digest = bytes.fromhex(run_digest_hex)
    return GenerationIdentity(
        run_digest=run_digest,
        workflow_digest=bytes.fromhex(workflow_digest_hex),
        model_digest=bytes.fromhex(model_digest_hex),
        model_revision_digest=bytes.fromhex(model_digest_hex),
        settings_digest=bytes.fromhex(settings_digest_hex),
        source_plan_digest=stable_digest(SOURCE_PLAN_DIGEST_LABEL),
        layout_digest=stable_digest(LAYOUT_DIGEST_LABEL),
        input_identity_digest=bytes.fromhex(input_identity_digest_hex),
        generation_id=max(1, int.from_bytes(run_digest[:8], "little")),
        scheduler_id=1,
        total_steps=20,
        width=864,
        height=480,
        frame_count=124,
        fps_numerator=24,
        fps_denominator=1,
    ).as_dict()


def generation_candidates(
    identity: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if len(evidence) > MAX_EVIDENCE_RECORDS:
        raise ValueError("evidence batch exceeds the bounded record limit")
    records = []
    for item in evidence:
        region = int(item["region"])
        rows = _region_rows(region)
        corrected = item["corrected"]
        finite = bool(corrected["finite"])
        state = str(item["predicted_state"])
        safe = str(item["actual_safety"]) == "SAFE"
        payload_bytes = int(item["payload_bytes"])
        omitted_rows = len(CPU_PROTOTYPE_PLANS[1 << region].region_rows[region]["omitted"])
        record = {
            "target_step": int(item["step"]),
            "source_step": int(item["source_step"]),
            "block_index": int(item["block"]),
            "region": region,
            "packed_row_start": min(rows),
            "packed_row_count": len(rows),
            "state": STATE_TO_ABI[state],
            "actual_safety_state": 1 if safe else 2,
            "safety_evidence_present": 1,
            "uncertainty_ppm": int(item["uncertainty_ppm"]),
            "motion_ppm": int(item["motion_ppm"]),
            "cosine_ppm": max(0, min(1_000_000, round(float(corrected["cosine"]) * 1_000_000))),
            "corrected_nl2_ppm": max(0, round(float(corrected["normalized_l2"]) * 1_000_000)),
            "false_safe_count": int(bool(item["false_safe"])),
            "nonfinite_count": int(not finite),
            "cache_age": 1,
            "source_kind": 1,
            "shape_rows": len(rows),
            "shape_width": SHAPE_WIDTH,
            "dtype": 1,
            "device_class": 1,
            "precision": 1,
            "quantization": 1,
            "admission_eligible": int(state == "STABLE" and safe and finite),
            "rejection_reason": 0 if state == "STABLE" and safe and finite else 1,
            "planned_q_rows": omitted_rows,
            "full_q_rows": 15_424,
            "payload_bytes": payload_bytes,
            "effect_numerator": omitted_rows,
            "effect_denominator": payload_bytes,
            "planned_d2h_bytes": payload_bytes,
            "planned_h2d_bytes": payload_bytes,
            "shape_digest": _shape_digest(region),
            "packed_row_digest": _row_digest(region),
            "lineage_digest": bytes(32),
        }
        record["lineage_digest"] = cache_lineage_v2_digest(identity, record)
        if frozenset(record) != CANDIDATE_FIELDS:
            raise ValueError("generated candidate does not match ABI V2")
        records.append(record)
    return records


if evidence_design_receipt()["maximum_records"] > MAX_EVIDENCE_RECORDS:
    raise RuntimeError("row/region evidence design exceeds its fixed record bound")
if not evidence_design_receipt()["cache_admitted"]:
    raise RuntimeError("row/region evidence design exceeds its fixed cache bound")
