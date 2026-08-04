from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import GameRecord, SourceProfile


class CatalogError(RuntimeError):
    pass


RETIRED_PROFILE_FIELDS = {
    "status",
    "acceptance_report",
    "acceptance_status",
    "maturity",
}


class CapsuleCatalog:
    def scan(self, collection_root: Path) -> tuple[GameRecord, ...]:
        collection_root = Path(collection_root).expanduser()
        if collection_root.is_symlink() or not collection_root.is_dir():
            raise CatalogError("The collection must be a regular directory")
        capsules_root = collection_root / "02_CAPSULES"
        if capsules_root.is_symlink() or not capsules_root.is_dir():
            raise CatalogError("The collection has no regular 02_CAPSULES")
        records: list[GameRecord] = []
        for path in sorted(capsules_root.glob("*/capsule.json")):
            records.append(self._load_capsule(collection_root, path))
        if not records:
            raise CatalogError("No capsule.json files were discovered")
        ids = [item.capsule_id for item in records]
        if len(ids) != len(set(ids)):
            raise CatalogError("Duplicate capsule IDs were discovered")
        return tuple(sorted(records, key=lambda item: item.title.casefold()))

    def _load_capsule(
        self,
        collection_root: Path,
        path: Path,
    ) -> GameRecord:
        resolved_collection = collection_root.resolve()
        if path.is_symlink() or not path.is_file():
            raise CatalogError(f"Capsule is not a regular file: {path}")
        resolved = path.resolve()
        if not resolved.is_relative_to(resolved_collection):
            raise CatalogError(f"Capsule escapes collection: {path}")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Invalid capsule JSON: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise CatalogError(f"Capsule root is not an object: {path}")
        capsule_id = value.get("capsule_id")
        if not isinstance(capsule_id, str) or not capsule_id:
            raise CatalogError(f"Capsule has no capsule_id: {path}")
        game = value.get("game")
        if not isinstance(game, dict):
            raise CatalogError(f"Capsule has no game object: {path}")
        title = game.get("title")
        if not isinstance(title, str) or not title:
            title = capsule_id
        profiles = value.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            raise CatalogError(f"Capsule has no profiles: {path}")
        parsed: list[SourceProfile] = []
        for raw in profiles:
            if not isinstance(raw, dict):
                raise CatalogError(f"Capsule profile is not an object: {path}")
            retired = sorted(RETIRED_PROFILE_FIELDS.intersection(raw))
            if retired:
                raise CatalogError(
                    f"{path}: profile contains retired fields: "
                    + ", ".join(retired)
                )
            parsed.append(self._parse_profile(path, raw))
        return GameRecord(
            capsule_id=capsule_id,
            title=title,
            capsule_path=resolved,
            source_profiles=tuple(parsed),
        )

    def _parse_profile(
        self,
        path: Path,
        value: dict[str, Any],
    ) -> SourceProfile:
        profile_id = value.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise CatalogError(f"Profile has no ID: {path}")
        platform = value.get("platform")
        adapter = value.get("adapter")
        if not isinstance(platform, str) or not platform:
            raise CatalogError(f"{profile_id}: platform is absent")
        if not isinstance(adapter, str) or not adapter:
            raise CatalogError(f"{profile_id}: adapter is absent")
        playable = value.get("playable")
        playable_backend: str | None = None
        if playable is not None:
            if not isinstance(playable, dict):
                raise CatalogError(f"{profile_id}: playable is not an object")
            backend = playable.get("backend")
            if backend is not None and not isinstance(backend, str):
                raise CatalogError(
                    f"{profile_id}: playable.backend is not a string"
                )
            playable_backend = backend
        return SourceProfile(
            profile_id=profile_id,
            platform=platform,
            adapter=adapter,
            playable_backend=playable_backend,
        )
