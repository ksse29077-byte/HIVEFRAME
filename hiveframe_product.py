#!/usr/bin/env python3
"""Run the HIVEFRAME local release alpha product."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlopen
import argparse
import sys
import threading
import time
import webbrowser

from hive_product.comfyui_backend import BACKEND_KEY, MiniMaxH3ComfyUIBackend
from hive_product.contracts import BackendFailure, default_artifact_root
from hive_product.server import create_server
from hive_product.service import ProductService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="HIVEFRAME local AI video studio")
    result.add_argument("--host", default="127.0.0.1", help="loopback host only")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--artifact-root", type=Path, default=default_artifact_root())
    result.add_argument("--start-local-runtime", action="store_true")
    result.add_argument("--open-browser", action="store_true")
    result.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--browser-signal-path", type=Path, help=argparse.SUPPRESS)
    return result


def _user_runtime_error(error: BackendFailure) -> str:
    if error.code in {"runtime_unavailable", "comfyui_start_failed", "comfyui_start_timeout"}:
        return "Local AI 실행 환경을 확인해주세요."
    return "필요한 모델 파일과 Local AI 설정을 확인해주세요."


def _wait_until_ready(url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/api/config", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError("server readiness timeout")


def main() -> int:
    args = parser().parse_args()
    service = ProductService(artifact_root=args.artifact_root)
    backend = service.backends[BACKEND_KEY]
    if not isinstance(backend, MiniMaxH3ComfyUIBackend):
        print("Local AI backend configuration is invalid.", file=sys.stderr)
        return 2

    runtime_owned = False
    server = None
    thread = None
    try:
        if args.start_local_runtime:
            started = backend.start_runtime()
            runtime_owned = bool(started.get("started_here"))
        config = service.public_config()
        local_status = config["backends"][BACKEND_KEY]
        if not config["can_generate"] and local_status.get("state") != "busy":
            print(config["backends"][BACKEND_KEY]["message"], file=sys.stderr)
            return 2

        server = create_server(service, args.host, args.port)
        host, port = server.server_address[:2]
        url = f"http://{host}:{port}"
        print(f"HIVEFRAME is ready at {url}", flush=True)

        if args.open_browser or args.smoke_test:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _wait_until_ready(url)
            if args.browser_signal_path is not None:
                args.browser_signal_path.parent.mkdir(parents=True, exist_ok=True)
                args.browser_signal_path.write_text("server_ready\nbrowser_open\n", encoding="utf-8")
            elif args.open_browser:
                webbrowser.open(url, new=2)
            if args.smoke_test:
                return 0
            while thread.is_alive():
                thread.join(timeout=0.5)
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except BackendFailure as error:
        print(_user_runtime_error(error), file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"HIVEFRAME 서버를 시작하지 못했습니다: {error}", file=sys.stderr)
        return 2
    finally:
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if runtime_owned:
            backend.stop_runtime()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
