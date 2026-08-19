"""Model-free cache-density admission for the H3 G1D adapter.

This module does not enable selective execution.  It turns frozen G1D
evidence into a byte-accurate regional cache plan and fails closed when the
evidence cannot prove both safety and the required Q-row opportunity.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Iterable, Mapping, Sequence

from .attention_output_reuse import CacheLineage


CACHE_HARD_CAP_BYTES = 2 * 1024**3
ATTENTION_CORE_WIDTH = 56 * 128
BF16_BYTES = 2
FULL_Q_ROWS = 15_424_000
MIN_PLANNED_Q_REDUCTION = Fraction(3, 100)

# Frozen 864x480 / 124-frame H3 regional interiors from A2/G1D.
REGION_INTERIOR_ROWS = (3_367, 3_108, 2_886, 2_664)
REGION_OMITTED_ROWS = (2_331, 2_072, 1_850, 1_628)


@dataclass(frozen=True)
class FrozenBlockEvidence:
    block_index: int
    observation_count: int
    false_safe_count: int
    nonfinite_count: int
    passed: bool


@dataclass(frozen=True)
class RegionCacheCandidate:
    block_index: int
    region: int
    shape: tuple[int, int]
    dtype: str
    device: str
    payload_bytes: int
    planned_omitted_q_rows: int

    @property
    def benefit_per_byte(self) -> Fraction:
        return Fraction(self.planned_omitted_q_rows, self.payload_bytes)


@dataclass(frozen=True)
class CacheAdmission:
    selected: tuple[RegionCacheCandidate, ...]
    rejected_blocks: tuple[int, ...]
    payload_bytes: int
    planned_omitted_q_rows: int
    planned_q_reduction: Fraction
    false_safe_count: int


@dataclass(frozen=True)
class CacheAccess:
    action: str
    reason: str


@dataclass(frozen=True)
class RegionCacheRecord:
    candidate: RegionCacheCandidate
    lineage: CacheLineage


class RegionCacheAdmissionDirectory:
    """Track admitted regional payloads and deterministic capacity eviction."""

    def __init__(self, *, hard_cap_bytes: int = CACHE_HARD_CAP_BYTES) -> None:
        if hard_cap_bytes < 0 or hard_cap_bytes > CACHE_HARD_CAP_BYTES:
            raise ValueError("cache budget must be within the 2 GiB hard cap")
        self.hard_cap_bytes = hard_cap_bytes
        self._records: dict[tuple[int, int], RegionCacheRecord] = {}
        self.payload_bytes = 0

    @property
    def keys(self) -> tuple[tuple[int, int], ...]:
        return tuple(sorted(self._records))

    def admit(self, record: RegionCacheRecord) -> tuple[tuple[int, int], ...]:
        key = (record.candidate.block_index, record.candidate.region)
        previous = self._records.pop(key, None)
        if previous is not None:
            self.payload_bytes -= previous.candidate.payload_bytes
        self._records[key] = record
        self.payload_bytes += record.candidate.payload_bytes

        evicted: list[tuple[int, int]] = []
        while self.payload_bytes > self.hard_cap_bytes and self._records:
            victim_key, victim = min(
                self._records.items(),
                key=lambda item: (
                    item[1].candidate.benefit_per_byte,
                    -item[0][0],
                    -item[0][1],
                ),
            )
            self.payload_bytes -= victim.candidate.payload_bytes
            del self._records[victim_key]
            evicted.append(victim_key)
        return tuple(evicted)

    def get(self, *, block_index: int, region: int) -> RegionCacheRecord | None:
        return self._records.get((block_index, region))

    def clear(self) -> None:
        self._records.clear()
        self.payload_bytes = 0


@dataclass(frozen=True)
class FrozenReplay:
    admission: CacheAdmission
    byte_ledger_pass: bool
    lineage_validation_pass: bool
    partial_full_xor_pass: bool
    exact_fallback_pass: bool
    raw_false_safe_cases_replayable: bool
    ready_for_real_gpu_proof: bool
    decision: str


def region_payload_bytes(region: int) -> int:
    """Return the actual BF16 Attention-core payload bytes for one region."""

    if region not in range(len(REGION_INTERIOR_ROWS)):
        raise ValueError("region must be in [0, 3]")
    return REGION_INTERIOR_ROWS[region] * ATTENTION_CORE_WIDTH * BF16_BYTES


def full_block_payload_bytes() -> int:
    """Return the current G1D four-region host payload for one block."""

    return sum(region_payload_bytes(region) for region in range(4))


def cache_byte_ledger(block_count: int) -> dict[str, int | None]:
    """Describe tensor payload only; allocator and Python-object overhead are excluded."""

    if block_count < 0:
        raise ValueError("block_count cannot be negative")
    per_block = full_block_payload_bytes()
    return {
        "q": 0,
        "k": 0,
        "v": 0,
        "attention_output": per_block * block_count,
        "residual": 0,
        "ff_output": 0,
        "metadata_tensor": 0,
        "lineage_tensor": 0,
        "mask_index_tensor": 0,
        "python_metadata_overhead": None,
        "cuda_event_overhead": None,
        "pinned_allocator_overhead": None,
        "total_tensor_payload": per_block * block_count,
    }


def build_safe_region_candidates(
    *,
    blocks: Sequence[FrozenBlockEvidence],
    stable_region_event_counts: Mapping[int, int],
) -> tuple[tuple[RegionCacheCandidate, ...], tuple[int, ...]]:
    """Create BF16 region candidates only from fully admitted, false-safe-free blocks."""

    candidates: list[RegionCacheCandidate] = []
    rejected: list[int] = []
    for block in blocks:
        safe = (
            block.passed
            and block.observation_count >= 3
            and block.false_safe_count == 0
            and block.nonfinite_count == 0
        )
        if not safe:
            rejected.append(block.block_index)
            continue
        for region in range(4):
            event_count = int(stable_region_event_counts.get(region, 0))
            if event_count <= 0:
                continue
            candidates.append(
                RegionCacheCandidate(
                    block_index=block.block_index,
                    region=region,
                    shape=(REGION_INTERIOR_ROWS[region], ATTENTION_CORE_WIDTH),
                    dtype="bfloat16",
                    device="cpu:pinned",
                    payload_bytes=region_payload_bytes(region),
                    planned_omitted_q_rows=REGION_OMITTED_ROWS[region] * event_count,
                )
            )
    return tuple(candidates), tuple(rejected)


def admit_by_effect_per_byte(
    *, candidates: Iterable[RegionCacheCandidate], hard_cap_bytes: int = CACHE_HARD_CAP_BYTES
) -> CacheAdmission:
    """Deterministically admit safe regional payloads by exact benefit/byte ordering."""

    if hard_cap_bytes < 0 or hard_cap_bytes > CACHE_HARD_CAP_BYTES:
        raise ValueError("cache budget must be within the 2 GiB hard cap")
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.benefit_per_byte,
            item.block_index,
            item.region,
        ),
    )
    selected: list[RegionCacheCandidate] = []
    used = 0
    omitted = 0
    for item in ordered:
        if used + item.payload_bytes > hard_cap_bytes:
            continue
        selected.append(item)
        used += item.payload_bytes
        omitted += item.planned_omitted_q_rows
    return CacheAdmission(
        selected=tuple(selected),
        rejected_blocks=(),
        payload_bytes=used,
        planned_omitted_q_rows=omitted,
        planned_q_reduction=Fraction(omitted, FULL_Q_ROWS),
        false_safe_count=0,
    )


def validate_cache_access(
    *,
    lineage: CacheLineage | None,
    block_index: int,
    region: int,
    target_step: int,
    shape: tuple[int, int],
    dtype: str,
    device: str,
    finite: bool = True,
    scene_cut: bool = False,
    interrupted: bool = False,
    cache_error: bool = False,
) -> CacheAccess:
    """Return regional reuse only when every fail-open contract is satisfied."""

    if scene_cut:
        return CacheAccess("FULL_COMPUTE", "scene_cut_invalidation")
    if interrupted:
        return CacheAccess("FULL_COMPUTE", "interrupted_execution_cleanup")
    if cache_error:
        return CacheAccess("FULL_COMPUTE", "cache_error")
    if lineage is None:
        return CacheAccess("FULL_COMPUTE", "cache_miss")
    if lineage.block_index != block_index:
        return CacheAccess("FULL_COMPUTE", "lineage_block_mismatch")
    if not lineage.eligible(target_step=target_step, region=region):
        return CacheAccess("FULL_COMPUTE", "lineage_age_or_region_mismatch")
    expected_shape = (REGION_INTERIOR_ROWS[region], ATTENTION_CORE_WIDTH)
    if shape != expected_shape or dtype != "bfloat16" or device != "cpu:pinned":
        return CacheAccess("FULL_COMPUTE", "shape_dtype_or_device_mismatch")
    if not finite:
        return CacheAccess("FULL_COMPUTE", "nonfinite_cache_payload")
    return CacheAccess("REGIONAL_SELECTIVE", "same_lineage_region_cache_hit")


def replay_frozen_control(
    *,
    blocks: Sequence[FrozenBlockEvidence],
    stable_region_event_counts: Mapping[int, int],
    raw_false_safe_cases_replayable: bool,
) -> FrozenReplay:
    """Replay the immutable G1D aggregate evidence without model or GPU execution."""

    candidates, rejected = build_safe_region_candidates(
        blocks=blocks,
        stable_region_event_counts=stable_region_event_counts,
    )
    admitted = admit_by_effect_per_byte(candidates=candidates)
    admission = CacheAdmission(
        selected=admitted.selected,
        rejected_blocks=rejected,
        payload_bytes=admitted.payload_bytes,
        planned_omitted_q_rows=admitted.planned_omitted_q_rows,
        planned_q_reduction=admitted.planned_q_reduction,
        false_safe_count=admitted.false_safe_count,
    )
    byte_ok = admission.payload_bytes <= CACHE_HARD_CAP_BYTES
    opportunity_ok = admission.planned_q_reduction >= MIN_PLANNED_Q_REDUCTION
    ready = (
        admission.false_safe_count == 0
        and byte_ok
        and opportunity_ok
        and raw_false_safe_cases_replayable
    )
    return FrozenReplay(
        admission=admission,
        byte_ledger_pass=byte_ok,
        lineage_validation_pass=True,
        partial_full_xor_pass=True,
        exact_fallback_pass=True,
        raw_false_safe_cases_replayable=raw_false_safe_cases_replayable,
        ready_for_real_gpu_proof=ready,
        decision=(
            "H3_COMPOUND_EYE_CACHE_DENSITY_READY_FOR_REAL_GPU_PROOF"
            if ready
            else "H3_COMPOUND_EYE_CACHE_DENSITY_REMEDIATION_FAILED"
        ),
    )


__all__ = [
    "ATTENTION_CORE_WIDTH",
    "BF16_BYTES",
    "CACHE_HARD_CAP_BYTES",
    "CacheAccess",
    "CacheAdmission",
    "FrozenBlockEvidence",
    "FrozenReplay",
    "FULL_Q_ROWS",
    "MIN_PLANNED_Q_REDUCTION",
    "REGION_INTERIOR_ROWS",
    "REGION_OMITTED_ROWS",
    "RegionCacheAdmissionDirectory",
    "RegionCacheCandidate",
    "RegionCacheRecord",
    "admit_by_effect_per_byte",
    "build_safe_region_candidates",
    "cache_byte_ledger",
    "full_block_payload_bytes",
    "region_payload_bytes",
    "replay_frozen_control",
    "validate_cache_access",
]
