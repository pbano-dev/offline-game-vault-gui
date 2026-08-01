from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .model import SaveSetRecord


UmuProfileKind = Literal[
    "native-exact",
    "native-modular",
    "derived-wine",
]


@dataclass(frozen=True, slots=True)
class UmuStateArchive:
    state_id: str
    filename: str
    digest: str
    policy: str

    @property
    def label(self) -> str:
        suffix = "required" if self.policy == "always" else "selectable"
        return f"{self.state_id} · {suffix}"


@dataclass(frozen=True, slots=True)
class UmuRunner:
    runner_id: str
    digest: str
    size: int
    archive_path: str
    object_path: Path
    archive_format: str
    source_root: str
    proton_path: str
    wine_path: str
    wineserver_path: str
    acceptance_status: str
    registration_operation_id: str | None = None
    derived_from_digest: str | None = None
    source_member_root: str | None = None

    @property
    def label(self) -> str:
        size_mib = self.size / (1024 * 1024)
        return (
            f"{self.runner_id} · {size_mib:.1f} MiB · "
            f"{self.acceptance_status}"
        )


@dataclass(frozen=True, slots=True)
class UmuBackendTemplate:
    capsule_path: Path
    capsule: dict[str, Any]
    profile_id: str
    composite_object_id: str
    composite_digest: str
    composite_object: dict[str, Any]
    source_mapping: dict[str, Any]
    runtime_var: str


@dataclass(frozen=True, slots=True)
class UmuProfile:
    capsule_id: str
    title: str
    preserved_version: str
    capsule_path: Path
    profile_id: str
    profile_status: str
    kind: UmuProfileKind
    source_profile_id: str
    state_root: Path | None
    state_archives: tuple[UmuStateArchive, ...]
    original_profile: dict[str, Any]
    capsule: dict[str, Any]
    backend_template: UmuBackendTemplate
    save_sets: tuple[SaveSetRecord, ...] = ()
    accepted_state_root: Path | None = None
    composite_object_id: str | None = None
    composite_digest: str | None = None

    @property
    def label(self) -> str:
        kind_label = {
            "native-exact": "exact preserved stack",
            "native-modular": "modular candidate",
            "derived-wine": "UMU candidate from Direct-Wine layout",
        }[self.kind]
        return (
            f"{self.profile_id} · {kind_label} · "
            f"{self.profile_status}"
        )

    @property
    def selectable_saves(self) -> tuple[UmuStateArchive, ...]:
        return tuple(
            item
            for item in self.state_archives
            if item.policy == "selectable"
        )

    @property
    def exact(self) -> bool:
        return self.kind == "native-exact"

    @property
    def candidate(self) -> bool:
        return not self.exact

    @property
    def requires_runner(self) -> bool:
        return not self.exact

    @property
    def required_runner_source_root(self) -> str | None:
        if self.kind != "native-modular":
            return None
        contract = self.original_profile.get("umu")
        if not isinstance(contract, dict):
            return None
        mutable = contract.get("mutable_paths", [])
        if not isinstance(mutable, list):
            return None
        roots: set[str] = set()
        for value in mutable:
            if not isinstance(value, str):
                continue
            parts = value.split("/")
            if (
                len(parts) >= 4
                and parts[0] == "engine"
                and parts[1] == "proton"
                and parts[2]
            ):
                roots.add(parts[2])
        return next(iter(roots)) if len(roots) == 1 else None


@dataclass(frozen=True, slots=True)
class UmuCatalog:
    profiles: tuple[UmuProfile, ...]
    runners: tuple[UmuRunner, ...]
    warnings: tuple[str, ...]

    def profiles_for_capsule(
        self,
        capsule_id: str,
    ) -> tuple[UmuProfile, ...]:
        return tuple(
            profile
            for profile in self.profiles
            if profile.capsule_id == capsule_id
        )

    def has_profiles(self, capsule_id: str) -> bool:
        return any(
            profile.capsule_id == capsule_id
            for profile in self.profiles
        )

    def has_native_profiles(self, capsule_id: str) -> bool:
        return any(
            profile.capsule_id == capsule_id
            and profile.kind in {"native-exact", "native-modular"}
            for profile in self.profiles
        )

    def compatible_runners(
        self,
        profile: UmuProfile,
    ) -> tuple[UmuRunner, ...]:
        if not profile.requires_runner:
            return ()
        if profile.kind == "native-modular":
            required_root = profile.required_runner_source_root
            if required_root is None:
                return ()
            return tuple(
                runner
                for runner in self.runners
                if runner.source_root == required_root
            )
        return self.runners


@dataclass(frozen=True, slots=True)
class UmuSelection:
    collection_root: Path
    immutable_vault_root: Path
    profile: UmuProfile
    runner: UmuRunner | None
    destination: Path
    save_id: str | None
    save_set: SaveSetRecord | None = None

    @property
    def selected_save_id(self) -> str | None:
        if self.save_set is not None:
            return self.save_set.save_set_id
        return self.save_id

    @property
    def effective_profile_id(self) -> str:
        if self.profile.exact:
            return self.profile.source_profile_id
        assert self.runner is not None
        return (
            f"{self.profile.profile_id}-"
            f"{self.runner.runner_id}"
        )


@dataclass(frozen=True, slots=True)
class UmuOperationResult:
    operation: str
    destination: Path
    profile_id: str
    runner_id: str | None
    payload: dict[str, Any]
    stdout: str
    stderr: str
