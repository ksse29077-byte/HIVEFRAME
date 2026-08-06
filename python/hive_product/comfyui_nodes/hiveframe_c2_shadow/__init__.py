"""Repository-owned ComfyUI node for C2 Compound Eye shadow policy."""

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
    wrap_shadow_callback,
)


POLICY_RECEIPT_ENV = "HIVEFRAME_C2_SHADOW_RECEIPT"
_ACTIVE = False


def _write_receipt(
    bridge: CompoundEyeShadowBridge, sampler_succeeded: bool, error: str | None
) -> None:
    target_value = os.environ.get(POLICY_RECEIPT_ENV)
    if not target_value:
        return
    target = Path(target_value)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = bridge.receipt()
    payload["sampler_succeeded"] = sampler_succeeded
    payload["error_type"] = error
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


class HIVEFRAMECompoundEyeShadowSampler(io.ComfyNode):
    """Wrap Standard H3 sampling without changing any compute decision."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="HIVEFRAMECompoundEyeShadowSampler",
            category="hiveframe/c2",
            inputs=[
                io.Noise.Input("noise"),
                io.Guider.Input("guider"),
                io.Sampler.Input("sampler"),
                io.Sigmas.Input("sigmas"),
                io.Latent.Input("latent_image"),
                io.String.Input("run_digest"),
                io.String.Input("workflow_revision_digest"),
                io.String.Input("settings_digest"),
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
    ) -> io.NodeOutput:
        global _ACTIVE
        if _ACTIVE:
            raise RuntimeError("C2 shadow wrapper rejects concurrent sampler execution")
        bridge = CompoundEyeShadowBridge(
            ShadowContext(
                run_digest=run_digest,
                workflow_revision_digest=workflow_revision_digest,
                settings_digest=settings_digest,
            )
        )
        original_prepare_callback = latent_preview.prepare_callback

        def prepare_callback(model: Any, steps: int, x0_output_dict: Any = None):
            original_callback = original_prepare_callback(model, steps, x0_output_dict)
            return wrap_shadow_callback(original_callback, bridge)

        _ACTIVE = True
        latent_preview.prepare_callback = prepare_callback
        try:
            result = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent_image)
        except BaseException as error:
            _write_receipt(bridge, False, type(error).__name__)
            raise
        else:
            _write_receipt(bridge, True, None)
            return result
        finally:
            latent_preview.prepare_callback = original_prepare_callback
            _ACTIVE = False


class C2ShadowExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [HIVEFRAMECompoundEyeShadowSampler]


async def comfy_entrypoint() -> C2ShadowExtension:
    return C2ShadowExtension()
