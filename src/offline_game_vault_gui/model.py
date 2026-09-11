from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Literal


Backend = Literal["bottles", "direct-wine", "umu"]
BACKENDS = {"bottles", "direct-wine", "umu"}
RUNNER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PORTABLE_ID = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
SHA256 = re.compile(r"(?:sha256:)?[0-9a-f]{64}")


def _path_has_symlink(root: Path, candidate: Path) -> bool:
    """Return True when an existing path component below root is a symlink."""

    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return True

    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
        if not current.exists():
            break
    return False


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return item


@dataclass(frozen=True, slots=True)
class UmuStateArchiveRecord:
    profile_id: str
    archive_id: str
    filename: str
    digest: str
    policy: Literal["always", "selectable"]

    @property
    def label(self) -> str:
        return f"{self.archive_id} ({self.policy}, {self.profile_id})"


@dataclass(frozen=True, slots=True)
class SourceProfile:
    profile_id: str
    platform: str
    adapter: str
    playable_backend: str | None
    umu_state_archives: tuple[UmuStateArchiveRecord, ...] = ()

    @property
    def label(self) -> str:
        details = ", ".join(
            item
            for item in (
                self.platform,
                self.adapter,
                self.playable_backend,
            )
            if item
        )
        return f"{self.profile_id} ({details})" if details else self.profile_id


@dataclass(frozen=True, slots=True)
class GameRecord:
    capsule_id: str
    title: str
    capsule_path: Path
    source_profiles: tuple[SourceProfile, ...]

    @property
    def label(self) -> str:
        return f"{self.title} [{self.capsule_id}]"


@dataclass(frozen=True, slots=True)
class RunnerRecord:
    runner_id: str
    digest: str
    archive_path: str
    size: int
    format: str
    source_root: str
    wine_path: str
    wineserver_path: str
    compatible_backends: tuple[str, ...]
    metadata_source: str
    proton_path: str | None
    kind: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunnerRecord":
        required_strings = (
            "runner_id",
            "digest",
            "archive_path",
            "format",
            "source_root",
            "wine_path",
            "wineserver_path",
            "metadata_source",
            "kind",
        )
        parsed = {
            key: _required_string(value, key, "runner")
            for key in required_strings
        }

        size = value.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("runner.size must be a non-negative integer")

        if RUNNER_ID.fullmatch(parsed["runner_id"]) is None:
            raise ValueError("runner.runner_id is not a portable identifier")
        if SHA256.fullmatch(parsed["digest"]) is None:
            raise ValueError("runner.digest is not a SHA-256 digest")

        backends = value.get("compatible_backends")
        if (
            not isinstance(backends, list)
            or not backends
            or any(
                not isinstance(item, str) or item not in BACKENDS
                for item in backends
            )
            or len(set(backends)) != len(backends)
        ):
            raise ValueError(
                "runner.compatible_backends must be unique supported backends"
            )

        proton = value.get("proton_path")
        if proton is not None and not isinstance(proton, str):
            raise ValueError("runner.proton_path must be a string or null")

        return cls(
            runner_id=parsed["runner_id"],
            digest=parsed["digest"],
            archive_path=parsed["archive_path"],
            size=size,
            format=parsed["format"],
            source_root=parsed["source_root"],
            wine_path=parsed["wine_path"],
            wineserver_path=parsed["wineserver_path"],
            compatible_backends=tuple(backends),
            metadata_source=parsed["metadata_source"],
            proton_path=proton,
            kind=parsed["kind"],
        )

    def supports(self, backend: str) -> bool:
        return backend in self.compatible_backends

    @property
    def label(self) -> str:
        return f"{self.runner_id} ({self.kind}, {self.size} bytes)"


@dataclass(frozen=True, slots=True)
class ComponentSet:
    component_set_id: str
    component_set_digest: str
    backend_component_id: str
    runtime_component_id: str
    backend_entrypoint: str
    runtime_var: str
    runtime_family: str
    platform_prefix: str
    platform_directory: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ComponentSet":
        fields = (
            "component_set_id",
            "component_set_digest",
            "backend_component_id",
            "runtime_component_id",
            "backend_entrypoint",
            "runtime_var",
            "runtime_family",
            "platform_prefix",
            "platform_directory",
        )
        parsed = {
            key: _required_string(value, key, "component_set")
            for key in fields
        }

        if SHA256.fullmatch(parsed["component_set_digest"]) is None:
            raise ValueError(
                "component_set.component_set_digest is not a SHA-256 digest"
            )
        for key in (
            "component_set_id",
            "backend_component_id",
            "runtime_component_id",
        ):
            if PORTABLE_ID.fullmatch(parsed[key]) is None:
                raise ValueError(
                    f"component_set.{key} is not a portable identifier"
                )

        return cls(**parsed)

    @property
    def label(self) -> str:
        return (
            f"{self.component_set_id}: "
            f"{self.backend_component_id} + {self.runtime_component_id}"
        )


@dataclass(frozen=True, slots=True)
class SaveSetItemRecord:
    state_id: str
    declared_path: str
    digest: str
    size: int
    payload_path: Path
    entry_type: str
    file_count: int
    directory_count: int


@dataclass(frozen=True, slots=True)
class SaveSetRecord:
    capsule_id: str
    save_set_id: str
    display_name: str
    captured_at: str
    captured_at_basis: str
    aggregate_digest: str
    size: int
    manifest_path: Path
    manifest_digest: str
    items: tuple[SaveSetItemRecord, ...]
    status: str
    source: dict[str, Any] | None

    @property
    def label(self) -> str:
        details = [self.save_set_id]
        if self.captured_at:
            details.append(self.captured_at)
        return f"{self.display_name} ({', '.join(details)})"

    def backup_path(self, collection_root: Path) -> Path | None:
        """Resolve a portable backend-neutral state-backup directory."""

        if not self.source:
            return None

        root = Path(collection_root).expanduser()
        if root.is_symlink() or not root.is_dir():
            return None
        resolved_root = root.resolve()

        for key in ("state_backup", "accepted_state", "backup_path"):
            value = self.source.get(key)
            if not isinstance(value, str) or not value:
                continue

            relative = Path(value)
            if (
                relative.is_absolute()
                or value in {".", ".."}
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                continue

            candidate = resolved_root.joinpath(*relative.parts)
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(resolved_root)
            except (FileNotFoundError, OSError, ValueError):
                continue

            if _path_has_symlink(resolved_root, candidate) or not resolved.is_dir():
                continue
            return resolved

        return None


@dataclass(frozen=True, slots=True)
class StateBackupRecord:
    backup_id: str
    path: Path
    backup_kind: str
    item_count: int
    present_count: int
    missing_count: int
    total_bytes: int
    created_at: str = ""
    present_save_count: int = 0
    present_identity_count: int = 0

    @property
    def created_datetime(self) -> datetime | None:
        value = self.created_at.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed

    @property
    def recency_key(self) -> tuple[int, float]:
        parsed = self.created_datetime
        if parsed is None:
            return (0, 0.0)
        return (1, parsed.timestamp())

    @property
    def display_date(self) -> str:
        parsed = self.created_datetime
        if parsed is None:
            return "Date unavailable"
        local = parsed.astimezone()
        zone = local.tzname() or local.strftime("%z")
        label = local.strftime("%d/%m/%Y %H:%M")
        return f"{label} {zone}".strip()

    @property
    def content_label(self) -> str:
        if self.present_save_count > 0:
            noun = "save" if self.present_save_count == 1 else "saves"
            return f"{self.present_save_count} preserved {noun}"
        if self.present_identity_count > 0:
            return "Identity only — no saved game"
        if self.present_count == 0:
            return "Empty state backup"
        return "Persistent state — no saved-game item"

    @property
    def label(self) -> str:
        return (
            f"{self.display_date} — {self.content_label} "
            f"({self.present_count}/{self.item_count} present)"
        )


@dataclass(frozen=True, slots=True)
class StateSelectionRecord:
    backup: StateBackupRecord
    display_name: str
    save_set_id: str | None

    @property
    def label(self) -> str:
        return self.display_name


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    collection_root: Path
    capsule_path: Path
    backend: Backend
    runner_id: str
    source_profile_id: str | None = None
    destination: Path | None = None
    state_backup: Path | None = None
    save_set_id: str | None = None
    fresh_start: bool = False
    no_state: bool = False
    umu_save_id: str | None = None
    content_ids: tuple[str, ...] = ()
    bottles_path: Path | None = None
    bottle_name: str | None = None
    play: bool = False
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompositionResult:
    capsule_id: str
    backend: str
    runner_id: str
    profile_id: str
    destination: Path
    materialized: bool
    played: bool
    play_complete: bool | None
    backend_result: dict[str, Any] = field(default_factory=dict)

    @property
    def windows_summary(self) -> str:
        native = self.backend_result.get("windows")
        if not isinstance(native, dict):
            return "Windows: no preparation information from the selected Core."
        if native.get("status") == "prepared-unverified":
            return (
                "Windows: launch files prepared; game compatibility remains untested. "
                "Use JUGAR_WINDOWS.bat on Windows and JUGAR_LINUX.sh on Linux. "
                "Native dependencies must be available on Windows."
            )
        if native.get("status") == "blocked":
            issues = native.get("issues", [])
            reason = "; ".join(str(item) for item in issues) if isinstance(issues, list) else ""
            return "Windows preparation blocked" + (": " + reason if reason else ".")
        return "Windows: unknown preparation status; compatibility has not been established."

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompositionResult":
        if value.get("schema") != 0:
            raise ValueError("Unsupported composition result schema")

        for key in (
            "capsule_id",
            "backend",
            "runner_id",
            "profile_id",
            "destination",
        ):
            _required_string(value, key, "composition")

        if value["backend"] not in BACKENDS:
            raise ValueError("composition.backend is unsupported")
        for key in ("materialized", "played"):
            if not isinstance(value.get(key), bool):
                raise ValueError(f"composition.{key} must be boolean")

        play_complete = value.get("play_complete")
        if play_complete is not None and not isinstance(play_complete, bool):
            raise ValueError(
                "composition.play_complete must be boolean or null"
            )

        backend_result = value.get("backend_result", {})
        if not isinstance(backend_result, dict):
            raise ValueError("composition.backend_result must be an object")

        return cls(
            capsule_id=value["capsule_id"],
            backend=value["backend"],
            runner_id=value["runner_id"],
            profile_id=value["profile_id"],
            destination=Path(value["destination"]),
            materialized=value["materialized"],
            played=value["played"],
            play_complete=play_complete,
            backend_result=backend_result,
        )
