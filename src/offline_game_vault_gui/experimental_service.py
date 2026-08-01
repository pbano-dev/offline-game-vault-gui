from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Sequence

from .core import CoreResolutionError, inspect_core, resolve_ogv_command
from .model import (
    BackendId,
    ExperimentalRequest,
    OperationResult,
    RunnerRecord,
)


class ExperimentalServiceError(RuntimeError):
    pass


_SUPPORTED_BACKENDS = ("bottles", "direct-wine", "umu")
_GUI_RECEIPT = ".ogv-gui-experimental.json"


def _parse_last_json(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if stripped:
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value

    decoder = json.JSONDecoder()
    candidates = [
        match.start()
        for match in re.finditer(r"(?m)^\s*\{", stdout)
    ]
    for start in reversed(candidates):
        candidate = stdout[start:].lstrip()
        try:
            value, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and not candidate[end:].strip():
            return value
    raise ExperimentalServiceError(
        "offline-game-vault did not emit a final JSON object"
    )


def _run_json(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    try:
        command, environment = resolve_ogv_command()
    except CoreResolutionError as exc:
        raise ExperimentalServiceError(str(exc)) from exc

    environment = dict(environment)
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    process = subprocess.run(
        [*command, *arguments],
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise ExperimentalServiceError(
            f"offline-game-vault exited with code {process.returncode}: "
            f"{detail[-8000:]}"
        )
    return process, _parse_last_json(process.stdout)


def _run_script_json(
    target: Path,
    script_name: str,
    arguments: Sequence[str] = (),
    *,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    if target.is_symlink() or not target.is_dir():
        raise ExperimentalServiceError(
            "The materialization target is unavailable"
        )
    script = target / script_name
    if (
        script.is_symlink()
        or not script.is_file()
        or not os.access(script, os.X_OK)
    ):
        raise ExperimentalServiceError(
            f"Materialization lacks executable {script_name}"
        )
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    process = subprocess.run(
        [str(script), *arguments],
        cwd=cwd or target,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip()
        raise ExperimentalServiceError(
            f"{script_name} exited with code {process.returncode}: "
            f"{detail[-8000:]}"
        )
    return process, _parse_last_json(process.stdout)


def validate_core() -> str:
    try:
        info = inspect_core()
    except CoreResolutionError as exc:
        raise ExperimentalServiceError(str(exc)) from exc
    return f"offline-game-vault {info.version} ({info.origin})"


def discover_bottles_path() -> Path:
    """Return Bottles' active managed directory as reported by the core."""

    _process, payload = _run_json(
        [
            "discover-bottles-path",
            "--json",
        ]
    )
    raw = payload.get("bottles_path")
    if not isinstance(raw, str) or not raw.strip():
        raise ExperimentalServiceError(
            "Core did not return a valid Bottles managed path"
        )
    candidate = Path(raw).expanduser()
    try:
        if candidate.is_symlink():
            raise OSError("managed path is a symlink")
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ExperimentalServiceError(
            "The Bottles managed path reported by the core is unavailable"
        ) from exc
    if not resolved.is_dir():
        raise ExperimentalServiceError(
            "The Bottles managed path reported by the core is not a directory"
        )
    return resolved


def _required_text(
    value: dict[str, Any],
    key: str,
    context: str,
) -> str:
    candidate = value.get(key)
    if not isinstance(candidate, str) or not candidate.strip():
        raise ExperimentalServiceError(
            f"{context}: missing valid text in {key!r}"
        )
    return candidate.strip()


def _optional_text(value: dict[str, Any], key: str) -> str | None:
    candidate = value.get(key)
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


def _required_int(
    value: dict[str, Any],
    key: str,
    context: str,
) -> int:
    candidate = value.get(key)
    if not isinstance(candidate, int) or isinstance(candidate, bool) or candidate < 0:
        raise ExperimentalServiceError(
            f"{context}: missing valid integer in {key!r}"
        )
    return candidate


def list_preserved_runners(
    collection_root: Path,
) -> tuple[tuple[RunnerRecord, ...], tuple[str, ...]]:
    _process, payload = _run_json(
        [
            "list-preserved-runners",
            "--collection-root",
            str(collection_root),
            "--json",
        ]
    )
    raw_runners = payload.get("runners")
    raw_warnings = payload.get("warnings", [])
    if not isinstance(raw_runners, list):
        raise ExperimentalServiceError(
            "Core runner catalog did not contain a runners array"
        )
    if not isinstance(raw_warnings, list):
        raw_warnings = []

    records: list[RunnerRecord] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_runners):
        context = f"runners[{index}]"
        if not isinstance(item, dict):
            raise ExperimentalServiceError(f"{context}: not an object")

        runner_id = _required_text(item, "runner_id", context)
        if runner_id in seen:
            raise ExperimentalServiceError(
                f"{context}: duplicate runner_id {runner_id!r}"
            )
        raw_backends = item.get("compatible_backends")
        if not isinstance(raw_backends, list):
            raise ExperimentalServiceError(
                f"{context}: compatible_backends is not an array"
            )
        backends = tuple(
            backend
            for backend in raw_backends
            if isinstance(backend, str)
            and backend in _SUPPORTED_BACKENDS
        )
        if not backends:
            continue

        digest_value = _required_text(item, "digest", context)
        digest = digest_value.removeprefix("sha256:")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ExperimentalServiceError(
                f"{context}: digest is not a SHA-256"
            )
        kind = _optional_text(item, "kind") or "wine"
        if kind not in {"wine", "proton"}:
            raise ExperimentalServiceError(
                f"{context}: unsupported runner kind {kind!r}"
            )

        records.append(
            RunnerRecord(
                runner_id=runner_id,
                digest=digest,
                archive_path=_required_text(
                    item, "archive_path", context
                ),
                size=_required_int(item, "size", context),
                format=_required_text(item, "format", context),
                source_root=_required_text(
                    item, "source_root", context
                ),
                wine_path=_required_text(item, "wine_path", context),
                wineserver_path=_required_text(
                    item, "wineserver_path", context
                ),
                compatible_backends=backends,
                metadata_source=_required_text(
                    item, "metadata_source", context
                ),
                proton_path=_optional_text(item, "proton_path"),
                kind=kind,  # type: ignore[arg-type]
                acceptance_status=(
                    _optional_text(item, "acceptance_status")
                    or "not_tested"
                ),
            )
        )
        seen.add(runner_id)

    records.sort(key=lambda record: record.runner_id.casefold())
    warnings = tuple(
        warning
        for warning in raw_warnings
        if isinstance(warning, str) and warning.strip()
    )
    return tuple(records), warnings


def compatible_runners(
    runners: Sequence[RunnerRecord],
    backend_id: str,
) -> tuple[RunnerRecord, ...]:
    if backend_id not in _SUPPORTED_BACKENDS:
        return ()
    return tuple(
        runner
        for runner in runners
        if runner.supports(backend_id)
    )


def _validate_request(request: ExperimentalRequest) -> None:
    if request.backend_id not in _SUPPORTED_BACKENDS:
        raise ExperimentalServiceError(
            f"Unsupported experimental backend: {request.backend_id}"
        )
    if not request.runner.supports(request.backend_id):
        raise ExperimentalServiceError(
            f"Runner {request.runner.runner_id} is not structurally "
            f"compatible with {request.backend_id}"
        )
    if request.capsule_path.is_symlink() or not request.capsule_path.is_file():
        raise ExperimentalServiceError(
            "The selected capsule.json is unavailable"
        )
    if request.collection_root.is_symlink() or not request.collection_root.is_dir():
        raise ExperimentalServiceError(
            "The selected collection root is unavailable"
        )

    if request.backend_id == "bottles":
        if (
            request.bottles_path is None
            or request.bottles_path.is_symlink()
            or not request.bottles_path.is_dir()
        ):
            raise ExperimentalServiceError(
                "Select the existing managed Bottles directory"
            )
        if not request.bottle_name:
            raise ExperimentalServiceError(
                "A non-empty Bottles derivative name is required"
            )
    else:
        if request.destination is None:
            raise ExperimentalServiceError(
                f"A destination is required for {request.backend_id}"
            )
        parent = request.destination.parent
        if parent.is_symlink() or not parent.is_dir():
            raise ExperimentalServiceError(
                "The destination parent must be an existing regular directory"
            )


def _materialize_arguments(
    request: ExperimentalRequest,
    *,
    play: bool,
) -> list[str]:
    _validate_request(request)
    arguments = [
        "materialize-experimental",
        "--collection-root",
        str(request.collection_root),
        "--capsule",
        str(request.capsule_path),
        "--backend",
        request.backend_id,
        "--runner",
        request.runner.runner_id,
    ]
    if request.source_profile_id:
        arguments.extend(
            ["--source-profile", request.source_profile_id]
        )

    if request.backend_id == "bottles":
        assert request.bottles_path is not None
        assert request.bottle_name is not None
        arguments.extend(
            [
                "--bottles-path",
                str(request.bottles_path),
                "--bottle-name",
                request.bottle_name,
            ]
        )
    else:
        assert request.destination is not None
        arguments.extend(
            ["--destination", str(request.destination)]
        )

    if (
        request.backend_id == "direct-wine"
        and request.state_backup is not None
    ):
        arguments.extend(
            ["--state-backup", str(request.state_backup)]
        )


    if play:
        arguments.append("--play")
    arguments.append("--json")
    return arguments


def _result(
    *,
    operation: str,
    request: ExperimentalRequest,
    process: subprocess.CompletedProcess[str],
    payload: dict[str, Any],
) -> OperationResult:
    destination = request.target
    if destination is None:
        raise ExperimentalServiceError(
            "The operation did not produce a resolvable target"
        )
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str):
        profile_id = request.source_profile_id or "automatic"
    runner_id = payload.get("runner_id")
    if not isinstance(runner_id, str):
        runner_id = request.runner.runner_id
    return OperationResult(
        operation=operation,
        backend_id=request.backend_id,
        destination=destination,
        profile_id=profile_id,
        runner_id=runner_id,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def materialize_experimental(
    request: ExperimentalRequest,
    *,
    play: bool,
) -> OperationResult:
    # Materialization and execution are deliberately separate.  The core
    # publishes one backend-specific JUGAR.sh and the GUI always invokes that
    # generated contract instead of rebuilding launch semantics itself.
    arguments = _materialize_arguments(request, play=False)
    cwd = (
        request.destination.parent
        if request.destination is not None
        else None
    )
    process, payload = _run_json(arguments, cwd=cwd)
    if payload.get("materialized") is not True:
        raise ExperimentalServiceError(
            "Core returned without confirming materialization"
        )
    materialized = _result(
        operation="materialize",
        request=request,
        process=process,
        payload=payload,
    )
    if not play:
        return materialized

    played = run_experimental(request)
    combined = dict(payload)
    combined["play"] = played.payload
    return OperationResult(
        operation="materialize-and-play",
        backend_id=request.backend_id,
        destination=materialized.destination,
        profile_id=materialized.profile_id,
        runner_id=materialized.runner_id,
        payload=combined,
        stdout=process.stdout + played.stdout,
        stderr=process.stderr + played.stderr,
    )


def verify_experimental(
    request: ExperimentalRequest,
) -> OperationResult:
    _validate_request(request)
    target = request.target
    if target is None:
        raise ExperimentalServiceError(
            "The selected materialization has no target"
        )
    process, payload = _run_script_json(
        target,
        "VERIFICAR.sh",
        ["--json"],
    )
    return _result(
        operation="verify",
        request=request,
        process=process,
        payload=payload,
    )


def run_experimental(
    request: ExperimentalRequest,
) -> OperationResult:
    _validate_request(request)
    target = request.target
    if target is None:
        raise ExperimentalServiceError(
            "The selected materialization has no target"
        )
    process, payload = _run_script_json(
        target,
        "JUGAR.sh",
        ["--json"],
    )
    return _result(
        operation="run",
        request=request,
        process=process,
        payload=payload,
    )


def remove_experimental(
    request: ExperimentalRequest,
) -> OperationResult:
    _validate_request(request)
    target = request.target
    if target is None:
        raise ExperimentalServiceError(
            "The selected materialization has no target"
        )
    if request.backend_id == "direct-wine":
        arguments = ["--discard-state", "--json"]
    elif request.backend_id == "umu":
        arguments = ["--confirm-state-preserved", "--json"]
    else:
        arguments = [
            "--confirm-state-preserved",
            "--confirm-stopped",
            "--json",
        ]
    process, payload = _run_script_json(
        target,
        "DESINSTALAR.sh",
        arguments,
        cwd=target.parent,
    )
    return _result(
        operation="remove",
        request=request,
        process=process,
        payload=payload,
    )


def target_occupied(request: ExperimentalRequest) -> bool:
    target = request.target
    return bool(
        target is not None
        and (target.exists() or target.is_symlink())
    )


def target_recognized(request: ExperimentalRequest) -> bool:
    target = request.target
    if (
        target is None
        or target.is_symlink()
        or not target.is_dir()
    ):
        return False
    receipt_name = {
        "direct-wine": "playable-materialization.json",
        "umu": "umu-materialization.json",
        "bottles": ".ogv-bottles-deployment.json",
    }.get(request.backend_id)
    if receipt_name is None:
        return False
    receipt = target / receipt_name
    if not receipt.is_file() or receipt.is_symlink():
        return False
    for name in ("JUGAR.sh", "VERIFICAR.sh", "DESINSTALAR.sh"):
        script = target / name
        if (
            script.is_symlink()
            or not script.is_file()
            or not os.access(script, os.X_OK)
        ):
            return False
    return True

def target_exists(request: ExperimentalRequest) -> bool:
    target = request.target
    return bool(
        target is not None
        and target.is_dir()
        and not target.is_symlink()
    )


def write_local_receipt(
    request: ExperimentalRequest,
    outcome: OperationResult,
) -> Path | None:
    """Write a convenience receipt beside directory materializations.

    The core receipts remain authoritative. This file only remembers the GUI
    selection and never grants permission to run or remove anything.
    """

    if request.backend_id == "bottles" or request.destination is None:
        return None
    destination = request.destination
    if not destination.is_dir() or destination.is_symlink():
        return None
    path = destination / _GUI_RECEIPT
    document = {
        "schema": 0,
        "kind": "experimental-selection",
        "acceptance_inherited": False,
        "capsule_id": request.capsule_id,
        "backend": request.backend_id,
        "runner_id": request.runner.runner_id,
        "source_profile_id": request.source_profile_id,
        "core_result": outcome.payload,
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            document,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return path
