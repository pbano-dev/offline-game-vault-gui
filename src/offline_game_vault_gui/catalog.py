from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    BackendId,
    GameRecord,
    MaterializationMode,
    ProfileRecord,
)


class CatalogError(RuntimeError):
    pass


_STATUS_ORDER = {
    "verified": 0,
    "accepted": 0,
    "candidate": 1,
    "not_tested": 2,
    "unsupported": 3,
    "unavailable": 4,
}


def _required_text(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{context}: missing valid text in {key!r}")
    return value.strip()


def _optional_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def profile_mode(profile: dict[str, Any]) -> MaterializationMode:
    adapter = profile.get("adapter")
    platform = profile.get("platform")
    if platform == "linux" and adapter == "wine":
        playable = profile.get("playable")
        if (
            isinstance(playable, dict)
            and playable.get("schema") == 0
            and playable.get("backend") == "wine"
        ):
            return "playable"
        host_contract = profile.get("host_contract")
        if isinstance(host_contract, str) and host_contract:
            return "playable"
    if platform == "windows" and adapter == "windows":
        return "playable"
    return "base"


def profile_backend(profile: dict[str, Any]) -> BackendId:
    platform = profile.get("platform")
    adapter = profile.get("adapter")
    if platform == "linux" and adapter == "bottles":
        return "bottles"
    if platform == "linux" and adapter == "wine":
        return "direct-wine"
    if platform == "windows" and adapter == "windows":
        return "windows"
    return "base"


def _runner_object_ids(objects: Any) -> set[str]:
    if not isinstance(objects, list):
        return set()

    result: set[str] = set()
    for item in objects:
        if not isinstance(item, dict):
            continue
        object_id = item.get("id")
        roles = item.get("roles")
        if (
            isinstance(object_id, str)
            and object_id
            and isinstance(roles, list)
            and "runner" in roles
        ):
            result.add(object_id)
    return result


def _default_runner_id(
    profile: dict[str, Any],
    runner_object_ids: set[str],
    context: str,
) -> str | None:
    backend = profile_backend(profile)
    if backend not in {"direct-wine", "bottles"}:
        return None

    dependencies = profile.get("dependencies")
    if not isinstance(dependencies, list):
        raise CatalogError(f"{context}: dependencies is not an array")

    candidates = [
        value
        for value in dependencies
        if isinstance(value, str) and value in runner_object_ids
    ]
    if len(candidates) > 1:
        raise CatalogError(
            f"{context}: profile depends on more than one runner object"
        )
    if not candidates:
        return None

    if backend == "direct-wine":
        playable = profile.get("playable")
        if isinstance(playable, dict):
            layout = playable.get("layout")
            if not isinstance(layout, list):
                raise CatalogError(f"{context}: playable.layout is not an array")
            mapped = [
                item
                for item in layout
                if isinstance(item, dict) and item.get("object") == candidates[0]
            ]
            if len(mapped) != 1:
                raise CatalogError(
                    f"{context}: playable.layout does not map exactly one runner"
                )
    return candidates[0]


def _parse_profile(
    value: Any,
    context: str,
    runner_object_ids: set[str],
) -> ProfileRecord:
    if not isinstance(value, dict):
        raise CatalogError(f"{context}: profile is not a JSON object")

    mode = profile_mode(value)
    return ProfileRecord(
        profile_id=_required_text(value, "id", context),
        platform=_optional_text(value, "platform"),
        adapter=_optional_text(value, "adapter"),
        status=_optional_text(value, "status") or "unspecified",
        mode=mode,
        backend_id=profile_backend(value),
        default_runner_id=_default_runner_id(
            value,
            runner_object_ids,
            context,
        ),
        host_contract=_optional_text(value, "host_contract") or None,
        runner_binding=(
            "select-at-materialization"
            if _default_runner_id(value, runner_object_ids, context) is None
            and profile_backend(value) in {"direct-wine", "bottles"}
            else "fixed"
        ),
    )


def _parse_capsule(path: Path) -> GameRecord:
    if path.is_symlink() or not path.is_file():
        raise CatalogError(f"{path}: capsule.json must be a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"{path}: unreadable JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path}: JSON root is not an object")

    capsule_id = _required_text(data, "capsule_id", str(path))
    if path.parent.name != capsule_id:
        raise CatalogError(f"{path}: capsule_id does not match its directory")

    game = data.get("game")
    if not isinstance(game, dict):
        raise CatalogError(f"{path}: missing game object")

    profiles_raw = data.get("profiles")
    if not isinstance(profiles_raw, list) or not profiles_raw:
        raise CatalogError(f"{path}: declares no profiles")

    runner_ids = _runner_object_ids(data.get("objects"))
    profiles = tuple(
        sorted(
            (
                _parse_profile(
                    item,
                    f"{path}: profiles[{index}]",
                    runner_ids,
                )
                for index, item in enumerate(profiles_raw)
            ),
            key=lambda profile: (
                0 if profile.mode == "playable" else 1,
                _STATUS_ORDER.get(profile.status.lower(), 9),
                profile.profile_id,
            ),
        )
    )

    baseline_state = "clean"
    content_status_path = path.parent / "CONTENT_STATUS.json"
    if content_status_path.is_file() and not content_status_path.is_symlink():
        try:
            content_status = json.loads(
                content_status_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            content_status = None
        if isinstance(content_status, dict):
            value = content_status.get("baseline_state")
            if isinstance(value, str) and value:
                baseline_state = value

    return GameRecord(
        capsule_id=capsule_id,
        title=_required_text(game, "title", str(path)),
        preserved_version=_optional_text(game, "preserved_version"),
        capsule_path=path,
        profiles=profiles,
        baseline_state=baseline_state,
    )


def scan_catalog(
    collection_root: Path,
) -> tuple[tuple[GameRecord, ...], tuple[str, ...]]:
    collection_root = Path(collection_root)
    if collection_root.is_symlink() or not collection_root.is_dir():
        raise CatalogError(
            "The collection root must exist and must not be a symbolic link"
        )

    capsules_root = collection_root / "02_CAPSULES"
    if capsules_root.is_symlink() or not capsules_root.is_dir():
        raise CatalogError("A regular 02_CAPSULES directory does not exist")

    games: list[GameRecord] = []
    warnings: list[str] = []

    for candidate in sorted(capsules_root.iterdir(), key=lambda item: item.name):
        if candidate.is_symlink() or not candidate.is_dir():
            warnings.append(
                f"Skipped {candidate.name}: is not a regular directory"
            )
            continue
        try:
            games.append(_parse_capsule(candidate / "capsule.json"))
        except CatalogError as exc:
            warnings.append(str(exc))

    games.sort(key=lambda item: (item.title.casefold(), item.capsule_id))
    if not games:
        detail = "; ".join(warnings) if warnings else "no entries"
        raise CatalogError(f"No valid capsule was found: {detail}")

    return tuple(games), tuple(warnings)
