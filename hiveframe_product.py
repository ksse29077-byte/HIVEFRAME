#!/usr/bin/env python3
"""Run the dependency-free HIVEFRAME P0 local product."""

from __future__ import annotations

from pathlib import Path
import argparse

from hive_product.contracts import default_artifact_root
from hive_product.server import create_server
from hive_product.service import ProductService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="HIVEFRAME P0 local Mock H3 product vertical slice")
    result.add_argument("--host", default="127.0.0.1", help="loopback host only")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument(
        "--artifact-root",
        type=Path,
        default=default_artifact_root(),
        help="external directory for SQLite metadata and user artifacts",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    service = ProductService(artifact_root=args.artifact_root)
    server = create_server(service, args.host, args.port)
    host, port = server.server_address[:2]
    print(f"HIVEFRAME P0 is available at http://{host}:{port}")
    print("Backend: deterministic Mock H3; live MiniMax calls are disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
