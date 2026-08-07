"""Source-gated, Full Compute-only H3 DiTBlock cost instrumentation.

This module is H3-adapter code.  It measures six source-backed logical groups
with deferred CUDA events and never authorizes skip, reuse, prediction, or
partial execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Mapping, Sequence
import ast
import math
import time


MODEL_SOURCE_SHA256 = "882c280b05aa60cd17f231e5e2389b921b52880fb3b4e23574c0aba5f2bd5024"
MODEL_SOURCE_RELATIVE = Path("comfy/ldm/minimax/model.py")
BLOCK_COUNT = 50
STEP_COUNT = 20
EXPECTED_BLOCK_CALLS = BLOCK_COUNT * STEP_COUNT
REFERENCE_SAMPLER_SECONDS = 488.584958
COMPARABILITY_RELATIVE_LIMIT = 0.05

BLOCK_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("early", 0, 16),
    ("middle", 17, 33),
    ("late", 34, 49),
)
STEP_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("early", 0, 6),
    ("middle", 7, 13),
    ("late", 14, 19),
)


@dataclass(frozen=True)
class LogicalGroup:
    group_id: str
    source_boundary: str
    coupling_class: str
    can_observe: bool
    can_wrap_without_source_patch: bool
    can_execute_subset_structurally: bool | None
    requires_all_tokens: bool | None
    requires_global_context: bool | None
    output_shape_preserving: bool
    fallback_to_original_possible: bool
    adapter_isolation_possible: bool
    observation_compatibility: bool | None
    overlap_classes: tuple[str, ...]

    def public(self) -> dict[str, Any]:
        def tri(value: bool | None) -> bool | str:
            return "unknown" if value is None else value

        return {
            "group_id": self.group_id,
            "source_boundary": self.source_boundary,
            "coupling_class": self.coupling_class,
            "can_observe": self.can_observe,
            "can_wrap_without_source_patch": self.can_wrap_without_source_patch,
            "can_execute_subset_structurally": tri(self.can_execute_subset_structurally),
            "requires_all_tokens": tri(self.requires_all_tokens),
            "requires_global_context": tri(self.requires_global_context),
            "output_shape_preserving": self.output_shape_preserving,
            "fallback_to_original_possible": self.fallback_to_original_possible,
            "adapter_isolation_possible": self.adapter_isolation_possible,
            "observation_compatibility": tri(self.observation_compatibility),
            "overlap_classes": list(self.overlap_classes),
        }


LOGICAL_GROUPS: tuple[LogicalGroup, ...] = (
    LogicalGroup(
        "modulation_parameter_projection",
        "shift/scale/gate = self.adaln_proj(t_emb)",
        "REDUCTION_OR_BROADCAST",
        True,
        True,
        None,
        False,
        False,
        False,
        True,
        True,
        None,
        ("overlaps_runtime_control", "independent_from_VAE"),
    ),
    LogicalGroup(
        "attention_norm_modulation",
        "self.norm1(x) followed by _mod_scale_shift(..., mod_segments)",
        "POSITIONWISE_OR_LOCAL",
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        ("overlaps_regional_compute", "independent_from_VAE"),
    ),
    LogicalGroup(
        "attention_global_mixing",
        "self.attn(h, rope_freqs, transformer_options), including QKV, RoPE, optimized attention, and out projection",
        "GLOBAL_MIXING",
        True,
        True,
        False,
        True,
        True,
        True,
        True,
        True,
        False,
        ("overlaps_attention_kernel", "overlaps_regional_compute", "independent_from_VAE"),
    ),
    LogicalGroup(
        "attention_residual_update",
        "_mod_gate(x, gate_msa, attention_output, mod_segments)",
        "POSITIONWISE_OR_LOCAL",
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        ("overlaps_residual_family", "overlaps_regional_compute", "independent_from_VAE"),
    ),
    LogicalGroup(
        "feed_forward_positionwise",
        "self.norm2(x), _mod_scale_shift(...), then self.mlp(h)",
        "POSITIONWISE_OR_LOCAL",
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        ("overlaps_regional_compute", "independent_from_attention_kernel", "independent_from_VAE"),
    ),
    LogicalGroup(
        "feed_forward_residual_update",
        "_mod_gate(x, gate_mlp, mlp_output, mod_segments)",
        "POSITIONWISE_OR_LOCAL",
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        ("overlaps_residual_family", "overlaps_regional_compute", "independent_from_VAE"),
    ),
)

GROUP_BY_ID = {group.group_id: group for group in LOGICAL_GROUPS}
MAX_EVENT_PAIR_COUNT = EXPECTED_BLOCK_CALLS * (len(LOGICAL_GROUPS) + 1) + 1
MAX_EVENT_OBJECT_COUNT = MAX_EVENT_PAIR_COUNT * 2


def inspect_installed_source(source: Path) -> dict[str, Any]:
    """Validate the exact installed source and recover the actual block order."""

    if not source.is_file():
        return {"admitted": False, "reason": "model_source_missing"}
    raw = source.read_bytes()
    digest = sha256(raw).hexdigest()
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError) as error:
        return {
            "admitted": False,
            "reason": "model_source_parse_failed",
            "error_type": type(error).__name__,
            "source_sha256": digest,
        }
    block = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "DiTBlock"),
        None,
    )
    if block is None:
        return {"admitted": False, "reason": "dit_block_class_missing", "source_sha256": digest}
    init = next((node for node in block.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"), None)
    forward = next((node for node in block.body if isinstance(node, ast.FunctionDef) and node.name == "forward"), None)
    if init is None or forward is None:
        return {"admitted": False, "reason": "dit_block_methods_missing", "source_sha256": digest}
    direct_submodules: list[str] = []
    for node in ast.walk(init):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                direct_submodules.append(target.attr)
    statements = [ast.unparse(node) for node in forward.body]
    normalized = "\n".join(statements)
    required_fragments = (
        "self.adaln_proj(t_emb)",
        "_mod_scale_shift(self.norm1(x)",
        "self.attn(h, rope_freqs=rope_freqs",
        "_mod_gate(x, gate_msa",
        "_mod_scale_shift(self.norm2(x)",
        "self.mlp(h)",
        "_mod_gate(x, gate_mlp",
    )
    checks = {
        "source_hash_matches": digest == MODEL_SOURCE_SHA256,
        "dit_block_class_present": True,
        "direct_submodules_match": sorted(set(direct_submodules))
        == ["adaln_proj", "attn", "mlp", "norm1", "norm2"],
        "forward_fragments_match": all(fragment in normalized for fragment in required_fragments),
        "logical_group_count_within_limit": 0 < len(LOGICAL_GROUPS) <= 6,
        "block_count_source_default": "num_layers=50" in raw.decode("utf-8"),
    }
    return {
        "admitted": all(checks.values()),
        "reason": None if all(checks.values()) else "source_contract_mismatch",
        "source_sha256": digest,
        "source_logical_path": "<comfyui-root>/comfy/ldm/minimax/model.py",
        "class_name": "DiTBlock",
        "block_count": BLOCK_COUNT,
        "direct_submodules": sorted(set(direct_submodules)),
        "forward_statements": statements,
        "checks": checks,
        "logical_groups": [group.public() for group in LOGICAL_GROUPS],
    }


@dataclass
class EventPair:
    start: Any
    end: Any


@dataclass
class BlockTimingRecord:
    step_index: int
    block_index: int
    block_pair: EventPair
    groups: dict[str, EventPair]


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {
            "support_status": "not_collected",
            "reason": "no valid deferred CUDA event samples",
            "unit": "milliseconds",
            "count": 0,
            "total_ms": None,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }
    finite = [float(value) for value in values if math.isfinite(float(value)) and float(value) >= 0.0]
    if len(finite) != len(values):
        return {
            "support_status": "unsupported",
            "reason": "one or more CUDA event durations were non-finite or negative",
            "unit": "milliseconds",
            "count": len(values),
            "total_ms": None,
            "mean_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }
    return {
        "support_status": "collected",
        "reason": None,
        "unit": "milliseconds",
        "count": len(finite),
        "total_ms": sum(finite),
        "mean_ms": mean(finite),
        "p50_ms": median(finite),
        "p95_ms": _percentile(finite, 0.95),
    }


class H3SubBlockTimingController:
    """Temporarily replace DiTBlock.forward with an operation-identical timed form."""

    def __init__(
        self,
        *,
        event_factory: Callable[[], Any],
        synchronize: Callable[[], None],
        mod_scale_shift: Callable[..., Any],
        mod_gate: Callable[..., Any],
        events_supported: bool = True,
        unsupported_reason: str | None = None,
    ) -> None:
        self.event_factory = event_factory
        self.synchronize = synchronize
        self.mod_scale_shift = mod_scale_shift
        self.mod_gate = mod_gate
        self.events_supported = events_supported
        self.unsupported_reason = unsupported_reason
        self.records: list[BlockTimingRecord] = []
        self.model_forward_count = 0
        self.block_call_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.event_pair_creation_count = 0
        self.synchronization_count = 0
        self.sampler_pair: EventPair | None = None
        self._sampler_started = False
        self._original_forward: Callable[..., Any] | None = None
        self._dit_class: Any = None
        self._finalized: dict[str, Any] | None = None

    def _event_pair(self) -> EventPair:
        pair = EventPair(self.event_factory(), self.event_factory())
        self.event_pair_creation_count += 1
        return pair

    def start_sampler(self) -> None:
        if not self.events_supported:
            return
        if self._sampler_started:
            raise RuntimeError("sampler timing already started")
        self.sampler_pair = self._event_pair()
        self.sampler_pair.start.record()
        self._sampler_started = True

    def end_sampler(self) -> None:
        if not self.events_supported:
            return
        if not self._sampler_started or self.sampler_pair is None:
            raise RuntimeError("sampler timing was not started")
        self.sampler_pair.end.record()
        self._sampler_started = False

    def _timed(self, pairs: dict[str, EventPair], group_id: str, operation: Callable[[], Any]) -> Any:
        pair = self._event_pair()
        pairs[group_id] = pair
        pair.start.record()
        try:
            return operation()
        finally:
            pair.end.record()

    def instrumented_forward(
        self,
        block: Any,
        x: Any,
        t_emb: Any,
        mod_segments: Any,
        rope_freqs: Any,
        transformer_options: Mapping[str, Any] | None = None,
    ) -> Any:
        call_index = self.block_call_count
        step_index, block_index = divmod(call_index, BLOCK_COUNT)
        if block_index == 0:
            self.model_forward_count += 1
        if step_index >= STEP_COUNT:
            self.mapping_error_count += 1
        pairs: dict[str, EventPair] = {}
        block_pair = self._event_pair()
        block_pair.start.record()
        options = {} if transformer_options is None else transformer_options
        try:
            shift_msa, scale_msa, gate_msa, shift_mlp, scale_mlp, gate_mlp = self._timed(
                pairs,
                "modulation_parameter_projection",
                lambda: block.adaln_proj(t_emb),
            )
            h = self._timed(
                pairs,
                "attention_norm_modulation",
                lambda: self.mod_scale_shift(block.norm1(x), shift_msa, scale_msa, mod_segments),
            )
            attention_output = self._timed(
                pairs,
                "attention_global_mixing",
                lambda: block.attn(
                    h,
                    rope_freqs=rope_freqs,
                    transformer_options=options,
                ),
            )
            x = self._timed(
                pairs,
                "attention_residual_update",
                lambda: self.mod_gate(x, gate_msa, attention_output, mod_segments),
            )

            def feed_forward() -> Any:
                ff_h = self.mod_scale_shift(block.norm2(x), shift_mlp, scale_mlp, mod_segments)
                return block.mlp(ff_h)

            mlp_output = self._timed(pairs, "feed_forward_positionwise", feed_forward)
            result = self._timed(
                pairs,
                "feed_forward_residual_update",
                lambda: self.mod_gate(x, gate_mlp, mlp_output, mod_segments),
            )
            return result
        except BaseException:
            self.wrapper_failure_count += 1
            raise
        finally:
            block_pair.end.record()
            self.records.append(BlockTimingRecord(step_index, block_index, block_pair, pairs))
            self.block_call_count += 1

    def install(self, dit_class: Any) -> None:
        if not self.events_supported:
            return
        if self._original_forward is not None:
            raise RuntimeError("DiTBlock timing wrapper already installed")
        self._dit_class = dit_class
        self._original_forward = dit_class.forward
        controller = self

        def timed_forward(
            block: Any,
            x: Any,
            t_emb: Any,
            mod_segments: Any,
            rope_freqs: Any,
            transformer_options: Mapping[str, Any] | None = None,
        ) -> Any:
            return controller.instrumented_forward(
                block,
                x,
                t_emb,
                mod_segments,
                rope_freqs,
                transformer_options,
            )

        dit_class.forward = timed_forward

    def restore(self) -> None:
        if self._original_forward is None or self._dit_class is None:
            return
        self._dit_class.forward = self._original_forward
        self._original_forward = None
        self._dit_class = None

    @staticmethod
    def _elapsed(pair: EventPair) -> float:
        return float(pair.start.elapsed_time(pair.end))

    def _bucket_summary(
        self,
        block_values: Mapping[int, Sequence[float]],
        buckets: Sequence[tuple[str, int, int]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for label, first, last in buckets:
            values: list[float] = []
            for index in range(first, last + 1):
                values.extend(block_values.get(index, ()))
            output.append({"bucket": label, "first": first, "last": last, **_summary(values)})
        return output

    def finalize(self) -> dict[str, Any]:
        if self._finalized is not None:
            return self._finalized
        if not self.events_supported:
            self._finalized = {
                "support_status": "unsupported",
                "reason": self.unsupported_reason or "CUDA events are unavailable",
                "measurement_method": "deferred torch.cuda.Event pairs",
                "value": None,
                "profiler_enabled": False,
                "kernel_profiler_seconds": None,
                "kernel_profiler_support_status": "not_collected",
                "kernel_profiler_reason": "Profiler execution was disabled by contract.",
                "synchronization_count": 0,
                "event_pair_creation_count": 0,
                "event_object_count": 0,
                "model_forward_count": 0,
                "block_call_count": 0,
                "full_compute_only": True,
                "skip_count": 0,
                "reuse_count": 0,
                "prediction_count": 0,
                "regional_execution_count": 0,
                "token_omission_count": 0,
                "attention_omission_count": 0,
            }
            return self._finalized
        if self._sampler_started:
            self.end_sampler()
        started = time.perf_counter()
        self.synchronize()
        self.synchronization_count += 1
        synchronization_wall_seconds = time.perf_counter() - started
        group_values: dict[str, list[float]] = {group.group_id: [] for group in LOGICAL_GROUPS}
        block_values: dict[int, list[float]] = {index: [] for index in range(BLOCK_COUNT)}
        step_values: dict[int, list[float]] = {index: [] for index in range(STEP_COUNT)}
        per_block_groups: dict[int, dict[str, list[float]]] = {
            index: {group.group_id: [] for group in LOGICAL_GROUPS} for index in range(BLOCK_COUNT)
        }
        per_step_groups: dict[int, dict[str, list[float]]] = {
            index: {group.group_id: [] for group in LOGICAL_GROUPS} for index in range(STEP_COUNT)
        }
        for record in self.records:
            block_ms = self._elapsed(record.block_pair)
            if record.block_index in block_values:
                block_values[record.block_index].append(block_ms)
            if record.step_index in step_values:
                step_values[record.step_index].append(block_ms)
            for group_id, pair in record.groups.items():
                value = self._elapsed(pair)
                group_values[group_id].append(value)
                if record.block_index in per_block_groups:
                    per_block_groups[record.block_index][group_id].append(value)
                if record.step_index in per_step_groups:
                    per_step_groups[record.step_index][group_id].append(value)
        block_all = [value for values in block_values.values() for value in values]
        sampler_ms = self._elapsed(self.sampler_pair) if self.sampler_pair is not None else None
        block_total = sum(block_all)
        groups: list[dict[str, Any]] = []
        for group in LOGICAL_GROUPS:
            metrics = _summary(group_values[group.group_id])
            total = metrics.get("total_ms")
            groups.append(
                {
                    **group.public(),
                    "timing": metrics,
                    "share_of_measured_dit_block_gpu_span": (
                        total / block_total if isinstance(total, (int, float)) and block_total > 0 else None
                    ),
                    "share_of_sampler_cuda_event_span": (
                        total / sampler_ms
                        if isinstance(total, (int, float)) and isinstance(sampler_ms, (int, float)) and sampler_ms > 0
                        else None
                    ),
                    "ideal_elimination_ceiling": {
                        "value": (
                            total / sampler_ms
                            if isinstance(total, (int, float)) and isinstance(sampler_ms, (int, float)) and sampler_ms > 0
                            else None
                        ),
                        "status": "THEORETICAL_ONLY" if sampler_ms else "not_collected",
                        "reason": "Assumes the measured group span disappears with zero closure, verification, or orchestration cost; not attainable speedup.",
                    },
                }
            )
        group_total = sum(
            entry["timing"]["total_ms"]
            for entry in groups
            if isinstance(entry["timing"].get("total_ms"), (int, float))
        )
        block_remainder = block_total - group_total
        report = {
            "support_status": "collected",
            "measurement_method": "deferred torch.cuda.Event pairs on the active CUDA stream; one synchronization after sampler completion",
            "measurement_scope": "CUDA event spans, not profiler kernel-duration sums",
            "profiler_enabled": False,
            "kernel_profiler_seconds": None,
            "kernel_profiler_support_status": "not_collected",
            "kernel_profiler_reason": "PyTorch profiler, CUPTI, Nsight, and kernel-by-kernel profiling were disabled by contract.",
            "synchronization_count": self.synchronization_count,
            "synchronization_wall_seconds": synchronization_wall_seconds,
            "event_pair_creation_count": self.event_pair_creation_count,
            "event_object_count": self.event_pair_creation_count * 2,
            "event_pair_bound": MAX_EVENT_PAIR_COUNT,
            "event_object_bound": MAX_EVENT_OBJECT_COUNT,
            "model_forward_count": self.model_forward_count,
            "block_call_count": self.block_call_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "full_compute_only": True,
            "skip_count": 0,
            "reuse_count": 0,
            "prediction_count": 0,
            "regional_execution_count": 0,
            "token_omission_count": 0,
            "attention_omission_count": 0,
            "sampler_cuda_event_span_ms": sampler_ms,
            "entire_dit_block": _summary(block_all),
            "logical_groups": groups,
            "group_span_sum_ms": group_total,
            "unattributed_within_dit_block_ms": block_remainder,
            "unattributed_method": "sum of entire-block event spans minus the six non-overlapping child group event spans; no normalization to 100 percent",
            "per_block": [
                {
                    "block_index": index,
                    "entire_block": _summary(block_values[index]),
                    "groups": {
                        group.group_id: _summary(per_block_groups[index][group.group_id])
                        for group in LOGICAL_GROUPS
                    },
                }
                for index in range(BLOCK_COUNT)
            ],
            "per_step": [
                {
                    "step_index": index,
                    "entire_block_aggregate": _summary(step_values[index]),
                    "groups": {
                        group.group_id: _summary(per_step_groups[index][group.group_id])
                        for group in LOGICAL_GROUPS
                    },
                }
                for index in range(STEP_COUNT)
            ],
            "block_buckets": self._bucket_summary(block_values, BLOCK_BUCKETS),
            "step_buckets": self._bucket_summary(step_values, STEP_BUCKETS),
        }
        self._finalized = report
        return report

    @property
    def sampler_timing_active(self) -> bool:
        return self._sampler_started


def instrumentation_comparability(measured_sampler_seconds: float) -> dict[str, Any]:
    delta = measured_sampler_seconds - REFERENCE_SAMPLER_SECONDS
    relative = delta / REFERENCE_SAMPLER_SECONDS
    return {
        "reference_sampler_seconds": REFERENCE_SAMPLER_SECONDS,
        "reference_method": "median of immutable same-profile Full Compute C0, C3-R2, C3-R3, and C3-R4 sampler wall spans",
        "reference_values_seconds": [486.603692, 488.459651, 488.710265, 488.865380],
        "measured_sampler_seconds": measured_sampler_seconds,
        "delta_seconds": delta,
        "relative_delta": relative,
        "allowed_relative_delta": COMPARABILITY_RELATIVE_LIMIT,
        "passed": abs(relative) <= COMPARABILITY_RELATIVE_LIMIT,
        "scope": "WebSocket sampler-node wall span; this is not GPU kernel time",
    }


def rank_compute_levers(timing_report: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the predeclared structural-first ranking after timing collection."""

    raw_groups = timing_report.get("logical_groups")
    if not isinstance(raw_groups, list) or len(raw_groups) != len(LOGICAL_GROUPS):
        raise ValueError("complete logical-group timing is required")
    ranked = sorted(
        raw_groups,
        key=lambda item: (
            -(float(item.get("share_of_sampler_cuda_event_span") or -1.0)),
            str(item.get("group_id")),
        ),
    )
    eligible = [
        item
        for item in ranked
        if item.get("can_execute_subset_structurally") is True
        and item.get("observation_compatibility") is True
        and item.get("fallback_to_original_possible") is True
        and item.get("coupling_class") != "GLOBAL_MIXING"
    ]
    dominant = ranked[0]
    if eligible:
        selected = eligible[0]
        if dominant.get("coupling_class") == "GLOBAL_MIXING":
            lever = "MIXED_SUBBLOCK_SELECTIVE"
            reason = "Keep the dominant global-mixing group Full Compute while targeting the highest-cost structurally local group."
        else:
            lever = "POSITIONWISE_REGIONAL_COMPUTE"
            reason = "The highest-cost structurally local, observation-compatible group is the primary candidate."
    elif dominant.get("group_id") == "attention_global_mixing":
        selected = dominant
        lever = "ATTENTION_COMPUTE_REDUCTION"
        reason = "No structurally local group is admitted; the dominant global attention surface requires an attention-specific strategy."
    else:
        selected = dominant
        lever = "OTHER_COST_DOMINANT_COMPONENT"
        reason = "The measured dominant component does not match an admitted regional or attention-specific path."
    secondaries = [
        {
            "group_id": item.get("group_id"),
            "coupling_class": item.get("coupling_class"),
            "share_of_sampler_cuda_event_span": item.get("share_of_sampler_cuda_event_span"),
        }
        for item in ranked
        if item.get("group_id") != selected.get("group_id")
    ]
    return {
        "next_primary_compute_lever": lever,
        "selected_group_id": selected.get("group_id"),
        "selection_reason": reason,
        "dominant_measured_group_id": dominant.get("group_id"),
        "secondary_candidates": secondaries,
        "claim_boundary": "Ranking selects the next bounded research candidate only; it is not safe-skip authority, attainable reduction, or speedup.",
    }
