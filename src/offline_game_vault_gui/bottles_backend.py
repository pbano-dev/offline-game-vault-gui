from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from typing import Any, Iterator


class BottlesEnvironmentError(RuntimeError):
    pass


class BottlesOverrideError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BottlesEnvironment:
    bottles_path: Path
    installed_runners: frozenset[str]
    flatpak: Path
    application_ref: str
    application_commit: str
    warnings: tuple[str, ...] = ()


_SAFE_RUNNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OVERRIDE_BACKUP = ".ogv-gui-bottle-yml.backup"
_OVERRIDE_JOURNAL = ".ogv-gui-bottles-runner-override.json"
_OVERRIDE_EVIDENCE = ".ogv-gui-runner-selection.json"


def _resolve_flatpak() -> Path:
    configured = os.environ.get("OGV_FLATPAK")
    candidate = configured or shutil.which("flatpak")
    if not candidate:
        raise BottlesEnvironmentError("flatpak was not found")
    path = Path(candidate).expanduser()
    if path.is_symlink():
        path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise BottlesEnvironmentError(f"flatpak is not executable: {path}")
    return path.resolve(strict=True)


def _run_text(command: list[str], label: str) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
    except OSError as exc:
        raise BottlesEnvironmentError(
            f"Could not query {label}: {exc}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise BottlesEnvironmentError(
            f"{label} exited with code {result.returncode}: "
            f"{detail or 'no details'}"
        )
    return result.stdout


def _decode_json_output(stdout: str, label: str) -> Any:
    candidates = [stdout.strip()]
    candidates.extend(
        line.strip()
        for line in reversed(stdout.splitlines())
        if line.strip()
    )
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise BottlesEnvironmentError(
        f"{label} did not return usable JSON"
    )


def _run_json(command: list[str], label: str) -> Any:
    return _decode_json_output(_run_text(command, label), label)


def _absolute_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str) and Path(value).is_absolute():
        found.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            found.extend(_absolute_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_absolute_strings(nested))
    return found


def _runner_strings(value: Any) -> set[str]:
    if isinstance(value, dict) and isinstance(value.get("runners"), list):
        values = value["runners"]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return {
        item
        for item in values
        if isinstance(item, str) and _SAFE_RUNNER.fullmatch(item)
    }


def _flatpak_identity(flatpak: Path) -> tuple[str, str]:
    application_ref = _run_text(
        [
            str(flatpak),
            "info",
            "--show-ref",
            "com.usebottles.bottles",
        ],
        "flatpak info --show-ref com.usebottles.bottles",
    ).strip()
    application_commit = _run_text(
        [
            str(flatpak),
            "info",
            "--show-commit",
            "com.usebottles.bottles",
        ],
        "flatpak info --show-commit com.usebottles.bottles",
    ).strip()
    if not application_ref.startswith(
        "app/com.usebottles.bottles/"
    ):
        raise BottlesEnvironmentError(
            "The Bottles Flatpak reference is not recognized"
        )
    if len(application_commit) != 64 or any(
        char not in "0123456789abcdef"
        for char in application_commit
    ):
        raise BottlesEnvironmentError(
            "The Bottles Flatpak commit is not hexadecimal SHA-256"
        )
    return application_ref, application_commit


def _default_bottles_path() -> Path:
    return (
        Path.home()
        / ".var/app/com.usebottles.bottles/data/bottles/bottles"
    )


def _filesystem_runners(bottles_path: Path) -> set[str]:
    components_root = bottles_path.parent
    runners_root = components_root / "runners"
    if runners_root.is_symlink() or not runners_root.is_dir():
        return set()
    found: set[str] = set()
    for entry in runners_root.iterdir():
        if (
            not entry.is_symlink()
            and entry.is_dir()
            and _SAFE_RUNNER.fullmatch(entry.name)
        ):
            found.add(entry.name)
    return found


def scan_bottles_environment() -> BottlesEnvironment:
    """Resolve the active Bottles path, Flatpak identity and runners.

    The lookup is read-only. It never downloads or installs components.
    """

    flatpak = _resolve_flatpak()
    application_ref, application_commit = _flatpak_identity(flatpak)
    warnings: list[str] = []

    configured = os.environ.get("OGV_BOTTLES_PATH")
    if configured:
        bottles_path = Path(configured).expanduser()
    else:
        try:
            payload = _run_json(
                [
                    str(flatpak),
                    "run",
                    "--command=bottles-cli",
                    "com.usebottles.bottles",
                    "--json",
                    "info",
                    "bottles-path",
                ],
                "bottles-cli info bottles-path",
            )
            paths = list(dict.fromkeys(_absolute_strings(payload)))
            if len(paths) != 1:
                raise BottlesEnvironmentError(
                    "bottles-cli did not return exactly one managed path"
                )
            bottles_path = Path(paths[0])
        except BottlesEnvironmentError as exc:
            fallback = _default_bottles_path()
            if fallback.is_symlink() or not fallback.is_dir():
                raise
            bottles_path = fallback
            warnings.append(
                "The Bottles path was resolved using the default Flatpak "
                f"location because bottles-cli was unusable: {exc}"
            )

    if bottles_path.is_symlink() or not bottles_path.is_dir():
        raise BottlesEnvironmentError(
            "The managed Bottles path is not a regular directory"
        )
    bottles_path = bottles_path.resolve(strict=True)
    if not os.access(bottles_path, os.W_OK | os.X_OK):
        raise BottlesEnvironmentError(
            "The managed Bottles path is not writable"
        )

    runners = _filesystem_runners(bottles_path)
    try:
        components = _run_json(
            [
                str(flatpak),
                "run",
                "--command=bottles-cli",
                "com.usebottles.bottles",
                "--json",
                "list",
                "components",
                "-f",
                "category:runners",
            ],
            "bottles-cli list components",
        )
        runners.update(_runner_strings(components))
    except BottlesEnvironmentError as exc:
        warnings.append(
            "The runner inventory was read from the real tree because "
            f"bottles-cli was unusable: {exc}"
        )

    if not runners:
        raise BottlesEnvironmentError(
            "Bottles contains no verifiable installed runner"
        )

    return BottlesEnvironment(
        bottles_path=bottles_path,
        installed_runners=frozenset(runners),
        flatpak=flatpak,
        application_ref=application_ref,
        application_commit=application_commit,
        warnings=tuple(warnings),
    )

def _safe_relative(value: str, label: str) -> PurePosixPath:
    if not value or "\x00" in value or "\\" in value:
        raise BottlesOverrideError(f"{label} is not a safe relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BottlesOverrideError(f"{label} is not a safe relative path")
    return path


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _atomic_write(
    path: Path,
    payload: bytes,
    mode: int | None = None,
) -> None:
    if mode is None:
        try:
            mode = path.stat(follow_symlinks=False).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o600
    temporary = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{os.urandom(6).hex()}"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _parse_top_runner(text: str) -> tuple[str, int]:
    matches: list[tuple[str, int]] = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.rstrip("\r\n")
        if not stripped or stripped[0].isspace() or ":" not in stripped:
            continue
        key, raw = stripped.split(":", 1)
        if key != "Runner":
            continue
        value = raw.strip()
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise BottlesOverrideError(
                    "The bottle.yml Runner value is not a valid YAML string"
                ) from exc
            if not isinstance(parsed, str):
                raise BottlesOverrideError(
                    "The bottle.yml Runner value is not a string"
                )
            runner = parsed
        elif value.startswith("'") and value.endswith("'"):
            runner = value[1:-1].replace("''", "'")
        else:
            if " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            runner = value
        matches.append((runner, index))
    if len(matches) != 1 or not matches[0][0]:
        raise BottlesOverrideError(
            "bottle.yml must declare exactly one top-level Runner"
        )
    return matches[0]


def _replace_top_runner(text: str, selected_runner: str) -> tuple[str, str]:
    if not _SAFE_RUNNER.fullmatch(selected_runner):
        raise BottlesOverrideError("The selected runner identifier is not portable")
    original_runner, target_index = _parse_top_runner(text)
    lines = text.splitlines(keepends=True)
    ending = ""
    if lines[target_index].endswith("\r\n"):
        ending = "\r\n"
    elif lines[target_index].endswith("\n"):
        ending = "\n"
    lines[target_index] = (
        "Runner: " + json.dumps(selected_runner, ensure_ascii=False) + ending
    )
    return "".join(lines), original_runner


def find_materialized_bottle_yml(materialization: Path) -> Path:
    root = Path(materialization)
    if root.is_symlink() or not root.is_dir():
        raise BottlesOverrideError(
            "The Bottles materialization is not a regular directory"
        )
    root = root.resolve(strict=True)
    objects = root / "objects"
    if objects.is_symlink() or not objects.is_dir():
        raise BottlesOverrideError(
            "The Bottles materialization does not contain a regular objects directory"
        )

    candidates: list[Path] = []
    stack = [objects]
    while stack:
        directory = stack.pop()
        for entry in os.scandir(directory):
            path = Path(entry.path)
            info = entry.stat(follow_symlinks=False)
            if path.name == "bottle.yml":
                if not path.is_file() or path.is_symlink():
                    raise BottlesOverrideError(
                        "bottle.yml must be a regular file"
                    )
                candidates.append(path)
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
    if len(candidates) != 1:
        raise BottlesOverrideError(
            "Expected exactly one bottle.yml in the materialization; "
            f"found {len(candidates)}"
        )
    candidate = candidates[0].resolve(strict=True)
    if not _is_within(candidate, root):
        raise BottlesOverrideError("bottle.yml escapes the materialization")
    return candidate


def _cleanup_override_files(root: Path, bottle_yml: Path) -> None:
    evidence = bottle_yml.parent / _OVERRIDE_EVIDENCE
    evidence.unlink(missing_ok=True)
    (root / _OVERRIDE_JOURNAL).unlink(missing_ok=True)
    (root / _OVERRIDE_BACKUP).unlink(missing_ok=True)


def recover_interrupted_runner_override(materialization: Path) -> bool:
    root = Path(materialization)
    journal_path = root / _OVERRIDE_JOURNAL
    backup_path = root / _OVERRIDE_BACKUP
    if not journal_path.exists() and not backup_path.exists():
        return False
    if (
        journal_path.is_symlink()
        or backup_path.is_symlink()
        or not journal_path.is_file()
        or not backup_path.is_file()
    ):
        raise BottlesOverrideError(
            "An incomplete Bottles override exists and cannot be recovered"
        )
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BottlesOverrideError(
            "The Bottles override journal is unreadable"
        ) from exc
    if not isinstance(journal, dict):
        raise BottlesOverrideError("The Bottles journal is not a JSON object")
    relative = _safe_relative(
        journal.get("bottle_yml", ""),
        "journal.bottle_yml",
    )
    root_resolved = root.resolve(strict=True)
    bottle_yml = root.joinpath(*relative.parts)
    try:
        bottle_yml.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise BottlesOverrideError(
            "The Bottles journal points outside the materialization"
        ) from exc
    original = backup_path.read_bytes()
    if hashlib.sha256(original).hexdigest() != journal.get("original_sha256"):
        raise BottlesOverrideError(
            "The bottle.yml recovery copy does not match the journal"
        )
    _atomic_write(bottle_yml, original)
    _cleanup_override_files(root, bottle_yml)
    return True


@contextmanager
def temporary_runner_override(
    materialization: Path,
    *,
    selected_runner: str,
    runner_digest: str,
    gui_version: str,
) -> Iterator[tuple[Path, str, bool]]:
    """Temporarily set Runner in the derived source bottle.

    The immutable vault is never touched. The source materialization is restored
    in ``finally`` and a durable journal allows recovery after interruption.
    """

    root = Path(materialization)
    if root.is_symlink() or not root.is_dir():
        raise BottlesOverrideError(
            "The Bottles materialization is not a regular directory"
        )
    root = root.resolve(strict=True)
    recover_interrupted_runner_override(root)
    bottle_yml = find_materialized_bottle_yml(root)
    original = bottle_yml.read_bytes()
    try:
        text = original.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BottlesOverrideError("bottle.yml is not valid UTF-8") from exc
    rewritten, original_runner = _replace_top_runner(text, selected_runner)
    if original_runner == selected_runner:
        yield bottle_yml, original_runner, False
        return

    backup_path = root / _OVERRIDE_BACKUP
    journal_path = root / _OVERRIDE_JOURNAL
    evidence_path = bottle_yml.parent / _OVERRIDE_EVIDENCE
    if any(
        path.exists() or path.is_symlink()
        for path in (backup_path, journal_path, evidence_path)
    ):
        raise BottlesOverrideError(
            "Evidence or temporary state from another Bottles override already exists"
        )

    original_sha = hashlib.sha256(original).hexdigest()
    relative_bottle = bottle_yml.relative_to(root).as_posix()
    journal = {
        "schema": 0,
        "operation": "temporary-bottles-runner-override",
        "bottle_yml": relative_bottle,
        "original_sha256": original_sha,
        "original_runner": original_runner,
        "selected_runner": selected_runner,
    }
    evidence = {
        "schema": 0,
        "operation": "bottles-runner-selection",
        "original_runner": original_runner,
        "selected_runner": selected_runner,
        "runner_digest": runner_digest,
        "acceptance_transferred": False,
        "generated_by": f"offline-game-vault-gui-{gui_version}",
    }

    try:
        _atomic_write(backup_path, original)
        _atomic_write(
            journal_path,
            (
                json.dumps(
                    journal,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        _atomic_write(
            evidence_path,
            (
                json.dumps(
                    evidence,
                    indent=2,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
        )
        _atomic_write(bottle_yml, rewritten.encode("utf-8"))
        yield bottle_yml, original_runner, True
    finally:
        try:
            _atomic_write(bottle_yml, original)
        except OSError as exc:
            raise BottlesOverrideError(
                "Could not restore the materialization after the "
                "Bottles override; the journal and recovery copy were preserved: "
                f"{exc}"
            ) from exc
        try:
            _cleanup_override_files(root, bottle_yml)
        except OSError as exc:
            raise BottlesOverrideError(
                "The source was restored, but not all "
                f"temporary Bottles state could be removed: {exc}"
            ) from exc
