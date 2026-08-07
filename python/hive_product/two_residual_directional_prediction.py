"""C3-R4 two-residual directional prediction for the H3 adapter.

The generic Rust Core reuses the existing tensor-free correction admission
contract.  H3 tensors, block indices, sufficient-statistic reductions, and
directional replay remain in this adapter module.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any, Callable, Mapping, Protocol, Sequence
import copy
import hashlib
import json
import math

from .compact_residual_correction import (
    CorrectionPlanBridge,
    CorrectionPlanContext,
    CorrectionShadowPipeline,
    REUSE_CORRECTED_TRANSFORM,
)
from .segment_residual_replay import (
    BLOCK_COUNT,
    FROZEN_CEILING,
    FULL_COMPUTE_ANCHORS,
    NORMALIZED_RESIDUAL_L2_MAX,
    RESIDUAL_COSINE_MIN,
    SEGMENT_BLOCKS,
    SEGMENT_END,
    SEGMENT_LOGICAL_ID,
    SEGMENT_START,
    TOTAL_STEPS,
    ResidualCache,
    TorchTensorOps,
    _timing,
)


MECHANISM = "TWO_RESIDUAL_LINEAR_DIRECTION_PREDICTION_V1"
PREDICTOR_KIND = "two_actual_full_compute_residual_linear_direction"
CONTROL = "CONTROL_DIRECTIONAL_SHADOW"
SELECTIVE = "SELECTIVE_DIRECTIONAL_RESIDUAL_REPLAY"
RAW_BASELINE_ALPHA = 0.0
ALPHA_GRID = (-0.50, -0.25, -0.125, 0.125, 0.25, 0.50, 0.75, 1.00)
MIN_CALIBRATED_TARGETS = 2
MIN_TARGET_SPACING = 3
STATISTIC_CHUNK_ROWS = 256
METRIC_EQUIVALENCE_TOLERANCE = 1.0e-9
MAX_PERSISTENT_RESIDUALS = 2
MAX_PERSISTENT_DIRECTIONS = 0
MAX_PERSISTENT_PREDICTIONS = 0
MAX_TRANSIENT_PREDICTIONS = 1


def validate_global_alpha(alpha: float | None, *, required: bool = False) -> None:
    if alpha is None:
        if required:
            raise ValueError("SELECTIVE requires one CONTROL-selected global alpha")
        return
    if not math.isfinite(alpha) or alpha == RAW_BASELINE_ALPHA:
        raise ValueError("global alpha must be one finite non-zero frozen candidate")
    if alpha not in ALPHA_GRID:
        raise ValueError("global alpha must belong to the frozen alpha grid")


def validate_calibrated_targets(targets: tuple[int, ...]) -> None:
    if targets != tuple(sorted(set(targets))):
        raise ValueError("calibrated targets must be unique and ordered")
    if any(target not in FROZEN_CEILING for target in targets):
        raise ValueError("calibrated targets must stay inside the frozen ceiling")
    if any(right - left < MIN_TARGET_SPACING for left, right in zip(targets, targets[1:])):
        raise ValueError("calibrated targets require two Full Compute re-seed steps")


def directional_metrics_from_statistics(
    statistics: Mapping[str, float], alpha: float
) -> dict[str, Any]:
    """Evaluate the exact C3-R2 metrics for P=B+alpha(B-A) from six scalars."""
    a2 = float(statistics["a2"])
    b2 = float(statistics["b2"])
    y2 = float(statistics["y2"])
    ab = float(statistics["ab"])
    ay = float(statistics["ay"])
    by = float(statistics["by"])
    d2 = max(0.0, b2 + a2 - 2.0 * ab)
    b_dot_d = b2 - ab
    d_dot_y = by - ay
    predicted2 = max(0.0, b2 + 2.0 * alpha * b_dot_d + alpha * alpha * d2)
    predicted_dot_y = by + alpha * d_dot_y
    predicted_norm = math.sqrt(predicted2)
    current_norm = math.sqrt(max(0.0, y2))
    denominator = predicted_norm * current_norm
    cosine = predicted_dot_y / denominator if denominator > 0.0 else None
    difference2 = max(0.0, predicted2 + y2 - 2.0 * predicted_dot_y)
    normalized_l2 = math.sqrt(difference2) / predicted_norm if predicted_norm > 0.0 else None
    finite = all(
        math.isfinite(value)
        for value in (a2, b2, y2, ab, ay, by, predicted2, predicted_dot_y)
    ) and isinstance(cosine, float) and isinstance(normalized_l2, float)
    return {
        "alpha": alpha,
        "normalized_residual_l2": normalized_l2,
        "residual_cosine_similarity": cosine,
        "finite": finite,
        "method": "exact sufficient statistics for P=B+alpha(B-A); C3-R2 normalization unchanged",
        "full_prediction_tensor_count": 0,
        "full_size_fp32_materialization_count": 0,
        "full_tensor_host_copy_bytes": 0,
    }


def sufficient_statistics_from_sequences(
    previous2: Sequence[float], previous1: Sequence[float], current: Sequence[float]
) -> dict[str, float]:
    """Small model-free reference used to lock exact scalar-metric equivalence."""
    if not previous2 or len(previous2) != len(previous1) or len(previous1) != len(current):
        raise ValueError("directional metric sequences must be non-empty and shape-equal")
    return {
        "a2": sum(value * value for value in previous2),
        "b2": sum(value * value for value in previous1),
        "y2": sum(value * value for value in current),
        "ab": sum(left * right for left, right in zip(previous2, previous1)),
        "ay": sum(left * right for left, right in zip(previous2, current)),
        "by": sum(left * right for left, right in zip(previous1, current)),
    }


def direct_directional_metrics(
    previous2: Sequence[float], previous1: Sequence[float], current: Sequence[float], alpha: float
) -> dict[str, float]:
    predicted = [b + alpha * (b - a) for a, b in zip(previous2, previous1)]
    predicted2 = sum(value * value for value in predicted)
    current2 = sum(value * value for value in current)
    dot = sum(left * right for left, right in zip(predicted, current))
    denominator = math.sqrt(predicted2) * math.sqrt(current2)
    difference2 = sum((left - right) ** 2 for left, right in zip(predicted, current))
    return {
        "residual_cosine_similarity": dot / denominator,
        "normalized_residual_l2": math.sqrt(difference2) / math.sqrt(predicted2),
    }


def _spaced(targets: Sequence[int]) -> tuple[int, ...]:
    selected: list[int] = []
    for target in sorted(set(int(value) for value in targets)):
        if target not in FROZEN_CEILING:
            continue
        if not selected or target - selected[-1] >= MIN_TARGET_SPACING:
            selected.append(target)
    result = tuple(selected)
    validate_calibrated_targets(result)
    return result


def select_global_alpha(diagnostics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the frozen global-alpha and deterministic spacing/tie-break contract."""
    summaries: list[dict[str, Any]] = []
    for alpha in ALPHA_GRID:
        admitted_targets: list[int] = []
        threshold_pass_count = 0
        raw_non_regression_pass_count = 0
        metrics_by_target: dict[int, Mapping[str, Any]] = {}
        for target_record in diagnostics:
            target = int(target_record["target_step"])
            for alpha_record in target_record.get("alpha_diagnostics", []):
                if float(alpha_record.get("alpha")) != alpha:
                    continue
                if alpha_record.get("threshold_pass") is True:
                    threshold_pass_count += 1
                if alpha_record.get("raw_non_regression_pass") is True:
                    raw_non_regression_pass_count += 1
                if alpha_record.get("admitted") is True:
                    admitted_targets.append(target)
                    metrics_by_target[target] = alpha_record
                break
        spaced = _spaced(admitted_targets)
        selected_metrics = [metrics_by_target[target] for target in spaced]
        minimum_cosine = (
            min(float(item["residual_cosine_similarity"]) for item in selected_metrics)
            if selected_metrics else None
        )
        maximum_l2 = (
            max(float(item["normalized_residual_l2"]) for item in selected_metrics)
            if selected_metrics else None
        )
        summaries.append({
            "alpha": alpha,
            "threshold_pass_count": threshold_pass_count,
            "raw_non_regression_pass_count": raw_non_regression_pass_count,
            "spaced_admitted_targets": list(spaced),
            "spaced_admitted_count": len(spaced),
            "selected_minimum_cosine": minimum_cosine,
            "selected_maximum_normalized_l2": maximum_l2,
        })
    def rank(item: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
        minimum_cosine = item["selected_minimum_cosine"]
        maximum_l2 = item["selected_maximum_normalized_l2"]
        alpha = float(item["alpha"])
        return (
            -float(item["spaced_admitted_count"]),
            -float(minimum_cosine) if minimum_cosine is not None else math.inf,
            float(maximum_l2) if maximum_l2 is not None else math.inf,
            abs(alpha),
            alpha,
        )
    selected = min(summaries, key=rank)
    return {
        "selection_rule": [
            "maximum spaced admitted count",
            "maximum selected minimum cosine",
            "minimum selected maximum normalized L2",
            "minimum absolute alpha",
            "minimum numeric alpha",
        ],
        "alpha_summaries": summaries,
        "global_alpha": float(selected["alpha"]),
        "calibrated_targets": list(selected["spaced_admitted_targets"]),
        "selective_admitted": int(selected["spaced_admitted_count"]) >= MIN_CALIBRATED_TARGETS,
    }


class DirectionalPlanBridge(CorrectionPlanBridge):
    """Reuse the generic C3-R3 correction ABI; alpha is bound by settings digest."""

    def __init__(
        self,
        context: CorrectionPlanContext,
        calibrated_targets: tuple[int, ...],
        global_alpha: float | None,
        extension: Any | None = None,
    ) -> None:
        validate_global_alpha(global_alpha, required=bool(calibrated_targets))
        validate_calibrated_targets(calibrated_targets)
        self.global_alpha = global_alpha
        super().__init__(context, calibrated_targets, extension)

    def receipt(self) -> dict[str, Any]:
        receipt = super().receipt()
        receipt.update({
            "schema_version": "c3-r4.directional-plan.1",
            "mechanism": MECHANISM,
            "predictor_kind": PREDICTOR_KIND,
            "global_alpha": self.global_alpha,
            "abi_reused_without_semantic_change": "c3-r3.correction-plan.1",
        })
        return receipt


DirectionalShadowPipeline = CorrectionShadowPipeline


class DirectionalTensorOps(Protocol):
    def clone(self, tensor: Any) -> Any: ...
    def residualize(self, snapshot: Any, output: Any) -> Any: ...
    def metadata(self, tensor: Any) -> Mapping[str, Any]: ...
    def finite(self, tensor: Any) -> bool: ...
    def similarity(self, previous: Any, current: Any) -> Mapping[str, Any]: ...
    def directional_grid(self, previous2: Any, previous1: Any, current: Any) -> Mapping[str, Any]: ...
    def apply_directional(
        self, current: Any, previous2: Any, previous1: Any, alpha: float
    ) -> Any: ...
    def cuda_memory(self, tensor: Any) -> Mapping[str, Any]: ...


class TorchDirectionalTensorOps(TorchTensorOps):
    """Exact bounded reductions; no alpha-specific full prediction tensor in shadow."""

    @staticmethod
    def _rows(tensor: Any) -> Any:
        if int(tensor.ndim) < 1 or int(tensor.numel()) <= 0:
            raise ValueError("directional residual tensor must be non-empty")
        return tensor.reshape(-1)

    def directional_grid(self, previous2: Any, previous1: Any, current: Any) -> Mapping[str, Any]:
        import torch

        a_rows, b_rows, y_rows = self._rows(previous2), self._rows(previous1), self._rows(current)
        if tuple(previous2.shape) != tuple(previous1.shape) or tuple(previous1.shape) != tuple(current.shape):
            raise ValueError("directional residual tensors must be shape-equal")
        started = perf_counter_ns()
        names = ("a2", "b2", "y2", "ab", "ay", "by")
        accumulators = {
            name: torch.zeros((), dtype=torch.float64, device=current.device) for name in names
        }
        for start in range(0, int(a_rows.numel()), STATISTIC_CHUNK_ROWS * 1024):
            stop = start + STATISTIC_CHUNK_ROWS * 1024
            a = a_rows[start:stop].to(dtype=torch.float32)
            b = b_rows[start:stop].to(dtype=torch.float32)
            y = y_rows[start:stop].to(dtype=torch.float32)
            accumulators["a2"].add_((a * a).sum(dtype=torch.float64))
            accumulators["b2"].add_((b * b).sum(dtype=torch.float64))
            accumulators["y2"].add_((y * y).sum(dtype=torch.float64))
            accumulators["ab"].add_((a * b).sum(dtype=torch.float64))
            accumulators["ay"].add_((a * y).sum(dtype=torch.float64))
            accumulators["by"].add_((b * y).sum(dtype=torch.float64))
        statistics = {name: float(value.item()) for name, value in accumulators.items()}
        statistic_ns = perf_counter_ns() - started
        evaluation_started = perf_counter_ns()
        raw = directional_metrics_from_statistics(statistics, RAW_BASELINE_ALPHA)
        candidates = [directional_metrics_from_statistics(statistics, alpha) for alpha in ALPHA_GRID]
        alpha_evaluation_ns = perf_counter_ns() - evaluation_started
        return {
            "statistics": statistics,
            "raw": raw,
            "candidates": candidates,
            "statistics_ns": statistic_ns,
            "alpha_evaluation_ns": alpha_evaluation_ns,
            "full_prediction_tensor_count": 0,
            "full_size_fp32_materialization_count": 0,
            "full_tensor_host_copy_bytes": 0,
        }

    def apply_directional(
        self, current: Any, previous2: Any, previous1: Any, alpha: float
    ) -> Any:
        prediction = previous1.clone()
        prediction.mul_(1.0 + alpha)
        prediction.add_(previous2, alpha=-alpha)
        current.add_(prediction)
        return current


@dataclass
class DirectionalHistory:
    residuals: list[ResidualCache]

    def valid_for(
        self,
        target: int,
        workflow_revision_digest: str,
        model_revision_digest: str,
        settings_digest: str,
    ) -> bool:
        if len(self.residuals) != 2:
            return False
        first, second = self.residuals
        return bool(
            first.source_execution_step + 1 == second.source_execution_step
            and second.source_execution_step + 1 == target
            and first.workflow_revision_digest == second.workflow_revision_digest == workflow_revision_digest
            and first.model_revision_digest == second.model_revision_digest == model_revision_digest
            and first.settings_digest == second.settings_digest == settings_digest
            and first.shape_digest == second.shape_digest
            and first.dtype == second.dtype
            and first.device == second.device
            and first.finite and second.finite
        )


class H3TwoResidualDirectionalController:
    """H3-only block 12..48 directional shadow and admitted replay adapter."""

    def __init__(
        self,
        mode: str,
        plan_bridge: DirectionalPlanBridge,
        *,
        workflow_revision_digest: str,
        model_revision_digest: str,
        settings_digest: str,
        global_alpha: float | None,
        tensor_ops: DirectionalTensorOps | None = None,
    ) -> None:
        if mode not in {CONTROL, SELECTIVE}:
            raise ValueError("invalid C3-R4 mode")
        validate_global_alpha(global_alpha, required=mode == SELECTIVE)
        self.mode = mode
        self.plan_bridge = plan_bridge
        self.workflow_revision_digest = workflow_revision_digest
        self.model_revision_digest = model_revision_digest
        self.settings_digest = settings_digest
        self.global_alpha = global_alpha
        self.ops = tensor_ops or TorchDirectionalTensorOps()
        self.history = DirectionalHistory([])
        self.segment_snapshot: Any | None = None
        self.replay_active_step: int | None = None
        self.model_forward_count = 0
        self.original_block_call_count = 0
        self.replayed_block_call_count = 0
        self.replay_count = 0
        self.residual_capture_count = 0
        self.mapping_error_count = 0
        self.wrapper_failure_count = 0
        self.expected_block_index = 0
        self.current_execution_step = -1
        self.max_persistent_residual_count = 0
        self.max_live_residual_sized_buffers = 0
        self.max_transient_prediction_count = 0
        self.max_additional_gpu_bytes = 0
        self.diagnostics: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.memory_samples: list[dict[str, Any]] = []
        self.per_step: dict[int, dict[str, Any]] = {}
        self.original_ns: list[int] = []
        self.capture_ns: list[int] = []
        self.history_rotation_ns: list[int] = []
        self.scalar_statistics_ns: list[int] = []
        self.alpha_evaluation_ns: list[int] = []
        self.prediction_application_ns: list[int] = []
        self.cache_invalidation_ns: list[int] = []
        self.plan_bridge.set_state_provider(self.state_for_target)

    def _step(self, step: int) -> dict[str, Any]:
        return self.per_step.setdefault(step, {
            "execution_step": step,
            "original_block_calls": 0,
            "replayed_block_calls": 0,
            "residual_captured": False,
            "directional_prediction_applied": False,
            "decision": "FULL_COMPUTE",
            "reason": "plan_unavailable",
        })

    def state_for_target(self, target: int) -> Mapping[str, Any]:
        valid = self.history.valid_for(
            target, self.workflow_revision_digest, self.model_revision_digest, self.settings_digest
        )
        residuals = self.history.residuals
        first_step = residuals[0].source_execution_step if len(residuals) == 2 else max(0, target - 2)
        second_step = residuals[1].source_execution_step if len(residuals) == 2 else max(0, target - 1)
        return {
            "first_source_execution_step": first_step,
            "second_source_execution_step": second_step,
            "cache_available": valid,
            "predictor_available": valid and self.global_alpha in ALPHA_GRID,
            "predictor_provenance_valid": valid,
            "correction_metadata_valid": self.global_alpha in ALPHA_GRID,
            "full_compute_seed_count": len(residuals),
            "reseed_required": len(residuals) < 2,
            "finite": valid,
        }

    def _invalidate_history(self, step: int) -> None:
        started = perf_counter_ns()
        self.history.residuals.clear()
        self.events.append({"event": "directional_history_invalidated", "step": step})
        self.cache_invalidation_ns.append(perf_counter_ns() - started)

    def _matches(self, tensor: Any, step: int) -> tuple[bool, str]:
        if not self.history.valid_for(
            step, self.workflow_revision_digest, self.model_revision_digest, self.settings_digest
        ):
            return False, "two_actual_sources_unavailable"
        metadata = dict(self.ops.metadata(tensor))
        for cache in self.history.residuals:
            if metadata["shape_digest"] != cache.shape_digest:
                return False, "shape_mismatch"
            if metadata["dtype"] != cache.dtype or metadata["device"] != cache.device:
                return False, "dtype_or_device_mismatch"
        return True, "directional_prediction_valid"

    @staticmethod
    def _admission(raw: Mapping[str, Any], predicted: Mapping[str, Any]) -> tuple[bool, bool, bool]:
        raw_cos, raw_l2 = raw.get("residual_cosine_similarity"), raw.get("normalized_residual_l2")
        cosine, l2 = predicted.get("residual_cosine_similarity"), predicted.get("normalized_residual_l2")
        numeric = all(isinstance(value, (int, float)) for value in (raw_cos, raw_l2, cosine, l2))
        threshold = bool(numeric and predicted.get("finite") and cosine >= RESIDUAL_COSINE_MIN
                         and l2 <= NORMALIZED_RESIDUAL_L2_MAX)
        non_regression = bool(numeric and cosine >= raw_cos and l2 <= raw_l2)
        return threshold, non_regression, threshold and non_regression

    def _capture(self, output: Any, step: int, record: dict[str, Any]) -> None:
        if self.segment_snapshot is None:
            raise RuntimeError("segment snapshot missing at block 48")
        started = perf_counter_ns()
        current = self.ops.residualize(self.segment_snapshot, output)
        metadata = dict(self.ops.metadata(current))
        finite = bool(self.ops.finite(current))
        prior = list(self.history.residuals)
        self.max_live_residual_sized_buffers = max(
            self.max_live_residual_sized_buffers, len(prior) + 1
        )
        if (
            len(prior) == 2
            and prior[0].source_execution_step + 1 == prior[1].source_execution_step
            and prior[1].source_execution_step + 1 == step
            and step in FROZEN_CEILING
            and all(cache.finite for cache in prior)
            and finite
        ):
            grid = dict(self.ops.directional_grid(prior[0].tensor, prior[1].tensor, current))
            self.scalar_statistics_ns.append(int(grid["statistics_ns"]))
            self.alpha_evaluation_ns.append(int(grid["alpha_evaluation_ns"]))
            raw = dict(grid["raw"])
            alpha_diagnostics: list[dict[str, Any]] = []
            for predicted_value in grid["candidates"]:
                predicted = dict(predicted_value)
                threshold, non_regression, admitted = self._admission(raw, predicted)
                raw_cos = raw.get("residual_cosine_similarity")
                raw_l2 = raw.get("normalized_residual_l2")
                cosine = predicted.get("residual_cosine_similarity")
                l2 = predicted.get("normalized_residual_l2")
                alpha_diagnostics.append({
                    **predicted,
                    "delta_cosine_vs_raw": (
                        cosine - raw_cos if isinstance(cosine, (int, float)) and isinstance(raw_cos, (int, float)) else None
                    ),
                    "delta_l2_vs_raw": (
                        l2 - raw_l2 if isinstance(l2, (int, float)) and isinstance(raw_l2, (int, float)) else None
                    ),
                    "threshold_pass": threshold,
                    "raw_non_regression_pass": non_regression,
                    "admitted": admitted,
                })
            self.diagnostics.append({
                "target_step": step,
                "first_source_step": prior[0].source_execution_step,
                "second_source_step": prior[1].source_execution_step,
                "source_kind": "actual_full_compute_residual",
                "raw": raw,
                "alpha_diagnostics": alpha_diagnostics,
                "full_prediction_tensor_count": 0,
            })
        rotation_started = perf_counter_ns()
        cache = ResidualCache(
            tensor=current,
            source_execution_step=step,
            workflow_revision_digest=self.workflow_revision_digest,
            model_revision_digest=self.model_revision_digest,
            settings_digest=self.settings_digest,
            segment_logical_id=SEGMENT_LOGICAL_ID,
            block_start=SEGMENT_START,
            block_end=SEGMENT_END,
            shape_digest=str(metadata["shape_digest"]),
            dtype=str(metadata["dtype"]),
            device=str(metadata["device"]),
            finite=finite,
            generation_count=self.residual_capture_count + 1,
            reuse_count=0,
            tensor_bytes=int(metadata["bytes"]),
        )
        self.history.residuals.append(cache)
        if len(self.history.residuals) > MAX_PERSISTENT_RESIDUALS:
            self.history.residuals.pop(0)
        self.history_rotation_ns.append(perf_counter_ns() - rotation_started)
        self.max_persistent_residual_count = max(
            self.max_persistent_residual_count, len(self.history.residuals)
        )
        self.max_additional_gpu_bytes = max(
            self.max_additional_gpu_bytes,
            int(metadata["bytes"]) * self.max_live_residual_sized_buffers,
        )
        self.segment_snapshot = None
        self.residual_capture_count += 1
        record["residual_captured"] = True
        self.capture_ns.append(perf_counter_ns() - started)
        self.memory_samples.append(dict(self.ops.cuda_memory(current)))

    def block_wrapper(self, block_index: int) -> Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]:
        if not 0 <= block_index < BLOCK_COUNT:
            raise ValueError("block index outside fixed H3 range")

        def wrapper(args: Mapping[str, Any], extra_options: Mapping[str, Any]) -> Mapping[str, Any]:
            if block_index == 0:
                if self.expected_block_index != 0:
                    self.mapping_error_count += 1
                self.current_execution_step = self.model_forward_count
                self.model_forward_count += 1
                self.replay_active_step = None
            if block_index != self.expected_block_index:
                self.mapping_error_count += 1
            self.expected_block_index = (block_index + 1) % BLOCK_COUNT
            step = self.current_execution_step
            record = self._step(step)
            plan = self.plan_bridge.plans.get(step)
            if plan:
                record["decision"], record["reason"] = plan["decision"], plan["reason"]
            if block_index == SEGMENT_START:
                replay = bool(
                    self.mode == SELECTIVE
                    and plan
                    and int(plan["decision_code"]) == REUSE_CORRECTED_TRANSFORM
                )
                valid, reason = self._matches(args["img"], step) if replay else (False, "full_compute")
                if replay and valid:
                    assert self.global_alpha is not None and len(self.history.residuals) == 2
                    started = perf_counter_ns()
                    try:
                        output = self.ops.apply_directional(
                            args["img"],
                            self.history.residuals[0].tensor,
                            self.history.residuals[1].tensor,
                            self.global_alpha,
                        )
                    except BaseException:
                        self.wrapper_failure_count += 1
                        self._invalidate_history(step)
                        raise
                    self.prediction_application_ns.append(perf_counter_ns() - started)
                    self.max_transient_prediction_count = max(self.max_transient_prediction_count, 1)
                    self.max_live_residual_sized_buffers = max(self.max_live_residual_sized_buffers, 3)
                    self.replay_active_step = step
                    self.replay_count += 1
                    self.replayed_block_call_count += 1
                    record.update({
                        "decision": "REUSE_DIRECTIONAL_TRANSFORM",
                        "reason": reason,
                        "directional_prediction_applied": True,
                        "replayed_block_calls": 1,
                    })
                    self._invalidate_history(step)
                    return {"img": output}
                metadata = dict(self.ops.metadata(args["img"]))
                self.max_live_residual_sized_buffers = max(
                    self.max_live_residual_sized_buffers, len(self.history.residuals) + 1
                )
                self.max_additional_gpu_bytes = max(
                    self.max_additional_gpu_bytes,
                    int(metadata["bytes"]) * self.max_live_residual_sized_buffers,
                )
                self.segment_snapshot = self.ops.clone(args["img"])
                record["decision"] = "FULL_COMPUTE"
                if replay and not valid:
                    record["reason"] = reason
            if self.replay_active_step == step and SEGMENT_START < block_index <= SEGMENT_END:
                self.replayed_block_call_count += 1
                record["replayed_block_calls"] += 1
                return {"img": args["img"]}
            started = perf_counter_ns()
            try:
                result = extra_options["original_block"](args)
            except BaseException:
                self.wrapper_failure_count += 1
                self.segment_snapshot = None
                self.history.residuals.clear()
                raise
            finally:
                self.original_ns.append(perf_counter_ns() - started)
            self.original_block_call_count += 1
            record["original_block_calls"] += 1
            if block_index == SEGMENT_END:
                self._capture(result["img"], step, record)
            return result

        return wrapper

    def install_on_guider_clone(self, guider: Any) -> Any:
        patched_guider = copy.copy(guider)
        patched_patcher = guider.model_patcher.clone()
        for index in range(BLOCK_COUNT):
            patched_patcher.set_model_patch_replace(
                self.block_wrapper(index), "dit", "double_block", index
            )
        patched_guider.model_patcher = patched_patcher
        patched_guider.model_options = patched_patcher.model_options
        return patched_guider

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": "c3-r4.two-residual-directional-prediction.1",
            "mode": self.mode,
            "mechanism": MECHANISM,
            "predictor_kind": PREDICTOR_KIND,
            "global_alpha": self.global_alpha,
            "alpha_grid": list(ALPHA_GRID),
            "segment": {
                "logical_id": SEGMENT_LOGICAL_ID,
                "block_start": SEGMENT_START,
                "block_end": SEGMENT_END,
                "block_count": len(SEGMENT_BLOCKS),
            },
            "model_forward_count": self.model_forward_count,
            "original_block_call_count": self.original_block_call_count,
            "replayed_block_call_count": self.replayed_block_call_count,
            "actual_replay_steps": self.replay_count,
            "residual_capture_count": self.residual_capture_count,
            "mapping_error_count": self.mapping_error_count,
            "wrapper_failure_count": self.wrapper_failure_count,
            "persistent_residual_count": len(self.history.residuals),
            "max_persistent_residual_count": self.max_persistent_residual_count,
            "persistent_direction_count": 0,
            "persistent_predicted_residual_count": 0,
            "per_block_cache_count": 0,
            "max_transient_prediction_count": self.max_transient_prediction_count,
            "max_live_residual_sized_buffers": self.max_live_residual_sized_buffers,
            "max_additional_gpu_bytes": self.max_additional_gpu_bytes,
            "shadow_full_prediction_tensor_count": 0,
            "diagnostics": self.diagnostics,
            "events": self.events,
            "per_step": [self.per_step[key] for key in sorted(self.per_step)],
            "memory_samples": self.memory_samples,
            "timing": {
                "original_block": _timing(self.original_ns),
                "residual_capture": _timing(self.capture_ns),
                "history_rotation": _timing(self.history_rotation_ns),
                "scalar_statistics": _timing(self.scalar_statistics_ns),
                "alpha_evaluation": _timing(self.alpha_evaluation_ns),
                "prediction_application": _timing(self.prediction_application_ns),
                "cache_invalidation": _timing(self.cache_invalidation_ns),
            },
            "tensor_bytes_to_rust": 0,
            "full_tensor_host_copy_bytes": 0,
            "full_size_fp32_materialization_count": 0,
        }


def directional_settings_digest(
    *, actual_replay_enabled: bool, global_alpha: float | None, calibrated_targets: tuple[int, ...]
) -> str:
    validate_global_alpha(global_alpha, required=actual_replay_enabled)
    validate_calibrated_targets(calibrated_targets)
    payload = {
        "mechanism": MECHANISM,
        "mode": SELECTIVE if actual_replay_enabled else CONTROL,
        "directional_replay_enabled": actual_replay_enabled,
        "global_alpha": global_alpha,
        "alpha_grid": list(ALPHA_GRID),
        "raw_baseline_alpha": RAW_BASELINE_ALPHA,
        "calibrated_targets": list(calibrated_targets),
        "candidate_ceiling": list(FROZEN_CEILING),
        "anchors": list(FULL_COMPUTE_ANCHORS),
        "segment": [SEGMENT_START, SEGMENT_END],
        "residual_cosine_min": RESIDUAL_COSINE_MIN,
        "normalized_residual_l2_max": NORMALIZED_RESIDUAL_L2_MAX,
        "raw_non_regression_required": True,
        "minimum_target_spacing": MIN_TARGET_SPACING,
        "minimum_calibrated_targets": MIN_CALIBRATED_TARGETS,
        "total_steps": TOTAL_STEPS,
        "block_count": BLOCK_COUNT,
        "persistent_full_residual_max": MAX_PERSISTENT_RESIDUALS,
        "persistent_direction_max": MAX_PERSISTENT_DIRECTIONS,
        "persistent_prediction_max": MAX_PERSISTENT_PREDICTIONS,
        "transient_prediction_max": MAX_TRANSIENT_PREDICTIONS,
        "prediction_chaining": False,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
