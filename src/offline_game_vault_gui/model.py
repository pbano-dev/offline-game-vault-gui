from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


MaterializationMode = Literal["base", "playable"]
BackendId = Literal["base", "direct-wine", "bottles", "umu", "windows"]
RunnerKind = Literal["wine", "proton"]


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
    proton_path: str | None = None
    kind: RunnerKind = "wine"
    acceptance_status: str = "not_tested"

    @property
    def label(self) -> str:
        size_mib = self.size / (1024 * 1024)
        suffix = (
            f" · {self.acceptance_status}"
            if self.acceptance_status
            else ""
        )
        return f"{self.runner_id} · {size_mib:.1f} MiB{suffix}"

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
    raw: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        backend = {
            "bottles": "Bottles",
            "direct-wine": "Direct-Wine",
            "umu": "UMU",
            "windows": "Windows",
            "base": "base",
        }[self.backend_id]
        return (
            f"{self.profile_id} · {backend} · "
            f"{self.status or 'unspecified'}"
        )


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
    save_set: SaveSetRecord | None = None
    bottles_path: Path | None = None


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation: str
    backend_id: BackendId
    destination: Path
    profile_id: str
    runner_id: str | None
    payload: dict[str, Any]
    stdout: str
    stderr: str




@dataclass(frozen=True, slots=True)
class ExperimentalRequest:
    collection_root: Path
    capsule_path: Path
    capsule_id: str
    backend_id: BackendId
    runner: RunnerRecord
    destination: Path | None
    source_profile_id: str | None = None
    save_set: SaveSetRecord | None = None
    state_backup: Path | None = None
    bottles_path: Path | None = None
    bottle_name: str | None = None

    @property
    def target(self) -> Path | None:
        if self.backend_id == "bottles":
            if self.bottles_path is None or not self.bottle_name:
                return None
            return self.bottles_path / self.bottle_name
        return self.destination


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
