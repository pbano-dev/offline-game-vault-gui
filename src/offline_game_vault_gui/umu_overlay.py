from __future__ import annotations

import copy
import hashlib
import json
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .umu_model import UmuRunner, UmuSelection
from .umu_state_bridge import (
    PreparedDerivedState,
    prepare_derived_state,
)


_PROFILE_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_BACKEND_PARTITIONS = (
    "engine/python-portable",
    "engine/umu-portable",
    "engine/xdg-data",
)


class UmuOverlayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedUmuOverlay:
    capsule_path: Path
    state_root: Path | None
    selected_save_id: str | None


def _safe_relative(
    value: Any,
    label: str,
    *,
    dot: bool = False,
) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise UmuOverlayError(f"{label} is not a safe relative path")
    if dot and value == ".":
        return PurePosixPath(".")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise UmuOverlayError(f"{label} is not a safe relative path")
    return path


def _under(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise UmuOverlayError(
            f"Path escapes the capsule root: {relative.as_posix()}"
        ) from exc
    return candidate


def _digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _portable_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.casefold())
    normalized = normalized.strip("._-")
    if not normalized:
        raise UmuOverlayError("Cannot derive a portable object ID")
    if not normalized[0].isalnum():
        normalized = "runner-" + normalized
    return normalized


def _unique_id(existing: set[str], preferred: str) -> str:
    candidate = _portable_id(preferred)
    if candidate not in existing:
        return candidate
    number = 2
    while f"{candidate}-{number}" in existing:
        number += 1
    return f"{candidate}-{number}"


def _asset_references(profile: dict[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    host = profile.get("host_contract")
    if isinstance(host, str):
        result.append(host)
    contract = profile.get("umu")
    if not isinstance(contract, dict):
        return tuple(result)
    for key in ("launchers", "protected_manifests", "symlink_manifests"):
        values = contract.get(key, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("source"), str):
                result.append(item["source"])
    return tuple(dict.fromkeys(result))


def _runner_object(
    runner: UmuRunner,
    object_id: str,
) -> dict[str, Any]:
    return {
        "id": object_id,
        "digest": f"sha256:{runner.digest}",
        "roles": ["runner"],
        "format": runner.archive_format,
        "required": True,
        "archive_path": runner.archive_path,
        "size": runner.size,
        "shared": True,
        "description": (
            "Structurally Proton-compatible shared runner selected at "
            "materialization time. Functional acceptance is not inherited."
        ),
    }


def _copy_referenced_assets(
    *,
    source_capsule_path: Path,
    profile: dict[str, Any],
    overlay_root: Path,
) -> None:
    source_root = source_capsule_path.parent.resolve(strict=True)
    for reference in _asset_references(profile):
        relative = _safe_relative(reference, "profile asset")
        source = _under(source_root, relative)
        if source.is_symlink() or not source.is_file():
            raise UmuOverlayError(
                f"Referenced profile asset is unavailable: "
                f"{relative.as_posix()}"
            )
        destination = _under(overlay_root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(source.stat().st_mode & 0o777)


def _write_asset(
    overlay_root: Path,
    relative: str,
    payload: bytes,
    mode: int,
) -> dict[str, Any]:
    path = _under(
        overlay_root,
        _safe_relative(relative, "generated asset"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(mode)
    return {
        "source": relative,
        "destination": relative,
        "digest": f"sha256:{_digest_bytes(payload)}",
        "mode": mode,
    }


def _shell_array(values: list[str]) -> str:
    return " ".join(shlex.quote(value) for value in values)


def _generic_launcher(
    *,
    capsule: dict[str, Any],
    profile: dict[str, Any],
    runner: UmuRunner,
) -> bytes:
    playable = profile.get("playable")
    launch = profile.get("launch")
    if not isinstance(playable, dict) or not isinstance(launch, dict):
        raise UmuOverlayError("Direct-Wine source profile is incomplete")
    paths = playable.get("paths")
    if not isinstance(paths, dict):
        raise UmuOverlayError("Direct-Wine source paths are absent")
    prefix = _safe_relative(
        paths.get("prefix"),
        "playable.paths.prefix",
    ).as_posix()
    entrypoint = _safe_relative(
        launch.get("entrypoint"),
        "launch.entrypoint",
    ).as_posix()
    working = _safe_relative(
        launch.get("working_directory", "."),
        "launch.working_directory",
        dot=True,
    ).as_posix()
    arguments_raw = launch.get("arguments", [])
    if (
        not isinstance(arguments_raw, list)
        or any(not isinstance(item, str) for item in arguments_raw)
    ):
        raise UmuOverlayError("launch.arguments must be an array of strings")
    arguments = list(arguments_raw)

    game = capsule.get("game", {})
    if not isinstance(game, dict):
        game = {}
    appid = game.get("appid")
    game_id = str(appid) if isinstance(appid, int) and appid >= 0 else "0"
    store_raw = game.get("source_store")
    store = (
        "steam"
        if isinstance(store_raw, str)
        and store_raw.casefold() == "steam"
        else "none"
    )
    proton_relative = f"engine/proton/{runner.source_root}"
    fixed_arguments = _shell_array(arguments)
    fixed_suffix = f" {fixed_arguments}" if fixed_arguments else ""

    script = f'''#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")/.." && pwd -P)"
PREFIX="$ROOT/{prefix}"
PROTON="$ROOT/{proton_relative}"
XDG_DATA="$ROOT/engine/xdg-data"
EXE="$ROOT/{entrypoint}"
WORKDIR="$ROOT/{working}"

for required in "$PREFIX" "$PROTON" "$XDG_DATA" "$WORKDIR"; do
    [[ -d "$required" ]] || {{
        printf 'UMU candidate: required directory missing: %s\\n' "$required" >&2
        exit 1
    }}
done

[[ -f "$EXE" ]] || {{
    printf 'UMU candidate: entrypoint missing: %s\\n' "$EXE" >&2
    exit 1
}}

UMU_COMMAND=()

mapfile -t UMU_BINARIES < <(
    find "$ROOT/engine/umu-portable" \
        -type f -name 'umu-run' -perm -u+x -print 2>/dev/null
)

if (( ${{#UMU_BINARIES[@]}} == 1 )); then
    UMU_COMMAND=("${{UMU_BINARIES[0]}}")
else
    mapfile -t UMU_PACKAGES < <(
        find "$ROOT/engine/umu-portable" \
            -type f -path '*/umu_run/__main__.py' -print 2>/dev/null
    )
    mapfile -t PYTHON_BINARIES < <(
        find "$ROOT/engine/python-portable" \
            -type f -name 'python3' -perm -u+x -print 2>/dev/null
    )
    if (( ${{#UMU_PACKAGES[@]}} == 1 && ${{#PYTHON_BINARIES[@]}} == 1 )); then
        UMU_PACKAGE_ROOT="$(
            dirname -- "$(dirname -- "${{UMU_PACKAGES[0]}}")"
        )"
        export PYTHONPATH="$UMU_PACKAGE_ROOT"
        UMU_COMMAND=("${{PYTHON_BINARIES[0]}}" -m umu_run)
    else
        printf '%s\\n' \
            'UMU candidate: preserved umu-run entrypoint is ambiguous or absent.' \
            "umu-run binaries: ${{#UMU_BINARIES[@]}}" \
            "umu_run packages: ${{#UMU_PACKAGES[@]}}" \
            "portable Python binaries: ${{#PYTHON_BINARIES[@]}}" >&2
        exit 1
    fi
fi

export WINEPREFIX="$PREFIX"
export PROTONPATH="$PROTON"
export XDG_DATA_HOME="$XDG_DATA"
export GAMEID={shlex.quote(game_id)}
export STORE={shlex.quote(store)}

cd -- "$WORKDIR"
exec "${{UMU_COMMAND[@]}}" "$EXE"{fixed_suffix} "$@"
'''
    return script.encode("utf-8")


def _generic_sanitizer(runtime_var: str, runner: UmuRunner) -> bytes:
    runtime = _safe_relative(
        runtime_var,
        "runtime_var",
    ).as_posix()
    proton = f"engine/proton/{runner.source_root}"
    script = f'''#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")/.." && pwd -P)"
RUNTIME_VAR="$ROOT/{runtime}"
PROTON_ROOT="$ROOT/{proton}"

if [[ -d "$RUNTIME_VAR" && ! -L "$RUNTIME_VAR" ]]; then
    find "$RUNTIME_VAR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {{}} +
fi

rm -f -- "$PROTON_ROOT/files/steampipe_fixups_mtime"
'''
    return script.encode("utf-8")


def _filter_native_verification(
    contract: dict[str, Any],
) -> None:
    protected = contract.get("protected_manifests", [])
    if isinstance(protected, list):
        contract["protected_manifests"] = [
            item
            for item in protected
            if not (
                isinstance(item, dict)
                and isinstance(item.get("source"), str)
                and "UMU_STACK" in item["source"]
            )
        ]
    symlinks = contract.get("symlink_manifests", [])
    if isinstance(symlinks, list):
        kept: list[Any] = []
        for item in symlinks:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            prefixes = item.get("prefixes")
            if (
                isinstance(prefixes, list)
                and any(
                    isinstance(value, str)
                    and (
                        value == "engine"
                        or value.startswith("engine/")
                    )
                    for value in prefixes
                )
            ):
                continue
            kept.append(item)
        contract["symlink_manifests"] = kept


def _native_modular_profile(
    selection: UmuSelection,
    runner: UmuRunner,
    capsule: dict[str, Any],
    objects: list[Any],
    existing_ids: set[str],
) -> dict[str, Any]:
    profile = selection.profile
    matches = [
        item
        for item in capsule.get("profiles", [])
        if (
            isinstance(item, dict)
            and item.get("id") == profile.source_profile_id
        )
    ]
    if len(matches) != 1:
        raise UmuOverlayError(
            "Native source UMU profile is absent or duplicated"
        )
    derived = copy.deepcopy(matches[0])
    contract = derived.get("umu")
    dependencies = derived.get("dependencies")
    if not isinstance(contract, dict) or not isinstance(dependencies, list):
        raise UmuOverlayError("Native UMU profile is incomplete")
    if profile.composite_object_id is None:
        raise UmuOverlayError("Native profile has no composite object ID")

    runner_object_id = _unique_id(
        existing_ids,
        f"shared-proton-{runner.runner_id}",
    )
    existing_ids.add(runner_object_id)
    objects.append(_runner_object(runner, runner_object_id))
    dependencies.append(runner_object_id)

    layout = contract.get("layout")
    if not isinstance(layout, list):
        raise UmuOverlayError("Native umu.layout is not an array")
    engine_indexes = [
        index
        for index, item in enumerate(layout)
        if (
            isinstance(item, dict)
            and item.get("object") == profile.composite_object_id
            and item.get("source") == "engine"
            and item.get("destination") == "engine"
        )
    ]
    if len(engine_indexes) != 1:
        raise UmuOverlayError(
            "Native profile does not have one exact engine mapping"
        )
    replacement = [
        {
            "object": profile.composite_object_id,
            "source": partition,
            "destination": partition,
        }
        for partition in _BACKEND_PARTITIONS
    ]
    replacement.append(
        {
            "object": runner_object_id,
            "source": runner.source_root,
            "destination": f"engine/proton/{runner.source_root}",
        }
    )
    index = engine_indexes[0]
    contract["layout"] = [
        *layout[:index],
        *replacement,
        *layout[index + 1 :],
    ]

    _filter_native_verification(contract)
    old_roots = {
        value.rsplit("/files/steampipe_fixups_mtime", 1)[0]
        for value in contract.get("mutable_paths", [])
        if (
            isinstance(value, str)
            and value.startswith("engine/proton/")
            and value.endswith("/files/steampipe_fixups_mtime")
        )
    }
    old_root = next(iter(old_roots), None)
    new_root = f"engine/proton/{runner.source_root}"
    mutable = contract.get("mutable_paths", [])
    if isinstance(mutable, list) and old_root is not None:
        contract["mutable_paths"] = [
            (
                value.replace(old_root, new_root, 1)
                if isinstance(value, str) and value.startswith(old_root)
                else value
            )
            for value in mutable
        ]

    derived["id"] = selection.effective_profile_id
    derived["status"] = "candidate"
    derived.pop("acceptance_report", None)
    note = (
        "GUI 0.3.3 compatibility UMU candidate. The preserved UMU, Python and "
        "Steam Linux Runtime partitions remain sourced from the composite "
        "object; the selected Proton object is independent. Historical "
        "acceptance is not inherited."
    )
    previous = derived.get("notes")
    derived["notes"] = (
        f"{previous}\n\n{note}"
        if isinstance(previous, str) and previous
        else note
    )
    return derived


def _derived_wine_profile(
    selection: UmuSelection,
    runner: UmuRunner,
    capsule: dict[str, Any],
    objects: list[Any],
    existing_ids: set[str],
    overlay_root: Path,
) -> tuple[dict[str, Any], PreparedDerivedState]:
    profile = selection.profile
    prepared_state = prepare_derived_state(
        selection,
        overlay_root,
    )
    source = copy.deepcopy(profile.original_profile)
    dependencies = source.get("dependencies")
    playable = source.get("playable")
    if not isinstance(dependencies, list) or not isinstance(playable, dict):
        raise UmuOverlayError("Direct-Wine source profile is incomplete")
    layout = playable.get("layout")
    if not isinstance(layout, list) or not layout:
        raise UmuOverlayError("Direct-Wine playable.layout is absent")

    object_index = {
        item.get("id"): item
        for item in objects
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    source_runner_ids = {
        dependency
        for dependency in dependencies
        if (
            isinstance(dependency, str)
            and isinstance(object_index.get(dependency), dict)
            and "runner"
            in (
                object_index[dependency].get("roles")
                if isinstance(
                    object_index[dependency].get("roles"),
                    list,
                )
                else []
            )
        )
    }
    remaining_dependencies = [
        value
        for value in dependencies
        if isinstance(value, str) and value not in source_runner_ids
    ]
    source_layout = [
        copy.deepcopy(item)
        for item in layout
        if (
            isinstance(item, dict)
            and item.get("object") not in source_runner_ids
        )
    ]
    mapped = {
        item.get("object")
        for item in source_layout
        if isinstance(item.get("object"), str)
    }
    if set(remaining_dependencies) != mapped:
        raise UmuOverlayError(
            "Direct-Wine layout does not map every non-runner dependency"
        )

    backend = profile.backend_template
    backend_object_id = _unique_id(
        existing_ids,
        "shared-umu-backend",
    )
    existing_ids.add(backend_object_id)
    backend_object = copy.deepcopy(backend.composite_object)
    backend_object["id"] = backend_object_id
    backend_object["description"] = (
        "Preserved UMU, portable Python and Steam Linux Runtime backend "
        "reused by a GUI-generated candidate. Embedded Proton is excluded "
        "by layout."
    )
    objects.append(backend_object)

    runner_object_id = _unique_id(
        existing_ids,
        f"shared-proton-{runner.runner_id}",
    )
    existing_ids.add(runner_object_id)
    objects.append(_runner_object(runner, runner_object_id))

    launcher = _generic_launcher(
        capsule=capsule,
        profile=source,
        runner=runner,
    )
    sanitizer = _generic_sanitizer(
        backend.runtime_var,
        runner,
    )
    launcher_item = _write_asset(
        overlay_root,
        "launchers/JUGAR_UMU_CANDIDATO.sh",
        launcher,
        0o755,
    )
    sanitizer_item = _write_asset(
        overlay_root,
        "launchers/sanear_umu_candidato.sh",
        sanitizer,
        0o755,
    )

    allowed_absolute = playable.get(
        "allowed_absolute_symlinks",
        [],
    )
    nested = playable.get("nested_archives", [])
    mutable = playable.get("mutable_paths", [])
    for value, label in (
        (allowed_absolute, "allowed_absolute_symlinks"),
        (nested, "nested_archives"),
        (mutable, "mutable_paths"),
    ):
        if not isinstance(value, list):
            raise UmuOverlayError(f"playable.{label} must be an array")

    source["id"] = selection.effective_profile_id
    source["adapter"] = "umu"
    source["platform"] = "linux"
    source["status"] = "candidate"
    source["dependencies"] = [
        *remaining_dependencies,
        backend_object_id,
        runner_object_id,
    ]
    source.pop("playable", None)
    source.pop("host_contract", None)
    source.pop("acceptance_report", None)

    launch = copy.deepcopy(source.get("launch", {}))
    if not isinstance(launch, dict):
        raise UmuOverlayError("Source launch contract is absent")
    launch["network"] = "host_default"
    source["launch"] = launch
    source["umu"] = {
        "schema": 0,
        "layout": [
            *source_layout,
            *[
                {
                    "object": backend_object_id,
                    "source": partition,
                    "destination": partition,
                }
                for partition in _BACKEND_PARTITIONS
            ],
            {
                "object": runner_object_id,
                "source": runner.source_root,
                "destination": f"engine/proton/{runner.source_root}",
            },
        ],
        "allowed_absolute_symlinks": copy.deepcopy(allowed_absolute),
        "nested_archives": copy.deepcopy(nested),
        "state_archives": [
            dict(item)
            for item in prepared_state.state_archives
        ],
        "launchers": [launcher_item, sanitizer_item],
        "protected_manifests": [
            dict(item)
            for item in prepared_state.protected_manifests
        ],
        "symlink_manifests": [],
        "mutable_paths": [
            *[
                value
                for value in mutable
                if isinstance(value, str)
            ],
            *prepared_state.mutable_paths,
            f"engine/proton/{runner.source_root}/files/steampipe_fixups_mtime",
        ],
        "paths": {
            "launcher": launcher_item["destination"],
            "sanitizer": sanitizer_item["destination"],
            "runtime_var": backend.runtime_var,
        },
    }
    source["notes"] = (
        "GUI 0.3.3 compatibility UMU candidate derived from a recorded Direct-Wine "
        "layout. It reuses a preserved UMU/Python/Steam Linux Runtime "
        "backend and a separately selected Proton runner. It has no "
        "functional acceptance, does not inherit the source profile's "
        "acceptance. A selected canonical save set is bridged through "
        "a deterministic, verified state archive; required identity or "
        "configuration is verified against the clean baseline."
    )
    return source, prepared_state


def build_umu_overlay(
    selection: UmuSelection,
    overlay_root: Path,
) -> GeneratedUmuOverlay:
    if selection.profile.exact:
        raise UmuOverlayError(
            "Exact native UMU profiles do not require an overlay"
        )
    runner = selection.runner
    if runner is None:
        raise UmuOverlayError("A modular UMU candidate requires a runner")

    derived_profile_id = selection.effective_profile_id
    if _PROFILE_ID_RE.fullmatch(derived_profile_id) is None:
        raise UmuOverlayError(
            f"Derived profile ID is invalid: {derived_profile_id}"
        )

    capsule = copy.deepcopy(selection.profile.capsule)
    objects = capsule.get("objects")
    profiles = capsule.get("profiles")
    if not isinstance(objects, list) or not isinstance(profiles, list):
        raise UmuOverlayError("Source capsule is incomplete")

    existing_ids = {
        item.get("id")
        for item in objects
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    overlay_root = Path(overlay_root)
    if overlay_root.exists() or overlay_root.is_symlink():
        raise UmuOverlayError(
            f"Overlay destination already exists: {overlay_root}"
        )
    overlay_root.mkdir(parents=True, mode=0o700)

    try:
        if selection.profile.kind == "native-modular":
            derived = _native_modular_profile(
                selection,
                runner,
                capsule,
                objects,
                existing_ids,
            )
            generated_state_root = selection.profile.state_root
            generated_save_id = selection.selected_save_id
            _copy_referenced_assets(
                source_capsule_path=selection.profile.capsule_path,
                profile=derived,
                overlay_root=overlay_root,
            )
        elif selection.profile.kind == "derived-wine":
            derived, prepared_state = _derived_wine_profile(
                selection,
                runner,
                capsule,
                objects,
                existing_ids,
                overlay_root,
            )
            generated_state_root = prepared_state.state_root
            generated_save_id = prepared_state.selected_save_id
        else:
            raise UmuOverlayError(
                f"Unsupported UMU profile kind: {selection.profile.kind}"
            )

        capsule["profiles"] = [derived]
        capsule_path = overlay_root / "capsule.json"
        capsule_path.write_text(
            json.dumps(
                capsule,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return GeneratedUmuOverlay(
            capsule_path=capsule_path,
            state_root=generated_state_root,
            selected_save_id=generated_save_id,
        )
    except Exception:
        shutil.rmtree(overlay_root, ignore_errors=True)
        raise
