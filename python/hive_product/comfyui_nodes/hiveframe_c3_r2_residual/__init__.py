"""Repository-owned C3-R2 H3 segment-residual replay sampler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import latent_preview

from hive_product.compound_eye_shadow import CompoundEyeShadowBridge, ShadowContext, wrap_async_shadow_callback
from hive_product.segment_residual_replay import (
    CONTROL,
    SELECTIVE,
    H3SegmentResidualController,
    ResidualReplayShadowPipeline,
    ReusePlanBridge,
    ReusePlanContext,
)


POLICY_RECEIPT_ENV = "HIVEFRAME_C3_R2_RECEIPT"
_ACTIVE = False


def _parse_targets(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    try:
        return tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise ValueError("calibrated_targets_csv must contain comma-separated integers") from error


def _write_receipt(
    pipeline: ResidualReplayShadowPipeline,
    controller: H3SegmentResidualController,
    sampler_succeeded: bool,
    error: str | None,
) -> None:
    target_value = os.environ.get(POLICY_RECEIPT_ENV)
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "c3-r2.segment-residual-replay.1",
        "sampler_succeeded": sampler_succeeded,
        "error_type": error,
        "c2_shadow": pipeline.receipt(),
        "c3_r2_plan": pipeline.plan_bridge.receipt(),
        "segment_execution": controller.receipt(),
    }
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class HIVEFRAMEH3SegmentResidualReplaySampler(io.ComfyNode):
    """Run matched residual-capture CONTROL or one-shot SELECTIVE sampling."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3SegmentResidualReplaySampler",
            category="hiveframe/c3-r2",
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
                io.String.Input("calibrated_targets_csv", default=""),
                io.Boolean.Input("actual_residual_replay_enabled", default=False),
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
        calibrated_targets_csv: str,
        actual_residual_replay_enabled: bool,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("C3-R2 wrapper rejects concurrent sampler execution")
        calibrated_targets = _parse_targets(calibrated_targets_csv)
        shadow_bridge = CompoundEyeShadowBridge(
            ShadowContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
            )
        )
        plan_bridge = ReusePlanBridge(
            ReusePlanContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
                model_revision_digest=model_revision_digest,
            ),
            calibrated_targets,
        )
        pipeline = ResidualReplayShadowPipeline(shadow_bridge, plan_bridge)
        controller = H3SegmentResidualController(
            SELECTIVE if bool(actual_residual_replay_enabled) else CONTROL,
            plan_bridge,
            workflow_revision_digest=workflow_revision_digest,
            model_revision_digest=model_revision_digest,
            settings_digest=settings_digest,
        )
        patched_guider = controller.install_on_guider_clone(guider)
        original_prepare_callback = latent_preview.prepare_callback

        def prepare_callback(model: Any, steps: int, x0_output_dict: Any = None):
            original_callback = original_prepare_callback(model, steps, x0_output_dict)
            return wrap_async_shadow_callback(original_callback, pipeline)

        _ACTIVE = True
        latent_preview.prepare_callback = prepare_callback
        try:
            result = SamplerCustomAdvanced.execute(noise, patched_guider, sampler, sigmas, latent_image)
        except BaseException as error:
            pipeline.drain()
            _write_receipt(pipeline, controller, False, type(error).__name__)
            raise
        else:
            pipeline.drain()
            _write_receipt(pipeline, controller, True, None)
            return result
        finally:
            latent_preview.prepare_callback = original_prepare_callback
            _ACTIVE = False


class C3R2ResidualExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3SegmentResidualReplaySampler]


async def comfy_entrypoint() -> C3R2ResidualExtension:
    return C3R2ResidualExtension()
