from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen
import base64
import json
import os
import sqlite3
import threading
import time
import unittest
from unittest.mock import patch

from hive_product.backends import MiniMaxH3LocalBackend, MockH3Backend
from hive_product.contracts import BackendFailure, BackendResult, H3ContentItem, H3GenerationRequest
from hive_product.local_pipeline import LocalH3Config, LocalPipelineFactory
from hive_product.server import create_server
from hive_product.service import ProductService


ROOT = Path(__file__).resolve().parents[2]


def local_config(model_source: str | None = None, *, enabled: bool = False) -> LocalH3Config:
    return LocalH3Config(
        model_source=model_source,
        revision=None,
        local_enabled=enabled,
        local_files_only=True,
        dtype="bfloat16",
        device_map="auto",
        trust_remote_code=False,
        model_root=None,
    )


class FakeVideoPipeline:
    def __call__(self, request: dict) -> BackendResult:
        return BackendResult("fake.mp4", "video/mp4", b"fake-local-video", {"output_classification": "provisional_video_output"})


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


def api(base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_for_terminal(base: str, job_id: str) -> dict:
    for _ in range(50):
        _, job = api(base, f"/api/jobs/{job_id}")
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal status")


class ProductLocalReadyTests(unittest.TestCase):
    def test_request_schema_parses_and_contract_round_trips(self) -> None:
        schema = json.loads((ROOT / "schemas" / "h3_generation_request.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["model"]["const"], "MiniMax-H3")
        request = H3GenerationRequest.create(content=[H3ContentItem("text", text="A quiet street")])
        self.assertEqual(H3GenerationRequest.from_dict(request.to_dict()).to_dict(), request.to_dict())
        self.assertNotIn("url", json.dumps(request.to_dict()))

    def test_empty_text_and_invalid_role_groups_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "prompt"):
            H3GenerationRequest.create(content=[H3ContentItem("text", text=" ")])
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            H3GenerationRequest.create(content=[
                H3ContentItem("text", text="test"),
                H3ContentItem("image", role="first_frame", asset_id="asset_a"),
                H3ContentItem("image", role="reference_image", asset_id="asset_b"),
            ])
        with self.assertRaisesRegex(ValueError, "reference_audio"):
            H3GenerationRequest.create(content=[
                H3ContentItem("text", text="test"),
                H3ContentItem("audio", role="reference_audio", asset_id="asset_a"),
            ])

    def test_t2v_ratio_is_concrete_and_frame_mode_normalizes_adaptive(self) -> None:
        with self.assertRaisesRegex(ValueError, "concrete"):
            H3GenerationRequest.create(content=[H3ContentItem("text", text="test")], ratio="adaptive")
        frame = H3GenerationRequest.create(content=[
            H3ContentItem("text", text="test"),
            H3ContentItem("image", role="first_frame", asset_id="asset_a"),
        ], ratio="16:9")
        self.assertEqual((frame.requested_ratio, frame.ratio), ("16:9", "adaptive"))

    def test_default_local_backend_is_artifact_pending_without_imports_or_network(self) -> None:
        backend = MiniMaxH3LocalBackend(config=local_config())
        with patch("hive_product.local_pipeline.importlib.import_module") as imports:
            prepared = backend.prepare_model()
        self.assertEqual(prepared["state"], "artifact_pending")
        self.assertEqual(prepared["network_call_count"], 0)
        imports.assert_not_called()
        with self.assertRaisesRegex(BackendFailure, "not configured") as failure:
            backend.load_model()
        self.assertEqual(failure.exception.code, "model_source_not_configured")

    def test_local_files_only_fake_factory_load_and_failure_paths(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-h3-artifact-") as artifact:
            config = local_config(artifact, enabled=True)
            calls: list[dict] = []
            factory = LocalPipelineFactory(loader=lambda **kwargs: calls.append(kwargs) or FakeVideoPipeline())
            backend = MiniMaxH3LocalBackend(config=config, pipeline_factory=factory)
            self.assertEqual(backend.load_model()["state"], "model_ready")
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["local_files_only"])
            self.assertEqual(backend.unload_model()["state"], "artifact_configured")
            failing = LocalPipelineFactory(loader=lambda **_: (_ for _ in ()).throw(RuntimeError("fake")))
            with self.assertRaises(BackendFailure) as context:
                MiniMaxH3LocalBackend(config=config, pipeline_factory=failing).load_model()
            self.assertEqual(context.exception.code, "model_load_failed")
            online_config = LocalH3Config(**{**config.__dict__, "local_files_only": False})
            with self.assertRaises(BackendFailure) as blocked:
                MiniMaxH3LocalBackend(config=online_config, pipeline_factory=factory).load_model()
            self.assertEqual(blocked.exception.code, "runtime_incompatible")

    def test_output_normalization_does_not_treat_images_or_frames_as_video(self) -> None:
        normalize = MiniMaxH3LocalBackend.normalize_output
        self.assertEqual(normalize(None)["classification"], "output_missing")
        self.assertEqual(normalize({"frames": [object()]})["classification"], "provisional_video_frames")
        self.assertEqual(normalize({"images": [object()]})["classification"], "provisional_image_output")
        self.assertIsNone(normalize({"image": object()})["result"])
        video = BackendResult("ok.mp4", "video/mp4", b"video", {})
        self.assertEqual(normalize(video)["classification"], "provisional_video_output")

    def test_fake_local_pipeline_success_and_local_failure_receipts(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-local-") as product_root, TemporaryDirectory(prefix="h3-files-") as model_root:
            local = MiniMaxH3LocalBackend(
                config=local_config(model_root, enabled=True),
                pipeline_factory=LocalPipelineFactory(loader=lambda **_: FakeVideoPipeline()),
            )
            service = ProductService(artifact_root=Path(product_root), local_backend=local)
            job = service.create_job({"backend": "local_h3", "prompt": "local test", "generation_consent": True})
            completed = service.execute_job(job["job_id"])
            self.assertEqual(completed["status"], "succeeded")
            receipt_meta, receipt_path = service.store.get_asset(completed["receipt_id"])
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["backend"], "local_h3")
            self.assertEqual(receipt["network_call_count"], 0)
            self.assertEqual(receipt_meta["kind"], "receipt")
        with TemporaryDirectory(prefix="hiveframe-p0-waiting-") as product_root:
            service = ProductService(artifact_root=Path(product_root))
            job = service.create_job({"backend": "local_h3", "prompt": "wait", "generation_consent": True})
            failed = service.execute_job(job["job_id"])
            self.assertEqual((failed["status"], failed["error_code"]), ("failed", "local_backend_unavailable"))

    def test_ui_exposes_mock_and_local_waiting_without_automatic_fallback(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-ui-") as temporary:
            service = ProductService(artifact_root=Path(temporary))
            config = service.public_config()
            self.assertEqual(config["default_backend"], "mock_h3")
            self.assertEqual(config["backends"]["local_h3"]["state"], "artifact_pending")
            self.assertIn("Waiting for official model files", config["backends"]["local_h3"]["message"])
            html = (ROOT / "python" / "hive_product" / "static" / "index.html").read_text(encoding="utf-8")
            self.assertIn("Mock H3", html)
            self.assertIn("Local H3", html)
            self.assertNotIn("transferConsent", html)

    def test_mock_h3_end_to_end_once_and_feedback_remains_evaluation_only(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-e2e-") as temporary:
            service = ProductService(artifact_root=Path(temporary))
            with running_product(service) as base:
                _, created = api(base, "/api/jobs", {
                    "backend": "mock_h3", "prompt": "A person waves", "generation_consent": True,
                    "resolution": "768P", "duration_seconds": 4, "ratio": "16:9",
                })
                job = wait_for_terminal(base, created["job_id"])
                self.assertEqual(job["status"], "succeeded")
                with urlopen(base + job["result_url"], timeout=5) as response:
                    result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(result["backend"], "Mock H3")
                self.assertIn("No video was generated", result["notice"])
                _, feedback = api(base, f"/api/jobs/{job['job_id']}/feedback", {
                    "decision": "accepted", "training_opt_in": False, "deletion_requested": False,
                })
                self.assertEqual(feedback["training_eligibility"], "evaluation_only")

    def test_first_frame_is_saved_by_asset_id_and_request_has_no_url(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-asset-") as temporary:
            service = ProductService(artifact_root=Path(temporary))
            job = service.create_job({
                "backend": "mock_h3", "prompt": "First frame", "generation_consent": True,
                "reference": {"name": "frame.png", "media_type": "image/png", "content_base64": base64.b64encode(b"png").decode()},
            })
            stored = service.store.get_job(job["job_id"])
            request = json.loads(stored["request_json"])
            self.assertEqual(request["ratio"], "adaptive")
            self.assertTrue(any(item.get("asset_id") == job["reference_asset_id"] for item in request["content"]))
            self.assertNotIn("url", json.dumps(request))

    def test_secret_api_cost_provider_and_paths_are_absent_from_public_state(self) -> None:
        secret = "must-not-persist"
        with patch.dict(os.environ, {"HIVEFRAME_H3_MODEL_SOURCE": secret, "MINIMAX_API_KEY": secret}, clear=False):
            with TemporaryDirectory(prefix="hiveframe-p0-security-") as temporary:
                service = ProductService(artifact_root=Path(temporary))
                config_dump = json.dumps(service.public_config())
                self.assertNotIn(secret, config_dump)
                job = service.create_job({"backend": "mock_h3", "prompt": "safe", "generation_consent": True})
                service.execute_job(job["job_id"])
                database = service.store.database_path.read_bytes()
                self.assertNotIn(secret.encode(), database)
                self.assertNotIn(b"api_key", database.lower())
                self.assertNotIn(b"cost", database.lower())
                public = service.get_job(job["job_id"])
                self.assertNotIn("provider_job_id", public)

    def test_traversal_and_repository_artifact_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            ProductService(artifact_root=ROOT / "hiveframe-product-data")
        with TemporaryDirectory(prefix="hiveframe-p0-path-") as temporary:
            service = ProductService(artifact_root=Path(temporary))
            with self.assertRaisesRegex(ValueError, "unsafe path"):
                service.create_job({
                    "backend": "mock_h3", "prompt": "safe", "generation_consent": True,
                    "reference": {"name": "../private.png", "media_type": "image/png", "content_base64": "aW1hZ2U="},
                })

    def test_receipt_and_database_record_only_sanitized_local_configuration(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-receipt-") as temporary:
            secret_path = str(Path(temporary) / "private-model")
            config = local_config(secret_path)
            backend = MiniMaxH3LocalBackend(config=config)
            receipt = backend.build_receipt(status="not_started")
            dump = json.dumps(receipt)
            self.assertNotIn(secret_path, dump)
            self.assertEqual(receipt["configuration"]["model_source"], "invalid")
            self.assertEqual(receipt["network_call_count"], 0)


if __name__ == "__main__":
    unittest.main()
