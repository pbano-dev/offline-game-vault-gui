from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .core import resolve_ogv_executable
from .umu_model import UmuOperationResult, UmuSelection
from .umu_overlay import build_umu_overlay


class UmuServiceError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise UmuServiceError(f"Cannot hash regular file: {path}") from exc
    return digest.hexdigest()


def _resolve_executable(
    environment_name: str,
    *,
    command: str,
    default: str | None = None,
) -> Path:
    value = os.environ.get(environment_name)
    candidate = value or shutil.which(command) or default
    if not candidate:
        raise UmuServiceError(
            f"Required executable was not found: {environment_name}/{command}"
        )
    path = Path(candidate).expanduser()
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise UmuServiceError(
            f"Executable cannot be resolved: {candidate}"
        ) from exc
    if not path.is_file() or not os.access(path, os.X_OK):
        raise UmuServiceError(f"Executable is not runnable: {path}")
    return path


def resolve_ogv() -> Path:
    try:
        return resolve_ogv_executable()
    except Exception as exc:
        raise UmuServiceError(str(exc)) from exc


def resolve_bwrap() -> Path:
    return _resolve_executable(
        "OGV_BWRAP",
        command="bwrap",
        default="/usr/bin/bwrap",
    )


def _parse_last_json(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates = [
        match.start()
        for match in re.finditer(r"(?m)^\s*\{", stdout)
    ]
    for start in reversed(candidates):
        stripped = stdout[start:].lstrip()
        try:
            value, end = decoder.raw_decode(stripped)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(value, dict)
            and not stripped[end:].strip()
        ):
            return value
    raise UmuServiceError(
        "OGV did not emit one final machine-readable JSON object"
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    process = subprocess.run(
        list(command),
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    payload: dict[str, Any] = {}
    if process.stdout.strip():
        try:
            payload = _parse_last_json(process.stdout)
        except UmuServiceError:
            if process.returncode == 0:
                raise
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise UmuServiceError(
            f"Command failed with code {process.returncode}: "
            f"{detail[-4000:]}"
        )
    if not payload:
        raise UmuServiceError("Successful OGV command returned no JSON")
    return process, payload


def _materialization_result_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Normalize the core materialize-umu JSON contract.

    Current core versions wrap the result as
    {"materialization": {...}}. A top-level result remains accepted for
    compatibility with development snapshots that emitted the dataclass
    directly.
    """
    nested = payload.get("materialization")
    if isinstance(nested, dict):
        return nested
    if payload.get("backend") == "umu":
        return payload
    raise UmuServiceError(
        "OGV returned no machine-readable UMU materialization result"
    )


def _critical_seal(collection_root: Path) -> dict[str, str]:
    relative_paths = (
        "INDEX.json",
        "COLLECTION_LAYOUT.json",
        "COLLECTION_SHA256.txt",
        "01_IMMUTABLE_VAULT/VAULT_INVENTORY.json",
    )
    seal: dict[str, str] = {}
    for relative in relative_paths:
        path = collection_root / relative
        if path.is_symlink() or not path.is_file():
            raise UmuServiceError(
                f"Critical collection file is unavailable: {relative}"
            )
        seal[relative] = _sha256_file(path)
    return seal


def _validate_destination(selection: UmuSelection) -> None:
    root = selection.collection_root.resolve(strict=True)
    parent = selection.destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise UmuServiceError(
            f"Destination parent is not a regular directory: {parent}"
        )
    parent = parent.resolve(strict=True)
    destination = selection.destination
    if destination.parent.resolve(strict=True) != parent:
        raise UmuServiceError("Destination parent changed during validation")
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError:
        pass
    else:
        raise UmuServiceError(
            "UMU materialization destination must be outside the collection"
        )
    if destination.is_symlink():
        raise UmuServiceError("Destination must not be a symlink")


def _verify_state_archives(selection: UmuSelection) -> None:
    profile = selection.profile
    if not profile.state_archives:
        return
    if profile.state_root is None:
        raise UmuServiceError(
            "The UMU profile declares state archives but has no state root"
        )
    root = profile.state_root.resolve(strict=True)
    for item in profile.state_archives:
        relative = Path(*item.filename.split("/"))
        path = root / relative
        try:
            path.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise UmuServiceError(
                f"State archive escapes its root: {item.filename}"
            ) from exc
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise UmuServiceError(
                f"State archive is unavailable: {item.filename}"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise UmuServiceError(
                f"State archive is not a regular file: {item.filename}"
            )
        if metadata.st_size < 0:
            raise UmuServiceError(
                f"State archive has an invalid size: {item.filename}"
            )
        actual = _sha256_file(path)
        if actual != item.digest:
            raise UmuServiceError(
                f"State archive digest mismatch: {item.filename}"
            )


def _verify_runner(selection: UmuSelection) -> None:
    runner = selection.runner
    if runner is None:
        if selection.profile.requires_runner:
            raise UmuServiceError("The selected UMU candidate has no runner")
        return
    try:
        metadata = runner.object_path.lstat()
    except OSError as exc:
        raise UmuServiceError(
            f"Runner object is unavailable: {runner.runner_id}"
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
    ):
        raise UmuServiceError("Runner object is not a regular file")
    if metadata.st_size != runner.size:
        raise UmuServiceError("Runner object size changed")
    actual = _sha256_file(runner.object_path)
    if actual != runner.digest:
        raise UmuServiceError("Runner object digest changed")


def build_materialize_command(
    selection: UmuSelection,
    *,
    capsule_path: Path,
    ogv: Path,
    bwrap: Path,
    state_root: Path | None = None,
) -> list[str]:
    command = [
        str(bwrap),
        "--ro-bind",
        "/",
        "/",
        "--bind",
        str(selection.destination.parent),
        str(selection.destination.parent),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--die-with-parent",
        "--new-session",
        "--chdir",
        str(selection.destination.parent),
        str(ogv),
        "materialize-umu",
        "--capsule",
        str(capsule_path),
        "--profile",
        selection.effective_profile_id,
        "--vault-root",
        str(selection.immutable_vault_root),
    ]
    effective_state_root = (
        state_root
        if state_root is not None
        else selection.profile.state_root
    )
    if effective_state_root is not None:
        command.extend(
            [
                "--state-root",
                str(effective_state_root),
            ]
        )
    elif (
        selection.profile.state_archives
        or selection.selected_save_id is not None
    ):
        raise UmuServiceError("UMU state root is unavailable")
    command.extend(
        [
            "--destination",
            str(selection.destination),
        ]
    )
    if selection.selected_save_id is not None:
        command.extend(["--save", selection.selected_save_id])
    command.append("--json")
    return command


def build_verify_command(destination: Path, *, ogv: Path) -> list[str]:
    return [
        str(ogv),
        "verify-umu",
        "--destination",
        str(destination),
        "--json",
    ]


def build_run_command(
    destination: Path,
    *,
    ogv: Path,
    arguments: Sequence[str] = (),
) -> list[str]:
    command = [
        str(ogv),
        "run-umu",
        "--destination",
        str(destination),
        "--json",
    ]
    if arguments:
        command.append("--")
        command.extend(arguments)
    return command


def build_remove_command(
    destination: Path,
    *,
    ogv: Path,
    confirm_state_preserved: bool,
) -> list[str]:
    command = [
        str(ogv),
        "remove-umu",
        "--destination",
        str(destination),
    ]
    if confirm_state_preserved:
        command.append("--confirm-state-preserved")
    command.append("--json")
    return command


def verify_core_contract(*, ogv: Path | None = None) -> None:
    executable = ogv or resolve_ogv()
    for command in (
        "materialize-umu",
        "verify-umu",
        "run-umu",
        "remove-umu",
    ):
        process = subprocess.run(
            [str(executable), command, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            raise UmuServiceError(
                f"Installed OGV core does not expose {command}"
            )


def materialize_umu(
    selection: UmuSelection,
) -> UmuOperationResult:
    _validate_destination(selection)
    if selection.profile.kind == "derived-wine":
        selectable = {
            item.save_set_id
            for item in selection.profile.save_sets
        }
    else:
        selectable = {
            item.state_id
            for item in selection.profile.selectable_saves
        }
    if (
        selection.selected_save_id is not None
        and selection.selected_save_id not in selectable
    ):
        raise UmuServiceError(
            f"Unknown selectable save: {selection.selected_save_id}"
        )

    ogv = resolve_ogv()
    bwrap = resolve_bwrap()
    verify_core_contract(ogv=ogv)
    before = _critical_seal(selection.collection_root)
    _verify_runner(selection)
    if selection.profile.kind != "derived-wine":
        _verify_state_archives(selection)

    cache_parent = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    ) / "offline-game-vault-gui" / "umu-overlays"
    cache_parent.mkdir(parents=True, exist_ok=True)

    if selection.profile.exact:
        capsule_path = selection.profile.capsule_path
        process, payload = _run(
            build_materialize_command(
                selection,
                capsule_path=capsule_path,
                ogv=ogv,
                bwrap=bwrap,
                state_root=selection.profile.state_root,
            ),
            cwd=selection.destination.parent,
        )
    else:
        with tempfile.TemporaryDirectory(
            prefix="overlay-",
            dir=cache_parent,
        ) as temporary:
            overlay_root = Path(temporary) / "capsule"
            generated = build_umu_overlay(
                selection,
                overlay_root,
            )
            if (
                generated.selected_save_id
                != selection.selected_save_id
            ):
                raise UmuServiceError(
                    "Generated UMU overlay changed the save selection"
                )
            process, payload = _run(
                build_materialize_command(
                    selection,
                    capsule_path=generated.capsule_path,
                    ogv=ogv,
                    bwrap=bwrap,
                    state_root=generated.state_root,
                ),
                cwd=selection.destination.parent,
            )

    after = _critical_seal(selection.collection_root)
    if after != before:
        raise UmuServiceError(
            "Critical collection seal changed during materialization"
        )

    result_payload = _materialization_result_payload(payload)
    if result_payload.get("backend") != "umu":
        raise UmuServiceError("OGV returned a non-UMU result")
    if result_payload.get("complete") is not True:
        raise UmuServiceError("UMU materialization is not complete")
    if (
        result_payload.get("profile_id")
        != selection.effective_profile_id
    ):
        raise UmuServiceError(
            "OGV returned another UMU profile ID"
        )
    if result_payload.get("selected_save") != selection.selected_save_id:
        raise UmuServiceError(
            "OGV returned another save selection"
        )
    if not selection.destination.is_dir():
        raise UmuServiceError(
            "OGV did not publish the selected destination"
        )
    return UmuOperationResult(
        operation="materialize",
        destination=selection.destination,
        profile_id=selection.effective_profile_id,
        runner_id=(
            selection.runner.runner_id
            if selection.runner is not None
            else None
        ),
        payload=result_payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def verify_umu(
    destination: Path,
    *,
    profile_id: str,
    runner_id: str | None,
) -> UmuOperationResult:
    ogv = resolve_ogv()
    process, payload = _run(
        build_verify_command(destination, ogv=ogv),
        cwd=Path(destination).parent,
    )
    if (
        payload.get("backend") != "umu"
        or payload.get("verified") is not True
    ):
        raise UmuServiceError("UMU verification did not pass")
    if payload.get("profile_id") != profile_id:
        raise UmuServiceError(
            "Existing UMU materialization belongs to another profile"
        )
    return UmuOperationResult(
        operation="verify",
        destination=Path(destination),
        profile_id=profile_id,
        runner_id=runner_id,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def run_umu(
    destination: Path,
    *,
    profile_id: str,
    runner_id: str | None,
    arguments: Sequence[str] = (),
) -> UmuOperationResult:
    ogv = resolve_ogv()
    process, payload = _run(
        build_run_command(
            destination,
            ogv=ogv,
            arguments=arguments,
        ),
        cwd=Path(destination),
    )
    if payload.get("backend") != "umu":
        raise UmuServiceError("OGV returned a non-UMU run result")
    if payload.get("profile_id") != profile_id:
        raise UmuServiceError(
            "UMU run result belongs to another profile"
        )
    return UmuOperationResult(
        operation="run",
        destination=Path(destination),
        profile_id=profile_id,
        runner_id=runner_id,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def remove_umu(
    destination: Path,
    *,
    profile_id: str,
    runner_id: str | None,
    confirm_state_preserved: bool,
) -> UmuOperationResult:
    ogv = resolve_ogv()
    process, payload = _run(
        build_remove_command(
            destination,
            ogv=ogv,
            confirm_state_preserved=confirm_state_preserved,
        ),
        cwd=Path(destination).parent,
    )
    if (
        payload.get("backend") != "umu"
        or payload.get("removed") is not True
    ):
        raise UmuServiceError("UMU removal did not complete")
    return UmuOperationResult(
        operation="remove",
        destination=Path(destination),
        profile_id=profile_id,
        runner_id=runner_id,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def destination_name(
    *,
    capsule_id: str,
    profile_id: str,
    runner_id: str | None,
    save_id: str | None,
) -> str:
    raw = "--".join(
        (
            capsule_id,
            "umu",
            profile_id,
            runner_id or "embedded-runner",
            save_id or "no-save",
        )
    )
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("._-")
    if not safe:
        raise UmuServiceError("Cannot derive a destination name")
    if len(safe) > 180:
        suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        safe = safe[:160].rstrip("._-") + "--" + suffix
    return safe


def destination_receipt(destination: Path) -> dict[str, Any] | None:
    path = Path(destination) / "umu-materialization.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
