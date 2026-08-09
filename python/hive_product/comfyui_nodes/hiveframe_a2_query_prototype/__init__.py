"""Repository-owned A2 GPU regional query-prototype sampler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import comfy.ldm.minimax.model as h3_model
import latent_preview
import torch

from hive_product.active_query_attention import ActiveQueryShadowPipeline
from hive_product.compound_eye_shadow import CompoundEyeShadowBridge, ShadowContext, wrap_async_shadow_callback
from hive_product.regional_query_prototype_attention import (
    CONTROL_MODE,
    MODEL_SOURCE_SHA256,
    SELECTIVE_MODE,
    AttentionRegionPlanBridge,
    H3RegionalQueryPrototypeController,
    RegionPlanContext,
    inspect_installed_attention_source,
)


RECEIPT_ENV = "HIVEFRAME_A2_RECEIPT"
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


class HIVEFRAMEH3RegionalQueryPrototypeSampler(io.ComfyNode):
    """Run matched A2 CONTROL or conditionally admitted SELECTIVE sampling."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3RegionalQueryPrototypeSampler",
            category="hiveframe/a2",
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.String.Input("mode"),
                io.String.Input("admitted_blocks_json"),
                io.String.Input("run_digest"),
                io.String.Input("workflow_revision_digest"),
                io.String.Input("settings_digest"),
                io.String.Input("model_revision_digest"),
            ],
            outputs=[io.Latent.Output(display_name="output"), io.Latent.Output(display_name="denoised_output")],
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
        admitted_blocks_json: str,
        run_digest: str,
        workflow_revision_digest: str,
        settings_digest: str,
        model_revision_digest: str,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("A2 rejects concurrent sampler execution")
        if mode not in {CONTROL_MODE, SELECTIVE_MODE}:
            raise RuntimeError("A2 mode is unsupported")
        try:
            parsed = json.loads(admitted_blocks_json)
        except json.JSONDecodeError as error:
            raise RuntimeError("A2 admitted block list is malformed") from error
        if not isinstance(parsed, list) or any(not isinstance(value, int) for value in parsed):
            raise RuntimeError("A2 admitted block list must contain integers")
        admitted_blocks = tuple(parsed)
        if mode == CONTROL_MODE and admitted_blocks:
            raise RuntimeError("A2 CONTROL cannot carry admitted execution blocks")
        if mode == SELECTIVE_MODE and not admitted_blocks:
            raise RuntimeError("A2 SELECTIVE requires the frozen CONTROL block set")
        model_source = Path(h3_model.__file__).resolve()
        source_gate = inspect_installed_attention_source(model_source, model_source.parents[1] / "modules" / "attention.py")
        if not source_gate.get("admitted") or source_gate.get("model_source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("A2 installed H3 attention source contract changed")

        shadow_bridge = CompoundEyeShadowBridge(
            ShadowContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
            )
        )
        plan_bridge = AttentionRegionPlanBridge(
            RegionPlanContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
                model_revision_digest=model_revision_digest,
            )
        )
        pipeline = ActiveQueryShadowPipeline(shadow_bridge, plan_bridge)
        controller = H3RegionalQueryPrototypeController(
            mode=mode,
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch,
            admitted_blocks=admitted_blocks,
        )
        payload: dict[str, Any] = {
            "schema_version": "a2.h3.query-prototype.callback.1",
            "mode": mode,
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "admitted_blocks": list(admitted_blocks),
            "sampler_succeeded": False,
            "error_type": None,
            "sage_enabled": False,
        }
        original_prepare_callback = latent_preview.prepare_callback

        def prepare_callback(model: Any, steps: int, x0_output_dict: Any = None):
            original_callback = original_prepare_callback(model, steps, x0_output_dict)
            return wrap_async_shadow_callback(original_callback, pipeline)

        _ACTIVE = True
        controller.install(h3_model.DiTBlock)
        latent_preview.prepare_callback = prepare_callback
        try:
            result = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent_image)
            pipeline.drain()
            payload["c2_shadow"] = pipeline.receipt()
            payload["region_plan"] = plan_bridge.receipt()
            payload["attention_execution"] = controller.finalize()
            payload["sampler_succeeded"] = True
            _write_receipt(payload)
            return result
        except BaseException as error:
            payload["error_type"] = type(error).__name__
            try:
                pipeline.drain()
                payload["c2_shadow"] = pipeline.receipt()
                payload["region_plan"] = plan_bridge.receipt()
                payload["attention_execution"] = controller.finalize()
            except BaseException as receipt_error:
                payload["receipt_error_type"] = type(receipt_error).__name__
            _write_receipt(payload)
            raise
        finally:
            latent_preview.prepare_callback = original_prepare_callback
            controller.restore()
            _ACTIVE = False


class A2QueryPrototypeExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3RegionalQueryPrototypeSampler]


async def comfy_entrypoint() -> A2QueryPrototypeExtension:
    return A2QueryPrototypeExtension()
