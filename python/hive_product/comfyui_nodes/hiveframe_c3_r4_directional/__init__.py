"""Repository-owned C3-R4 two-residual directional sampler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import latent_preview

from hive_product.compound_eye_shadow import (
    CompoundEyeShadowBridge,
    ShadowContext,
    wrap_async_shadow_callback,
)
from hive_product.compact_residual_correction import CorrectionPlanContext
from hive_product.two_residual_directional_prediction import (
    CONTROL,
    SELECTIVE,
    DirectionalPlanBridge,
    DirectionalShadowPipeline,
    H3TwoResidualDirectionalController,
    validate_calibrated_targets,
    validate_global_alpha,
)


POLICY_RECEIPT_ENV = "HIVEFRAME_C3_R4_RECEIPT"
_ACTIVE = False


def _parse_targets(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    try:
        targets = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as error:
        raise ValueError("calibrated_targets_csv must contain comma-separated integers") from error
    validate_calibrated_targets(targets)
    return targets


def _parse_alpha(value: str, *, required: bool) -> float | None:
    if not value.strip():
        validate_global_alpha(None, required=required)
        return None
    try:
        alpha = float(value)
    except ValueError as error:
        raise ValueError("global_alpha_text must be one frozen numeric alpha") from error
    validate_global_alpha(alpha, required=required)
    return alpha


def _write_receipt(
    pipeline: DirectionalShadowPipeline,
    controller: H3TwoResidualDirectionalController,
    sampler_succeeded: bool,
    error: str | None,
) -> None:
    target_value = os.environ.get(POLICY_RECEIPT_ENV)
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "c3-r4.two-residual-directional-prediction.1",
        "sampler_succeeded": sampler_succeeded,
        "error_type": error,
        "c2_shadow": pipeline.receipt(),
        "c3_r4_plan": pipeline.plan_bridge.receipt(),
        "segment_execution": controller.receipt(),
    }
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class HIVEFRAMEH3TwoResidualDirectionalSampler(io.ComfyNode):
    """Run Full Compute directional shadow or an admitted directional replay."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3TwoResidualDirectionalSampler",
            category="hiveframe/c3-r4",
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
                io.String.Input("global_alpha_text", default=""),
                io.Boolean.Input("directional_replay_enabled", default=False),
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
        global_alpha_text: str,
        directional_replay_enabled: bool,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("C3-R4 wrapper rejects concurrent sampler execution")
        targets = _parse_targets(calibrated_targets_csv)
        global_alpha = _parse_alpha(global_alpha_text, required=bool(directional_replay_enabled))
        if not directional_replay_enabled and targets:
            raise ValueError("CONTROL must not receive calibrated targets")
        shadow_bridge = CompoundEyeShadowBridge(
            ShadowContext(run_digest, workflow_revision_digest, settings_digest)
        )
        plan_bridge = DirectionalPlanBridge(
            CorrectionPlanContext(
                run_digest, workflow_revision_digest, settings_digest, model_revision_digest
            ),
            targets,
            global_alpha,
        )
        pipeline = DirectionalShadowPipeline(shadow_bridge, plan_bridge)
        controller = H3TwoResidualDirectionalController(
            SELECTIVE if bool(directional_replay_enabled) else CONTROL,
            plan_bridge,
            workflow_revision_digest=workflow_revision_digest,
            model_revision_digest=model_revision_digest,
            settings_digest=settings_digest,
            global_alpha=global_alpha,
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


class C3R4DirectionalExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3TwoResidualDirectionalSampler]


async def comfy_entrypoint() -> C3R4DirectionalExtension:
    return C3R4DirectionalExtension()
