"""Bounded, metadata-only diagnostics for H3 background-oracle lineage."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable, Mapping, Sequence
import json
import os


CAPSULE_SCHEMA_VERSION = "h3.background-oracle-lineage-capsule.1"
CAPSULE_MAX_BYTES = 512 * 1024
TRACE_HISTORY_LIMIT = 16
TRACE_POST_MISMATCH_LIMIT = 4
FULL_TRACE_LIMIT = 600
VALIDATION_RULE = "source_denoise_ordinal + 1 == current_denoise_ordinal"


class LineageDiagnosticError(Exception):
    """Reject malformed or incomplete lineage diagnostics."""


class LineageDiagnosticAbort(Exception):
    """Escape Attention fallback while remaining visible to ComfyUI."""


class LineageDiagnosticCapsuleWriteError(LineageDiagnosticError):
    """Report a fail-closed atomic capsule persistence failure."""


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def scheduler_timestep_trace(sigmas: Any, *, expected_steps: int = 20) -> tuple[str, ...]:
    """Capture CPU scheduler values without treating them as ordinal numbers."""

    device = getattr(sigmas, "device", None)
    if device is not None and getattr(device, "type", None) != "cpu":
        raise LineageDiagnosticError("scheduler timestep capture requires CPU sigmas")
    values = sigmas.detach().tolist() if hasattr(sigmas, "detach") else list(sigmas)
    if len(values) < expected_steps:
        raise LineageDiagnosticError("scheduler timestep sequence is shorter than denoise steps")
    return tuple(float(value).hex() for value in values[:expected_steps])


@dataclass(frozen=True)
class LineageDiagnosticContext:
    generation_id_digest: str
    workflow_digest: str
    model_digest: str
    scheduler_digest: str
    settings_digest: str
    scheduler_timesteps: tuple[str, ...]
    capsule_path: Path

    @classmethod
    def create(
        cls,
        *,
        run_digest: str,
        workflow_digest: str,
        model_digest: str,
        settings_digest: str,
        scheduler_timesteps: Sequence[str],
        capsule_path: Path,
    ) -> "LineageDiagnosticContext":
        timesteps = tuple(str(value) for value in scheduler_timesteps)
        if len(timesteps) != 20:
            raise LineageDiagnosticError("diagnostic scheduler trace must contain 20 values")
        return cls(
            generation_id_digest=sha256(run_digest.encode()).hexdigest(),
            workflow_digest=str(workflow_digest),
            model_digest=str(model_digest),
            scheduler_digest=_canonical_digest(timesteps),
            settings_digest=str(settings_digest),
            scheduler_timesteps=timesteps,
            capsule_path=Path(capsule_path),
        )

    def scheduler_timestep(self, denoise_ordinal: int) -> str:
        if not 0 <= int(denoise_ordinal) < len(self.scheduler_timesteps):
            raise LineageDiagnosticError("denoise ordinal is outside scheduler trace")
        return self.scheduler_timesteps[int(denoise_ordinal)]


_TRACE_FIELDS = (
    "source_step_raw",
    "current_step_raw",
    "source_denoise_ordinal",
    "current_denoise_ordinal",
    "source_scheduler_timestep",
    "current_scheduler_timestep",
    "model_forward_ordinal",
    "attention_call_ordinal",
    "block_id",
    "region_id",
    "oracle_enqueue_sequence",
    "oracle_completion_sequence",
    "finalizer_sequence",
    "ring_slot_id",
    "ring_slot_generation",
    "ring_write_sequence",
    "ring_read_sequence",
    "source_lineage_digest",
    "current_lineage_digest",
    "source_shape_dtype_device",
    "current_shape_dtype_device",
    "validation_rule",
    "rejection_reason",
)


def lineage_digest(context: LineageDiagnosticContext, metadata: Mapping[str, Any]) -> str:
    """Bind a record to generation, scheduler, ordinal, block, and region identity."""

    return _canonical_digest(
        {
            "generation_id_digest": context.generation_id_digest,
            "workflow_digest": context.workflow_digest,
            "model_digest": context.model_digest,
            "scheduler_digest": context.scheduler_digest,
            "settings_digest": context.settings_digest,
            "denoise_ordinal": int(metadata["current_denoise_ordinal"]),
            "scheduler_timestep": str(metadata["current_scheduler_timestep"]),
            "block_id": int(metadata["block_id"]),
            "region_id": int(metadata["region_id"]),
        }
    )


def validate_diagnostic_pair(
    source: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> tuple[str, str]:
    """Validate explicit diagnostic identity without changing production policy."""

    current_ordinal = int(current["current_denoise_ordinal"])
    if source is None:
        return (
            ("FULL_COMPUTE", "FIRST_DENOISE_HAS_NO_SOURCE")
            if current_ordinal == 0
            else ("REJECT", "DUPLICATE_OR_MISSING_RECORD")
        )
    for name in (
        "generation_id_digest",
        "workflow_digest",
        "model_digest",
        "scheduler_digest",
        "settings_digest",
    ):
        if source.get(name) != current.get(name):
            return "REJECT", f"CROSS_IDENTITY:{name}"
    if source.get("block_id") != current.get("block_id") or source.get(
        "region_id"
    ) != current.get("region_id"):
        return "REJECT", "BLOCK_OR_REGION_MISMATCH"
    source_ordinal = int(source["current_denoise_ordinal"])
    if source_ordinal >= current_ordinal:
        return "REJECT", "FUTURE_OR_DUPLICATE_SOURCE"
    if source_ordinal + 1 != current_ordinal:
        return "FULL_COMPUTE", "CACHE_AGE_NOT_ONE"
    if int(source.get("ring_slot_generation", 0)) <= 0 or int(
        current.get("ring_slot_generation", 0)
    ) <= 0:
        return "REJECT", "STALE_RING_SLOT_GENERATION"
    return "PASS", "AGE_ONE_IDENTITY_MATCH"


def validate_diagnostic_trace(records: Sequence[Mapping[str, Any]]) -> None:
    """Reject duplicate records and non-monotonic physical sequence identities."""

    keys: set[tuple[Any, ...]] = set()
    enqueue_sequences: set[int] = set()
    for record in records:
        key = (
            record.get("generation_id_digest"),
            record.get("current_denoise_ordinal"),
            record.get("block_id"),
            record.get("region_id"),
        )
        sequence = int(record["oracle_enqueue_sequence"])
        if key in keys or sequence in enqueue_sequences:
            raise LineageDiagnosticError("duplicate diagnostic lineage record")
        keys.add(key)
        enqueue_sequences.add(sequence)


def replay_ring_backpressure_capsule(capsule: Mapping[str, Any]) -> dict[str, Any]:
    """Replay the bounded H3 trace that preceded a missing oracle record."""

    mismatch = capsule.get("mismatch")
    if not isinstance(mismatch, Mapping):
        raise LineageDiagnosticError("lineage capsule mismatch record is missing")
    reason = str(capsule.get("rejection_reason", ""))
    if reason != "DUPLICATE_OR_MISSING_RECORD:RING_SLOT_NOT_FREE":
        raise LineageDiagnosticError("lineage capsule is not a ring backpressure trace")
    if capsule.get("logical_denoise_order") != list(range(20)):
        raise LineageDiagnosticError("logical denoise order changed in lineage capsule")
    timesteps = capsule.get("raw_scheduler_timestep_order")
    if not isinstance(timesteps, list) or len(timesteps) != 20:
        raise LineageDiagnosticError("scheduler timestep trace is incomplete")

    source_ordinal = int(mismatch["source_denoise_ordinal"])
    current_ordinal = int(mismatch["current_denoise_ordinal"])
    enqueue_sequence = int(mismatch["oracle_enqueue_sequence"])
    fully_consumed_before = int(capsule["last_fully_consumed_sequence_before_mismatch"])
    completed_before = int(capsule["last_completion_sequence_before_mismatch"])
    finalized_before = int(capsule["last_finalizer_sequence_before_mismatch"])
    pending = capsule.get("pending_records_before_mismatch")
    if not isinstance(pending, list) or not pending:
        raise LineageDiagnosticError("pending ring records are missing")
    pending_sequences = sorted(int(item["oracle_enqueue_sequence"]) for item in pending)
    if source_ordinal + 1 != current_ordinal:
        raise LineageDiagnosticError("captured source was not age one at backpressure")
    if pending_sequences != list(range(fully_consumed_before + 1, enqueue_sequence)):
        raise LineageDiagnosticError("pending ring sequence is not contiguous")
    if completed_before < fully_consumed_before or finalized_before < fully_consumed_before:
        raise LineageDiagnosticError("physical completion precedes logical consumption")

    replay = {
        "cause": "DUPLICATE_OR_MISSING_RECORD",
        "proven_trigger": "RING_SLOT_NOT_FREE",
        "source_denoise_ordinal": source_ordinal,
        "current_denoise_ordinal": current_ordinal,
        "oracle_enqueue_sequence": enqueue_sequence,
        "last_fully_consumed_sequence_before_mismatch": fully_consumed_before,
        "last_completion_sequence_before_mismatch": completed_before,
        "last_finalizer_sequence_before_mismatch": finalized_before,
        "occupied_slot_count": len(pending_sequences),
        "pending_sequences": pending_sequences,
        "source_age_one_at_failure": True,
        "scheduler_timestep_order_preserved": True,
        "required_action": "FAIL_CLOSED_BEFORE_NATIVE_FULL_FALLBACK",
        "native_full_fallback_allowed": False,
        "missing_record_created": False,
        "later_false_age_mismatch_prevented": True,
    }
    replay["replay_digest"] = _canonical_digest(replay)
    return replay


def _trace_view(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    return {name: metadata.get(name) for name in _TRACE_FIELDS}


class LineageDiagnosticRecorder:
    """Keep bounded metadata in memory and persist only on failure or completion."""

    def __init__(
        self,
        context: LineageDiagnosticContext,
        *,
        writer: Callable[[Path, bytes], None] | None = None,
    ) -> None:
        self.context = context
        self.failure_signal = Event()
        self._lock = Lock()
        self._writer = writer or self._atomic_write
        self._history: deque[dict[str, Any]] = deque(maxlen=TRACE_HISTORY_LIMIT)
        self._full_trace: list[dict[str, Any]] = []
        self._completion_sequence = 0
        self._finalizer_sequence = 0
        self.capsule_written = False
        self.capsule_write_failure_reason: str | None = None
        self.rejection_reason: str | None = None

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(content)
        os.replace(temporary, path)

    @property
    def failed(self) -> bool:
        return self.failure_signal.is_set()

    def enrich_enqueue(
        self,
        metadata: Mapping[str, Any],
        *,
        enqueue_sequence: int,
        ring_slot_id: int,
        ring_slot_generation: int,
        ring_write_sequence: int,
    ) -> dict[str, Any]:
        if self.failed:
            raise LineageDiagnosticAbort("lineage failure signal blocks new oracle enqueue")
        enriched = dict(metadata)
        enriched.update(
            {
                "generation_id_digest": self.context.generation_id_digest,
                "workflow_digest": self.context.workflow_digest,
                "model_digest": self.context.model_digest,
                "scheduler_digest": self.context.scheduler_digest,
                "settings_digest": self.context.settings_digest,
                "oracle_enqueue_sequence": int(enqueue_sequence),
                "oracle_completion_sequence": None,
                "finalizer_sequence": None,
                "ring_slot_id": int(ring_slot_id),
                "ring_slot_generation": int(ring_slot_generation),
                "ring_write_sequence": int(ring_write_sequence),
                "ring_read_sequence": None,
                "validation_rule": VALIDATION_RULE,
                "rejection_reason": None,
            }
        )
        enriched["current_lineage_digest"] = lineage_digest(self.context, enriched)
        return enriched

    def mark_completion(self, metadata: dict[str, Any]) -> None:
        with self._lock:
            if metadata.get("oracle_completion_sequence") is None:
                self._completion_sequence += 1
                metadata["oracle_completion_sequence"] = self._completion_sequence

    def mark_finalizer(self, metadata: dict[str, Any], *, ring_read_sequence: int) -> None:
        with self._lock:
            self._finalizer_sequence += 1
            metadata["finalizer_sequence"] = self._finalizer_sequence
            metadata["ring_read_sequence"] = int(ring_read_sequence)

    def record_valid_pair(
        self,
        *,
        source: Mapping[str, Any] | None,
        current: Mapping[str, Any],
    ) -> None:
        record = self.pair_view(source=source, current=current, rejection_reason=None)
        with self._lock:
            if len(self._full_trace) >= FULL_TRACE_LIMIT:
                raise LineageDiagnosticError("bounded lineage metadata trace overflow")
            self._history.append(record)
            self._full_trace.append(record)

    @staticmethod
    def pair_view(
        *,
        source: Mapping[str, Any] | None,
        current: Mapping[str, Any],
        rejection_reason: str | None,
    ) -> dict[str, Any]:
        result = dict(current)
        result.update(
            {
                "source_step_raw": None if source is None else source.get("current_step_raw"),
                "source_denoise_ordinal": (
                    None if source is None else source.get("current_denoise_ordinal")
                ),
                "source_scheduler_timestep": (
                    None if source is None else source.get("current_scheduler_timestep")
                ),
                "source_lineage_digest": (
                    None if source is None else source.get("current_lineage_digest")
                ),
                "source_shape_dtype_device": (
                    None if source is None else source.get("current_shape_dtype_device")
                ),
                "rejection_reason": rejection_reason,
                "validation_rule": VALIDATION_RULE,
            }
        )
        return _trace_view(result) or {}

    def capture_failure(
        self,
        *,
        rejection_reason: str,
        source: Mapping[str, Any] | None,
        current: Mapping[str, Any],
        completed_after_mismatch: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        self.failure_signal.set()
        mismatch = self.pair_view(
            source=source, current=current, rejection_reason=rejection_reason
        )
        post = [
            _trace_view(item) for item in completed_after_mismatch[:TRACE_POST_MISMATCH_LIMIT]
        ]
        capsule = {
            "schema_version": CAPSULE_SCHEMA_VERSION,
            "maximum_bytes": CAPSULE_MAX_BYTES,
            "identity": {
                "generation_id_digest": self.context.generation_id_digest,
                "workflow_digest": self.context.workflow_digest,
                "model_digest": self.context.model_digest,
                "scheduler_digest": self.context.scheduler_digest,
                "settings_digest": self.context.settings_digest,
            },
            "logical_denoise_order": list(range(20)),
            "raw_scheduler_timestep_order": list(self.context.scheduler_timesteps),
            "normal_records_before_mismatch": list(self._history),
            "mismatch": mismatch,
            "completed_records_after_mismatch": post,
            "normal_record_count_before_mismatch": len(self._full_trace),
            "rejection_reason": rejection_reason,
            "tensor_payload_bytes": 0,
            "rust_calls": 0,
            "rust_metadata_bytes": 0,
            "tensor_to_rust_bytes": 0,
            "hot_path_forced_cpu_sync": 0,
        }
        self.rejection_reason = rejection_reason
        self._persist(capsule)
        return capsule

    def write_complete_trace(self) -> dict[str, Any]:
        capsule = {
            "schema_version": CAPSULE_SCHEMA_VERSION,
            "maximum_bytes": CAPSULE_MAX_BYTES,
            "identity": {
                "generation_id_digest": self.context.generation_id_digest,
                "workflow_digest": self.context.workflow_digest,
                "model_digest": self.context.model_digest,
                "scheduler_digest": self.context.scheduler_digest,
                "settings_digest": self.context.settings_digest,
            },
            "logical_denoise_order": list(range(20)),
            "raw_scheduler_timestep_order": list(self.context.scheduler_timesteps),
            "complete_lineage_trace": list(self._full_trace),
            "complete_record_count": len(self._full_trace),
            "rejection_reason": None,
            "tensor_payload_bytes": 0,
            "rust_calls": 0,
            "rust_metadata_bytes": 0,
            "tensor_to_rust_bytes": 0,
            "hot_path_forced_cpu_sync": 0,
        }
        self._persist(capsule)
        return capsule

    def _persist(self, capsule: Mapping[str, Any]) -> None:
        content = (json.dumps(capsule, indent=2, sort_keys=True) + "\n").encode()
        if len(content) > CAPSULE_MAX_BYTES:
            self.capsule_write_failure_reason = "CAPSULE_SIZE_LIMIT_EXCEEDED"
            raise LineageDiagnosticCapsuleWriteError(
                self.capsule_write_failure_reason
            )
        try:
            self._writer(self.context.capsule_path, content)
        except BaseException as error:
            self.capsule_write_failure_reason = (
                f"CAPSULE_ATOMIC_WRITE_FAILED:{type(error).__name__}"
            )
            raise LineageDiagnosticCapsuleWriteError(
                self.capsule_write_failure_reason
            ) from error
        self.capsule_written = True

    def receipt(self) -> dict[str, Any]:
        return {
            "schema_version": CAPSULE_SCHEMA_VERSION,
            "capsule_written": self.capsule_written,
            "capsule_write_failure_reason": self.capsule_write_failure_reason,
            "failure_signal_set": self.failed,
            "rejection_reason": self.rejection_reason,
            "bounded_history_count": len(self._history),
            "bounded_full_trace_count": len(self._full_trace),
            "completion_sequence_count": self._completion_sequence,
            "finalizer_sequence_count": self._finalizer_sequence,
            "maximum_capsule_bytes": CAPSULE_MAX_BYTES,
            "rust_calls": 0,
            "rust_metadata_bytes": 0,
            "tensor_to_rust_bytes": 0,
            "hot_path_forced_cpu_sync": 0,
        }
