from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .shared_backend import SharedBackendRecord


MaterializationMode = Literal["base", "playable"]
BackendId = Literal["base", "direct-wine", "bottles", "windows"]


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

    @property
    def label(self) -> str:
        size_mib = self.size / (1024 * 1024)
        return f"{self.runner_id} · {size_mib:.1f} MiB"

    def supports(self, backend_id: str) -> bool:
        return backend_id in self.compatible_backends


@dataclass(frozen=True, slots=True)
class SaveSetItemRecord:
    state_id: str
    declared_path: str
    digest: str
    size: int
    payload_path: Path
    entry_type: str = "file"
    file_count: int = 1
    directory_count: int = 0


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
        size_mib = self.size / (1024 * 1024)
        captured = self.captured_at or "date not recorded"
        suffix = " · candidate" if self.status == "candidate" else ""
        return (
            f"{self.display_name} · {captured} · {size_mib:.1f} MiB"
            f"{suffix}"
        )

    @property
    def state_ids(self) -> tuple[str, ...]:
        return tuple(item.state_id for item in self.items)

    # Compatibility accessors for save-sets v1 and older callers. They are
    # intentionally strict: multi-item save sets must be handled atomically.
    @property
    def state_id(self) -> str:
        if len(self.items) != 1:
            raise ValueError("multi-item save set has no single state_id")
        return self.items[0].state_id

    @property
    def declared_path(self) -> str:
        if len(self.items) != 1:
            raise ValueError("multi-item save set has no single path")
        return self.items[0].declared_path

    @property
    def digest(self) -> str:
        return self.aggregate_digest

    @property
    def payload_path(self) -> Path:
        if len(self.items) != 1:
            raise ValueError("multi-item save set has no single payload")
        return self.items[0].payload_path


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    profile_id: str
    platform: str
    adapter: str
    status: str
    mode: MaterializationMode
    backend_id: BackendId
    default_runner_id: str | None
    host_contract: str | None = None
    runner_binding: str = "fixed"

    @property
    def label(self) -> str:
        capability = (
            "Bottles"
            if self.backend_id == "bottles"
            else (
                "Windows"
                if self.backend_id == "windows"
                else (
                    "playable"
                    if self.mode == "playable"
                    else "base"
                )
            )
        )
        details = " · ".join(
            item
            for item in (
                self.adapter,
                self.status,
                capability,
            )
            if item
        )
        return f"{self.profile_id} ({details})"


@dataclass(frozen=True, slots=True)
class GameRecord:
    capsule_id: str
    title: str
    preserved_version: str
    capsule_path: Path
    profiles: tuple[ProfileRecord, ...]
    baseline_state: str = "clean"

    @property
    def label(self) -> str:
        suffix = (
            f" — {self.preserved_version}"
            if self.preserved_version
            else ""
        )
        return f"{self.title}{suffix}"


@dataclass(frozen=True, slots=True)
class MaterializationRequest:
    collection_root: Path
    capsule_path: Path
    capsule_id: str
    profile_id: str
    backend_id: BackendId
    runner: RunnerRecord | None
    destination: Path
    bottles_path: Path | None = None
    bottles_backend: SharedBackendRecord | None = None
    save_set: SaveSetRecord | None = None


@dataclass(frozen=True, slots=True)
class ValidatedRequest:
    collection_root: Path
    immutable_vault_root: Path
    capsule_path: Path
    capsule_id: str
    profile_id: str
    backend_id: BackendId
    destination_parent: Path
    destination: Path
    mode: MaterializationMode
    state_backup: Path | None
    save_set: SaveSetRecord | None
    runner: RunnerRecord | None
    default_runner_id: str | None
    overlay_required: bool
    reusable: bool
    source_reusable: bool
    control_reusable: bool
    bottles_path: Path | None
    bottle_name: str | None
    deployment_path: Path | None
    bottles_backend: SharedBackendRecord | None = None

    @property
    def save_set_id(self) -> str | None:
        return (
            self.save_set.save_set_id
            if self.save_set is not None
            else None
        )


@dataclass(frozen=True, slots=True)
class MaterializationOutcome:
    mode: MaterializationMode
    backend_id: BackendId
    runner_id: str | None
    destination: Path
    receipt_path: Path
    launcher_path: Path | None
    uninstaller_path: Path | None
    deployment_path: Path | None
    bottle_name: str | None
    payload: dict[str, Any]
    stdout: str
    stderr: str
    save_set_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    backend_id: BackendId
    runner_id: str
    destination: Path
    game_process_rc: int
    wineserver_wait_rc: int | None
    complete: bool
    payload: dict[str, Any]
    stdout: str
    stderr: str
    save_set_id: str | None = None


@dataclass(frozen=True, slots=True)
class LogRecord:
    timestamp: str
    stream: str
    level: str
    message: str

    def render(self) -> str:
        return (
            f"[{self.timestamp}] [{self.level}] "
            f"{self.message.rstrip()}\n"
        )
