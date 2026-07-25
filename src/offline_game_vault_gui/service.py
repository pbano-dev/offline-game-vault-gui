from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from queue import Queue
import subprocess
import tempfile
import threading
from typing import Any, Callable, Iterator

from . import __version__
from .bottles_backend import (
    BottlesEnvironmentError,
    BottlesOverrideError,
    scan_bottles_environment,
    find_materialized_bottle_yml,
    temporary_runner_override,
)
from .bottles_control import (
    BottlesControlError,
    refresh_bottles_control,
    validate_bottles_control,
    write_bottles_control,
)
from .guard import (
    BASE_RECEIPT_NAME,
    PLAYABLE_RECEIPT_NAME,
    validate_request,
)
from .logging_model import make_record
from .neutral_profiles import (
    NeutralProfileError,
    materialize_neutral_bottle_source,
    validate_neutral_bottles_source,
)
from .windows_export import (
    WindowsExportError,
    transform_base_to_windows_export,
)
from .model import (
    ExecutionOutcome,
    LogRecord,
    MaterializationOutcome,
    MaterializationRequest,
    ValidatedRequest,
)
from .runner_override import RunnerOverrideError, build_derived_capsule
from .shared_backend import (
    SharedBackendError,
    validate_shared_backend_record,
)
from .sandbox import (
    build_command,
    build_deploy_bottles_command,
    build_run_bottles_command,
    build_remove_materialization_command,
    build_run_playable_command,
    build_verify_bottles_command,
    build_verify_playable_command,
    resolve_bwrap,
    resolve_ogv,
    resolve_state_bridge,
    build_restore_state_command,
)
from .seal import capture_collection_seal
from .selection_receipt import (
    DERIVATIVE_RELATIVE,
    DIRECT_RELATIVE,
    SelectionReceiptError,
    write_selection_receipt,
)
from .state_selection import (
    PreparedStateBackup,
    StateSelectionError,
    prepared_state_backup,
)


class MaterializationError(RuntimeError):
    pass


class ExecutionError(RuntimeError):
    pass


LogCallback = Callable[[LogRecord], None]


def _emit(
    callback: LogCallback | None,
    message: str,
    *,
    stream: str = "internal",
    level: str | None = None,
) -> None:
    if callback is not None:
        callback(make_record(message, stream=stream, level=level))


def _pump(
    stream: Any,
    name: str,
    queue: Queue[tuple[str, str | None]],
) -> None:
    try:
        for line in iter(stream.readline, ""):
            queue.put((name, line.rstrip("\r\n")))
    finally:
        stream.close()
        queue.put((name, None))


def _stream_process(
    command: list[str],
    environment: dict[str, str],
    callback: LogCallback | None,
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
        shell=False,
    )
    assert process.stdout is not None
    assert process.stderr is not None

    queue: Queue[tuple[str, str | None]] = Queue()
    threads = [
        threading.Thread(
            target=_pump,
            args=(process.stdout, "stdout", queue),
            daemon=True,
        ),
        threading.Thread(
            target=_pump,
            args=(process.stderr, "stderr", queue),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    closed = 0
    while closed < 2:
        stream_name, line = queue.get()
        if line is None:
            closed += 1
            continue
        if stream_name == "stdout":
            stdout_lines.append(line)
        else:
            stderr_lines.append(line)
        _emit(callback, line, stream=stream_name)

    returncode = process.wait()
    for thread in threads:
        thread.join()

    return returncode, "\n".join(stdout_lines), "\n".join(stderr_lines)


def _parse_json(stdout: str, label: str = "The core") -> dict[str, Any]:
    """Return the last complete JSON object emitted on stdout.

    ``run-playable`` executes Wine before printing its JSON result. Some
    runners may write diagnostics to stdout, so requiring the entire stream to
    be JSON would be unsafe. Only a JSON object followed by whitespace is
    accepted, preventing trailing output from being hidden.
    """

    stripped = stdout.strip()
    if stripped:
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload
        if payload is not None:
            raise MaterializationError(
                f"The JSON response from {label.lower()} is not an object"
            )

    decoder = json.JSONDecoder()
    candidates = [
        index
        for index, character in enumerate(stdout)
        if character == "{"
        and (index == 0 or stdout[index - 1] in "\r\n")
    ]
    for index in reversed(candidates):
        try:
            payload, end = decoder.raw_decode(stdout, index)
        except json.JSONDecodeError:
            continue
        if stdout[end:].strip():
            continue
        if not isinstance(payload, dict):
            raise MaterializationError(
                f"The JSON response from {label.lower()} is not an object"
            )
        return payload

    raise MaterializationError(
        f"{label} finished without returning a valid JSON object"
    )


def _safe_relative(value: Any, field: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        raise MaterializationError(
            f"{field} is not a safe relative path"
        )

    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise MaterializationError(
            f"{field} is not a safe relative path"
        )
    return path


def _validate_base_result(
    request: ValidatedRequest,
    payload: dict[str, Any],
) -> tuple[Path, None, None]:
    if payload.get("complete") is not True:
        raise MaterializationError(
            "The base materialization is not marked complete"
        )

    reported = payload.get("destination")
    if isinstance(reported, str) and reported != str(request.destination):
        raise MaterializationError(
            "The core reported a different base destination"
        )

    receipt = request.destination / BASE_RECEIPT_NAME
    if receipt.is_symlink() or not receipt.is_file():
        raise MaterializationError(
            "A regular materialization-receipt.json is missing"
        )
    return receipt, None, None


def _validate_runner_in_receipt(
    request: ValidatedRequest,
    document: dict[str, Any],
) -> None:
    runner = request.runner
    if runner is None:
        raise MaterializationError(
            "The playable materialization does not preserve the selected runner"
        )

    layout = document.get("layout")
    objects = document.get("objects")
    if not isinstance(layout, list) or not isinstance(objects, list):
        raise MaterializationError(
            "The playable receipt does not declare layout and objects"
        )

    expected_destination = f"runner/{runner.runner_id}"
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
    object_matches = [
        item
        for item in objects
        if (
            isinstance(item, dict)
            and item.get("id") == runner.runner_id
            and item.get("digest") == runner.digest
        )
    ]
    paths = document.get("paths")
    expected_paths = {
        "runner": expected_destination,
        "wine": f"{expected_destination}/{runner.wine_path}",
        "wineserver": f"{expected_destination}/{runner.wineserver_path}",
    }
    if (
        len(mappings) != 1
        or len(object_matches) != 1
        or not isinstance(paths, dict)
        or any(paths.get(key) != value for key, value in expected_paths.items())
    ):
        raise MaterializationError(
            "The receipt does not match the selected runner"
        )


def _validate_playable_result(
    request: ValidatedRequest,
    payload: dict[str, Any],
) -> tuple[Path, Path, Path]:
    section = payload.get("materialization")
    if not isinstance(section, dict) or section.get("complete") is not True:
        raise MaterializationError(
            "The playable materialization is not marked complete"
        )

    reported = section.get("destination")
    if isinstance(reported, str) and reported != str(request.destination):
        raise MaterializationError(
            "The core reported a different playable destination"
        )

    receipt = request.destination / PLAYABLE_RECEIPT_NAME
    if receipt.is_symlink() or not receipt.is_file():
        raise MaterializationError(
            "A regular playable-materialization.json is missing"
        )
    try:
        document = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(
            "The playable receipt is not valid JSON"
        ) from exc

    if not isinstance(document, dict) or document.get("complete") is not True:
        raise MaterializationError(
            "The playable receipt is not complete"
        )
    if (
        document.get("capsule_id") != request.capsule_id
        or document.get("profile_id") != request.profile_id
        or document.get("backend") != "wine"
    ):
        raise MaterializationError(
            "The playable receipt does not match the selection"
        )

    _validate_runner_in_receipt(request, document)

    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise MaterializationError(
            "The playable receipt does not declare paths"
        )

    resolved: list[Path] = []
    destination_resolved = request.destination.resolve()
    for key in ("launcher", "uninstaller"):
        relative = _safe_relative(paths.get(key), f"paths.{key}")
        candidate = request.destination.joinpath(*relative.parts)
        try:
            candidate.resolve(strict=False).relative_to(
                destination_resolved
            )
        except ValueError as exc:
            raise MaterializationError(
                f"paths.{key} escapes the materialization"
            ) from exc

        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or not os.access(candidate, os.X_OK)
        ):
            raise MaterializationError(
                f"The {key} generated file is not executable"
            )
        resolved.append(candidate)

    return receipt, resolved[0], resolved[1]


def _failure_detail(stdout: str, stderr: str) -> str:
    lines = [
        line
        for line in (stderr + "\n" + stdout).splitlines()
        if line.strip()
    ]
    return " | ".join(lines[-8:]) if lines else "no details"


def _safe_overlay_destination(
    root: Path,
    relative_value: str,
) -> Path:
    if "\x00" in relative_value or "\\" in relative_value:
        raise MaterializationError(
            "The overlay companion does not have a portable path"
        )
    relative = PurePosixPath(relative_value)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise MaterializationError(
            "The overlay companion does not have a safe relative path"
        )

    destination = root.joinpath(*relative.parts)
    try:
        destination.resolve(strict=False).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise MaterializationError(
            "The overlay companion is outside the temporary directory"
        ) from exc
    return destination


def _write_overlay_file(
    root: Path,
    relative_value: str,
    payload: bytes,
    mode: int,
) -> Path:
    destination = _safe_overlay_destination(root, relative_value)

    current = root
    for part in PurePosixPath(relative_value).parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise MaterializationError(
                    "An overlay component is not a regular directory"
                )
        else:
            current.mkdir(mode=0o700)
        current.chmod(0o700)

    if destination.exists() or destination.is_symlink():
        raise MaterializationError(
            "The overlay companion already exists"
        )

    try:
        with destination.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        destination.chmod(mode)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise MaterializationError(
            f"Could not write an overlay companion: {exc}"
        ) from exc

    return destination


def _overlay_cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    root = base / "offline-game-vault-gui" / "overlays"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise MaterializationError(
            "The temporary overlay directory is not regular"
        )
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root.resolve(strict=True)


@contextmanager
def _effective_capsule(
    request: ValidatedRequest,
) -> Iterator[Path]:
    if not request.overlay_required:
        yield request.capsule_path
        return

    if request.runner is None:
        raise MaterializationError(
            "An overlay was requested without a selected runner"
        )

    try:
        derived = build_derived_capsule(
            request.capsule_path,
            request.profile_id,
            request.runner,
        )
    except RunnerOverrideError as exc:
        raise MaterializationError(str(exc)) from exc

    if not derived.changed:
        raise MaterializationError(
            "The guard requested an overlay, but the contract did not change"
        )

    with tempfile.TemporaryDirectory(
        prefix="ogv-gui-runner-",
        dir=_overlay_cache_root(),
    ) as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        capsule = directory / "capsule.json"
        with capsule.open("xb") as handle:
            handle.write(derived.serialized)
            handle.flush()
            os.fsync(handle.fileno())
        capsule.chmod(0o600)

        staged_companions: list[Path] = []
        for companion in derived.companion_files:
            staged = _write_overlay_file(
                directory,
                companion.relative_path,
                companion.payload,
                companion.mode,
            )
            if hashlib.sha256(staged.read_bytes()).hexdigest() != companion.sha256:
                raise MaterializationError(
                    "An overlay companion failed verification"
                )
            staged_companions.append(staged)

        if not staged_companions:
            raise MaterializationError(
                "The derived overlay does not include its host contract"
            )

        yield capsule


def _base_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment



def _validate_bottles_environment(
    request: ValidatedRequest,
) -> None:
    runner = request.runner
    if (
        request.bottles_path is None
        or request.bottle_name is None
        or request.deployment_path is None
        or request.bottles_backend is None
        or runner is None
    ):
        raise MaterializationError(
            "The Bottles request does not preserve backend, path, name, and runner"
        )
    try:
        environment = scan_bottles_environment()
    except BottlesEnvironmentError as exc:
        raise MaterializationError(str(exc)) from exc
    try:
        validate_shared_backend_record(
            request.collection_root,
            request.bottles_backend,
        )
    except SharedBackendError as exc:
        raise MaterializationError(str(exc)) from exc
    if (
        environment.application_ref
        != request.bottles_backend.application_ref
        or environment.application_commit
        != request.bottles_backend.application_commit
    ):
        raise MaterializationError(
            "The Bottles Flatpak installation does not match the "
            "preserved shared backend"
        )
    if environment.bottles_path != request.bottles_path:
        raise MaterializationError(
            "The managed Bottles path changed after selection"
        )
    if runner.runner_id not in environment.installed_runners:
        raise MaterializationError(
            f"Runner {runner.runner_id} is not installed in Bottles; "
            "the GUI does not download components"
        )


def _validate_bottles_deployment_payload(
    request: ValidatedRequest,
    payload: dict[str, Any],
) -> Path:
    runner = request.runner
    if (
        runner is None
        or request.bottle_name is None
        or request.deployment_path is None
    ):
        raise MaterializationError("Incomplete Bottles request")
    if (
        payload.get("complete") is not True
        or payload.get("capsule_id") != request.capsule_id
        or payload.get("profile_id") != request.profile_id
        or payload.get("bottle_name") != request.bottle_name
        or payload.get("runner") != runner.runner_id
    ):
        raise MaterializationError(
            "The Bottles deployment does not match the selection"
        )
    receipt = request.deployment_path / ".ogv-bottles-deployment.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise MaterializationError(
            "A regular .ogv-bottles-deployment.json is missing"
        )
    try:
        document = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaterializationError(
            "The Bottles deployment receipt is unreadable"
        ) from exc
    if (
        not isinstance(document, dict)
        or document.get("capsule_id") != request.capsule_id
        or document.get("profile_id") != request.profile_id
        or document.get("bottle_name") != request.bottle_name
        or document.get("runner") != runner.runner_id
        or document.get("destination") != "."
    ):
        raise MaterializationError(
            "The Bottles receipt does not match the selection"
        )
    return receipt


def _run_verify_bottles(
    request: ValidatedRequest,
    *,
    ogv: Path,
    environment: dict[str, str],
    on_log: LogCallback | None,
) -> dict[str, Any]:
    runner = request.runner
    if (
        request.bottles_path is None
        or request.bottle_name is None
        or runner is None
    ):
        raise MaterializationError("Incomplete Bottles request")
    command = build_verify_bottles_command(
        request.bottles_path,
        request.bottle_name,
        ogv=ogv,
    )
    try:
        returncode, stdout, stderr = _stream_process(
            command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise MaterializationError(
            f"Could not start verify-bottles-deployment: {exc}"
        ) from exc
    if returncode != 0:
        raise MaterializationError(
            "verify-bottles-deployment exited with code "
            f"{returncode}: {_failure_detail(stdout, stderr)}"
        )
    payload = _parse_json(stdout, label="verify-bottles-deployment")
    if (
        payload.get("verified") is not True
        or payload.get("capsule_id") != request.capsule_id
        or payload.get("profile_id") != request.profile_id
        or payload.get("bottle_name") != request.bottle_name
        or payload.get("runner") != runner.runner_id
    ):
        raise MaterializationError(
            "verify-bottles-deployment confirmed a different bottle"
        )
    return payload



def _remove_bottles_source(
    request: ValidatedRequest,
    *,
    ogv: Path,
    environment: dict[str, str],
    on_log: LogCallback | None,
) -> tuple[dict[str, Any], str, str]:
    command = build_remove_materialization_command(
        request,
        bwrap=resolve_bwrap(),
        ogv=ogv,
    )
    try:
        returncode, stdout, stderr = _stream_process(
            command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise MaterializationError(
            f"Could not remove the transient base source: {exc}"
        ) from exc
    if returncode != 0:
        raise MaterializationError(
            "remove-materialization exited with code "
            f"{returncode}: {_failure_detail(stdout, stderr)}"
        )
    payload = _parse_json(stdout, label="remove-materialization")
    if (
        payload.get("removed") is not True
        or payload.get("capsule_id") != request.capsule_id
        or payload.get("profile_id") != request.profile_id
    ):
        raise MaterializationError(
            "remove-materialization removed a different materialization"
        )
    if request.destination.exists() or request.destination.is_symlink():
        raise MaterializationError(
            "The base source remained after remove-materialization"
        )
    return payload, stdout, stderr


def _validated_bottles_control(
    request: ValidatedRequest,
) -> tuple[Path, Path, Path]:
    runner = request.runner
    backend = request.bottles_backend
    if (
        runner is None
        or backend is None
        or request.bottle_name is None
    ):
        raise MaterializationError("Incomplete Bottles request")
    result = validate_bottles_control(
        request.destination,
        capsule_id=request.capsule_id,
        profile_id=request.profile_id,
        runner=runner,
        bottle_name=request.bottle_name,
        backend=backend,
    )
    if result is None:
        raise MaterializationError(
            "The single-instance Bottles control is not verifiable"
        )
    return result


def _create_bottles_control(
    request: ValidatedRequest,
) -> tuple[Path, Path, Path]:
    runner = request.runner
    backend = request.bottles_backend
    if (
        runner is None
        or backend is None
        or request.bottle_name is None
    ):
        raise MaterializationError("Incomplete Bottles request")
    try:
        write_bottles_control(
            request.destination,
            capsule_path=request.capsule_path,
            capsule_id=request.capsule_id,
            profile_id=request.profile_id,
            runner=runner,
            bottle_name=request.bottle_name,
            backend=backend,
        )
    except (BottlesControlError, OSError) as exc:
        raise MaterializationError(
            f"Could not create the Bottles control: {exc}"
        ) from exc
    return _validated_bottles_control(request)


def _refresh_bottles_control(
    request: ValidatedRequest,
) -> tuple[Path, Path, Path]:
    runner = request.runner
    backend = request.bottles_backend
    if (
        runner is None
        or backend is None
        or request.bottle_name is None
    ):
        raise MaterializationError("Incomplete Bottles request")
    try:
        return refresh_bottles_control(
            request.destination,
            capsule_path=request.capsule_path,
            capsule_id=request.capsule_id,
            profile_id=request.profile_id,
            runner=runner,
            bottle_name=request.bottle_name,
            backend=backend,
        )
    except (BottlesControlError, OSError) as exc:
        raise MaterializationError(
            f"Could not update the Bottles control: {exc}"
        ) from exc


def _write_state_selection(
    root: Path,
    *,
    relative: Path,
    request: ValidatedRequest,
) -> Path:
    try:
        return write_selection_receipt(
            root,
            relative=relative,
            capsule_id=request.capsule_id,
            profile_id=request.profile_id,
            backend_id=request.backend_id,
            runner_id=(
                request.runner.runner_id
                if request.runner is not None
                else None
            ),
            save_set=request.save_set,
        )
    except (SelectionReceiptError, OSError) as exc:
        raise MaterializationError(
            f"Could not record the save selection: {exc}"
        ) from exc


def _restore_bottles_state(
    request: ValidatedRequest,
    prepared: PreparedStateBackup,
    *,
    ogv: Path,
    environment: dict[str, str],
    on_log: LogCallback | None,
    state_root: Path | None = None,
) -> dict[str, Any] | None:
    if prepared.backup_path is None:
        return None
    if prepared.snapshot_path is None:
        raise MaterializationError(
            "The Bottles restore operation has no temporary snapshot"
        )

    managed_deployment = state_root is not None
    if state_root is None:
        try:
            bottle_yml = find_materialized_bottle_yml(
                request.destination
            )
        except BottlesOverrideError as exc:
            raise MaterializationError(str(exc)) from exc
        effective_state_root = bottle_yml.parent
    else:
        if (
            request.deployment_path is None
            or request.bottles_path is None
        ):
            raise MaterializationError(
                "The managed restore operation has no Bottles paths"
            )
        candidate = Path(state_root)
        if candidate.is_symlink() or not candidate.is_dir():
            raise MaterializationError(
                "The managed bottle is not a regular directory"
            )
        effective_state_root = candidate.resolve(strict=True)
        if effective_state_root != request.deployment_path.resolve(
            strict=True
        ):
            raise MaterializationError(
                "The managed state root does not match the selected "
                "bottle"
            )
        try:
            effective_state_root.relative_to(
                request.bottles_path.resolve(strict=True)
            )
        except ValueError as exc:
            raise MaterializationError(
                "The managed bottle is outside the Bottles path"
            ) from exc

    command = build_restore_state_command(
        request,
        state_root=effective_state_root,
        backup=prepared.backup_path,
        snapshot=prepared.snapshot_path,
        bwrap=resolve_bwrap(),
        ogv=ogv,
    )
    _emit(
        on_log,
        (
            "Reconciling managed-bottle state: "
            if managed_deployment
            else "Applying persistent state to the Bottles source: "
        )
        + prepared.label,
        level=("WARNING" if managed_deployment else "INFO"),
    )
    try:
        returncode, stdout, stderr = _stream_process(
            command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise MaterializationError(
            f"Could not start restore-state: {exc}"
        ) from exc

    if returncode != 0:
        raise MaterializationError(
            "restore-state exited with code "
            f"{returncode}: {_failure_detail(stdout, stderr)}"
        )

    payload = _parse_json(stdout, label="restore-state")
    if (
        payload.get("complete") is not True
        or payload.get("capsule_id") != request.capsule_id
        or payload.get("rollback_performed") is not False
        or not isinstance(payload.get("restored_count"), int)
        or not isinstance(payload.get("missing_count"), int)
    ):
        raise MaterializationError(
            "restore-state did not confirm the selected state"
        )
    return payload


def _materialize_bottles(
    request: ValidatedRequest,
    prepared: PreparedStateBackup,
    on_log: LogCallback | None,
) -> MaterializationOutcome:
    runner = request.runner
    assert runner is not None
    assert request.bottles_path is not None
    assert request.bottle_name is not None
    assert request.deployment_path is not None
    assert request.bottles_backend is not None

    _validate_bottles_environment(request)
    _emit(
        on_log,
        (
            f"Bottles backend; selected runner: {runner.runner_id}. "
            "No components will be downloaded."
        ),
        level="INFO",
    )
    _emit(
        on_log,
        (
            "Single-instance mode: the final large copy will exist only "
            "in the managed bottle; the selected destination will retain "
            "launchers and the receipt."
        ),
        level="INFO",
    )
    if request.overlay_required:
        _emit(
            on_log,
            (
                f"The profile was accepted with {request.default_runner_id}; "
                f"{runner.runner_id} will be recorded as a derived variant "
                "without transferring acceptance."
            ),
            level="WARNING",
        )

    before = capture_collection_seal(
        request.collection_root,
        request.capsule_path,
    )
    environment = _base_environment()
    environment["TMPDIR"] = "/tmp"
    ogv = resolve_ogv()
    all_stdout: list[str] = []
    all_stderr: list[str] = []

    if request.reusable:
        _emit(
            on_log,
            (
                "The managed bottle already exists; it will be verified and "
                "reconciled with the current save selection."
            ),
            level="INFO",
        )
        verify_before_payload = _run_verify_bottles(
            request,
            ogv=ogv,
            environment=environment,
            on_log=on_log,
        )

        restore_payload = _restore_bottles_state(
            request,
            prepared,
            ogv=ogv,
            environment=environment,
            on_log=on_log,
            state_root=request.deployment_path,
        )
        _write_state_selection(
            request.deployment_path,
            relative=DERIVATIVE_RELATIVE,
            request=request,
        )
        verify_payload = _run_verify_bottles(
            request,
            ogv=ogv,
            environment=environment,
            on_log=on_log,
        )

        removal_payload: dict[str, Any] | None = None
        if request.control_reusable:
            _emit(
                on_log,
                "Updating the lightweight Bottles backend launcher.",
                level="INFO",
            )
            receipt, launcher, uninstaller = _refresh_bottles_control(
                request
            )
        else:
            if request.source_reusable:
                _emit(
                    on_log,
                    (
                        "Removing the duplicate base materialization after "
                        "confirming the managed bottle."
                    ),
                    level="INFO",
                )
                removal_payload, stdout, stderr = _remove_bottles_source(
                    request,
                    ogv=ogv,
                    environment=environment,
                    on_log=on_log,
                )
                all_stdout.append(stdout)
                all_stderr.append(stderr)
            elif request.destination.exists() or request.destination.is_symlink():
                raise MaterializationError(
                    "The Bottles destination exists but is neither a source nor "
                    "a recognized control"
                )
            receipt, launcher, uninstaller = _create_bottles_control(request)

        _write_state_selection(
            request.destination,
            relative=DERIVATIVE_RELATIVE,
            request=request,
        )

        after = capture_collection_seal(
            request.collection_root,
            request.capsule_path,
        )
        if after != before:
            raise MaterializationError(
                "Critical failure: a collection seal changed"
            )
        _emit(
            on_log,
            (
                "Single instance verified and reconciled: managed bottle "
                f"plus launcher {launcher.name}."
            ),
            level="INFO",
        )
        payload: dict[str, Any] = {
            "single_copy": True,
            "deployment_verification_before_state":
                verify_before_payload,
            "state_restore": restore_payload,
            "deployment_verification": verify_payload,
            "source_removal": removal_payload,
        }
        return MaterializationOutcome(
            mode="base",
            backend_id="bottles",
            runner_id=runner.runner_id,
            destination=request.destination,
            receipt_path=receipt,
            launcher_path=launcher,
            uninstaller_path=uninstaller,
            deployment_path=request.deployment_path,
            bottle_name=request.bottle_name,
            payload=payload,
            stdout="\n".join(all_stdout),
            stderr="\n".join(all_stderr),
            save_set_id=request.save_set_id,
        )

    source_present = request.source_reusable
    if not source_present:
        _emit(
            on_log,
            (
                "Creating a transient base source for the deployment "
                "Bottles."
            ),
            level="INFO",
        )
        command = build_command(
            request,
            bwrap=resolve_bwrap(),
            ogv=ogv,
        )
        try:
            returncode, stdout, stderr = _stream_process(
                command,
                environment,
                on_log,
            )
        except OSError as exc:
            raise MaterializationError(
                f"Could not start ogv materialize: {exc}"
            ) from exc
        all_stdout.append(stdout)
        all_stderr.append(stderr)
        if returncode != 0:
            raise MaterializationError(
                f"ogv materialize exited with code {returncode}: "
                f"{_failure_detail(stdout, stderr)}"
            )
        base_payload = _parse_json(stdout)
        _validate_base_result(request, base_payload)
        source_present = True
    else:
        _emit(
            on_log,
            "Reusing a recognized base materialization.",
            level="INFO",
        )

    try:
        neutral_conversion = materialize_neutral_bottle_source(
            materialization=request.destination,
            capsule_path=request.capsule_path,
            profile_id=request.profile_id,
            runner=runner,
            bottle_name=request.bottle_name,
        )
    except NeutralProfileError as exc:
        raise MaterializationError(str(exc)) from exc
    if neutral_conversion is not None:
        _emit(
            on_log,
            "Neutral object converted into a derived Bottles source.",
            level="INFO",
        )
        try:
            source_preflight = validate_neutral_bottles_source(
                materialization=request.destination,
                capsule_path=request.capsule_path,
                profile_id=request.profile_id,
            )
        except NeutralProfileError as exc:
            raise MaterializationError(
                f"Derived Bottles preflight failed: {exc}"
            ) from exc
        _emit(
            on_log,
            (
                "Derived Bottles source verified: wrapper, receipt, "
                "source_object, bottle.yml, and entrypoint are consistent."
            ),
            level="INFO",
        )
    else:
        source_preflight = None

    restore_payload = _restore_bottles_state(
        request,
        prepared,
        ogv=ogv,
        environment=environment,
        on_log=on_log,
    )

    _emit(
        on_log,
        (
            "Deploying the mutable bottle to the managed Bottles path "
            "Bottles."
        ),
        level="INFO",
    )
    try:
        with temporary_runner_override(
            request.destination,
            selected_runner=runner.runner_id,
            runner_digest=runner.digest,
            gui_version=__version__,
        ) as (_bottle_yml, original_runner, changed):
            if changed:
                _emit(
                    on_log,
                    (
                        f"Source runner {original_runner} replaced "
                        "temporarily only in the derived materialization."
                    ),
                    level="WARNING",
                )
            command = build_deploy_bottles_command(
                request,
                bwrap=resolve_bwrap(),
                ogv=ogv,
            )
            try:
                returncode, stdout, stderr = _stream_process(
                    command,
                    environment,
                    on_log,
                )
            except OSError as exc:
                raise MaterializationError(
                    f"Could not start deploy-bottles: {exc}"
                ) from exc
            all_stdout.append(stdout)
            all_stderr.append(stderr)
            if returncode != 0:
                raise MaterializationError(
                    f"deploy-bottles exited with code {returncode}: "
                    f"{_failure_detail(stdout, stderr)}"
                )
            deployment_payload = _parse_json(
                stdout,
                label="deploy-bottles",
            )
    except BottlesOverrideError as exc:
        raise MaterializationError(str(exc)) from exc

    _validate_bottles_deployment_payload(
        request,
        deployment_payload,
    )
    _write_state_selection(
        request.deployment_path,
        relative=DERIVATIVE_RELATIVE,
        request=request,
    )
    verify_payload = _run_verify_bottles(
        request,
        ogv=ogv,
        environment=environment,
        on_log=on_log,
    )

    if not source_present:
        raise MaterializationError(
            "There is no base source to remove"
        )
    _emit(
        on_log,
        (
            "Bottle verified; removing the transient base source to "
            "avoid a duplicate final copy."
        ),
        level="INFO",
    )
    removal_payload, stdout, stderr = _remove_bottles_source(
        request,
        ogv=ogv,
        environment=environment,
        on_log=on_log,
    )
    all_stdout.append(stdout)
    all_stderr.append(stderr)
    receipt, launcher, uninstaller = _create_bottles_control(request)
    _write_state_selection(
        request.destination,
        relative=DERIVATIVE_RELATIVE,
        request=request,
    )

    after = capture_collection_seal(
        request.collection_root,
        request.capsule_path,
    )
    if after != before:
        raise MaterializationError(
            "Critical failure: a collection seal changed"
        )
    _emit(
        on_log,
        (
            "Single instance created: the managed bottle contains the "
            f"data and {launcher.name} remains in the selected destination."
        ),
        level="INFO",
    )
    return MaterializationOutcome(
        mode="base",
        backend_id="bottles",
        runner_id=runner.runner_id,
        destination=request.destination,
        receipt_path=receipt,
        launcher_path=launcher,
        uninstaller_path=uninstaller,
        deployment_path=request.deployment_path,
        bottle_name=request.bottle_name,
        payload={
            "single_copy": True,
            "neutral_source_preflight": source_preflight,
            "deployment": deployment_payload,
            "deployment_verification": verify_payload,
            "state_restore": restore_payload,
            "source_removal": removal_payload,
        },
        stdout="\n".join(all_stdout),
        stderr="\n".join(all_stderr),
        save_set_id=request.save_set_id,
    )


def _materialize_windows(
    validated: ValidatedRequest,
    on_log: LogCallback | None = None,
) -> MaterializationOutcome:
    _emit(
        on_log,
        "Creating a candidate Windows export; it will not be run on Linux.",
        level="INFO",
    )
    before = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )
    command = build_command(
        validated,
        bwrap=resolve_bwrap(),
        ogv=resolve_ogv(),
    )
    environment = _base_environment()
    environment["TMPDIR"] = "/tmp"
    try:
        returncode, stdout, stderr = _stream_process(
            command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise MaterializationError(
            f"Could not start ogv materialize for Windows: {exc}"
        ) from exc
    if returncode != 0:
        raise MaterializationError(
            f"ogv materialize exited with code {returncode}: "
            f"{_failure_detail(stdout, stderr)}"
        )
    payload = _parse_json(stdout)
    _validate_base_result(validated, payload)
    try:
        export_receipt = transform_base_to_windows_export(
            materialization=validated.destination,
            capsule_path=validated.capsule_path,
            profile_id=validated.profile_id,
            capsule_id=validated.capsule_id,
            save_set=validated.save_set,
            state_backup=validated.state_backup,
        )
    except WindowsExportError as exc:
        raise MaterializationError(str(exc)) from exc

    after = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )
    if after != before:
        raise MaterializationError(
            "Critical failure: a collection seal changed"
        )
    receipt = validated.destination / "windows-export-receipt.json"
    launcher = validated.destination / "PLAY.cmd"
    installer = validated.destination / "INSTALL_STATE.ps1"
    for path, label in (
        (receipt, "receipt Windows"),
        (launcher, "launcher Windows"),
        (installer, "Windows state installer"),
    ):
        if path.is_symlink() or not path.is_file():
            raise MaterializationError(f"Missing {label} regular")
    return MaterializationOutcome(
        mode="base",
        backend_id="windows",
        runner_id=None,
        destination=validated.destination,
        receipt_path=receipt,
        launcher_path=launcher,
        uninstaller_path=None,
        deployment_path=None,
        bottle_name=None,
        payload={
            "source_materialization": payload,
            "windows_export": export_receipt,
        },
        stdout=stdout,
        stderr=stderr,
        save_set_id=validated.save_set_id,
    )

def _materialize_validated(
    validated: ValidatedRequest,
    on_log: LogCallback | None = None,
) -> MaterializationOutcome:
    operation_name = (
        "playable materialization"
        if validated.mode == "playable"
        else "materialization base"
    )
    _emit(on_log, f"Request validated: {operation_name}.", level="INFO")
    _emit(
        on_log,
        "The worker will see the collection as read-only.",
        level="INFO",
    )

    if validated.mode == "base":
        _emit(
            on_log,
            "This backend will generate neither a launcher nor an uninstaller.",
            level="WARNING",
        )
    else:
        assert validated.runner is not None
        _emit(
            on_log,
            (
                f"Direct-Wine backend; selected runner: "
                f"{validated.runner.runner_id}."
            ),
            level="INFO",
        )
        if validated.overlay_required:
            _emit(
                on_log,
                (
                    "A temporary bundle with a derived capsule.json "
                    "and verified host contract will be used. Acceptance of the runner "
                    "is not transferred."
                ),
                level="WARNING",
            )
        if validated.state_backup is not None:
            _emit(
                on_log,
                "The accepted backup declared by the capsule will be used.",
                level="INFO",
            )

    before = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )

    with _effective_capsule(validated) as capsule_path:
        state_bridge = (
            resolve_state_bridge()
            if (
                validated.overlay_required
                and validated.state_backup is not None
            )
            else None
        )
        if state_bridge is not None:
            _emit(
                on_log,
                (
                    "The accepted backup will be verified and restored against "
                    "the original capsule; the overlay defines only the runner and "
                    "playable contract."
                ),
                level="INFO",
            )
        command = build_command(
            validated,
            bwrap=resolve_bwrap(),
            ogv=resolve_ogv(),
            capsule_path=capsule_path,
            state_bridge=state_bridge,
        )
        environment = _base_environment()
        environment["TMPDIR"] = "/tmp"

        _emit(
            on_log,
            (
                "Starting ogv materialize-playable."
                if validated.mode == "playable"
                else "Starting ogv materialize."
            ),
            level="INFO",
        )

        try:
            returncode, stdout, stderr = _stream_process(
                command,
                environment,
                on_log,
            )
        except OSError as exc:
            raise MaterializationError(
                f"Could not start the worker: {exc}"
            ) from exc

    after = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )
    if after != before:
        raise MaterializationError(
            "Critical failure: a collection seal changed"
        )
    _emit(
        on_log,
        "Critical collection seals are unchanged.",
        level="INFO",
    )

    if returncode != 0:
        raise MaterializationError(
            f"ogv exited with code {returncode}: "
            f"{_failure_detail(stdout, stderr)}"
        )

    payload = _parse_json(stdout)
    if validated.mode == "playable":
        receipt, launcher, uninstaller = _validate_playable_result(
            validated,
            payload,
        )
        _write_state_selection(
            validated.destination,
            relative=DIRECT_RELATIVE,
            request=validated,
        )
        _emit(
            on_log,
            f"Verified launcher: {launcher.name}",
            level="INFO",
        )
        _emit(
            on_log,
            f"Verified uninstaller: {uninstaller.name}",
            level="INFO",
        )
    else:
        receipt, launcher, uninstaller = _validate_base_result(
            validated,
            payload,
        )
        _emit(on_log, "Base receipt verified.", level="INFO")

    return MaterializationOutcome(
        mode=validated.mode,
        backend_id=validated.backend_id,
        runner_id=(
            validated.runner.runner_id
            if validated.runner is not None
            else None
        ),
        destination=validated.destination,
        receipt_path=receipt,
        launcher_path=launcher,
        uninstaller_path=uninstaller,
        deployment_path=None,
        bottle_name=None,
        payload=payload,
        stdout=stdout,
        stderr=stderr,
        save_set_id=validated.save_set_id,
    )


def materialize(
    request: MaterializationRequest,
    on_log: LogCallback | None = None,
) -> MaterializationOutcome:
    validated = validate_request(request)
    try:
        with prepared_state_backup(validated) as prepared:
            effective = replace(
                validated,
                state_backup=prepared.backup_path,
            )
            _emit(
                on_log,
                f"Save selection: {prepared.label}.",
                level="INFO",
            )
            if effective.backend_id == "bottles":
                return _materialize_bottles(
                    effective,
                    prepared,
                    on_log,
                )
            if effective.backend_id == "windows":
                return _materialize_windows(
                    effective,
                    on_log,
                )
            return _materialize_validated(
                effective,
                on_log,
            )
    except StateSelectionError as exc:
        raise MaterializationError(str(exc)) from exc


def _validate_execution_payload(
    request: ValidatedRequest,
    payload: dict[str, Any],
) -> ExecutionOutcome:
    runner = request.runner
    if runner is None:
        raise ExecutionError("The Direct-Wine execution has no runner")

    required_ints = ("game_process_rc", "wineserver_wait_rc")
    if any(not isinstance(payload.get(key), int) for key in required_ints):
        raise ExecutionError("The execution result does not declare return codes")

    if (
        payload.get("capsule_id") != request.capsule_id
        or payload.get("profile_id") != request.profile_id
        or payload.get("backend") != "wine"
        or payload.get("destination") != str(request.destination)
    ):
        raise ExecutionError(
            "The execution result does not match the selection"
        )

    complete = payload.get("complete")
    if not isinstance(complete, bool):
        raise ExecutionError("The execution result does not declare complete")

    return ExecutionOutcome(
        backend_id="direct-wine",
        runner_id=runner.runner_id,
        destination=request.destination,
        game_process_rc=payload["game_process_rc"],
        wineserver_wait_rc=payload["wineserver_wait_rc"],
        complete=complete,
        payload=payload,
        stdout="",
        stderr="",
        save_set_id=request.save_set_id,
    )



def _execute_bottles(
    request: ValidatedRequest,
    on_log: LogCallback | None,
) -> ExecutionOutcome:
    runner = request.runner
    if (
        runner is None
        or request.bottles_path is None
        or request.bottle_name is None
        or request.deployment_path is None
    ):
        raise ExecutionError("The Bottles request is incomplete")
    if not request.reusable:
        raise ExecutionError(
            "A recognized managed bottle must exist first"
        )

    try:
        _validate_bottles_environment(request)
    except MaterializationError as exc:
        raise ExecutionError(str(exc)) from exc

    before = capture_collection_seal(
        request.collection_root,
        request.capsule_path,
    )
    ogv = resolve_ogv()
    environment = _base_environment()

    _emit(
        on_log,
        (
            f"Verifying bottle {request.bottle_name} before "
            f"running with {runner.runner_id}."
        ),
        level="INFO",
    )
    try:
        _run_verify_bottles(
            request,
            ogv=ogv,
            environment=environment,
            on_log=on_log,
        )
    except MaterializationError as exc:
        raise ExecutionError(str(exc)) from exc

    _emit(
        on_log,
        (
            "Starting ogv run-bottles outside the materialization sandbox "
            "to preserve display, audio, and controller access."
        ),
        level="INFO",
    )
    command = build_run_bottles_command(
        request.bottles_path,
        request.bottle_name,
        ogv=ogv,
    )
    try:
        returncode, stdout, stderr = _stream_process(
            command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise ExecutionError(
            f"Could not start run-bottles: {exc}"
        ) from exc

    try:
        payload = _parse_json(stdout, label="run-bottles")
    except MaterializationError as exc:
        raise ExecutionError(str(exc)) from exc

    game_returncode = payload.get("returncode")
    if not isinstance(game_returncode, int):
        raise ExecutionError(
            "run-bottles did not declare the game return code"
        )
    if (
        payload.get("capsule_id") != request.capsule_id
        or payload.get("profile_id") != request.profile_id
        or payload.get("bottle_name") != request.bottle_name
    ):
        raise ExecutionError("run-bottles executed a different bottle")

    try:
        _run_verify_bottles(
            request,
            ogv=ogv,
            environment=environment,
            on_log=on_log,
        )
    except MaterializationError as exc:
        raise ExecutionError(
            f"The bottle was no longer verifiable after execution: {exc}"
        ) from exc

    after = capture_collection_seal(
        request.collection_root,
        request.capsule_path,
    )
    if after != before:
        raise ExecutionError(
            "Critical failure: execution changed a collection seal"
        )

    complete = returncode == 0 and game_returncode == 0
    outcome = ExecutionOutcome(
        backend_id="bottles",
        runner_id=runner.runner_id,
        destination=request.deployment_path,
        game_process_rc=game_returncode,
        wineserver_wait_rc=None,
        complete=complete,
        payload=payload,
        stdout=stdout,
        stderr=stderr,
        save_set_id=request.save_set_id,
    )
    if not complete:
        raise ExecutionError(
            f"run-bottles exited with code {returncode}: "
            f"{_failure_detail(stdout, stderr)}"
        )

    _emit(
        on_log,
        (
            "Bottles execution finished; deployment verified and collection "
            "seals unchanged."
        ),
        level="INFO",
    )
    return outcome

def execute(
    request: MaterializationRequest,
    on_log: LogCallback | None = None,
) -> ExecutionOutcome:
    validated = validate_request(request)
    if validated.backend_id == "bottles":
        return _execute_bottles(validated, on_log)
    if (
        validated.backend_id != "direct-wine"
        or validated.mode != "playable"
        or validated.runner is None
    ):
        raise ExecutionError(
            "Execution is available only for Direct-Wine"
        )
    if not validated.reusable:
        raise ExecutionError(
            "A recognized materialization must exist first"
        )

    before = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )
    ogv = resolve_ogv()
    environment = _base_environment()

    _emit(
        on_log,
        (
            f"Verifying materialization before running with "
            f"{validated.runner.runner_id}."
        ),
        level="INFO",
    )
    verify_command = build_verify_playable_command(
        validated.destination,
        ogv=ogv,
    )
    try:
        verify_rc, verify_stdout, verify_stderr = _stream_process(
            verify_command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise ExecutionError(
            f"Could not start verify-playable: {exc}"
        ) from exc

    if verify_rc != 0:
        raise ExecutionError(
            f"verify-playable exited with code {verify_rc}: "
            f"{_failure_detail(verify_stdout, verify_stderr)}"
        )
    try:
        verify_payload = _parse_json(
            verify_stdout,
            label="verify-playable",
        )
    except MaterializationError as exc:
        raise ExecutionError(str(exc)) from exc
    if verify_payload.get("verified") is not True:
        raise ExecutionError(
            "verify-playable did not confirm the materialization"
        )
    if (
        verify_payload.get("capsule_id") != validated.capsule_id
        or verify_payload.get("profile_id") != validated.profile_id
        or verify_payload.get("backend") != "wine"
        or verify_payload.get("destination") != str(validated.destination)
    ):
        raise ExecutionError(
            "verify-playable confirmed a different materialization"
        )

    _emit(
        on_log,
        (
            "Starting ogv run-playable outside the "
            "materialization sandbox to preserve display, audio, and controller access."
        ),
        level="INFO",
    )
    run_command = build_run_playable_command(
        validated.destination,
        ogv=ogv,
    )
    try:
        run_rc, stdout, stderr = _stream_process(
            run_command,
            environment,
            on_log,
        )
    except OSError as exc:
        raise ExecutionError(
            f"Could not start run-playable: {exc}"
        ) from exc

    after = capture_collection_seal(
        validated.collection_root,
        validated.capsule_path,
    )
    if after != before:
        raise ExecutionError(
            "Critical failure: execution changed a collection seal"
        )

    try:
        payload = _parse_json(stdout, label="run-playable")
    except MaterializationError as exc:
        raise ExecutionError(str(exc)) from exc

    outcome = _validate_execution_payload(validated, payload)
    outcome = ExecutionOutcome(
        backend_id=outcome.backend_id,
        runner_id=outcome.runner_id,
        destination=outcome.destination,
        game_process_rc=outcome.game_process_rc,
        wineserver_wait_rc=outcome.wineserver_wait_rc,
        complete=outcome.complete,
        payload=payload,
        stdout=stdout,
        stderr=stderr,
    )

    if run_rc != 0 or not outcome.complete:
        raise ExecutionError(
            f"run-playable exited with code {run_rc}: "
            f"{_failure_detail(stdout, stderr)}"
        )

    _emit(
        on_log,
        "Execution finished; collection seals are unchanged.",
        level="INFO",
    )
    return outcome
