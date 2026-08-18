from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
import json
import threading
import time
import unittest
from unittest.mock import patch

from hive_product.comfyui_backend import (
    REQUIRED_MODELS,
    REQUIRED_NODES,
    SAGE_NODE_CLASS,
    SAGE_NODE_ID,
    ComfyUIH3Config,
    LoopbackComfyClient,
    MiniMaxH3ComfyUIBackend,
)
from hive_product.server import create_server
from hive_product.service import ProductService


ROOT = Path(__file__).resolve().parents[2]


class FakeComfyClient:
    def __init__(self) -> None:
        self.submits = 0
        self.queue_reads = 0
        self.phase = "automatic"
        self.prompt_id = "prompt-test-001"
        self.sage_available = True
        self.uploads: list[dict] = []
        self.submitted_prompt: dict | None = None

    def json(self, method: str, path: str, body: dict | None = None):
        if path == "/system_stats":
            return {
                "system": {
                    "comfyui_version": "test",
                    "python_version": "test",
                    "pytorch_version": "test",
                    "ram_total": 64_000,
                    "ram_free": 32_000,
                },
                "devices": [{"name": "cuda:0 test", "type": "cuda", "vram_total": 12_000, "vram_free": 8_000}],
            }
        if path == "/object_info":
            result = {name: {"input": {"required": {}}} for name in REQUIRED_NODES}
            result["LoadImage"] = {"input": {"required": {}}}
            result["UNETLoader"]["input"]["required"]["unet_name"] = [[REQUIRED_MODELS["diffusion_model"]]]
            result["CLIPLoader"]["input"]["required"]["clip_name"] = [[REQUIRED_MODELS["text_encoder"]]]
            result["VAELoader"]["input"]["required"]["vae_name"] = [[REQUIRED_MODELS["video_vae"], REQUIRED_MODELS["audio_vae"]]]
            if self.sage_available:
                result[SAGE_NODE_CLASS] = {"input": {"required": {"sage_attention": [["auto", "disabled"]]}}}
            return result
        if path == "/prompt" and method == "POST":
            self.submits += 1
            self.submitted_prompt = body["prompt"] if body else None
            return {"prompt_id": self.prompt_id, "node_errors": {}}
        if path.startswith("/history/"):
            succeeded = self.phase == "succeeded" or (self.phase == "automatic" and self.queue_reads >= 2)
            if not succeeded:
                return {}
            return {
                self.prompt_id: {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {
                        "14": {"video": [{"filename": "hiveframe.mp4", "subfolder": "hiveframe", "type": "output"}]}
                    },
                }
            }
        if path == "/queue" and method == "GET":
            if self.submits == 0:
                return {"queue_running": [], "queue_pending": []}
            if self.phase == "cancelled":
                return {"queue_running": [], "queue_pending": []}
            self.queue_reads += 1
            if self.phase == "queued" or (self.phase == "automatic" and self.queue_reads == 1):
                return {"queue_running": [], "queue_pending": [[1, self.prompt_id]]}
            return {"queue_running": [[1, self.prompt_id]], "queue_pending": []}
        if path == "/queue" and method == "POST":
            self.phase = "cancelled"
            return {}
        if path == "/interrupt" and method == "POST":
            self.phase = "cancelled"
            return {}
        raise AssertionError(f"unexpected fake request: {method} {path}")

    def bytes(self, path: str) -> bytes:
        if path.startswith("/view?"):
            return b"fake-comfyui-video"
        raise AssertionError(path)

    def upload_image(self, *, filename: str, media_type: str, content: bytes) -> dict:
        self.uploads.append({"filename": filename, "media_type": media_type, "content": content})
        return {"name": filename, "subfolder": "", "type": "input"}


def write_fixture(root: Path) -> ComfyUIH3Config:
    asset_root = root / "assets"
    asset_root.mkdir()
    for filename in REQUIRED_MODELS.values():
        (asset_root / filename).write_bytes(b"fixture")
    nested = [{"id": index, "type": name} for index, name in enumerate(sorted(REQUIRED_NODES - {"SaveVideo"}), 1)]
    workflow = {
        "nodes": [{"id": 1, "type": "SaveVideo"}],
        "definitions": {"subgraphs": [{"id": "fixture", "nodes": nested}]},
        "model_refs": list(REQUIRED_MODELS.values()),
    }
    workflow_path = asset_root / "video_minimax_h3_t2v.json"
    workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
    comfy_root = root / "comfyui"
    comfy_root.mkdir()
    output_root = root / "output"
    return ComfyUIH3Config(
        asset_root=asset_root,
        comfyui_root=comfy_root,
        base_url="http://127.0.0.1:8188",
        workflow=workflow_path,
        output_root=output_root,
        # Keep each externally visible state observable through the HTTP API.
        poll_interval_seconds=0.05,
        timeout_seconds=10,
    )


@contextmanager
def running_product(service: ProductService):
    server = create_server(service, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def api(base: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class ProductComfyUIBackendTests(unittest.TestCase):
    def test_loopback_client_accepts_empty_success_response(self) -> None:
        class EmptyResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def read() -> bytes:
                return b""

        client = LoopbackComfyClient("http://127.0.0.1:8188")
        with patch("hive_product.comfyui_backend.urlopen", return_value=EmptyResponse()):
            self.assertEqual(client.json("POST", "/queue", {"delete": ["prompt-id"]}), {})

    def test_runtime_asset_workflow_and_api_copy_contract(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary:
            client = FakeComfyClient()
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            self.assertEqual(backend.inspect_runtime()["state"], "ready")
            self.assertEqual(backend.inspect_assets()["state"], "ready")
            workflow = backend.inspect_workflow()
            self.assertEqual(workflow["state"], "ready")
            self.assertTrue(workflow["api_copy_required"])
            fast_profile = next(
                profile
                for profile in workflow["available_execution_profiles"]
                if profile["profile"] == "fast_2m_candidate"
            )
            self.assertEqual(fast_profile["target_wall_seconds"], 180)
            api_workflow = backend.build_api_workflow(
                {"content": [{"type": "text", "text": "fixture prompt"}]},
                output_prefix="hiveframe/test",
            )
            self.assertEqual(api_workflow["8"]["inputs"]["length"], 124)
            self.assertEqual(api_workflow["6"]["inputs"]["steps"], 20)
            self.assertEqual(api_workflow["7"]["inputs"]["sampler_name"], "res_multistep")
            self.assertEqual(api_workflow["5"]["inputs"]["noise_seed"], 101)

            fast_workflow = backend.build_api_workflow(
                {"profile": "fast_2m_candidate", "content": [{"type": "text", "text": "fixture prompt"}]},
                output_prefix="hiveframe/fast-test",
            )
            self.assertEqual(fast_workflow["8"]["inputs"]["width"], 608)
            self.assertEqual(fast_workflow["8"]["inputs"]["height"], 352)
            self.assertEqual(fast_workflow["8"]["inputs"]["length"], 124)
            self.assertEqual(fast_workflow["6"]["inputs"]["steps"], 7)
            self.assertEqual(fast_workflow[SAGE_NODE_ID]["inputs"]["sage_attention"], "auto")
            self.assertNotIn(SAGE_NODE_ID, api_workflow)

    def test_fast_profile_fails_before_submission_without_sageattention(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary:
            client = FakeComfyClient()
            client.sage_available = False
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            with self.assertRaisesRegex(Exception, "requires SageAttention"):
                backend.create_job({
                    "generation_request": {
                        "profile": "fast_2m_candidate",
                        "content": [{"type": "text", "text": "fixture prompt"}],
                    }
                })
            self.assertEqual(client.submits, 0)

    def test_fake_comfy_submit_status_result_and_sanitized_receipt(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary:
            client = FakeComfyClient()
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            prompt_id = backend.create_job({"generation_request": {"content": [{"type": "text", "text": "fixture prompt"}]}})
            self.assertEqual(client.submits, 1)
            self.assertEqual(backend.get_job_status(prompt_id), "queued")
            self.assertEqual(backend.get_job_status(prompt_id), "running")
            self.assertEqual(backend.get_job_status(prompt_id), "succeeded")
            result = backend.get_result(prompt_id)
            self.assertEqual((result.media_type, result.content), ("video/mp4", b"fake-comfyui-video"))
            receipt = backend.build_receipt(backend_job_id=prompt_id, status="succeeded")
            dump = json.dumps(receipt)
            self.assertNotIn(str(Path(temporary)), dump)
            self.assertEqual(receipt["external_api_call_count"], 0)
            self.assertEqual(receipt["metrics"]["model_load_seconds"]["value"], None)

    def test_product_http_flow_exposes_real_video_and_feedback(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary, TemporaryDirectory(prefix="hiveframe-product-test-") as artifact:
            client = FakeComfyClient()
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            service = ProductService(artifact_root=Path(artifact), comfyui_backend=backend)
            with running_product(service) as base:
                job = api(base, "/api/jobs", {
                    "backend": "minimax_h3_comfyui_local",
                    "prompt": "fixture prompt",
                    "generation_consent": True,
                })
                states = [job["status"]]
                for _ in range(50):
                    job = api(base, f"/api/jobs/{job['job_id']}")
                    if states[-1] != job["status"]:
                        states.append(job["status"])
                    if job["status"] not in {"queued", "running"}:
                        break
                    time.sleep(0.01)
                self.assertEqual(job["status"], "succeeded")
                self.assertIsNotNone(job["receipt_id"])
                self.assertIn("queued", states)
                self.assertIn("running", states)
                self.assertEqual(job["result_media_type"], "video/mp4")
                with urlopen(base + job["result_url"], timeout=5) as response:
                    self.assertEqual(response.read(), b"fake-comfyui-video")
                feedback = api(base, f"/api/jobs/{job['job_id']}/feedback", {
                    "decision": "accepted", "training_opt_in": False, "deletion_requested": False,
                })
                self.assertEqual(feedback["training_eligibility"], "evaluation_only")

    def test_product_reference_is_uploaded_and_wired_as_first_frame(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary, TemporaryDirectory(prefix="hiveframe-product-test-") as artifact:
            client = FakeComfyClient()
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            service = ProductService(artifact_root=Path(artifact), comfyui_backend=backend)
            job = service.create_job({
                "backend": "minimax_h3_comfyui_local",
                "mode": "image_to_video",
                "prompt": "the dog blinks",
                "generation_consent": True,
                "reference": {
                    "name": "dog.png",
                    "media_type": "image/png",
                    "content_base64": "cG5nLWZpeHR1cmU=",
                },
            })
            result = service.execute_job(job["job_id"])
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(len(client.uploads), 1)
            self.assertEqual(client.uploads[0]["content"], b"png-fixture")
            self.assertIsNotNone(client.submitted_prompt)
            assert client.submitted_prompt is not None
            self.assertEqual(client.submitted_prompt["16"]["class_type"], "LoadImage")
            self.assertEqual(client.submitted_prompt["8"]["inputs"]["first_frame"], ["16", 0])

    def test_cancel_and_ui_backend_keys(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary:
            client = FakeComfyClient()
            client.phase = "queued"
            backend = MiniMaxH3ComfyUIBackend(config=write_fixture(Path(temporary)), client=client)
            prompt_id = backend.create_job({"generation_request": {"content": [{"type": "text", "text": "fixture"}]}})
            self.assertEqual(backend.cancel_job(prompt_id)["status"], "cancelled")
        html = (ROOT / "python" / "hive_product" / "static" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "python" / "hive_product" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('value="mock_h3"', html)
        self.assertIn('value="minimax_h3_comfyui_local"', html)
        self.assertIn("resultVideo", html)
        self.assertIn("/cancel", script)
        self.assertNotIn('value="local_h3"', html)

    def test_loopback_and_output_prefix_safety(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-comfy-test-") as temporary:
            config = write_fixture(Path(temporary))
            bad = ComfyUIH3Config(**{**config.__dict__, "base_url": "http://0.0.0.0:8188"})
            with self.assertRaisesRegex(Exception, "loopback"):
                MiniMaxH3ComfyUIBackend(config=bad, client=FakeComfyClient())
            backend = MiniMaxH3ComfyUIBackend(config=config, client=FakeComfyClient())
            with self.assertRaisesRegex(Exception, "unsafe"):
                backend.build_api_workflow(
                    {"content": [{"type": "text", "text": "fixture"}]},
                    output_prefix="../escape",
                )


if __name__ == "__main__":
    unittest.main()
