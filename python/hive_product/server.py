"""Dependency-free local HTTP server for the P0 product slice."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import json

from .service import ProductService


STATIC_ROOT = Path(__file__).with_name("static")
MAX_REQUEST_BYTES = 15 * 1024 * 1024


class ProductHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], service: ProductService) -> None:
        self.service = service
        super().__init__(address, ProductRequestHandler)


class ProductRequestHandler(BaseHTTPRequestHandler):
    server: ProductHTTPServer

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log prompts, bodies, headers, credentials, or filesystem paths.
        print(f"hiveframe-product {self.command} {urlparse(self.path).path}")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
            return
        if path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if path == "/api/config":
            self._json(HTTPStatus.OK, self.server.service.public_config())
            return
        parts = self._parts(path)
        if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
            self._handle_get_job(parts[2])
            return
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "result":
            self._handle_result(parts[2])
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            parts = self._parts(path)
            if parts == ["api", "jobs"]:
                job = self.server.service.create_job(body)
                self.server.service.execute_job_async(job["job_id"])
                self._json(HTTPStatus.ACCEPTED, job)
                return
            if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "feedback":
                feedback = self.server.service.save_feedback(parts[2], body)
                self._json(HTTPStatus.CREATED, feedback)
                return
            if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "retry":
                job = self.server.service.retry_job(parts[2])
                self.server.service.execute_job_async(job["job_id"])
                self._json(HTTPStatus.ACCEPTED, job)
                return
            if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel":
                job = self.server.service.cancel_job(parts[2])
                self._json(HTTPStatus.OK, job)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValueError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_input", "message": str(error)})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception:
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_failure", "message": "The local product service failed safely."},
            )

    def _handle_get_job(self, job_id: str) -> None:
        try:
            self._json(HTTPStatus.OK, self.server.service.get_job(job_id))
        except (KeyError, ValueError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _handle_result(self, job_id: str) -> None:
        try:
            metadata, path = self.server.service.result_asset(job_id)
            content = path.read_bytes()
        except (KeyError, ValueError, FileNotFoundError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "no_result"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", metadata["media_type"])
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Content-Disposition", f'attachment; filename="{metadata["filename"]}"')
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, filename: str, media_type: str) -> None:
        content = (STATIC_ROOT / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("request body size is invalid")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("request must be valid UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    @staticmethod
    def _parts(path: str) -> list[str]:
        return [part for part in path.split("/") if part]

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def create_server(service: ProductService, host: str = "127.0.0.1", port: int = 8765) -> ProductHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("P0 may bind only to a loopback interface")
    if not 0 <= port <= 65535:
        raise ValueError("port is out of range")
    return ProductHTTPServer((host, port), service)
