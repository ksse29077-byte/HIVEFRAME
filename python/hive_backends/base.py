"""Backend capability contract for the research scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BackendCapabilities:
    scheduler_step_hook: bool
    latent_snapshots: bool
    attention_hooks: bool
    deterministic_seed: bool


class VideoBackend(Protocol):
    @property
    def capabilities(self) -> BackendCapabilities: ...

    def fingerprint(self) -> dict[str, str]: ...

