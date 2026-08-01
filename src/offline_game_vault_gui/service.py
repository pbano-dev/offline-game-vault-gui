from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Iterator, Sequence

from .core import (
    CoreResolutionError,
    resolve_ogv_command,
)
from .model import (
    MaterializationRequest,
    OperationResult,
)
from .runner_override import (
    RunnerOverrideError,
    build_derived_capsule,
)


class MaterializationError(RuntimeError):
    pass


class ExecutionError(RuntimeError):
    pass


_GUI_RECEIPT = ".ogv-gui-selection.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _critical_seal(collection_root: Path) -> dict[str, str]:
    relative_paths = (
        "INDEX.json",
        "COLLECTION_LAYOUT.json",
        "COLLECTION_SHA256.txt",
        "01_IMMUTABLE_VAULT/VAULT_INVENTORY.json",
    )
    result: dict[str, str] = {}
    for relative in relative_paths:
        path = collection_root / relative
        if path.is_symlink() or not path.is_file():
            raise MaterializationError(
                f"Critical collection file is unavailable: {relative}"
            )
        result[relative] = _sha256_file(path)
    return result


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
    raise MaterializationError(
        "The core did not emit a final JSON object"
    )


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    try:
        prefix, environment = resolve_ogv_command()
    except CoreResolutionError as exc:
        raise MaterializationError(str(exc)) from exc

    process = subprocess.run(
        [*prefix, *arguments],
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
        raise MaterializationError(
            f"Core command failed with code {process.returncode}: "
            f"{detail[-8000:]}"
        )
    payload = _parse_last_json(process.stdout)
    return process, payload


def _validate_destination(request: MaterializationRequest) -> None:
    root = request.collection_root.resolve(strict=True)
    parent = request.destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise MaterializationError(
            f"Destination parent is not a regular directory: {parent}"
        )
    try:
        request.destination.resolve(strict=False).relative_to(root)
    except ValueError:
        pass
    else:
        raise MaterializationError(
            "Destination must be outside the collection"
        )
    if request.destination.is_symlink():
        raise MaterializationError("Destination must not be a symlink")


def _index_capsule_entry(
    request: MaterializationRequest,
) -> dict[str, Any]:
    path = request.collection_root / "INDEX.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationError("INDEX.json is invalid") from exc
    if not isinstance(document, dict):
        raise MaterializationError("INDEX.json root is not an object")
    entries = document.get("capsules")
    if not isinstance(entries, list):
        return {}
    matches = [
        item
        for item in entries
        if (
            isinstance(item, dict)
            and item.get("capsule_id") == request.capsule_id
        )
    ]
    return matches[0] if len(matches) == 1 else {}


def _safe_collection_path(
    request: MaterializationRequest,
    value: str,
) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise MaterializationError(
            "State path is not collection-relative"
        )
    candidate = request.collection_root / relative
    try:
        candidate.resolve(strict=False).relative_to(
            request.collection_root.resolve(strict=True)
        )
    except ValueError as exc:
        raise MaterializationError(
            "State path escapes the collection"
        ) from exc
    return candidate


def _state_backup(
    request: MaterializationRequest,
) -> Path | None:
    if request.save_set is not None and request.save_set.source:
        source = request.save_set.source
        for key in (
            "state_backup",
            "accepted_state",
            "backup_path",
        ):
            value = source.get(key)
            if isinstance(value, str) and value:
                candidate = _safe_collection_path(request, value)
                if candidate.is_dir() and not candidate.is_symlink():
                    return candidate.resolve(strict=True)

    entry = _index_capsule_entry(request)
    value = entry.get("accepted_state")
    if isinstance(value, str) and value:
        candidate = _safe_collection_path(request, value)
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate.resolve(strict=True)
    return None


@contextmanager
def _effective_capsule(
    request: MaterializationRequest,
) -> Iterator[Path]:
    if (
        request.backend_id not in {"direct-wine", "bottles"}
        or request.runner is None
    ):
        yield request.capsule_path
        return

    try:
        payload = build_derived_capsule(
            request.capsule_path,
            request.profile_id,
            request.runner,
        )
    except RunnerOverrideError as exc:
        raise MaterializationError(str(exc)) from exc

    cache = Path(
        os.environ.get(
            "XDG_CACHE_HOME",
            str(Path.home() / ".cache"),
        )
    ) / "offline-game-vault-gui" / "runner-overlays"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="capsule-",
        dir=cache,
    ) as temporary:
        capsule = Path(temporary) / "capsule.json"
        capsule.write_bytes(payload)
        capsule.chmod(0o600)
        yield capsule


def _write_gui_receipt(
    request: MaterializationRequest,
    payload: dict[str, Any],
) -> Path:
    request.destination.mkdir(parents=True, exist_ok=True)
    path = request.destination / _GUI_RECEIPT
    document = {
        "schema": 0,
        "backend": request.backend_id,
        "capsule_id": request.capsule_id,
        "profile_id": request.profile_id,
        "runner_id": (
            request.runner.runner_id
            if request.runner is not None
            else None
        ),
        "save_set_id": (
            request.save_set.save_set_id
            if request.save_set is not None
            else None
        ),
        "destination": str(request.destination),
        "complete": True,
        "core_result": payload,
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def destination_receipt(destination: Path) -> dict[str, Any] | None:
    path = destination / _GUI_RECEIPT
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def materialize(request: MaterializationRequest) -> OperationResult:
    _validate_destination(request)
    before = _critical_seal(request.collection_root)
    vault_root = (
        request.collection_root / "01_IMMUTABLE_VAULT"
    )

    with _effective_capsule(request) as capsule:
        if request.backend_id == "direct-wine":
            arguments = [
                "materialize-playable",
                "--capsule",
                str(capsule),
                "--profile",
                request.profile_id,
                "--vault-root",
                str(vault_root),
                "--destination",
                str(request.destination),
            ]
            backup = _state_backup(request)
            if backup is not None:
                arguments.extend(["--state-backup", str(backup)])
            arguments.append("--json")
            process, payload = _run(
                arguments,
                cwd=request.destination.parent,
            )

        elif request.backend_id == "bottles":
            if request.bottles_path is None:
                raise MaterializationError(
                    "Bottles managed path was not discovered by the active core"
                )
            process, payload = _run(
                [
                    "materialize",
                    "--capsule",
                    str(capsule),
                    "--profile",
                    request.profile_id,
                    "--vault-root",
                    str(vault_root),
                    "--destination",
                    str(request.destination),
                    "--json",
                ],
                cwd=request.destination.parent,
            )
            bottle_name = request.destination.name
            _, deployment = _run(
                [
                    "deploy-bottles",
                    "--capsule",
                    str(capsule),
                    "--profile",
                    request.profile_id,
                    "--materialization",
                    str(request.destination),
                    "--bottles-path",
                    str(request.bottles_path),
                    "--name",
                    bottle_name,
                    "--json",
                ]
            )
            payload = {
                "materialization": payload,
                "deployment": deployment,
                "bottle_name": bottle_name,
                "bottles_path": str(request.bottles_path),
            }

        else:
            process, payload = _run(
                [
                    "materialize",
                    "--capsule",
                    str(capsule),
                    "--profile",
                    request.profile_id,
                    "--vault-root",
                    str(vault_root),
                    "--destination",
                    str(request.destination),
                    "--json",
                ],
                cwd=request.destination.parent,
            )

    after = _critical_seal(request.collection_root)
    if after != before:
        raise MaterializationError(
            "The collection control seal changed during materialization"
        )
    _write_gui_receipt(request, payload)
    return OperationResult(
        operation="materialize",
        backend_id=request.backend_id,
        destination=request.destination,
        profile_id=request.profile_id,
        runner_id=(
            request.runner.runner_id
            if request.runner is not None
            else None
        ),
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def verify(
    destination: Path,
    backend_id: str,
) -> OperationResult:
    if backend_id == "direct-wine":
        process, payload = _run(
            [
                "verify-playable",
                "--destination",
                str(destination),
                "--json",
            ]
        )
    elif backend_id == "bottles":
        receipt = destination_receipt(destination)
        if not receipt:
            raise MaterializationError(
                "GUI Bottles receipt is missing"
            )
        core = receipt.get("core_result")
        bottle_name = (
            core.get("bottle_name")
            if isinstance(core, dict)
            else None
        )
        bottles_path = (
            core.get("bottles_path")
            if isinstance(core, dict)
            else None
        )
        if not isinstance(bottle_name, str) or not isinstance(
            bottles_path,
            str,
        ):
            raise MaterializationError(
                "GUI Bottles receipt is incomplete"
            )
        process, payload = _run(
            [
                "verify-bottles-deployment",
                "--bottles-path",
                bottles_path,
                "--name",
                bottle_name,
                "--json",
            ]
        )
    else:
        receipt = destination_receipt(destination)
        if not receipt or receipt.get("complete") is not True:
            raise MaterializationError(
                "Recognized complete GUI receipt is missing"
            )
        process = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )
        payload = {"complete": True, "receipt": receipt}

    return OperationResult(
        operation="verify",
        backend_id=backend_id,  # type: ignore[arg-type]
        destination=destination,
        profile_id="",
        runner_id=None,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def run(destination: Path, backend_id: str) -> OperationResult:
    if backend_id == "direct-wine":
        process, payload = _run(
            [
                "run-playable",
                "--destination",
                str(destination),
                "--json",
            ],
            cwd=destination,
        )
    elif backend_id == "bottles":
        receipt = destination_receipt(destination)
        core = receipt.get("core_result") if receipt else None
        bottle_name = (
            core.get("bottle_name")
            if isinstance(core, dict)
            else None
        )
        bottles_path = (
            core.get("bottles_path")
            if isinstance(core, dict)
            else None
        )
        if not isinstance(bottle_name, str) or not isinstance(
            bottles_path,
            str,
        ):
            raise ExecutionError(
                "GUI Bottles receipt is incomplete"
            )
        process, payload = _run(
            [
                "run-bottles",
                "--bottles-path",
                bottles_path,
                "--name",
                bottle_name,
                "--json",
            ]
        )
    else:
        raise ExecutionError(
            f"Backend {backend_id} has no Linux execution command"
        )

    return OperationResult(
        operation="run",
        backend_id=backend_id,  # type: ignore[arg-type]
        destination=destination,
        profile_id="",
        runner_id=None,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def remove(
    destination: Path,
    backend_id: str,
    *,
    confirm_state_preserved: bool,
    confirm_stopped: bool = False,
) -> OperationResult:
    if backend_id == "direct-wine":
        arguments = [
            "remove-playable",
            "--destination",
            str(destination),
        ]
        # Explicit confirmation is required before discarding changed state.
        if confirm_state_preserved:
            arguments.append("--discard-state")
        arguments.append("--json")
        process, payload = _run(arguments)
    elif backend_id == "bottles":
        receipt = destination_receipt(destination)
        core = receipt.get("core_result") if receipt else None
        bottle_name = (
            core.get("bottle_name")
            if isinstance(core, dict)
            else None
        )
        bottles_path = (
            core.get("bottles_path")
            if isinstance(core, dict)
            else None
        )
        if not isinstance(bottle_name, str) or not isinstance(
            bottles_path,
            str,
        ):
            raise MaterializationError(
                "GUI Bottles receipt is incomplete"
            )
        arguments = [
            "remove-bottles-deployment",
            "--bottles-path",
            bottles_path,
            "--name",
            bottle_name,
        ]
        if confirm_state_preserved:
            arguments.append("--confirm-state-preserved")
        if confirm_stopped:
            arguments.append("--confirm-stopped")
        arguments.append("--json")
        process, payload = _run(arguments)
        # The source materialization remains independently removable.
    else:
        arguments = [
            "remove-materialization",
            "--destination",
            str(destination),
        ]
        if confirm_state_preserved:
            arguments.append("--confirm-state-preserved")
        arguments.append("--json")
        process, payload = _run(arguments)

    return OperationResult(
        operation="remove",
        backend_id=backend_id,  # type: ignore[arg-type]
        destination=destination,
        profile_id="",
        runner_id=None,
        payload=payload,
        stdout=process.stdout,
        stderr=process.stderr,
    )
