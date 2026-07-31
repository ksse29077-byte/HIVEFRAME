"""Source-checkout entrypoint for the HIVEFRAME M0 runner."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

from hive_benchmarks.m0_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
