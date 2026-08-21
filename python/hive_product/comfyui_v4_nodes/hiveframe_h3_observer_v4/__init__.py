"""CONTROL-only ComfyUI node for the isolated H3 V4 observation runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import comfy.ldm.minimax.model as h3_model
import latent_preview
import psutil
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
from hive_product.h3_background_oracle_lineage import scheduler_timestep_trace
from hive_product.h3_bounded_host_source_oracle_v4 import (
    RAM_RESERVE_MIN_BYTES,
    frozen_inventory_digest,
    settings_digest,
)
from hive_product.h3_observer_v4 import (
    H3ObserverControllerV4,
    PROFILE_DIGEST,
    PROFILE_ID,
    V4HostSourceResources,
)
from hive_product.h3_row_region_safety import SafetyEvidencePlanBridge


RECEIPT_ENV = "HIVEFRAME_H3_OBSERVER_V4_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_OBSERVER_V4_ADMISSION"
NODE_CLASS = "HIVEFRAMEH3ObserverV4ControlSampler"
_ACTIVE = False


def _write_json(path_value: str | None, payload: dict[str, Any]) -> None:
    if not path_value:
        return
    target = Path(path_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(target)


try:
    _memory_before = psutil.virtual_memory()
    _RESOURCES = V4HostSourceResources(torch)
    _memory_after = psutil.virtual_memory()
    if int(_memory_after.available) < RAM_RESERVE_MIN_BYTES:
        raise RuntimeError("V4 host allocation violates the 1.5 GiB RAM reserve")
    _RESOURCE_ERROR: BaseException | None = None
    _write_json(
        os.environ.get(ADMISSION_ENV),
        {
            **_RESOURCES.admission_receipt(),
            "physical_ram_bytes": int(_memory_before.total),
            "available_ram_before_pinned_bytes": int(_memory_before.available),
            "available_ram_after_pinned_bytes": int(_memory_after.available),
            "required_ram_reserve_bytes": RAM_RESERVE_MIN_BYTES,
            "process_id": os.getpid(),
        },
    )
except BaseException as error:
    _RESOURCES = None
    _RESOURCE_ERROR = error
    _write_json(
        os.environ.get(ADMISSION_ENV),
        {
            "status": "BLOCK",
            "error_type": type(error).__name__,
            "process_id": os.getpid(),
        },
    )


class HIVEFRAMEH3ObserverV4ControlSampler(io.ComfyNode):
    """Run exact H3 Full Compute while collecting the frozen V4 holdout."""

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
                io.String.Input("observer_profile_digest"),
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
        observer_profile_digest: str,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("V4 observer rejects concurrent sampler execution")
        if _RESOURCES is None:
            raise RuntimeError("V4 observer pinned-host admission failed") from _RESOURCE_ERROR
        if mode != CONTROL_MODE:
            raise RuntimeError("V4 observer is disabled outside explicit CONTROL mode")
        if settings_digest != PROFILE_DIGEST or observer_profile_digest != PROFILE_DIGEST:
            raise RuntimeError("V4 observer profile identity changed")

        model_source = Path(h3_model.__file__).resolve()
        attention_source = model_source.parents[1] / "modules" / "attention.py"
        source_gate = inspect_installed_attention_source(model_source, attention_source)
        if (
            not source_gate.get("admitted")
            or source_gate.get("model_source_sha256") != MODEL_SOURCE_SHA256
        ):
            raise RuntimeError("installed H3 Attention source contract changed")

        generation_digest = __import__("hashlib").sha256(
            (
                f"{run_digest}:{workflow_revision_digest}:{settings_digest}:"
                f"{model_revision_digest}:{observer_profile_digest}"
            ).encode()
        ).hexdigest()
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
        controller = H3ObserverControllerV4(
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch,
            resources=_RESOURCES,
            generation_digest=generation_digest,
            workflow_digest=workflow_revision_digest,
            model_digest=model_revision_digest,
            profile_digest=observer_profile_digest,
            scheduler_timesteps=tuple(
                str(value) for value in scheduler_timestep_trace(sigmas)
            ),
        )
        payload: dict[str, Any] = {
            "schema_version": "h3.observer-v4.callback.1",
            "mode": mode,
            "profile_id": PROFILE_ID,
            "profile_digest": observer_profile_digest,
            "inventory_digest": frozen_inventory_digest(),
            "run_digest": run_digest,
            "workflow_revision_digest": workflow_revision_digest,
            "settings_digest": settings_digest,
            "model_revision_digest": model_revision_digest,
            "source_admission": source_gate,
            "sampler_succeeded": False,
            "sampler_execution_completed": False,
            "error_type": None,
            "sage_enabled": False,
            "full_compute_only": True,
            "selective_execution_count": 0,
            "partial_q_execution_count": 0,
            "attention_omission_count": 0,
            "output_mutation_count": 0,
            "controller_creation_count": 1,
        }
        original_prepare_callback = latent_preview.prepare_callback
        finalized = False

        def prepare_callback(model: Any, steps: int, x0_output_dict: Any = None):
            original_callback = original_prepare_callback(model, steps, x0_output_dict)
            return wrap_async_shadow_callback(original_callback, pipeline)

        _ACTIVE = True
        controller.start_observing()
        controller.install(h3_model.DiTBlock)
        latent_preview.prepare_callback = prepare_callback
        try:
            result = SamplerCustomAdvanced.execute(
                noise, guider, sampler, sigmas, latent_image
            )
            pipeline.drain()
            payload["c2_shadow"] = pipeline.receipt()
            payload["region_plan"] = plan_bridge.receipt()
            payload["attention_execution"] = controller.finalize()
            finalized = True
            payload["sampler_succeeded"] = True
            payload["sampler_execution_completed"] = True
            _write_json(os.environ.get(RECEIPT_ENV), payload)
            return result
        except BaseException as error:
            payload["error_type"] = type(error).__name__
            payload["error_message"] = str(error)[:1000]
            try:
                pipeline.drain()
                payload["c2_shadow"] = pipeline.receipt()
                payload["region_plan"] = plan_bridge.receipt()
            except BaseException as pipeline_error:
                payload["pipeline_error_type"] = type(pipeline_error).__name__
            if not finalized:
                controller.abort(type(error).__name__)
                payload["attention_execution"] = controller.failure_receipt()
            _write_json(os.environ.get(RECEIPT_ENV), payload)
            raise
        finally:
            latent_preview.prepare_callback = original_prepare_callback
            controller.restore()
            controller.close()
            _ACTIVE = False


class H3ObserverV4ControlExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3ObserverV4ControlSampler]


async def comfy_entrypoint() -> H3ObserverV4ControlExtension:
    return H3ObserverV4ControlExtension()
