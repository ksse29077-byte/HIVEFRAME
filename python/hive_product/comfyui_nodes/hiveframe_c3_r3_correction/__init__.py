"""Repository-owned C3-R3 compact residual correction sampler node."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import os

from comfy_api.latest import ComfyExtension, io
from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced
import latent_preview

from hive_product.compound_eye_shadow import CompoundEyeShadowBridge, ShadowContext, wrap_async_shadow_callback
from hive_product.compact_residual_correction import (
    CONTROL,
    SELECTIVE,
    CorrectionPlanBridge,
    CorrectionPlanContext,
    CorrectionShadowPipeline,
    H3CompactResidualCorrectionController,
    validate_calibrated_targets,
)


POLICY_RECEIPT_ENV = "HIVEFRAME_C3_R3_RECEIPT"
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


def _write_receipt(
    pipeline: CorrectionShadowPipeline,
    controller: H3CompactResidualCorrectionController,
    sampler_succeeded: bool,
    error: str | None,
) -> None:
    target_value = os.environ.get(POLICY_RECEIPT_ENV)
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "c3-r3.compact-residual-correction.1",
        "sampler_succeeded": sampler_succeeded,
        "error_type": error,
        "c2_shadow": pipeline.receipt(),
        "c3_r3_plan": pipeline.plan_bridge.receipt(),
        "segment_execution": controller.receipt(),
    }
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class HIVEFRAMEH3CompactResidualCorrectionSampler(io.ComfyNode):
    """Run correction-shadow CONTROL or admitted corrected replay sampling."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMEH3CompactResidualCorrectionSampler",
            category="hiveframe/c3-r3",
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
                io.Boolean.Input("actual_corrected_replay_enabled", default=False),
            ],
            outputs=[
                io.Latent.Output(display_name="output"),
                io.Latent.Output(display_name="denoised_output"),
            ],
        )

    @classmethod
    def execute(
        cls, noise: Any, guider: Any, sampler: Any, sigmas: Any, latent_image: Any,
        run_digest: str, workflow_revision_digest: str, settings_digest: str,
        model_revision_digest: str, calibrated_targets_csv: str,
        actual_corrected_replay_enabled: bool,
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("C3-R3 wrapper rejects concurrent sampler execution")
        calibrated_targets = _parse_targets(calibrated_targets_csv)
        shadow_bridge = CompoundEyeShadowBridge(
            ShadowContext(run_digest, workflow_revision_digest, settings_digest)
        )
        plan_bridge = CorrectionPlanBridge(
            CorrectionPlanContext(
                run_digest, workflow_revision_digest, settings_digest, model_revision_digest
            ),
            calibrated_targets,
        )
        pipeline = CorrectionShadowPipeline(shadow_bridge, plan_bridge)
        controller = H3CompactResidualCorrectionController(
            SELECTIVE if bool(actual_corrected_replay_enabled) else CONTROL,
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


class C3R3CorrectionExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMEH3CompactResidualCorrectionSampler]


async def comfy_entrypoint() -> C3R3CorrectionExtension:
    return C3R3CorrectionExtension()
