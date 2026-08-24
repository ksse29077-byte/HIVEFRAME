"""Production-shaped executor boundary for the bounded H3 V4 cache plan.

The executor never decides whether a row is safe.  It validates a frozen Rust
CachePlan and either runs one reduced-Q attention call plus exact cache reuse,
or immediately uses the unchanged Full Attention callable.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter_ns
from typing import Any, Callable, Mapping

from .h3_bounded_host_source_oracle_v4 import (
    CALIBRATION_VETO_BLOCKS,
    OMITTED_POSITIONS,
    REGION_ROWS,
)
from .h3_row_region_safety import SHAPE_WIDTH


STANDARD_FULL = "STANDARD_FULL"
V4_CONTROL_FULL_COMPUTE = "V4_CONTROL_FULL_COMPUTE"
V4_EXECUTOR_BENCHMARK = "V4_EXECUTOR_BENCHMARK"
V4_SELECTIVE_FUTURE = "V4_SELECTIVE_FUTURE"
ALLOWED_ACTIVE_PROFILES = frozenset(
    {V4_CONTROL_FULL_COMPUTE, V4_EXECUTOR_BENCHMARK}
)
FULL_SEQUENCE_ROWS = 15_424
H3_HEADS = 56
H3_HEAD_DIM = 128
H3_DTYPE = "torch.bfloat16"
H3_LAYOUT = "H3_PACKED_SEQUENCE_HEADS_DIM_V1"


class V4ExecutorContractError(ValueError):
    """Reject an invalid profile or an internally inconsistent row plan."""


def _digest(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).hexdigest()


@dataclass(frozen=True)
class V4GenerationContext:
    """Immutable identity and tensor contract for one generation."""

    generation_digest: str
    model_digest: str
    settings_digest: str
    scheduler_digest: str
    input_digest: str
    sequence_rows: int = FULL_SEQUENCE_ROWS
    heads: int = H3_HEADS
    head_dim: int = H3_HEAD_DIM
    dtype: str = H3_DTYPE
    device: str = "cuda:0"
    layout: str = H3_LAYOUT

    def digest(self) -> str:
        return _digest(self.__dict__)


@dataclass(frozen=True)
class V4ExecutorPlan:
    """CPU metadata produced from one admitted CachePlan selection."""

    context_digest: str
    lineage_digest: str
    step: int
    block: int
    computed_rows: tuple[int, ...]
    reused_rows: tuple[int, ...]
    cache_region_rows: tuple[int, ...]
    cache_reused_positions: tuple[int, ...]

    @classmethod
    def frozen_region_zero(
        cls,
        context: V4GenerationContext,
        *,
        lineage_digest: str,
        step: int = 1,
        block: int = 0,
    ) -> "V4ExecutorPlan":
        reused = tuple(REGION_ROWS[position] for position in OMITTED_POSITIONS)
        reused_set = frozenset(reused)
        computed = tuple(
            row for row in range(context.sequence_rows) if row not in reused_set
        )
        return cls(
            context_digest=context.digest(),
            lineage_digest=lineage_digest,
            step=step,
            block=block,
            computed_rows=computed,
            reused_rows=reused,
            cache_region_rows=tuple(REGION_ROWS),
            cache_reused_positions=tuple(OMITTED_POSITIONS),
        )

    @classmethod
    def from_rust_cache_plan(
        cls,
        context: V4GenerationContext,
        cache_plan: Mapping[str, Any],
        *,
        lineage_digest: str,
        step: int,
        block: int,
        region: int = 0,
    ) -> "V4ExecutorPlan":
        """Decode one selected block/region from the release CachePlan V2 result."""

        if int(cache_plan.get("decision_code", 0)) != 1 or bool(
            cache_plan.get("fallback_required", True)
        ):
            raise V4ExecutorContractError("Rust CachePlan is not PLAN_READY")
        if int(cache_plan.get("planned_reduction_ppm", 0)) < 30_000:
            raise V4ExecutorContractError("Rust CachePlan is below the fixed 3% Gate")
        matches = [
            item
            for item in cache_plan.get("selected", ())
            if int(item.get("block_index", -1)) == block
            and int(item.get("region", -1)) == region
        ]
        if len(matches) != 1:
            raise V4ExecutorContractError(
                "Rust CachePlan selection is missing or duplicated"
            )
        selected = matches[0]
        if int(selected.get("planned_q_rows", -1)) != len(OMITTED_POSITIONS):
            raise V4ExecutorContractError("Rust CachePlan row geometry changed")
        if int(selected.get("payload_bytes", -1)) != len(REGION_ROWS) * SHAPE_WIDTH * 2:
            raise V4ExecutorContractError("Rust CachePlan payload geometry changed")
        return cls.frozen_region_zero(
            context,
            lineage_digest=lineage_digest,
            step=step,
            block=block,
        )

    def validate_partition(self, sequence_rows: int) -> None:
        computed = self.computed_rows
        reused = self.reused_rows
        if not computed or not reused:
            raise V4ExecutorContractError("V4 plan requires computed and reused rows")
        if len(set(computed)) != len(computed) or len(set(reused)) != len(reused):
            raise V4ExecutorContractError("V4 plan contains duplicate rows")
        if set(computed).intersection(reused):
            raise V4ExecutorContractError("V4 computed and reused rows overlap")
        union = set(computed).union(reused)
        if union != set(range(sequence_rows)):
            raise V4ExecutorContractError("V4 plan does not cover the full sequence")
        if min(union) < 0 or max(union) >= sequence_rows:
            raise V4ExecutorContractError("V4 plan row is out of bounds")
        if len(self.cache_region_rows) != len(REGION_ROWS):
            raise V4ExecutorContractError("V4 cache region geometry changed")
        if len(self.cache_reused_positions) != len(reused):
            raise V4ExecutorContractError("V4 cache positions do not match reused rows")


@dataclass
class V4GpuPlan:
    """Generation-scoped GPU indices materialized once from V4ExecutorPlan."""

    cpu: V4ExecutorPlan
    computed_indices: Any
    reused_indices: Any
    cache_region_indices: Any
    cache_reused_positions: Any


@dataclass
class V4CacheHandle:
    """One exact BF16 region payload and its immutable lineage."""

    context_digest: str
    lineage_digest: str
    tensor: Any


@dataclass
class V4ExecutionResult:
    """Executor row accounting and fallback receipt."""

    output: Any
    mode: str
    full_rows: int
    planned_reusable_rows: int
    actual_computed_rows: int
    actual_reused_rows: int
    fallback_rows: int
    fallback_reason: str | None
    context_validation_ns: int


def materialize_gpu_plan(
    torch_module: Any, plan: V4ExecutorPlan, context: V4GenerationContext
) -> V4GpuPlan:
    """Validate CPU metadata and materialize its indices on the context device."""

    plan.validate_partition(context.sequence_rows)
    device = torch_module.device(context.device)
    return V4GpuPlan(
        cpu=plan,
        computed_indices=torch_module.tensor(
            plan.computed_rows, dtype=torch_module.long, device=device
        ),
        reused_indices=torch_module.tensor(
            plan.reused_rows, dtype=torch_module.long, device=device
        ),
        cache_region_indices=torch_module.tensor(
            plan.cache_region_rows, dtype=torch_module.long, device=device
        ),
        cache_reused_positions=torch_module.tensor(
            plan.cache_reused_positions, dtype=torch_module.long, device=device
        ),
    )


def validate_runtime_contract(
    *,
    profile: str,
    context: V4GenerationContext,
    plan: V4ExecutorPlan,
    cache: V4CacheHandle | None,
    q: Any,
    k: Any,
    v: Any,
) -> tuple[str | None, int]:
    """Return a fallback reason without synchronizing or inspecting tensor values."""

    started = perf_counter_ns()
    reason = None
    if profile not in ALLOWED_ACTIVE_PROFILES:
        reason = "PROFILE_NOT_AUTHORIZED"
    elif profile == V4_CONTROL_FULL_COMPUTE:
        reason = "CONTROL_FULL_COMPUTE"
    elif plan.block in CALIBRATION_VETO_BLOCKS:
        reason = "CALIBRATION_VETO_BLOCK"
    elif plan.context_digest != context.digest():
        reason = "CONTEXT_MISMATCH"
    elif cache is None:
        reason = "CACHE_MISS"
    elif cache.context_digest != plan.context_digest:
        reason = "CACHE_CONTEXT_MISMATCH"
    elif cache.lineage_digest != plan.lineage_digest:
        reason = "CACHE_LINEAGE_MISMATCH"
    else:
        expected = (context.sequence_rows, context.heads, context.head_dim)
        tensors = (q, k, v)
        if any(tuple(tensor.shape) != expected for tensor in tensors):
            reason = "TENSOR_SHAPE_MISMATCH"
        elif any(str(tensor.dtype) != context.dtype for tensor in tensors):
            reason = "TENSOR_DTYPE_MISMATCH"
        elif any(str(tensor.device) != context.device for tensor in tensors):
            reason = "TENSOR_DEVICE_MISMATCH"
        elif tuple(cache.tensor.shape) != (
            len(plan.cache_region_rows),
            SHAPE_WIDTH,
        ):
            reason = "CACHE_SHAPE_MISMATCH"
        elif str(cache.tensor.dtype) != context.dtype:
            reason = "CACHE_DTYPE_MISMATCH"
        elif str(cache.tensor.device) != context.device:
            reason = "CACHE_DEVICE_MISMATCH"
    return reason, perf_counter_ns() - started


class V4ExecutorAdapter:
    """Execute Full Attention or one production-shaped selective target."""

    def __init__(
        self,
        *,
        torch_module: Any,
        profile: str,
        context: V4GenerationContext,
        full_attention: Callable[[Any, Any, Any], Any],
    ) -> None:
        if profile not in ALLOWED_ACTIVE_PROFILES:
            raise V4ExecutorContractError(
                f"runtime profile is not authorized in this task: {profile}"
            )
        self.torch = torch_module
        self.profile = profile
        self.context = context
        self.full_attention = full_attention

    def capture_cache(
        self, full_output: Any, gpu_plan: V4GpuPlan
    ) -> V4CacheHandle:
        """Capture the exact region payload used by a later age-one target."""

        payload = full_output.index_select(0, gpu_plan.cache_region_indices)
        return V4CacheHandle(
            context_digest=gpu_plan.cpu.context_digest,
            lineage_digest=gpu_plan.cpu.lineage_digest,
            tensor=payload,
        )

    def execute(
        self,
        *,
        q: Any,
        k: Any,
        v: Any,
        gpu_plan: V4GpuPlan,
        cache: V4CacheHandle | None,
    ) -> V4ExecutionResult:
        """Run exactly one Full or selective branch; never both."""

        plan = gpu_plan.cpu
        fallback_reason, validation_ns = validate_runtime_contract(
            profile=self.profile,
            context=self.context,
            plan=plan,
            cache=cache,
            q=q,
            k=k,
            v=v,
        )
        if fallback_reason is not None:
            output = self.full_attention(q, k, v)
            return V4ExecutionResult(
                output=output,
                mode="FULL",
                full_rows=self.context.sequence_rows,
                planned_reusable_rows=len(plan.reused_rows),
                actual_computed_rows=self.context.sequence_rows,
                actual_reused_rows=0,
                fallback_rows=self.context.sequence_rows,
                fallback_reason=fallback_reason,
                context_validation_ns=validation_ns,
            )

        selected_q = q.index_select(0, gpu_plan.computed_indices)
        computed = self.full_attention(selected_q, k, v)
        reused = cache.tensor.index_select(0, gpu_plan.cache_reused_positions)
        output = computed.new_empty((self.context.sequence_rows, SHAPE_WIDTH))
        output.index_copy_(0, gpu_plan.computed_indices, computed)
        output.index_copy_(0, gpu_plan.reused_indices, reused)
        return V4ExecutionResult(
            output=output,
            mode="SELECTIVE",
            full_rows=self.context.sequence_rows,
            planned_reusable_rows=len(plan.reused_rows),
            actual_computed_rows=len(plan.computed_rows),
            actual_reused_rows=len(plan.reused_rows),
            fallback_rows=0,
            fallback_reason=None,
            context_validation_ns=validation_ns,
        )


__all__ = [
    "ALLOWED_ACTIVE_PROFILES",
    "FULL_SEQUENCE_ROWS",
    "H3_DTYPE",
    "H3_HEAD_DIM",
    "H3_HEADS",
    "H3_LAYOUT",
    "STANDARD_FULL",
    "V4_CONTROL_FULL_COMPUTE",
    "V4_EXECUTOR_BENCHMARK",
    "V4_SELECTIVE_FUTURE",
    "V4CacheHandle",
    "V4ExecutionResult",
    "V4ExecutorAdapter",
    "V4ExecutorContractError",
    "V4ExecutorPlan",
    "V4GenerationContext",
    "V4GpuPlan",
    "materialize_gpu_plan",
    "validate_runtime_contract",
]
