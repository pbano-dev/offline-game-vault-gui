from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .catalog import profile_mode
from .bottles_control import validate_bottles_control
from .model import (
    BackendId,
    MaterializationMode,
    MaterializationRequest,
    RunnerRecord,
    ValidatedRequest,
)
from .runner_override import RunnerOverrideError, build_derived_capsule
from .runners import RunnerCatalogError, validate_runner_record
from .save_sets import (
    SaveSetCatalogError,
    validate_save_set_record,
)
from .selection_receipt import (
    DERIVATIVE_RELATIVE,
    DIRECT_RELATIVE,
    selection_receipt_matches,
)
from .shared_backend import (
    SharedBackendError,
    validate_shared_backend_record,
)


class GuardError(RuntimeError):
    pass


_CAPSULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_DESTINATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")
BASE_RECEIPT_NAME = "materialization-receipt.json"
PLAYABLE_RECEIPT_NAME = "playable-materialization.json"
BOTTLES_RECEIPT_NAME = ".ogv-bottles-deployment.json"


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _regular_directory(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise GuardError(f"{label} must be a regular directory: {path}")
    return path.resolve(strict=True)


def _load_capsule(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError("capsule.json cannot be validated") from exc
    if not isinstance(document, dict):
        raise GuardError("capsule.json does not contain a JSON object")
    return document


def _selected_profile(
    document: dict[str, Any],
    profile_id: str,
) -> tuple[dict[str, Any], MaterializationMode]:
    profiles = document.get("profiles")
    if not isinstance(profiles, list):
        raise GuardError("The capsule declares no valid profiles")

    matches = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("id") == profile_id
    ]
    if len(matches) != 1:
        raise GuardError(
            "The selected profile does not exist exactly once"
        )

    profile = matches[0]
    status = profile.get("status")
    if status == "unavailable":
        raise GuardError("The selected profile is marked unavailable")
    if not isinstance(status, str) or not status:
        raise GuardError("The selected profile does not declare a valid status")
    if not isinstance(profile.get("dependencies"), list):
        raise GuardError("The selected profile does not declare dependencies")

    return profile, profile_mode(profile)


def _state_backup(
    collection: Path,
    capsule_id: str,
    document: dict[str, Any],
    backend_id: BackendId,
) -> Path | None:
    if backend_id == "base":
        return None

    state = document.get("persistent_state", [])
    if not isinstance(state, list):
        raise GuardError("persistent_state must be an array")
    if not state:
        return None
    if any(not isinstance(item, dict) for item in state):
        raise GuardError(
            "persistent_state contains an invalid entry"
        )

    accepted = _regular_directory(
        collection
        / "03_PERSISTENT_STATE"
        / capsule_id
        / "accepted",
        "The accepted backup",
    )
    receipt = accepted / "state-backup.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise GuardError(
            "A regular state-backup.json is missing from accepted"
        )
    return accepted

def _portable_component(value: str, label: str) -> str:
    if not _CAPSULE_ID_RE.fullmatch(value):
        raise GuardError(f"{label} contains unsupported characters")
    return value


def variant_destination_name(
    capsule_id: str,
    profile_id: str,
    backend_id: BackendId,
    runner_id: str | None,
    save_set_id: str | None = None,
) -> str:
    _portable_component(capsule_id, "capsule_id")
    _portable_component(profile_id, "profile_id")

    if save_set_id is not None:
        _portable_component(save_set_id, "save_set_id")

    if backend_id == "direct-wine":
        if runner_id is None:
            raise GuardError("Direct-Wine requires a runner")
        _portable_component(runner_id, "runner_id")
        suffix = f"{profile_id}--{runner_id}"
    elif backend_id == "bottles":
        if runner_id is None:
            raise GuardError("Bottles requires a runner")
        _portable_component(runner_id, "runner_id")
        suffix = f"{profile_id}--bottles--{runner_id}"
    elif backend_id == "windows":
        if runner_id is not None:
            raise GuardError("Windows does not accept a Wine runner")
        suffix = f"{profile_id}--windows"
    elif backend_id == "base":
        if save_set_id is not None:
            raise GuardError(
                "Base materialization does not accept a save set"
            )
        suffix = f"{profile_id}--base"
    else:
        raise GuardError(
            f"Unsupported backend: {backend_id}"
        )

    if save_set_id is not None:
        suffix += f"--save-{save_set_id}"

    candidate = f"{capsule_id}--{suffix}"
    if (
        len(candidate) <= 240
        and _DESTINATION_RE.fullmatch(candidate)
    ):
        return candidate

    digest = hashlib.sha256(
        candidate.encode("utf-8")
    ).hexdigest()[:16]
    available = 240 - len(digest) - 2
    shortened = f"{candidate[:available]}--{digest}"
    if not _DESTINATION_RE.fullmatch(shortened):
        raise GuardError(
            "Could not build a portable destination name"
        )
    return shortened

def _runner_receipt_matches(
    receipt: dict[str, Any],
    *,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
) -> bool:
    if (
        receipt.get("capsule_id") != capsule_id
        or receipt.get("profile_id") != profile_id
        or receipt.get("backend") != "wine"
        or receipt.get("complete") is not True
    ):
        return False

    expected_destination = f"runner/{runner.runner_id}"
    layout = receipt.get("layout")
    if not isinstance(layout, list):
        return False

    mappings = [
        item
        for item in layout
        if (
            isinstance(item, dict)
            and item.get("object") == runner.runner_id
            and item.get("source") == runner.source_root
            and item.get("destination") == expected_destination
        )
    ]
    if len(mappings) != 1:
        return False

    objects = receipt.get("objects")
    if not isinstance(objects, list):
        return False

    object_matches = [
        item
        for item in objects
        if (
            isinstance(item, dict)
            and item.get("id") == runner.runner_id
            and item.get("digest") == runner.digest
        )
    ]
    paths = receipt.get("paths")
    expected_paths = {
        "runner": expected_destination,
        "wine": f"{expected_destination}/{runner.wine_path}",
        "wineserver": f"{expected_destination}/{runner.wineserver_path}",
    }
    return (
        len(object_matches) == 1
        and isinstance(paths, dict)
        and all(paths.get(key) == value for key, value in expected_paths.items())
    )


def _recognized_playable_destination(
    destination: Path,
    *,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
    save_set: Any,
) -> bool:
    receipt_path = destination / PLAYABLE_RECEIPT_NAME
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False

    return (
        isinstance(receipt, dict)
        and _runner_receipt_matches(
            receipt,
            capsule_id=capsule_id,
            profile_id=profile_id,
            runner=runner,
        )
        and selection_receipt_matches(
            destination,
            relative=DIRECT_RELATIVE,
            capsule_id=capsule_id,
            profile_id=profile_id,
            backend_id="direct-wine",
            runner_id=runner.runner_id,
            save_set=save_set,
            allow_legacy_none=True,
        )
    )

def _recognized_base_destination(
    destination: Path,
    *,
    capsule_id: str,
    profile_id: str,
) -> bool:
    receipt_path = destination / BASE_RECEIPT_NAME
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(receipt, dict)
        and receipt.get("complete") is True
        and receipt.get("destination") == "."
        and receipt.get("capsule_id") == capsule_id
        and receipt.get("profile_id") == profile_id
    )


def bottle_deployment_name(
    capsule_id: str,
    profile_id: str,
    runner_id: str,
    save_set_id: str | None = None,
) -> str:
    for value, label in (
        (capsule_id, "capsule_id"),
        (profile_id, "profile_id"),
        (runner_id, "runner_id"),
    ):
        _portable_component(value, label)

    raw = (
        f"ogv--{capsule_id}--{profile_id}--{runner_id}"
    )
    if save_set_id is not None:
        _portable_component(save_set_id, "save_set_id")
        raw += f"--save-{save_set_id}"

    if (
        len(raw) <= 128
        and _CAPSULE_ID_RE.fullmatch(raw)
    ):
        return raw

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:16]
    available = 128 - len(digest) - 2
    candidate = f"{raw[:available]}--{digest}"
    if not _CAPSULE_ID_RE.fullmatch(candidate):
        raise GuardError(
            "Could not build a portable bottle name"
        )
    return candidate

def _recognized_bottles_deployment(
    deployment: Path,
    *,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
    bottle_name: str,
    save_set: Any,
) -> bool:
    receipt_path = deployment / BOTTLES_RECEIPT_NAME
    if receipt_path.is_symlink() or not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(
            receipt_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False

    return (
        isinstance(receipt, dict)
        and receipt.get("capsule_id") == capsule_id
        and receipt.get("profile_id") == profile_id
        and receipt.get("bottle_name") == bottle_name
        and receipt.get("destination") == "."
        and receipt.get("runner") == runner.runner_id
        and isinstance(receipt.get("deployment_id"), str)
        and bool(receipt.get("deployment_id"))
        and selection_receipt_matches(
            deployment,
            relative=DERIVATIVE_RELATIVE,
            capsule_id=capsule_id,
            profile_id=profile_id,
            backend_id="bottles",
            runner_id=runner.runner_id,
            save_set=save_set,
            allow_legacy_none=True,
        )
    )

def resolve_destination(
    parent: Path,
    *,
    capsule_id: str,
    profile_id: str,
    backend_id: BackendId,
    runner: RunnerRecord | None,
    save_set_id: str | None = None,
) -> Path:
    preferred = parent / variant_destination_name(
        capsule_id,
        profile_id,
        backend_id,
        runner.runner_id if runner else None,
        save_set_id,
    )
    if (
        preferred.exists()
        or preferred.is_symlink()
        or backend_id != "direct-wine"
        or save_set_id is not None
    ):
        return preferred

    assert runner is not None
    legacy = parent / capsule_id
    if (
        legacy.is_dir()
        and not legacy.is_symlink()
        and _recognized_playable_destination(
            legacy,
            capsule_id=capsule_id,
            profile_id=profile_id,
            runner=runner,
            save_set=None,
        )
    ):
        return legacy
    return preferred

def validate_request(request: MaterializationRequest) -> ValidatedRequest:
    _portable_component(request.capsule_id, "capsule_id")
    _portable_component(request.profile_id, "profile_id")

    collection = _regular_directory(request.collection_root, "The collection")
    immutable = _regular_directory(
        collection / "01_IMMUTABLE_VAULT",
        "The immutable vault",
    )
    capsules_root = _regular_directory(
        collection / "02_CAPSULES",
        "The capsule directory",
    )
    expected_parent = _regular_directory(
        capsules_root / request.capsule_id,
        "The selected capsule",
    )

    capsule = Path(request.capsule_path)
    if capsule.is_symlink() or not capsule.is_file():
        raise GuardError("capsule.json must be a regular file")
    capsule = capsule.resolve(strict=True)
    if capsule != expected_parent / "capsule.json":
        raise GuardError(
            "The capsule does not belong to the selected capsule_id"
        )
    if not _is_within(capsule, capsules_root):
        raise GuardError("The capsule is outside 02_CAPSULES")

    document = _load_capsule(capsule)
    if document.get("capsule_id") != request.capsule_id:
        raise GuardError("capsule_id does not match capsule.json")

    profile, profile_mode_value = _selected_profile(
        document,
        request.profile_id,
    )

    if request.save_set is not None:
        if request.backend_id == "base":
            raise GuardError(
                "Only Direct-Wine, Bottles, and Windows accept a save set"
            )
        if request.save_set.capsule_id != request.capsule_id:
            raise GuardError(
                "The selected save set belongs to another capsule"
            )
        try:
            validate_save_set_record(
                collection,
                capsule_path=capsule,
                expected=request.save_set,
            )
        except SaveSetCatalogError as exc:
            raise GuardError(str(exc)) from exc

    runner: RunnerRecord | None = None
    default_runner_id: str | None = None
    overlay_required = False
    effective_mode: MaterializationMode
    bottles_path: Path | None = None
    bottle_name: str | None = None
    deployment_path: Path | None = None
    bottles_backend = None

    if request.backend_id == "base":
        if request.runner is not None:
            raise GuardError("Base materialization does not accept a runner")
        effective_mode = "base"
    elif request.backend_id == "direct-wine":
        if profile_mode_value != "playable":
            raise GuardError(
                "The selected profile has no Direct-Wine contract"
            )
        if request.runner is None:
            raise GuardError("A Direct-Wine runner must be selected")
        if not request.runner.supports("direct-wine"):
            raise GuardError(
                "The selected runner does not declare Direct-Wine compatibility"
            )

        try:
            validate_runner_record(collection, request.runner)
            derived = build_derived_capsule(
                capsule,
                request.profile_id,
                request.runner,
            )
        except (RunnerCatalogError, RunnerOverrideError) as exc:
            raise GuardError(str(exc)) from exc

        runner = request.runner
        default_runner_id = derived.original_runner_id
        overlay_required = derived.changed
        effective_mode = "playable"
    elif request.backend_id == "windows":
        if (
            profile.get("platform") != "windows"
            or profile.get("adapter") != "windows"
        ):
            raise GuardError(
                "The selected profile does not declare the Windows adapter"
            )
        if request.runner is not None:
            raise GuardError("Windows export does not accept a Wine runner")
        effective_mode = "base"
    elif request.backend_id == "bottles":
        if (
            profile.get("platform") != "linux"
            or profile.get("adapter") != "bottles"
        ):
            raise GuardError(
                "The selected profile does not declare the Bottles adapter"
            )
        if request.runner is None:
            raise GuardError("A Bottles runner must be selected")
        if not request.runner.supports("bottles"):
            raise GuardError(
                "The selected runner does not declare Bottles compatibility"
            )
        try:
            validate_runner_record(collection, request.runner)
        except RunnerCatalogError as exc:
            raise GuardError(str(exc)) from exc

        dependencies = profile.get("dependencies")
        objects = document.get("objects")
        if not isinstance(dependencies, list) or not isinstance(objects, list):
            raise GuardError(
                "The Bottles profile does not declare valid dependencies and objects"
            )
        runner_objects = {
            item.get("id")
            for item in objects
            if (
                isinstance(item, dict)
                and isinstance(item.get("roles"), list)
                and "runner" in item["roles"]
                and isinstance(item.get("id"), str)
            )
        }
        candidates = [
            value
            for value in dependencies
            if isinstance(value, str) and value in runner_objects
        ]
        if len(candidates) > 1:
            raise GuardError(
                "The Bottles profile depends on more than one runner object"
            )
        runner = request.runner
        default_runner_id = candidates[0] if candidates else None
        overlay_required = (
            default_runner_id is None
            or runner.runner_id != default_runner_id
        )
        effective_mode = "base"

        if request.bottles_backend is None:
            raise GuardError(
                "The vault Bottles shared backend has not been resolved"
            )
        try:
            validate_shared_backend_record(
                collection,
                request.bottles_backend,
            )
        except SharedBackendError as exc:
            raise GuardError(str(exc)) from exc
        bottles_backend = request.bottles_backend

        if request.bottles_path is None:
            raise GuardError(
                "The managed Bottles path has not been resolved"
            )
        bottles_path = _regular_directory(
            request.bottles_path,
            "The managed Bottles path",
        )
        if not os.access(bottles_path, os.W_OK | os.X_OK):
            raise GuardError(
                "The managed Bottles path is not writable"
            )
        if _is_within(bottles_path, collection):
            raise GuardError(
                "The managed Bottles path cannot be inside the vault"
            )
        bottle_name = bottle_deployment_name(
            request.capsule_id,
            request.profile_id,
            runner.runner_id,
            (
                request.save_set.save_set_id
                if request.save_set is not None
                else None
            ),
        )
        deployment_path = bottles_path / bottle_name
    else:
        raise GuardError(f"Unsupported backend: {request.backend_id}")

    state_backup = _state_backup(
        collection,
        request.capsule_id,
        document,
        request.backend_id,
    )

    destination = Path(request.destination)
    if not _DESTINATION_RE.fullmatch(destination.name):
        raise GuardError("The final destination name is not portable")

    parent = _regular_directory(
        destination.parent,
        "The parent directory",
    )
    expected_destination = resolve_destination(
        parent,
        capsule_id=request.capsule_id,
        profile_id=request.profile_id,
        backend_id=request.backend_id,
        runner=runner,
        save_set_id=(
            request.save_set.save_set_id
            if request.save_set is not None
            else None
        ),
    )
    if destination != expected_destination:
        raise GuardError(
            "The exact destination does not match the selected variant"
        )

    if _is_within(parent, collection) or _is_within(
        expected_destination,
        collection,
    ):
        raise GuardError("The destination must be outside the collection")
    if not os.access(parent, os.W_OK | os.X_OK):
        raise GuardError("The parent directory is not writable")

    reusable = False
    source_reusable = False
    control_reusable = False
    if expected_destination.exists() or expected_destination.is_symlink():
        if (
            expected_destination.is_symlink()
            or not expected_destination.is_dir()
        ):
            raise GuardError(
                "The existing destination is not a regular directory"
            )

        if request.backend_id == "base":
            raise GuardError(
                "Base materialization requires a new destination; "
                "the core does not overwrite existing destinations"
            )
        if request.backend_id == "direct-wine":
            assert runner is not None
            if not _recognized_playable_destination(
                expected_destination,
                capsule_id=request.capsule_id,
                profile_id=request.profile_id,
                runner=runner,
                save_set=request.save_set,
            ):
                raise GuardError(
                    "The destination already exists but does not match the backend, "
                    "profile, and runner selected"
                )
            reusable = True
            source_reusable = True
        elif request.backend_id == "windows":
            raise GuardError(
                "Windows export requires a new destination"
            )
        else:
            assert runner is not None
            assert bottle_name is not None
            control = validate_bottles_control(
                expected_destination,
                capsule_id=request.capsule_id,
                profile_id=request.profile_id,
                runner=runner,
                bottle_name=bottle_name,
                backend=bottles_backend,
            )
            if control is not None:
                if not selection_receipt_matches(
                    expected_destination,
                    relative=DERIVATIVE_RELATIVE,
                    capsule_id=request.capsule_id,
                    profile_id=request.profile_id,
                    backend_id="bottles",
                    runner_id=runner.runner_id,
                    save_set=request.save_set,
                    allow_legacy_none=True,
                ):
                    raise GuardError(
                        "The existing Bottles control belongs "
                        "another save selection"
                    )
                control_reusable = True
            elif _recognized_base_destination(
                expected_destination,
                capsule_id=request.capsule_id,
                profile_id=request.profile_id,
            ):
                source_reusable = True
            else:
                raise GuardError(
                    "The existing Bottles destination is neither a base source nor "
                    "a recognized single-instance control"
                )

    if request.backend_id == "bottles":
        assert deployment_path is not None
        assert runner is not None
        assert bottle_name is not None
        if deployment_path.exists() or deployment_path.is_symlink():
            if deployment_path.is_symlink() or not deployment_path.is_dir():
                raise GuardError(
                    "The managed Bottles destination is not a regular directory"
                )
            if not _recognized_bottles_deployment(
                deployment_path,
                capsule_id=request.capsule_id,
                profile_id=request.profile_id,
                runner=runner,
                bottle_name=bottle_name,
                save_set=request.save_set,
            ):
                raise GuardError(
                    "The existing bottle does not match the capsule, profile, "
                    "and selected runner"
                )
            reusable = True

    if request.backend_id == "bottles" and control_reusable and not reusable:
        raise GuardError(
            "The Bottles control exists, but the managed bottle is missing"
        )

    return ValidatedRequest(
        collection_root=collection,
        immutable_vault_root=immutable,
        capsule_path=capsule,
        capsule_id=request.capsule_id,
        profile_id=request.profile_id,
        backend_id=request.backend_id,
        destination_parent=parent,
        destination=expected_destination,
        mode=effective_mode,
        state_backup=state_backup,
        save_set=request.save_set,
        runner=runner,
        default_runner_id=default_runner_id,
        overlay_required=overlay_required,
        reusable=reusable,
        source_reusable=source_reusable,
        control_reusable=control_reusable,
        bottles_path=bottles_path,
        bottle_name=bottle_name,
        deployment_path=deployment_path,
        bottles_backend=bottles_backend,
    )
