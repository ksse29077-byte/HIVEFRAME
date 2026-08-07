"""Repository-owned C4-S0 Full Compute H3 sub-block timing node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

import torch
from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import comfy.ldm.minimax.model as h3_model

from hive_product.h3_subblock_cost_surface import (
    H3SubBlockTimingController,
    MODEL_SOURCE_SHA256,
    inspect_installed_source,
)


RECEIPT_ENV = "HIVEFRAME_C4_S0_RECEIPT"
_ACTIVE = False


def _write_receipt(payload: dict[str, Any]) -> None:
    target_value = os.environ.get(RECEIPT_ENV)
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class HIVEFRAMEH3SubBlockCostSampler(io.ComfyNode):
    """Run the Standard sampler with operation-identical deferred event timing."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3SubBlockCostSampler",
            category="hiveframe/c4-s0",
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
            raise RuntimeError("C4-S0 rejects concurrent sampler execution")
        source_path = Path(h3_model.__file__).resolve()
        source_gate = inspect_installed_source(source_path)
        if not source_gate.get("admitted") or source_gate.get("source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("C4-S0 installed H3 source contract changed")
        controller = H3SubBlockTimingController(
            event_factory=lambda: torch.cuda.Event(enable_timing=True),
            synchronize=torch.cuda.synchronize,
            mod_scale_shift=h3_model._mod_scale_shift,
            mod_gate=h3_model._mod_gate,
            events_supported=torch.cuda.is_available(),
            unsupported_reason=None if torch.cuda.is_available() else "torch.cuda.is_available() is false",
        )
        payload: dict[str, Any] = {
            "schema_version": "c4-s0.h3.subblock-cost-surface.1",
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "sampler_succeeded": False,
            "error_type": None,
            "full_compute_only": True,
            "skip_count": 0,
            "reuse_count": 0,
            "prediction_count": 0,
            "regional_execution_count": 0,
            "token_omission_count": 0,
            "attention_omission_count": 0,
        }
        _ACTIVE = True
        controller.install(h3_model.DiTBlock)
        controller.start_sampler()
        try:
            result = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent_image)
            controller.end_sampler()
            payload["timing"] = controller.finalize()
            payload["sampler_succeeded"] = True
            _write_receipt(payload)
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
                    "value": None,
                }
            _write_receipt(payload)
            raise
        finally:
            controller.restore()
            _ACTIVE = False


class C4S0SubBlockCostExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3SubBlockCostSampler]


async def comfy_entrypoint() -> C4S0SubBlockCostExtension:
    return C4S0SubBlockCostExtension()
