from __future__ import annotations

import copy
import json
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .runners import RunnerCatalogError, scan_runners
from .save_sets import scan_save_sets
from .umu_model import (
    UmuBackendTemplate,
    UmuCatalog,
    UmuProfile,
    UmuRunner,
    UmuStateArchive,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PORTABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UmuCatalogError(RuntimeError):
    pass


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise UmuCatalogError(f"{label} is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UmuCatalogError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise UmuCatalogError(f"{label} does not contain a JSON object")
    return value


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise UmuCatalogError(f"{label} is not a safe relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise UmuCatalogError(f"{label} is not a safe relative path")
    return path


def _digest(value: Any, label: str) -> str:
    if isinstance(value, str) and value.startswith("sha256:"):
        value = value.removeprefix("sha256:")
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise UmuCatalogError(f"{label} is not a valid SHA-256")
    return value


def _under(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UmuCatalogError(
            f"Path escapes its root: {relative.as_posix()}"
        ) from exc
    return candidate


def _index_capsules(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = index.get("capsules")
    if not isinstance(raw, list):
        raise UmuCatalogError("INDEX.json capsules must be an array")
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        capsule_id = item.get("capsule_id")
        if isinstance(capsule_id, str) and capsule_id:
            result[capsule_id] = item
    return result


def _state_archives(
    profile: dict[str, Any],
    label: str,
) -> tuple[UmuStateArchive, ...]:
    contract = profile.get("umu")
    if not isinstance(contract, dict):
        return ()
    raw = contract.get("state_archives", [])
    if not isinstance(raw, list):
        raise UmuCatalogError(
            f"{label}: umu.state_archives must be an array"
        )
    result: list[UmuStateArchive] = []
    seen: set[str] = set()
    for number, item in enumerate(raw):
        if not isinstance(item, dict):
            raise UmuCatalogError(
                f"{label}: state archive {number} is not an object"
            )
        state_id = item.get("id")
        policy = item.get("policy")
        if (
            not isinstance(state_id, str)
            or not state_id
            or state_id in seen
            or policy not in {"always", "selectable"}
        ):
            raise UmuCatalogError(
                f"{label}: invalid or duplicate state archive"
            )
        filename = _safe_relative(
            item.get("filename"),
            f"{label}.state_archives[{number}].filename",
        ).as_posix()
        digest = _digest(
            item.get("digest"),
            f"{label}.state_archives[{number}].digest",
        )
        result.append(
            UmuStateArchive(
                state_id=state_id,
                filename=filename,
                digest=digest,
                policy=policy,
            )
        )
        seen.add(state_id)
    return tuple(result)


def _native_template(
    capsule_path: Path,
    capsule: dict[str, Any],
    profile: dict[str, Any],
) -> UmuBackendTemplate:
    profile_id = profile.get("id")
    if not isinstance(profile_id, str) or not profile_id:
        raise UmuCatalogError("Native UMU profile has no ID")
    contract = profile.get("umu")
    dependencies = profile.get("dependencies")
    objects_raw = capsule.get("objects")
    if (
        not isinstance(contract, dict)
        or not isinstance(dependencies, list)
        or not isinstance(objects_raw, list)
    ):
        raise UmuCatalogError(
            f"{profile_id}: native UMU contract is incomplete"
        )
    layout = contract.get("layout")
    paths = contract.get("paths")
    if not isinstance(layout, list) or not isinstance(paths, dict):
        raise UmuCatalogError(
            f"{profile_id}: native UMU layout or paths are absent"
        )
    engine = [
        item
        for item in layout
        if (
            isinstance(item, dict)
            and item.get("source") == "engine"
            and item.get("destination") == "engine"
            and isinstance(item.get("object"), str)
        )
    ]
    if len(engine) != 1:
        raise UmuCatalogError(
            f"{profile_id}: expected one engine -> engine mapping"
        )
    composite_id = engine[0]["object"]
    if composite_id not in dependencies:
        raise UmuCatalogError(
            f"{profile_id}: composite object is not a dependency"
        )
    declarations = [
        item
        for item in objects_raw
        if isinstance(item, dict) and item.get("id") == composite_id
    ]
    if len(declarations) != 1:
        raise UmuCatalogError(
            f"{profile_id}: composite object declaration is not unique"
        )
    composite = declarations[0]
    composite_digest = _digest(
        composite.get("digest"),
        f"{profile_id}.composite.digest",
    )
    runtime_var = _safe_relative(
        paths.get("runtime_var"),
        f"{profile_id}.umu.paths.runtime_var",
    ).as_posix()
    return UmuBackendTemplate(
        capsule_path=capsule_path.resolve(strict=True),
        capsule=copy.deepcopy(capsule),
        profile_id=profile_id,
        composite_object_id=composite_id,
        composite_digest=composite_digest,
        composite_object=copy.deepcopy(composite),
        source_mapping=copy.deepcopy(engine[0]),
        runtime_var=runtime_var,
    )


def _profile_status(profile: dict[str, Any]) -> str:
    value = profile.get("status")
    return value if isinstance(value, str) and value else "not_tested"


def _profile_id(profile: dict[str, Any], label: str) -> str:
    value = profile.get("id")
    if (
        not isinstance(value, str)
        or not value
        or _PORTABLE_ID_RE.fullmatch(value) is None
    ):
        raise UmuCatalogError(f"{label}: profile ID is invalid")
    return value


def _accepted_state(
    collection_root: Path,
    index_entry: dict[str, Any] | None,
) -> Path | None:
    if not isinstance(index_entry, dict):
        return None
    raw = index_entry.get("accepted_state")
    if not isinstance(raw, str) or not raw:
        return None
    relative = _safe_relative(raw, "INDEX accepted_state")
    path = _under(collection_root, relative)
    if path.is_symlink() or not path.is_dir():
        return None
    return path.resolve(strict=True)


def _convertible_wine_profiles(
    capsule: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    raw = capsule.get("profiles")
    if not isinstance(raw, list):
        return ()
    result: list[dict[str, Any]] = []
    for profile in raw:
        if (
            not isinstance(profile, dict)
            or profile.get("platform") != "linux"
            or profile.get("adapter") != "wine"
        ):
            continue
        playable = profile.get("playable")
        launch = profile.get("launch")
        dependencies = profile.get("dependencies")
        if (
            not isinstance(playable, dict)
            or playable.get("backend") != "wine"
            or not isinstance(playable.get("layout"), list)
            or not playable.get("layout")
            or not isinstance(playable.get("paths"), dict)
            or not isinstance(launch, dict)
            or not isinstance(launch.get("entrypoint"), str)
            or not launch.get("entrypoint")
            or not isinstance(dependencies, list)
            or not dependencies
        ):
            continue
        result.append(profile)
    return tuple(result)


def _tar_has_proton(
    archive_path: Path,
    source_root: str,
) -> bool:
    target = f"{source_root}/proton"
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            member = archive.getmember(target)
    except (KeyError, OSError, tarfile.TarError):
        return False
    return member.isfile() or member.issym()


def _zip_has_proton(
    archive_path: Path,
    source_root: str,
) -> bool:
    target = f"{source_root}/proton"
    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = archive.getinfo(target)
    except (KeyError, OSError, zipfile.BadZipFile):
        return False
    return not info.is_dir()


def _registration_by_digest(
    layout: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    raw = layout.get("registrations", [])
    if not isinstance(raw, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        value = item.get("object_sha256")
        try:
            digest = _digest(value, "registration.object_sha256")
        except UmuCatalogError:
            continue
        if isinstance(item.get("runner_id"), str):
            result[digest] = item
    return result


def _scan_proton_runners(
    collection_root: Path,
    layout: dict[str, Any],
) -> tuple[tuple[UmuRunner, ...], tuple[str, ...]]:
    try:
        records, warnings_raw = scan_runners(collection_root)
    except RunnerCatalogError as exc:
        return (), (f"Runner catalog unavailable for UMU: {exc}",)

    registrations = _registration_by_digest(layout)
    immutable_root = collection_root / "01_IMMUTABLE_VAULT"
    result: list[UmuRunner] = []
    warnings = list(warnings_raw)

    for record in records:
        digest = _digest(record.digest, f"{record.runner_id}.digest")
        relative = _safe_relative(
            record.archive_path,
            f"{record.runner_id}.archive_path",
        )
        object_path = _under(immutable_root, relative)
        try:
            metadata = object_path.lstat()
        except OSError as exc:
            warnings.append(
                f"{record.runner_id}: runner object is unavailable: {exc}"
            )
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size != record.size
        ):
            warnings.append(
                f"{record.runner_id}: runner object is not a stable regular file"
            )
            continue

        compatible = (
            _zip_has_proton(object_path, record.source_root)
            if record.format == "zip"
            else _tar_has_proton(object_path, record.source_root)
        )
        if not compatible:
            continue

        registration = registrations.get(digest, {})
        registered_id = registration.get("runner_id")
        runner_id = (
            registered_id
            if (
                isinstance(registered_id, str)
                and _PORTABLE_ID_RE.fullmatch(registered_id) is not None
            )
            else record.runner_id
        )
        acceptance = registration.get(
            "acceptance_status",
            "not_tested_as_umu_runner",
        )
        if not isinstance(acceptance, str) or not acceptance:
            acceptance = "not_tested_as_umu_runner"
        operation_id = registration.get("operation_id")
        if not isinstance(operation_id, str):
            operation_id = None

        derived_from: str | None = None
        raw_source = registration.get("derived_from_object_sha256")
        if raw_source is not None:
            try:
                derived_from = _digest(
                    raw_source,
                    f"{runner_id}.derived_from_object_sha256",
                )
            except UmuCatalogError:
                warnings.append(
                    f"{runner_id}: ignored invalid derivation metadata"
                )

        source_member = registration.get("source_member_root")
        if not isinstance(source_member, str):
            source_member = None

        result.append(
            UmuRunner(
                runner_id=runner_id,
                digest=digest,
                size=record.size,
                archive_path=relative.as_posix(),
                object_path=object_path,
                archive_format=record.format,
                source_root=record.source_root,
                proton_path="proton",
                wine_path=record.wine_path,
                wineserver_path=record.wineserver_path,
                acceptance_status=acceptance,
                registration_operation_id=operation_id,
                derived_from_digest=derived_from,
                source_member_root=source_member,
            )
        )

    result.sort(key=lambda item: item.runner_id.casefold())
    return tuple(result), tuple(warnings)


def scan_umu_catalog(collection_root: Path) -> UmuCatalog:
    root = Path(collection_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise UmuCatalogError(
            f"Collection root is not a regular directory: {root}"
        )
    root = root.resolve(strict=True)
    index = _load_json(root / "INDEX.json", "INDEX.json")
    layout = _load_json(
        root / "COLLECTION_LAYOUT.json",
        "COLLECTION_LAYOUT.json",
    )
    index_capsules = _index_capsules(index)
    capsules_root = root / "02_CAPSULES"
    if capsules_root.is_symlink() or not capsules_root.is_dir():
        raise UmuCatalogError("02_CAPSULES is not a regular directory")

    capsule_documents: list[tuple[Path, dict[str, Any]]] = []
    native_candidates: list[
        tuple[Path, dict[str, Any], dict[str, Any]]
    ] = []
    warnings: list[str] = []

    for capsule_path in sorted(capsules_root.glob("*/capsule.json")):
        try:
            capsule = _load_json(capsule_path, str(capsule_path))
            capsule_id = capsule.get("capsule_id")
            if not isinstance(capsule_id, str) or not capsule_id:
                raise UmuCatalogError(
                    f"{capsule_path}: capsule_id is invalid"
                )
            capsule_documents.append((capsule_path, capsule))
            profiles = capsule.get("profiles", [])
            if not isinstance(profiles, list):
                raise UmuCatalogError(
                    f"{capsule_id}: profiles must be an array"
                )
            for profile in profiles:
                if (
                    isinstance(profile, dict)
                    and profile.get("platform") == "linux"
                    and profile.get("adapter") == "umu"
                ):
                    native_candidates.append(
                        (capsule_path, capsule, profile)
                    )
        except UmuCatalogError as exc:
            warnings.append(str(exc))

    if not native_candidates:
        raise UmuCatalogError(
            "No native UMU profile exists to supply the preserved "
            "UMU/Python/Steam Linux Runtime backend"
        )

    templates: list[UmuBackendTemplate] = []
    for capsule_path, capsule, profile in native_candidates:
        try:
            templates.append(
                _native_template(capsule_path, capsule, profile)
            )
        except UmuCatalogError as exc:
            warnings.append(str(exc))

    if not templates:
        raise UmuCatalogError(
            "No structurally usable reusable UMU runtime source exists"
        )
    templates.sort(
        key=lambda item: (
            item.capsule_path.as_posix(),
            item.profile_id,
        )
    )
    template = templates[0]
    if any(
        item.composite_digest != template.composite_digest
        for item in templates[1:]
    ):
        warnings.append(
            "Multiple different UMU runtime sources exist; "
            f"using {template.profile_id}"
        )

    proton_runners, runner_warnings = _scan_proton_runners(
        root,
        layout,
    )
    warnings.extend(runner_warnings)
    if not proton_runners:
        warnings.append(
            "No structurally Proton-compatible shared runner is registered"
        )

    profiles: list[UmuProfile] = []
    native_capsules: set[str] = set()

    for capsule_path, capsule, profile in native_candidates:
        try:
            capsule_id = str(capsule["capsule_id"])
            native_capsules.add(capsule_id)
            game = capsule.get("game", {})
            if not isinstance(game, dict):
                game = {}
            title = (
                game.get("title")
                if isinstance(game.get("title"), str)
                else capsule_id
            )
            version = (
                game.get("preserved_version")
                if isinstance(game.get("preserved_version"), str)
                else ""
            )
            source_id = _profile_id(
                profile,
                f"{capsule_id} native UMU profile",
            )
            state_root = _accepted_state(
                root,
                index_capsules.get(capsule_id),
            )
            archives = _state_archives(
                profile,
                f"{capsule_id}/{source_id}",
            )
            native_template = _native_template(
                capsule_path,
                capsule,
                profile,
            )
            exact = UmuProfile(
                capsule_id=capsule_id,
                title=title,
                preserved_version=version,
                capsule_path=capsule_path.resolve(strict=True),
                profile_id=source_id,
                profile_status=_profile_status(profile),
                kind="native-exact",
                source_profile_id=source_id,
                state_root=state_root,
                state_archives=archives,
                original_profile=copy.deepcopy(profile),
                capsule=copy.deepcopy(capsule),
                backend_template=native_template,
                composite_object_id=native_template.composite_object_id,
                composite_digest=native_template.composite_digest,
            )
            modular = UmuProfile(
                capsule_id=capsule_id,
                title=title,
                preserved_version=version,
                capsule_path=capsule_path.resolve(strict=True),
                profile_id=f"{source_id}-modular",
                profile_status="candidate",
                kind="native-modular",
                source_profile_id=source_id,
                state_root=state_root,
                state_archives=archives,
                original_profile=copy.deepcopy(profile),
                capsule=copy.deepcopy(capsule),
                backend_template=native_template,
                composite_object_id=native_template.composite_object_id,
                composite_digest=native_template.composite_digest,
            )
            profiles.extend((exact, modular))
            if archives and state_root is None:
                warnings.append(
                    f"{capsule_id}: state archives exist but accepted_state "
                    "is unavailable"
                )
        except (KeyError, UmuCatalogError) as exc:
            warnings.append(str(exc))

    for capsule_path, capsule in capsule_documents:
        capsule_id = capsule.get("capsule_id")
        if not isinstance(capsule_id, str) or capsule_id in native_capsules:
            continue
        game = capsule.get("game", {})
        if not isinstance(game, dict):
            game = {}
        title = (
            game.get("title")
            if isinstance(game.get("title"), str)
            else capsule_id
        )
        version = (
            game.get("preserved_version")
            if isinstance(game.get("preserved_version"), str)
            else ""
        )
        convertible = _convertible_wine_profiles(capsule)
        if not convertible:
            warnings.append(
                f"{capsule_id}: UMU not offered because no portable "
                "Direct-Wine playable layout is recorded"
            )
            continue
        for source_profile in convertible:
            try:
                source_id = _profile_id(
                    source_profile,
                    f"{capsule_id} Direct-Wine profile",
                )
                save_sets, save_warnings = scan_save_sets(
                    root,
                    capsule_id,
                )
                warnings.extend(
                    f"{capsule_id}: {warning}"
                    for warning in save_warnings
                )
                accepted_state_root = _accepted_state(
                    root,
                    index_capsules.get(capsule_id),
                )
                profiles.append(
                    UmuProfile(
                        capsule_id=capsule_id,
                        title=title,
                        preserved_version=version,
                        capsule_path=capsule_path.resolve(strict=True),
                        profile_id=f"{source_id}-umu-candidate",
                        profile_status="candidate",
                        kind="derived-wine",
                        source_profile_id=source_id,
                        state_root=None,
                        state_archives=(),
                        original_profile=copy.deepcopy(source_profile),
                        capsule=copy.deepcopy(capsule),
                        backend_template=template,
                        save_sets=save_sets,
                        accepted_state_root=accepted_state_root,
                    )
                )
            except UmuCatalogError as exc:
                warnings.append(str(exc))

    profiles.sort(
        key=lambda item: (
            item.title.casefold(),
            item.capsule_id,
            {
                "native-exact": 0,
                "native-modular": 1,
                "derived-wine": 2,
            }[item.kind],
            item.profile_id,
        )
    )
    return UmuCatalog(
        profiles=tuple(profiles),
        runners=proton_runners,
        warnings=tuple(dict.fromkeys(warnings)),
    )
