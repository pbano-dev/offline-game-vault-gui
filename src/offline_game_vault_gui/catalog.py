from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    GameRecord,
    SourceProfile,
    UmuStateArchiveRecord,
)


class CatalogError(RuntimeError):
    pass


RETIRED_PROFILE_FIELDS = {
    "status",
    "acceptance_report",
    "acceptance_status",
    "maturity",
}


class CapsuleCatalog:
    """Read operational capsules without adding authorization semantics."""

    def scan(self, collection_root: Path) -> tuple[GameRecord, ...]:
        collection_root = Path(collection_root).expanduser()
        if collection_root.is_symlink() or not collection_root.is_dir():
            raise CatalogError("The collection must be a regular directory")

        root = collection_root.resolve()
        capsules_root = root / "02_CAPSULES"
        if capsules_root.is_symlink() or not capsules_root.is_dir():
            raise CatalogError("The collection has no regular 02_CAPSULES")

        records = [
            self._load_capsule(root, path)
            for path in sorted(capsules_root.glob("*/capsule.json"))
        ]
        if not records:
            raise CatalogError("No capsule.json files were discovered")

        identifiers = [item.capsule_id for item in records]
        if len(identifiers) != len(set(identifiers)):
            raise CatalogError("Duplicate capsule IDs were discovered")

        return tuple(sorted(records, key=lambda item: item.title.casefold()))

    def _load_capsule(
        self,
        collection_root: Path,
        path: Path,
    ) -> GameRecord:
        if path.is_symlink() or not path.is_file():
            raise CatalogError(f"Capsule is not a regular file: {path}")

        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(collection_root)
        except (OSError, ValueError) as exc:
            raise CatalogError(f"Capsule escapes the collection: {path}") from exc

        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Invalid capsule JSON: {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise CatalogError(f"Capsule root is not an object: {path}")

        capsule_id = value.get("capsule_id")
        game = value.get("game")
        if not isinstance(capsule_id, str) or not capsule_id:
            raise CatalogError(f"Capsule has no capsule_id: {path}")
        if not isinstance(game, dict):
            raise CatalogError(f"Capsule has no game object: {path}")
        title = game.get("title")
        if not isinstance(title, str) or not title:
            raise CatalogError(f"Capsule has no game.title: {path}")

        profiles_raw = value.get("profiles")
        if not isinstance(profiles_raw, list) or not profiles_raw:
            raise CatalogError(f"Capsule has no profiles: {path}")

        profiles: list[SourceProfile] = []
        for profile in profiles_raw:
            profiles.append(self._profile(profile, path))

        identifiers = [item.profile_id for item in profiles]
        if len(identifiers) != len(set(identifiers)):
            raise CatalogError(f"Capsule contains duplicate profile IDs: {path}")

        return GameRecord(
            capsule_id=capsule_id,
            title=title,
            capsule_path=resolved,
            source_profiles=tuple(profiles),
        )

    def _profile(self, value: Any, path: Path) -> SourceProfile:
        if not isinstance(value, dict):
            raise CatalogError(f"Capsule profile is not an object: {path}")
        retired = RETIRED_PROFILE_FIELDS.intersection(value)
        if retired:
            raise CatalogError(
                f"Profile contains retired state fields: {sorted(retired)}"
            )

        profile_id = value.get("id")
        platform = value.get("platform")
        adapter = value.get("adapter")
        playable = value.get("playable")
        playable_backend: str | None = None

        if not isinstance(profile_id, str) or not profile_id:
            raise CatalogError(f"Profile has no id: {path}")
        if not isinstance(platform, str) or not platform:
            raise CatalogError(f"Profile has no platform: {path}")
        if not isinstance(adapter, str) or not adapter:
            raise CatalogError(f"Profile has no adapter: {path}")

        if isinstance(playable, dict):
            backend = playable.get("backend")
            if backend is not None and not isinstance(backend, str):
                raise CatalogError(
                    f"Profile playable.backend is not a string: {path}"
                )
            playable_backend = backend
        elif playable is not None:
            raise CatalogError(f"Profile playable is not an object: {path}")

        umu_state_archives: list[UmuStateArchiveRecord] = []
        umu = value.get("umu")
        if adapter == "umu" and isinstance(umu, dict):
            raw_archives = umu.get("state_archives", [])
            if isinstance(raw_archives, list):
                for raw_archive in raw_archives:
                    if not isinstance(raw_archive, dict):
                        continue
                    archive_id = raw_archive.get("id")
                    filename = raw_archive.get("filename")
                    digest = raw_archive.get("digest")
                    policy = raw_archive.get("policy")
                    if (
                        not isinstance(archive_id, str)
                        or not archive_id
                        or not isinstance(filename, str)
                        or not filename
                        or not isinstance(digest, str)
                        or not digest
                        or policy not in {"always", "selectable"}
                    ):
                        continue
                    umu_state_archives.append(
                        UmuStateArchiveRecord(
                            profile_id=profile_id,
                            archive_id=archive_id,
                            filename=filename,
                            digest=digest,
                            policy=policy,
                        )
                    )

        return SourceProfile(
            profile_id=profile_id,
            platform=platform,
            adapter=adapter,
            playable_backend=playable_backend,
            umu_state_archives=tuple(umu_state_archives),
        )
