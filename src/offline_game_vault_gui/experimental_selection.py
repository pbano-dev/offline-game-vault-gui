from __future__ import annotations

import re
from typing import Sequence

from .model import GameRecord, ProfileRecord, RunnerRecord


BACKENDS = ("bottles", "direct-wine", "umu")
BACKEND_LABELS = {
    "bottles": "Bottles",
    "direct-wine": "Direct-Wine",
    "umu": "UMU / Proton",
}
_PORTABLE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def portable_id(value: str) -> str:
    result = _PORTABLE_RE.sub("-", value).strip("._-")
    return result or "selection"


def source_profiles(
    game: GameRecord,
) -> tuple[ProfileRecord, ...]:
    """Return every Linux source profile without treating status as a gate."""

    return tuple(
        profile
        for profile in game.profiles
        if profile.platform == "linux"
    )


def compatible_runners(
    runners: Sequence[RunnerRecord],
    backend: str,
) -> tuple[RunnerRecord, ...]:
    return tuple(
        runner
        for runner in runners
        if runner.supports(backend)
    )


def derivative_name(
    *,
    capsule_id: str,
    backend: str,
    runner_id: str,
    source_profile_id: str | None = None,
    save_set_id: str | None = None,
) -> str:
    parts = [
        portable_id(capsule_id),
        portable_id(backend),
        portable_id(runner_id),
    ]
    if source_profile_id:
        parts.append("source-" + portable_id(source_profile_id))
    if save_set_id:
        parts.append("state-" + portable_id(save_set_id))
    return "--".join(parts)
