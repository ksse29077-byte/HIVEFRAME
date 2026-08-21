"""Repository-owned Full Compute H3 CONTROL V2 sampler."""

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
from hive_product.h3_row_region_safety import SafetyEvidencePlanBridge
from hive_product.h3_background_oracle_lineage import (
    LineageDiagnosticAbort,
    LineageDiagnosticContext,
    LineageDiagnosticRecorder,
    scheduler_timestep_trace,
)
from hive_product.h3_row_region_safety_v2 import (
    H3RowRegionSafetyControllerV2,
    PreallocatedPinnedRing,
    settings_digest as v2_settings_digest,
)
from hive_product.h3_hybrid_cache_staging import build_ring_capacity_admission


RECEIPT_ENV = "HIVEFRAME_H3_ROW_REGION_V2_RECEIPT"
ADMISSION_ENV = "HIVEFRAME_H3_ROW_REGION_V2_ADMISSION"
LINEAGE_CAPSULE_ENV = "HIVEFRAME_H3_LINEAGE_DIAGNOSTIC_CAPSULE"
NODE_CLASS = "HIVEFRAMEH3RowRegionSafetyControlV2Sampler"
_ACTIVE = False


def _write_json(path_value: str | None, payload: dict[str, Any]) -> None:
    if not path_value:
        return
    target = Path(path_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


try:
    _memory = psutil.virtual_memory()
    _ring_admission = build_ring_capacity_admission(
        current_available_ram_bytes=int(_memory.available)
    )
    if not _ring_admission["admitted"]:
        raise RuntimeError("available host RAM cannot admit the required pinned ring")
    _RESOURCES = PreallocatedPinnedRing(
        torch, slot_count=int(_ring_admission["required_slots"])
    )
    _memory_after = psutil.virtual_memory()
    if int(_memory_after.available) < (
        int(_ring_admission["required_host_reserve_bytes"])
        + int(_ring_admission["non_ring_runtime_reserve_bytes"])
    ):
        raise RuntimeError("host reserve fell below the post-allocation requirement")
    _RESOURCE_ERROR: BaseException | None = None
    _write_json(
        os.environ.get(ADMISSION_ENV),
        {
            "status": "PASS",
            "page_locked": all(slot.payload.is_pinned() for slot in _RESOURCES.slots),
            "pinned_host_bytes": _RESOURCES.allocated_bytes,
            "slot_bytes": int(_RESOURCES.slots[0].payload.numel())
            * int(_RESOURCES.slots[0].payload.element_size()),
            "slot_states": [slot.state for slot in _RESOURCES.slots],
            "ring_capacity": _ring_admission,
            "physical_ram_bytes": int(_memory.total),
            "available_ram_before_pinned_bytes": int(_memory.available),
            "available_ram_after_pinned_bytes": int(_memory_after.available),
            "process_id": os.getpid(),
        },
    )
except BaseException as error:
    _RESOURCES = None
    _RESOURCE_ERROR = error
    _write_json(
        os.environ.get(ADMISSION_ENV),
        {"status": "BLOCK", "error_type": type(error).__name__, "process_id": os.getpid()},
    )


class HIVEFRAMEH3RowRegionSafetyControlV2Sampler(io.ComfyNode):
    """Run one exact Full Compute CONTROL with the Balanced12GB oracle."""

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
            raise RuntimeError("CONTROL V2 rejects concurrent sampler execution")
        if _RESOURCES is None:
            raise RuntimeError("CONTROL V2 pinned-host admission failed") from _RESOURCE_ERROR
        if mode != CONTROL_MODE or settings_digest != v2_settings_digest():
            raise RuntimeError("CONTROL V2 settings contract changed")

        model_source = Path(h3_model.__file__).resolve()
        attention_source = model_source.parents[1] / "modules" / "attention.py"
        source_gate = inspect_installed_attention_source(model_source, attention_source)
        if not source_gate.get("admitted") or source_gate.get("model_source_sha256") != MODEL_SOURCE_SHA256:
            raise RuntimeError("installed H3 Attention source contract changed")

        lineage_base = __import__("hashlib").sha256(
            f"{run_digest}:{workflow_revision_digest}:{settings_digest}:{model_revision_digest}".encode()
        ).hexdigest()
        capsule_path = os.environ.get(LINEAGE_CAPSULE_ENV)
        diagnostic = None
        if capsule_path:
            context = LineageDiagnosticContext.create(
                run_digest=run_digest,
                workflow_digest=workflow_revision_digest,
                model_digest=model_revision_digest,
                settings_digest=settings_digest,
                scheduler_timesteps=scheduler_timestep_trace(sigmas),
                capsule_path=Path(capsule_path),
            )
            diagnostic = LineageDiagnosticRecorder(context)
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
        controller = H3RowRegionSafetyControllerV2(
            plan_bridge=plan_bridge,
            h3_model=h3_model,
            torch_module=torch,
            resources=_RESOURCES,
            lineage_base=lineage_base,
            diagnostic=diagnostic,
        )
        payload: dict[str, Any] = {
            "schema_version": "h3.row-region-safety-control-v2.callback.1",
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
            "partial_q_execution_count": 0,
            "attention_omission_count": 0,
            "lineage_diagnostic_only": diagnostic is not None,
            "valid_control_result_count": 0 if diagnostic is not None else None,
        }
        original_prepare_callback = latent_preview.prepare_callback
        finalize_attempted = False

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
            finalize_attempted = True
            payload["attention_execution"] = (
                controller.finalize()
                if diagnostic is None
                else controller.finalize_diagnostic()
            )
            payload["sampler_succeeded"] = diagnostic is None
            payload["sampler_execution_completed"] = True
            _write_json(os.environ.get(RECEIPT_ENV), payload)
            if diagnostic is not None:
                raise LineageDiagnosticAbort(
                    "lineage diagnostic completed without a mismatch"
                )
            return result
        except BaseException as error:
            payload["error_type"] = type(error).__name__
            payload["error_message"] = str(error)[:1000]
            try:
                pipeline.drain()
                payload["c2_shadow"] = pipeline.receipt()
                payload["region_plan"] = plan_bridge.receipt()
                if diagnostic is not None and not finalize_attempted:
                    finalize_attempted = True
                    payload["attention_execution"] = (
                        controller.diagnostic_failure_receipt()
                    )
                elif not finalize_attempted:
                    finalize_attempted = True
                    payload["attention_execution"] = controller.finalize()
            except BaseException as receipt_error:
                payload["receipt_error_type"] = type(receipt_error).__name__
            _write_json(os.environ.get(RECEIPT_ENV), payload)
            raise
        finally:
            latent_preview.prepare_callback = original_prepare_callback
            controller.restore()
            controller.close()
            _ACTIVE = False


class H3RowRegionSafetyControlV2Extension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3RowRegionSafetyControlV2Sampler]


async def comfy_entrypoint() -> H3RowRegionSafetyControlV2Extension:
    return H3RowRegionSafetyControlV2Extension()
