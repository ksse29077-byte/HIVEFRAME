from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from hive_product.backends import MiniMaxH3Backend, MockH3Backend
from hive_product.contracts import BackendFailure, derive_training_eligibility
from hive_product.server import create_server
from hive_product.service import ProductService


ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def running_product():
    with TemporaryDirectory(prefix="hiveframe-p0-") as temporary:
        service = ProductService(artifact_root=Path(temporary))
        server = create_server(service, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield service, f"http://127.0.0.1:{server.server_address[1]}"
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
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal status")


class ProductVerticalSliceTests(unittest.TestCase):
    def test_focused_job_feedback_training_and_error_contracts(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-unit-") as temporary:
            service = ProductService(artifact_root=Path(temporary), backend=MockH3Backend())
            job = service.create_job(
                {
                    "prompt": "한 사람이 창가에서 천천히 고개를 든다.",
                    "profile": "standard",
                    "duration_seconds": 5,
                    "generation_consent": True,
                }
            )
            self.assertEqual(job["status"], "queued")
            job = service.execute_job(job["job_id"])
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(service.store.job_events(job["job_id"]), ["queued", "running", "succeeded"])

            feedback = service.save_feedback(
                job["job_id"],
                {"decision": "accepted", "training_opt_in": True, "deletion_requested": False},
            )
            self.assertTrue(feedback["user_accepted"])
            self.assertEqual(feedback["training_eligibility"], "preference_only")
            self.assertEqual(
                derive_training_eligibility(
                    generation_consent=True,
                    training_opt_in=True,
                    output_training_rights_confirmed=True,
                    deletion_requested=False,
                ),
                ("training_allowed", "retained"),
            )

            backend = MiniMaxH3Backend(live_enabled=False)
            with self.assertRaises(BackendFailure) as context:
                backend.create_job({})
            self.assertEqual(context.exception.code, "live_disabled")
            normalized = backend.normalize_error(TimeoutError())
            self.assertEqual((normalized.code, normalized.retryable), ("timeout", True))
            with patch.dict(os.environ, {"MINIMAX_API_KEY": ""}):
                with self.assertRaises(BackendFailure) as missing_key:
                    MiniMaxH3Backend(live_enabled=True).create_job({})
            self.assertEqual(missing_key.exception.code, "missing_api_key")

    def test_smoke_server_ui_and_mock_job_creation(self) -> None:
        with running_product() as (_, base):
            with urlopen(base + "/", timeout=5) as response:
                html = response.read().decode("utf-8")
                self.assertEqual(response.status, 200)
                self.assertIn("HIVEFRAME P0", html)
            status, job = api(
                base,
                "/api/jobs",
                {
                    "prompt": "한 사람이 카메라를 바라본다.",
                    "profile": "standard",
                    "duration_seconds": 3,
                    "generation_consent": True,
                    "backend_transfer_consent": False,
                },
            )
            self.assertEqual(status, 202)
            self.assertIn(job["status"], {"queued", "running", "succeeded"})

    def test_e2e_prompt_mock_result_download_and_feedback(self) -> None:
        with running_product() as (_, base):
            _, created = api(
                base,
                "/api/jobs",
                {
                    "prompt": "한 사람이 의자에 앉아 손을 천천히 든다.",
                    "profile": "standard",
                    "duration_seconds": 5,
                    "generation_consent": True,
                    "backend_transfer_consent": False,
                },
            )
            job = wait_for_terminal(base, created["job_id"])
            self.assertEqual(job["status"], "succeeded")
            with urlopen(base + job["result_url"], timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
                self.assertEqual(result["kind"], "hiveframe_mock_video_result")
                self.assertEqual(result["notice"], "No video was generated and no network call was made.")
            status, feedback = api(
                base,
                f"/api/jobs/{job['job_id']}/feedback",
                {
                    "decision": "rejected",
                    "feedback_reason": "motion",
                    "training_opt_in": False,
                    "deletion_requested": False,
                },
            )
            self.assertEqual(status, 201)
            self.assertFalse(feedback["user_accepted"])
            self.assertEqual(feedback["training_eligibility"], "evaluation_only")

    def test_fallback_failure_partial_receipt_and_one_manual_retry(self) -> None:
        with TemporaryDirectory(prefix="hiveframe-p0-fallback-") as temporary:
            service = ProductService(artifact_root=Path(temporary))
            created = service.create_job(
                {
                    "prompt": "한 사람이 서 있다.",
                    "profile": "standard",
                    "duration_seconds": 3,
                    "generation_consent": True,
                }
            )
            failed = service.execute_job(created["job_id"], fixture="provider_failure")
            self.assertEqual((failed["status"], failed["error_code"]), ("failed", "provider_failure"))
            self.assertIsNotNone(failed["receipt_id"])
            retry_feedback = service.save_feedback(
                failed["job_id"],
                {"decision": "retry_requested", "training_opt_in": False, "deletion_requested": False},
            )
            self.assertIsNone(retry_feedback["user_accepted"])
            queued = service.retry_job(failed["job_id"])
            self.assertEqual((queued["status"], queued["retry_count"]), ("queued", 1))
            failed_again = service.execute_job(queued["job_id"], fixture="timeout")
            with self.assertRaisesRegex(ValueError, "maximum retry"):
                service.retry_job(failed_again["job_id"])
        with TemporaryDirectory(prefix="hiveframe-p0-artifact-failure-") as temporary:
            service = ProductService(artifact_root=Path(temporary), fail_artifact_writes=True)
            created = service.create_job(
                {
                    "prompt": "한 사람이 걷는다.",
                    "profile": "standard",
                    "duration_seconds": 3,
                    "generation_consent": True,
                }
            )
            failed = service.execute_job(created["job_id"])
            self.assertEqual((failed["status"], failed["error_code"]), ("failed", "artifact_save_failure"))

    def test_security_key_path_upload_and_external_artifact_boundaries(self) -> None:
        secret = "test-only-secret-that-must-not-be-persisted"
        previous = os.environ.get("MINIMAX_API_KEY")
        os.environ["MINIMAX_API_KEY"] = secret
        try:
            with TemporaryDirectory(prefix="hiveframe-p0-security-") as temporary:
                service = ProductService(artifact_root=Path(temporary))
                with self.assertRaisesRegex(ValueError, "unsafe path"):
                    service.create_job(
                        {
                            "prompt": "한 사람이 서 있다.",
                            "duration_seconds": 3,
                            "generation_consent": True,
                            "reference": {
                                "name": "../private.png",
                                "media_type": "image/png",
                                "content_base64": "aW1hZ2U=",
                            },
                        }
                    )
                backend = MiniMaxH3Backend(live_enabled=True)
                self.assertTrue(backend.api_key_available)
                with self.assertRaises(BackendFailure) as context:
                    backend.create_job({})
                self.assertEqual(context.exception.code, "live_not_implemented")
                receipt = backend.build_receipt(status="not_started")
                self.assertNotIn(secret, json.dumps(receipt))
                self.assertNotIn(secret.encode(), service.store.database_path.read_bytes())
                self.assertNotIn(ROOT, service.store.root.parents)
                source = b"".join(path.read_bytes() for path in (ROOT / "python" / "hive_product").rglob("*.py"))
                self.assertNotIn(secret.encode(), source)
        finally:
            if previous is None:
                os.environ.pop("MINIMAX_API_KEY", None)
            else:
                os.environ["MINIMAX_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
