from __future__ import annotations

from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping
import json
import os
import socket
import subprocess
import sys
import threading
import unittest

from hive_product.backends import H3Backend
from hive_product.comfyui_backend import REQUIRED_MODELS, REQUIRED_NODES
from hive_product.contracts import BackendFailure, BackendResult, MAX_REFERENCE_BYTES
from hive_product.service import ProductService


ROOT = Path(__file__).resolve().parents[2]
HTML = ROOT / "python" / "hive_product" / "static" / "index.html"
SCRIPT = ROOT / "python" / "hive_product" / "static" / "app.js"
LAUNCHER = ROOT / "scripts" / "hiveframe-local.ps1"


class CaptureBackend(H3Backend):
    name = "minimax_h3_comfyui_local"
    display_name = "Local H3"

    def __init__(self, *, fail: BackendFailure | None = None) -> None:
        self.fail = fail
        self.created: list[Mapping[str, Any]] = []

    def create_job(self, request: Mapping[str, Any]) -> str:
        self.created.append(request)
        if self.fail:
            raise self.fail
        return "capture-job"

    def get_job_status(self, backend_job_id: str) -> str:
        return "succeeded"

    def get_result(self, backend_job_id: str) -> BackendResult:
        return BackendResult("result.mp4", "video/mp4", b"video", {"output_classification": "video"})

    def cancel_job(self, backend_job_id: str) -> dict[str, Any]:
        return {"status": "cancelled"}

    def normalize_error(self, error: BaseException) -> BackendFailure:
        return error if isinstance(error, BackendFailure) else BackendFailure("generation_failed", "failed")

    def build_receipt(self, **fields: Any) -> dict[str, Any]:
        return {"backend": self.name, "external_api_call_count": 0, **fields}

    def public_status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "state": "ready",
            "can_generate": True,
            "message": "영상 생성 준비가 완료되었습니다.",
            "readiness": {
                "gpu": {"state": "ready", "label": "준비됨"},
                "local_ai": {"state": "ready", "label": "준비됨"},
                "model": {"state": "ready", "label": "준비됨"},
            },
        }


class MockCaptureBackend(CaptureBackend):
    name = "mock_h3"
    display_name = "Mock H3"


class FakeRuntimeHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/system_stats":
            value = {"system": {"comfyui_version": "test"}, "devices": [{"name": "test GPU", "type": "cuda", "vram_total": 12_000}]}
        elif self.path == "/queue":
            value = {"queue_running": [], "queue_pending": []}
        elif self.path == "/object_info":
            value = {name: {"input": {"required": {}}} for name in REQUIRED_NODES}
            value["UNETLoader"]["input"]["required"]["unet_name"] = [[REQUIRED_MODELS["diffusion_model"]]]
            value["CLIPLoader"]["input"]["required"]["clip_name"] = [[REQUIRED_MODELS["text_encoder"]]]
            value["VAELoader"]["input"]["required"]["vae_name"] = [[REQUIRED_MODELS["video_vae"], REQUIRED_MODELS["audio_vae"]]]
        else:
            self.send_error(404)
            return
        content = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class P1ReleaseAlphaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory(prefix="hiveframe-p1-alpha-")
        self.backend = CaptureBackend()
        self.service = ProductService(artifact_root=Path(self.temporary.name), comfyui_backend=self.backend)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def image(name: str, media_type: str, content: bytes = b"image") -> dict[str, str]:
        return {"name": name, "media_type": media_type, "content_base64": b64encode(content).decode()}

    def create(self, **overrides: Any) -> dict[str, Any]:
        request = {"prompt": "A calm scene", "generation_consent": True, **overrides}
        return self.service.create_job(request)

    def test_01_default_mode_is_t2v(self) -> None:
        self.assertEqual(self.create()["generation_mode"], "text_to_video")

    def test_02_t2v_transmits_no_reference(self) -> None:
        job = self.create(mode="text_to_video", reference=self.image("stale.png", "image/png"))
        self.assertIsNone(job["reference_asset_id"])
        stored = json.loads(self.service.store.get_job(job["job_id"])["request_json"])
        self.assertFalse(any(item["type"] == "image" for item in stored["content"]))

    def test_03_i2v_requires_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires"):
            self.create(mode="image_to_video")

    def test_04_i2v_accepts_png(self) -> None:
        self.assertIsNotNone(self.create(mode="image_to_video", reference=self.image("first.png", "image/png"))["reference_asset_id"])

    def test_05_i2v_accepts_jpeg(self) -> None:
        self.assertIsNotNone(self.create(mode="image_to_video", reference=self.image("first.jpg", "image/jpeg"))["reference_asset_id"])

    def test_06_i2v_accepts_webp(self) -> None:
        self.assertIsNotNone(self.create(mode="image_to_video", reference=self.image("first.webp", "image/webp"))["reference_asset_id"])

    def test_07_unsupported_image_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, or WebP"):
            self.create(mode="image_to_video", reference=self.image("first.gif", "image/gif"))

    def test_08_oversize_image_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 to"):
            self.create(mode="image_to_video", reference=self.image("first.png", "image/png", b"x" * (MAX_REFERENCE_BYTES + 1)))

    def test_09_product_request_is_always_standard(self) -> None:
        job = self.create(profile="standard", resolution="2K", duration_seconds=15)
        self.assertEqual((job["profile"], job["resolution"], job["duration_seconds"]), ("standard", "768P", 4))
        with self.assertRaisesRegex(ValueError, "Standard Quality"):
            self.create(profile="fast_2m_candidate")

    def test_10_normal_ui_cannot_select_fast_profile(self) -> None:
        self.assertNotIn("fast_2m_candidate", HTML.read_text(encoding="utf-8"))

    def test_11_normal_mode_defaults_local_h3(self) -> None:
        self.assertEqual(self.service.public_config()["default_backend"], "minimax_h3_comfyui_local")
        self.assertEqual(self.create()["backend"], "minimax_h3_comfyui_local")

    def test_12_mock_is_hidden_in_normal_mode(self) -> None:
        self.assertNotIn("mock_h3", self.service.public_config()["backends"])
        self.assertNotIn('value="mock_h3"', HTML.read_text(encoding="utf-8"))

    def test_13_developer_mode_exposes_mock(self) -> None:
        service = ProductService(artifact_root=Path(self.temporary.name) / "dev", comfyui_backend=self.backend, dev_mode=True)
        self.assertIn("mock_h3", service.public_config()["backends"])

    def test_14_local_failure_does_not_auto_fallback(self) -> None:
        local = CaptureBackend(fail=BackendFailure("runtime_unavailable", "unavailable"))
        mock = MockCaptureBackend()
        service = ProductService(artifact_root=Path(self.temporary.name) / "fallback", backend=mock, comfyui_backend=local)
        job = service.create_job({"prompt": "test", "generation_consent": True})
        failed = service.execute_job(job["job_id"])
        self.assertEqual((failed["status"], failed["backend"]), ("failed", local.name))
        self.assertEqual(len(mock.created), 0)

    def _assert_script_text(self, text: str) -> None:
        self.assertIn(text, SCRIPT.read_text(encoding="utf-8"))

    def test_15_queued_localization(self) -> None: self._assert_script_text('queued: "준비 중"')
    def test_16_running_localization(self) -> None: self._assert_script_text('running: "영상 생성 중"')
    def test_17_succeeded_localization(self) -> None: self._assert_script_text('succeeded: "완료"')
    def test_18_failed_localization(self) -> None: self._assert_script_text('failed: "생성 실패"')
    def test_19_cancelled_localization(self) -> None: self._assert_script_text('cancelled: "취소됨"')

    def test_20_ui_has_no_fake_percentage(self) -> None:
        self.assertNotIn("% 경과", SCRIPT.read_text(encoding="utf-8"))
        self.assertIn("경과", SCRIPT.read_text(encoding="utf-8"))

    def test_21_runtime_unavailable_message(self) -> None: self._assert_script_text("Local AI 실행 환경을 확인해주세요.")
    def test_22_model_missing_message(self) -> None: self._assert_script_text("필요한 모델 파일을 확인해주세요.")
    def test_23_oom_message(self) -> None: self._assert_script_text("GPU 메모리가 부족합니다.")
    def test_24_save_failure_message(self) -> None: self._assert_script_text("결과 파일을 저장하지 못했습니다.")
    def test_25_timeout_message(self) -> None: self._assert_script_text("생성 시간이 제한을 초과했습니다.")

    def test_26_succeeded_real_video_has_result_url(self) -> None:
        job = self.create()
        result = self.service.execute_job(job["job_id"])
        self.assertEqual((result["status"], result["result_media_type"]), ("succeeded", "video/mp4"))
        self.assertTrue(result["result_url"].endswith("/result"))

    def test_27_download_is_enabled_only_for_succeeded_video(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('job.status === "succeeded"', script)
        self.assertIn('downloadLink").classList.toggle("hidden", !succeededVideo)', script)

    def launcher_fixture(self, root: Path, runtime_port: int) -> dict[str, str]:
        comfy = root / "comfy"
        (comfy / ".venv" / "Scripts").mkdir(parents=True)
        (comfy / "main.py").write_text("# fixture", encoding="utf-8")
        (comfy / ".venv" / "Scripts" / "python.exe").write_bytes(b"fixture")
        assets = root / "assets"
        assets.mkdir()
        for filename in REQUIRED_MODELS.values():
            (assets / filename).write_bytes(b"fixture")
        workflow = {
            "nodes": [{"id": 1, "type": "SaveVideo"}],
            "definitions": {"subgraphs": [{"nodes": [{"id": index, "type": name} for index, name in enumerate(REQUIRED_NODES - {"SaveVideo"}, 2)]}]},
        }
        workflow_path = assets / "workflow.json"
        workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "HIVEFRAME_COMFYUI_ROOT": str(comfy),
            "HIVEFRAME_H3_ASSET_ROOT": str(assets),
            "HIVEFRAME_H3_WORKFLOW": str(workflow_path),
            "HIVEFRAME_H3_OUTPUT_ROOT": str(root / "output"),
            "HIVEFRAME_COMFYUI_BASE_URL": f"http://127.0.0.1:{runtime_port}",
        })
        return env

    def run_launcher(self, env: dict[str, str], *arguments: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCHER), *arguments],
            cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        )

    def test_28_missing_python_fails_bounded(self) -> None:
        root = Path(self.temporary.name) / "missing-python"
        root.mkdir()
        result = self.run_launcher(self.launcher_fixture(root, free_port()), "-PythonExecutable", str(root / "missing.exe"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python", result.stdout)

    def test_29_bad_runtime_fails_bounded(self) -> None:
        root = Path(self.temporary.name) / "bad-runtime"
        root.mkdir()
        env = self.launcher_fixture(root, free_port())
        env["HIVEFRAME_COMFYUI_ROOT"] = str(root / "missing")
        result = self.run_launcher(env, "-PythonExecutable", sys.executable)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Local AI", result.stdout)

    def test_30_port_conflict_fails_bounded(self) -> None:
        root = Path(self.temporary.name) / "port-conflict"
        root.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            port = int(listener.getsockname()[1])
            result = self.run_launcher(self.launcher_fixture(root, free_port()), "-PythonExecutable", sys.executable, "-Port", str(port))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("포트", result.stdout)

    def _successful_launcher_smoke(self, suffix: str) -> list[str]:
        root = Path(self.temporary.name) / suffix
        root.mkdir()
        runtime = ThreadingHTTPServer(("127.0.0.1", 0), FakeRuntimeHandler)
        thread = threading.Thread(target=runtime.serve_forever, daemon=True)
        thread.start()
        try:
            signal = root / "browser-signal.txt"
            result = self.run_launcher(
                self.launcher_fixture(root, runtime.server_address[1]),
                "-PythonExecutable", sys.executable,
                "-Port", str(free_port()),
                "-ArtifactRoot", str(root / "artifacts"),
                "-SmokeTest", "-BrowserSignalPath", str(signal),
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            return signal.read_text(encoding="utf-8").splitlines()
        finally:
            runtime.shutdown(); runtime.server_close(); thread.join(timeout=2)

    def test_31_successful_server_ready_smoke(self) -> None:
        self.assertIn("server_ready", self._successful_launcher_smoke("ready-smoke"))

    def test_32_browser_open_occurs_after_ready_signal(self) -> None:
        self.assertEqual(self._successful_launcher_smoke("browser-order"), ["server_ready", "browser_open"])


if __name__ == "__main__":
    unittest.main()
