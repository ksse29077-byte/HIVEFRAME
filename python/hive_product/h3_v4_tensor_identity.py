"""Inference-compatible tensor identity for the H3 V4 observer."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping
import json


INFERENCE_NO_VERSION_COUNTER = "INFERENCE_NO_VERSION_COUNTER"
NORMAL_VERSION_COUNTER = "NORMAL_VERSION_COUNTER"


class TensorIdentityError(ValueError):
    """Reject an unsafe or unsupported tensor identity."""


@dataclass(frozen=True)
class TensorIdentitySnapshot:
    """Separate authoritative logical identity from diagnostic storage telemetry."""

    logical_identity: dict[str, Any]
    logical_digest: str
    storage_telemetry: dict[str, Any]
    version_semantics: str
    version_counter_available: bool
    version_counter_value: int | None

    def bounded_receipt(self) -> dict[str, Any]:
        """Return structural identity without pointer or Python object values."""

        return {
            "logical_digest": self.logical_digest,
            "shape": list(self.logical_identity["tensor_shape"]),
            "stride": list(self.logical_identity["tensor_stride"]),
            "layout": self.logical_identity["tensor_layout"],
            "dtype": self.logical_identity["tensor_dtype"],
            "device": self.logical_identity["tensor_device"],
            "storage_offset": self.logical_identity["storage_offset"],
            "expected_byte_range": list(
                self.logical_identity["expected_byte_range"]
            ),
            "is_inference": self.storage_telemetry["is_inference"],
            "version_semantics": self.version_semantics,
            "version_counter_available": self.version_counter_available,
        }


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(value), sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def _expected_byte_range(tensor: Any) -> tuple[int, int]:
    shape = tuple(int(value) for value in tensor.shape)
    stride = tuple(int(value) for value in tensor.stride())
    if len(shape) != len(stride) or any(value < 0 for value in stride):
        raise TensorIdentityError("V4 tensor layout is unsupported")
    element_size = int(tensor.element_size())
    storage_offset = int(tensor.storage_offset())
    if storage_offset < 0 or element_size <= 0:
        raise TensorIdentityError("V4 tensor storage metadata is invalid")
    if not shape or any(value == 0 for value in shape):
        byte_offset = storage_offset * element_size
        return byte_offset, byte_offset
    final_element = storage_offset + sum(
        (extent - 1) * axis_stride
        for extent, axis_stride in zip(shape, stride, strict=True)
    )
    return storage_offset * element_size, (final_element + 1) * element_size


def capture_tensor_identity(
    torch_module: Any,
    tensor: Any,
    *,
    lineage_identity: Mapping[str, Any],
    workflow_digest: str,
) -> TensorIdentitySnapshot:
    """Capture one identity without touching an inference tensor version counter."""

    try:
        is_inference = bool(torch_module.is_inference(tensor))
    except (AttributeError, RuntimeError, TypeError) as error:
        raise TensorIdentityError("V4 tensor inference state is unavailable") from error
    version_available = not is_inference
    version_value: int | None = None
    semantics = INFERENCE_NO_VERSION_COUNTER
    if version_available:
        semantics = NORMAL_VERSION_COUNTER
        try:
            version_value = int(tensor._version)
        except (AttributeError, RuntimeError, TypeError) as error:
            raise TensorIdentityError(
                "V4 normal tensor version counter is unavailable"
            ) from error

    try:
        storage = tensor.untyped_storage()
        storage_nbytes = int(storage.nbytes())
        byte_range = _expected_byte_range(tensor)
        if byte_range[0] < 0 or byte_range[1] > storage_nbytes:
            raise TensorIdentityError("V4 tensor byte range exceeds its storage")
        logical_identity = {
            **dict(lineage_identity),
            "workflow_digest": str(workflow_digest),
            "tensor_shape": tuple(int(value) for value in tensor.shape),
            "tensor_stride": tuple(int(value) for value in tensor.stride()),
            "tensor_layout": str(tensor.layout),
            "tensor_dtype": str(tensor.dtype),
            "tensor_device": str(tensor.device),
            "storage_offset": int(tensor.storage_offset()),
            "expected_byte_range": byte_range,
        }
        storage_telemetry = {
            "python_object_id": id(tensor),
            "data_ptr": int(tensor.data_ptr()),
            "storage_data_ptr": int(storage.data_ptr()),
            "storage_nbytes": storage_nbytes,
            "is_inference": is_inference,
        }
    except TensorIdentityError:
        raise
    except (AttributeError, RuntimeError, TypeError, ValueError) as error:
        raise TensorIdentityError("V4 tensor identity capture failed") from error

    return TensorIdentitySnapshot(
        logical_identity=logical_identity,
        logical_digest=_canonical_digest(logical_identity),
        storage_telemetry=storage_telemetry,
        version_semantics=semantics,
        version_counter_available=version_available,
        version_counter_value=version_value,
    )


def tensor_identity_matches(
    before: TensorIdentitySnapshot, after: TensorIdentitySnapshot
) -> bool:
    """Compare logical identity and diagnostic storage continuity."""

    return (
        before.logical_identity == after.logical_identity
        and before.logical_digest == after.logical_digest
        and before.storage_telemetry == after.storage_telemetry
        and before.version_semantics == after.version_semantics
        and before.version_counter_available == after.version_counter_available
        and before.version_counter_value == after.version_counter_value
    )


__all__ = [
    "INFERENCE_NO_VERSION_COUNTER",
    "NORMAL_VERSION_COUNTER",
    "TensorIdentityError",
    "TensorIdentitySnapshot",
    "capture_tensor_identity",
    "tensor_identity_matches",
]
