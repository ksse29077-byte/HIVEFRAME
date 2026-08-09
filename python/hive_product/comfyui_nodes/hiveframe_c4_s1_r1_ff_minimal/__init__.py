"""Repository-owned C4-S1-R1 minimal-telemetry H3 sampler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import comfy.ldm.minimax.model as h3_model
import torch

from hive_product.ff_token_minimal import (
    CONTROL_MODE,
    SELECTIVE_MODE,
    H3FFTokenMinimalController,
)
from hive_product.ff_token_selective import (
    MODEL_SOURCE_SHA256,
    POLICY_BY_ID,
    inspect_installed_ff_source,
)


RECEIPT_ENV = "HIVEFRAME_C4_S1_R1_RECEIPT"
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


class HIVEFRAMEH3FFTokenMinimalSampler(io.ComfyNode):
    """Keep global attention Full Compute while minimizing selector telemetry."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3FFTokenMinimalSampler",
            category="hiveframe/c4-s1-r1",
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.String.Input("mode"),
                io.String.Input("selected_policy"),
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
        mode: str,
        selected_policy: str,
        run_digest: str,
        workflow_revision_digest: str,
        settings_digest: str,
        model_revision_digest: str,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("C4-S1-R1 rejects concurrent sampler execution")
        if mode == SELECTIVE_MODE and selected_policy not in POLICY_BY_ID:
            raise RuntimeError("C4-S1-R1 SELECTIVE policy is not frozen")
        if mode == CONTROL_MODE and selected_policy:
            raise RuntimeError("C4-S1-R1 CONTROL cannot select a live policy")
        if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
            raise RuntimeError("C4-S1-R1 mode is unsupported")
        source_gate = inspect_installed_ff_source(Path(h3_model.__file__).resolve())
        if not source_gate.get("admitted") or source_gate.get("source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("C4-S1-R1 installed H3 source contract changed")
        controller = H3FFTokenMinimalController(
            mode=mode,
            selected_policy=selected_policy or None,
            mod_scale_shift=h3_model._mod_scale_shift,
            mod_gate=h3_model._mod_gate,
            torch_module=torch,
        )
        payload: dict[str, Any] = {
            "schema_version": "c4-s1-r1.h3.ff-token-minimal.callback.1",
            "mode": mode,
            "selected_policy": selected_policy or None,
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "sampler_succeeded": False,
            "error_type": None,
            "attention_execution": "ALWAYS_FULL_COMPUTE",
        }
        _ACTIVE = True
        controller.install(h3_model.DiTBlock)
        controller.start_sampler()
        try:
            result = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent_image)
            controller.end_sampler()
            payload["instrumentation"] = controller.finalize()
            payload["sampler_succeeded"] = True
            _write_receipt(payload)
            return result
        except BaseException as error:
            payload["error_type"] = type(error).__name__
            try:
                if controller.sampler_timing_active:
                    controller.end_sampler()
                payload["instrumentation"] = controller.finalize()
            except BaseException as instrumentation_error:
                payload["instrumentation"] = {
                    "support_status": "unsupported",
                    "reason": type(instrumentation_error).__name__,
                    "value": None,
                }
            _write_receipt(payload)
            raise
        finally:
            controller.restore()
            _ACTIVE = False


class C4S1R1FFMinimalExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3FFTokenMinimalSampler]


async def comfy_entrypoint() -> C4S1R1FFMinimalExtension:
    return C4S1R1FFMinimalExtension()
