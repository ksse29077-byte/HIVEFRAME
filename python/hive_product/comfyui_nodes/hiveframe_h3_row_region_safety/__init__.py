"""Repository-owned Full Compute H3 row/region safety sampler."""

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

from hive_product.a3_g1_conditional_reuse import CONTROL_MODE
from hive_product.active_query_attention import (
    MODEL_SOURCE_SHA256,
    ActiveQueryShadowPipeline,
    RegionPlanContext,
    inspect_installed_attention_source,
)
from hive_product.compound_eye_shadow import (
    CompoundEyeShadowBridge,
    ShadowContext,
    wrap_async_shadow_callback,
)
from hive_product.h3_row_region_safety import (
    H3RowRegionSafetyController,
    SafetyEvidencePlanBridge,
    settings_digest as safety_settings_digest,
)


RECEIPT_ENV = "HIVEFRAME_H3_ROW_REGION_RECEIPT"
NODE_CLASS = "HIVEFRAMEH3RowRegionSafetyControlSampler"
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


class HIVEFRAMEH3RowRegionSafetyControlSampler(io.ComfyNode):
    """Run exactly one Full Compute CONTROL with bounded safety observation."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id=NODE_CLASS,
            category="hiveframe/h3-safety",
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.String.Input("mode"),
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
        run_digest: str,
        workflow_revision_digest: str,
        settings_digest: str,
        model_revision_digest: str,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("row/region CONTROL rejects concurrent sampler execution")
        if mode != CONTROL_MODE:
            raise RuntimeError("row/region safety node accepts Full Compute CONTROL only")
        if settings_digest != safety_settings_digest():
            raise RuntimeError("row/region safety settings digest mismatch")

        model_source = Path(h3_model.__file__).resolve()
        attention_source = model_source.parents[1] / "modules" / "attention.py"
        source_gate = inspect_installed_attention_source(model_source, attention_source)
        if not source_gate.get("admitted") or source_gate.get("model_source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("installed H3 Attention source contract changed")

        shadow_bridge = CompoundEyeShadowBridge(
            ShadowContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
            )
        )
        plan_bridge = SafetyEvidencePlanBridge(
            RegionPlanContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
                model_revision_digest=model_revision_digest,
            )
        )
        pipeline = ActiveQueryShadowPipeline(shadow_bridge, plan_bridge)
        controller = H3RowRegionSafetyController(
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch,
        )
        payload: dict[str, Any] = {
            "schema_version": "h3.row-region-safety.callback.1",
            "mode": mode,
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "sampler_succeeded": False,
            "error_type": None,
            "sage_enabled": False,
            "full_compute_only": True,
            "selective_execution_count": 0,
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
            payload["error_message"] = str(error)[:1000]
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
            controller.close()
            _ACTIVE = False


class H3RowRegionSafetyExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3RowRegionSafetyControlSampler]


async def comfy_entrypoint() -> H3RowRegionSafetyExtension:
    return H3RowRegionSafetyExtension()
