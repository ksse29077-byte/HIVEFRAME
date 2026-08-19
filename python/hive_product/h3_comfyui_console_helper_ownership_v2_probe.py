"""Run one model-free ComfyUI console-helper ownership lifecycle."""

from __future__ import annotations

import json

from .h3_comfyui_launcher_child_ownership_v2_probe import build_parser, run


READY = "H3_COMFYUI_CONSOLE_HELPER_OWNERSHIP_CONTRACT_V2_READY"
BLOCKED = "H3_COMFYUI_CONSOLE_HELPER_OWNERSHIP_CONTRACT_V2_BLOCKED"


def main() -> int:
    parser = build_parser(
        "Verify one model-free ComfyUI trusted console-helper ownership lifecycle."
    )
    code, receipt = run(
        parser.parse_args(),
        ready_decision=READY,
        blocked_decision=BLOCKED,
        schema_version="h3.comfyui-console-helper-ownership-v2-probe.1",
    )
    print(json.dumps(receipt, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
