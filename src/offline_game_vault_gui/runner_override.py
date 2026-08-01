from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .model import RunnerRecord


class RunnerOverrideError(RuntimeError):
    pass


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def build_derived_capsule(
    capsule_path: Path,
    profile_id: str,
    runner: RunnerRecord,
) -> bytes:
    if _ID_RE.fullmatch(runner.runner_id) is None:
        raise RunnerOverrideError("Runner ID is not portable")
    try:
        document = json.loads(
            capsule_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerOverrideError("Capsule is not valid JSON") from exc
    if not isinstance(document, dict):
        raise RunnerOverrideError("Capsule root is not an object")

    derived = copy.deepcopy(document)
    profiles = derived.get("profiles")
    objects = derived.get("objects")
    if not isinstance(profiles, list) or not isinstance(objects, list):
        raise RunnerOverrideError(
            "Capsule does not declare profiles and objects"
        )
    selected = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("id") == profile_id
    ]
    if len(selected) != 1:
        raise RunnerOverrideError(
            "Selected profile is absent or duplicated"
        )
    profile = selected[0]
    playable = profile.get("playable")
    if (
        profile.get("adapter") != "wine"
        or not isinstance(playable, dict)
        or playable.get("backend") != "wine"
    ):
        raise RunnerOverrideError(
            "Runner override requires a Direct-Wine playable profile"
        )

    dependencies = profile.get("dependencies")
    layout = playable.get("layout")
    paths = playable.get("paths")
    if (
        not isinstance(dependencies, list)
        or not isinstance(layout, list)
        or not isinstance(paths, dict)
    ):
        raise RunnerOverrideError(
            "Direct-Wine profile has an incomplete playable contract"
        )

    object_index = {
        item.get("id"): item
        for item in objects
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    old_runner_ids = [
        dependency
        for dependency in dependencies
        if (
            isinstance(dependency, str)
            and isinstance(object_index.get(dependency), dict)
            and "runner" in object_index[dependency].get("roles", [])
        )
    ]
    if len(old_runner_ids) != 1:
        raise RunnerOverrideError(
            "Profile does not bind exactly one existing runner"
        )
    old_id = old_runner_ids[0]
    if old_id == runner.runner_id:
        return (
            json.dumps(
                derived,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    if runner.runner_id in object_index and runner.runner_id != old_id:
        raise RunnerOverrideError(
            "Selected runner ID collides with another capsule object"
        )

    old_declaration = object_index[old_id]
    new_declaration = {
        "id": runner.runner_id,
        "digest": f"sha256:{runner.digest}",
        "archive_path": runner.archive_path,
        "format": runner.format,
        "size": runner.size,
        "roles": ["runner"],
    }
    objects[objects.index(old_declaration)] = new_declaration
    profile["dependencies"] = [
        runner.runner_id if value == old_id else value
        for value in dependencies
    ]

    mappings = [
        item
        for item in layout
        if isinstance(item, dict) and item.get("object") == old_id
    ]
    if len(mappings) != 1:
        raise RunnerOverrideError(
            "Playable layout does not map exactly one runner"
        )
    mapping = mappings[0]
    destination = f"runner/{runner.runner_id}"
    mapping["object"] = runner.runner_id
    mapping["source"] = runner.source_root
    mapping["destination"] = destination
    paths["runner"] = destination
    paths["wine"] = f"{destination}/{runner.wine_path}"
    paths["wineserver"] = f"{destination}/{runner.wineserver_path}"

    return (
        json.dumps(
            derived,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
