"""Repository-owned Standard H3 aggregate bottleneck profiler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

import torch
from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import comfy.ldm.minimax.model as h3_model

from hive_product.h3_e2e_bottleneck_profile import H3AggregateTimingController
from hive_product.h3_subblock_cost_surface import (
    MODEL_SOURCE_SHA256,
    inspect_installed_source,
)


RECEIPT_ENV = "HIVEFRAME_H3_E2E_PROFILE_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_E2E_PROFILE_ADMISSION"
_ACTIVE = False


def _atomic_write(target_value: str | None, payload: dict[str, Any]) -> None:
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


_SOURCE_GATE = inspect_installed_source(Path(h3_model.__file__).resolve())
_atomic_write(
    os.environ.get(ADMISSION_ENV),
    {
        "schema_version": "h3.e2e-bottleneck-profile.admission.1",
        "process_id": os.getpid(),
        "status": "PASS"
        if _SOURCE_GATE.get("admitted")
        and _SOURCE_GATE.get("source_sha256") == MODEL_SOURCE_SHA256
        else "FAIL",
        "source_admission": _SOURCE_GATE,
        "v4_observer_enabled": False,
        "v4_evidence_transfer_bytes": 0,
    },
)


class HIVEFRAMEH3EndToEndProfileSampler(io.ComfyNode):
    """Run the unchanged Standard sampler with bounded deferred aggregate timing."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3EndToEndProfileSampler",
            category="hiveframe/profile",
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.String.Input("run_digest"),
                io.String.Input("workflow_revision_digest"),
                io.String.Input("settings_digest"),
                io.String.Input("model_revision_digest"),
            ],
            outputs=[
                io.Latent.Output(display_name="output"),
                io.Latent.Output(display_name="denoised_output"),
            ],
        )

    @classmethod
    def execute(
        cls,
        noise: Any,
        guider: Any,
        sampler: Any,
        sigmas: Any,
        latent_image: Any,
        run_digest: str,
        workflow_revision_digest: str,
        settings_digest: str,
        model_revision_digest: str,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("H3 aggregate profiler rejects concurrent execution")
        source_gate = inspect_installed_source(Path(h3_model.__file__).resolve())
        if not source_gate.get("admitted") or source_gate.get("source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("H3 aggregate profiler source contract changed")
        cuda_available = torch.cuda.is_available()
        controller = H3AggregateTimingController(
            event_factory=lambda: torch.cuda.Event(enable_timing=True),
            synchronize=torch.cuda.synchronize,
            mod_scale_shift=h3_model._mod_scale_shift,
            mod_gate=h3_model._mod_gate,
            optimized_attention=h3_model.optimized_attention,
            cast_to=h3_model.comfy.model_management.cast_to,
            in_training=lambda: bool(h3_model.comfy.model_management.in_training),
            rms_rope=h3_model.comfy.quant_ops.ck.rms_rope_split_half,
            rms_rope_in_place=h3_model.comfy.quant_ops.ck.rms_rope_split_half_,
            linear_input_act=h3_model.comfy.ops.linear_input_act,
            events_supported=cuda_available,
            unsupported_reason=None if cuda_available else "torch.cuda.is_available() is false",
        )
        payload: dict[str, Any] = {
            "schema_version": "h3.e2e-bottleneck-profile.callback.1",
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "sampler_succeeded": False,
            "error_type": None,
            "full_compute_only": True,
            "v4_observer_enabled": False,
            "v4_evidence_transfer_bytes": 0,
        }
        _ACTIVE = True
        allocator_before: dict[str, int] = {}
        try:
            if cuda_available:
                allocator_before = {
                    "allocated_bytes": int(torch.cuda.memory_allocated()),
                    "reserved_bytes": int(torch.cuda.memory_reserved()),
                    "max_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                    "max_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                }
            controller.install(h3_model.DiTBlock, h3_model.MiniMaxH3Model)
            controller.start_sampler()
            result = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent_image)
            controller.end_sampler()
            payload["timing"] = controller.finalize()
            payload["allocator"] = {
                "support_status": "collected" if cuda_available else "unsupported",
                "before": allocator_before if cuda_available else None,
                "after": {
                    "allocated_bytes": int(torch.cuda.memory_allocated()),
                    "reserved_bytes": int(torch.cuda.memory_reserved()),
                    "max_allocated_bytes": int(torch.cuda.max_memory_allocated()),
                    "max_reserved_bytes": int(torch.cuda.max_memory_reserved()),
                }
                if cuda_available
                else None,
                "reset_peak_memory_stats_called": False,
            }
            payload["sampler_succeeded"] = True
            _atomic_write(os.environ.get(RECEIPT_ENV), payload)
            return result
        except BaseException as error:
            payload["error_type"] = type(error).__name__
            try:
                if controller.sampler_timing_active:
                    controller.end_sampler()
                payload["timing"] = controller.finalize()
            except BaseException as timing_error:
                payload["timing"] = {
                    "support_status": "unsupported",
                    "reason": type(timing_error).__name__,
                }
            _atomic_write(os.environ.get(RECEIPT_ENV), payload)
            raise
        finally:
            controller.restore()
            _ACTIVE = False


class H3EndToEndProfileExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3EndToEndProfileSampler]


async def comfy_entrypoint() -> H3EndToEndProfileExtension:
    return H3EndToEndProfileExtension()
