from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Literal


Backend = Literal["bottles", "direct-wine", "umu"]
BACKENDS = {"bottles", "direct-wine", "umu"}
RUNNER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PORTABLE_ID = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
SHA256 = re.compile(r"(?:sha256:)?[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SourceProfile:
    profile_id: str
    platform: str
    adapter: str
    playable_backend: str | None

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
        for key in required_strings:
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(f"runner.{key} must be a non-empty string")
        size = value.get("size")
        if not isinstance(size, int) or size < 0:
            raise ValueError("runner.size must be a non-negative integer")
        if RUNNER_ID.fullmatch(value["runner_id"]) is None:
            raise ValueError("runner.runner_id is not a portable identifier")
        if SHA256.fullmatch(value["digest"]) is None:
            raise ValueError("runner.digest is not a SHA-256 digest")
        backends = value.get("compatible_backends")
        if (
            not isinstance(backends, list)
            or not backends
            or any(
                not isinstance(item, str) or item not in BACKENDS
                for item in backends
            )
            or len(backends) != len(set(backends))
        ):
            raise ValueError(
                "runner.compatible_backends must contain unique known backends"
            )
        proton = value.get("proton_path")
        if proton is not None and not isinstance(proton, str):
            raise ValueError("runner.proton_path must be a string or null")
        return cls(
            runner_id=value["runner_id"],
            digest=value["digest"],
            archive_path=value["archive_path"],
            size=size,
            format=value["format"],
            source_root=value["source_root"],
            wine_path=value["wine_path"],
            wineserver_path=value["wineserver_path"],
            compatible_backends=tuple(backends),
            metadata_source=value["metadata_source"],
            proton_path=proton,
            kind=value["kind"],
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
        for key in fields:
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(
                    f"component_set.{key} must be a non-empty string"
                )
        if SHA256.fullmatch(value["component_set_digest"]) is None:
            raise ValueError(
                "component_set.component_set_digest is not a SHA-256 digest"
            )
        for key in (
            "component_set_id",
            "backend_component_id",
            "runtime_component_id",
        ):
            if PORTABLE_ID.fullmatch(value[key]) is None:
                raise ValueError(
                    f"component_set.{key} is not a portable identifier"
                )
        return cls(**{key: value[key] for key in fields})

    @property
    def label(self) -> str:
        return (
            f"{self.component_set_id}: "
            f"{self.backend_component_id} + {self.runtime_component_id}"
        )


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    collection_root: Path
    capsule_path: Path
    backend: Backend
    runner_id: str
    source_profile_id: str | None = None
    destination: Path | None = None
    state_backup: Path | None = None
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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CompositionResult":
        if value.get("schema") != 0:
            raise ValueError("Unsupported composition result schema")
        required = (
            "capsule_id",
            "backend",
            "runner_id",
            "profile_id",
            "destination",
            "materialized",
            "played",
            "play_complete",
        )
        for key in required[:5]:
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(f"composition.{key} must be a non-empty string")
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
            play_complete=value["play_complete"],
            backend_result=backend_result,
        )
