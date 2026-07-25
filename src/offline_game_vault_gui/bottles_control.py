from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import Any

from . import __version__
from .model import RunnerRecord
from .shared_backend import SharedBackendRecord


CONTROL_RECEIPT_NAME = ".ogv-bottles-control.json"
_SAFE_SCRIPT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.sh$")


class BottlesControlError(RuntimeError):
    pass


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise BottlesControlError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BottlesControlError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BottlesControlError(f"{label} does not contain a JSON object")
    return value


def _script_names(capsule_path: Path) -> tuple[str, str]:
    capsule = _load_json(Path(capsule_path), "capsule.json")
    profiles = capsule.get("profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            playable = profile.get("playable")
            if not isinstance(playable, dict):
                continue
            paths = playable.get("paths")
            if not isinstance(paths, dict):
                continue
            launcher = paths.get("launcher")
            uninstaller = paths.get("uninstaller")
            if (
                isinstance(launcher, str)
                and isinstance(uninstaller, str)
                and _SAFE_SCRIPT.fullmatch(Path(launcher).name)
                and _SAFE_SCRIPT.fullmatch(Path(uninstaller).name)
            ):
                return Path(launcher).name, Path(uninstaller).name

    title = ""
    game = capsule.get("game")
    if isinstance(game, dict) and isinstance(game.get("title"), str):
        title = game["title"]
    if not title:
        title = str(capsule.get("capsule_id", "game"))
    slug = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_") or "game"
    return f"play_{slug}.sh", f"uninstall_{slug}.sh"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


_PATH_PARSER = "\n".join(
    [
        "\"$python_bin\" -c '",
        "import json",
        "import sys",
        "from pathlib import Path",
        "",
        "raw = sys.stdin.read()",
        "paths = []",
        "",
        "def add_path(value):",
        "    if not isinstance(value, str):",
        "        return",
        "    candidate = value.strip()",
        "    if candidate and Path(candidate).is_absolute():",
        "        paths.append(candidate)",
        "",
        "def walk(value):",
        "    if isinstance(value, str):",
        "        add_path(value)",
        "    elif isinstance(value, dict):",
        "        for item in value.values():",
        "            walk(item)",
        "    elif isinstance(value, list):",
        "        for item in value:",
        "            walk(item)",
        "",
        "candidates = [raw.strip()]",
        "candidates.extend(",
        "    line.strip() for line in raw.splitlines() if line.strip()",
        ")",
        "",
        "seen = set()",
        "for candidate in candidates:",
        "    if candidate in seen:",
        "        continue",
        "    seen.add(candidate)",
        "    try:",
        "        walk(json.loads(candidate))",
        "    except json.JSONDecodeError:",
        "        add_path(candidate)",
        "",
        "unique = list(dict.fromkeys(paths))",
        "if len(unique) != 1:",
        "    raise SystemExit(",
        "        \"ERROR: bottles-cli did not return exactly one usable path\"",
        "    )",
        "print(unique[0])",
        "'",
    ]
)


def _launcher_text(
    *,
    bottle_name: str,
    runner_id: str,
    backend: SharedBackendRecord,
) -> str:
    app_id = backend.application_ref.split("/", 2)[1]
    return f"""#!/usr/bin/env bash
set -euo pipefail

die() {{
  printf 'ERROR: %s\\n' "$*" >&2
  exit 2
}}

flatpak_bin="${{FLATPAK_EXECUTABLE:-}}"
if [[ -z "$flatpak_bin" ]]; then
  flatpak_bin="$(command -v flatpak || true)"
fi
[[ -n "$flatpak_bin" && -x "$flatpak_bin" ]] || \
  die 'No usable flatpak executable was found.'

python_bin="${{PYTHON_EXECUTABLE:-}}"
if [[ -z "$python_bin" ]]; then
  python_bin="$(command -v python3 || true)"
fi
[[ -n "$python_bin" && -x "$python_bin" ]] || \
  die 'python3 was not found; it is required to verify the deployment.'

app_id={_shell_quote(app_id)}
expected_ref={_shell_quote(backend.application_ref)}
expected_commit={_shell_quote(backend.application_commit)}
expected_runner={_shell_quote(runner_id)}
bottle_name={_shell_quote(bottle_name)}

if ! actual_ref="$("$flatpak_bin" info --show-ref "$app_id" 2>&1)"; then
  die "Could not query the Bottles Flatpak reference: $actual_ref"
fi
if ! actual_commit="$("$flatpak_bin" info --show-commit "$app_id" 2>&1)"; then
  die "Could not query the Bottles Flatpak commit: $actual_commit"
fi

[[ "$actual_ref" == "$expected_ref" ]] || \
  die "Unexpected Flatpak reference: $actual_ref"
[[ "$actual_commit" == "$expected_commit" ]] || \
  die "Unexpected Flatpak commit: $actual_commit"

if ! raw_path="$("$flatpak_bin" run --command=bottles-cli "$app_id" \
  --json info bottles-path 2>&1)"; then
  die "Could not obtain bottles-path: $raw_path"
fi

if ! bottles_path="$(printf '%s\\n' "$raw_path" | {_PATH_PARSER})"; then
  exit 2
fi

deployment="$bottles_path/$bottle_name"
[[ -d "$deployment" && ! -L "$deployment" ]] || \
  die "The expected managed bottle does not exist: $deployment"

exec "$python_bin" - \
  "$flatpak_bin" \
  "$app_id" \
  "$deployment" \
  "$bottle_name" \
  "$expected_runner" <<'PY'
import json
import os
from pathlib import Path, PurePosixPath
import sys


def fail(message):
    raise SystemExit(f"ERROR: {{message}}")


flatpak, app_id, deployment_raw, bottle_name, expected_runner = sys.argv[1:]
deployment = Path(deployment_raw)

receipt_path = deployment / ".ogv-bottles-deployment.json"
bottle_yml = deployment / "bottle.yml"

if receipt_path.is_symlink() or not receipt_path.is_file():
    fail("missing Bottles deployment receipt")
if bottle_yml.is_symlink() or not bottle_yml.is_file():
    fail("missing bottle.yml")

try:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    fail(f"invalid deployment receipt: {{exc}}")

if not isinstance(receipt, dict):
    fail("deployment receipt is not a JSON object")

expected = {{
    "schema": 0,
    "adapter": "bottles-flatpak",
    "bottle_name": bottle_name,
    "destination": ".",
    "runner": expected_runner,
}}
for key, value in expected.items():
    if receipt.get(key) != value:
        fail(f"unexpected receipt field: {{key}}")

launch = receipt.get("launch")
if not isinstance(launch, dict):
    fail("launch is not an object")

entrypoint = launch.get("entrypoint")
if (
    not isinstance(entrypoint, str)
    or not entrypoint
    or chr(0) in entrypoint
    or "\\\\" in entrypoint
):
    fail("invalid entrypoint")

relative = PurePosixPath(entrypoint)
if relative.is_absolute() or any(
    part in {{"", ".", ".."}} for part in relative.parts
):
    fail("entrypoint is not a safe relative path")

network = launch.get("network")
if network not in {{"isolated", "host_default"}}:
    fail("invalid network policy")

arguments = launch.get("arguments", [])
if not isinstance(arguments, list) or not all(
    isinstance(item, str) for item in arguments
):
    fail("invalid launch arguments")

try:
    lines = bottle_yml.read_text(
        encoding="utf-8",
        errors="strict",
    ).splitlines()
except (OSError, UnicodeError) as exc:
    fail(f"could not read bottle.yml: {{exc}}")

wanted = {{"Name", "Path", "Custom_Path", "Runner"}}
fields = {{key: [] for key in wanted}}

for line in lines:
    if not line or line[0].isspace() or ":" not in line:
        continue
    key, raw = line.split(":", 1)
    if key not in wanted:
        continue
    value = raw.strip()
    if value in {{"true", "True"}}:
        parsed = True
    elif value in {{"false", "False"}}:
        parsed = False
    elif value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            fail(f"invalid YAML value for {{key}}")
    elif value.startswith("'") and value.endswith("'"):
        parsed = value[1:-1].replace("''", "'")
    else:
        parsed = value.split(" #", 1)[0].rstrip()
    fields[key].append(parsed)

for key, values in fields.items():
    if len(values) != 1:
        fail(f"bottle.yml must declare exactly one {{key}}")

if fields["Name"][0] != bottle_name:
    fail("Name does not match the bottle")
if fields["Path"][0] != bottle_name:
    fail("Path does not match the bottle")
if fields["Custom_Path"][0] is not False:
    fail("Custom_Path must be false")
if fields["Runner"][0] != expected_runner:
    fail("Runner does not match the lightweight control")

executable = deployment.joinpath(*relative.parts)
if executable.is_symlink() or not executable.is_file():
    fail("the entrypoint executable does not exist or is a symbolic link")

command = [flatpak, "run"]
if network == "isolated":
    command.append("--unshare=network")
command.extend(
    [
        "--command=bottles-cli",
        app_id,
        "run",
        "-b",
        bottle_name,
        "-e",
        str(executable),
    ]
)
if arguments:
    command.append("--")
    command.extend(arguments)

os.execv(flatpak, command)
PY
"""


def _uninstaller_text(
    *,
    bottle_name: str,
    backend: SharedBackendRecord,
) -> str:
    app_id = backend.application_ref.split("/", 2)[1]
    return f"""#!/usr/bin/env bash
set -euo pipefail

die() {{
  printf 'ERROR: %s\\n' "$*" >&2
  exit 2
}}

if [[ "$#" -eq 0 ]]; then
  printf '%s\\n' \
    'Usage: this script requires the explicit ogv confirmations.' \
    'Example after preserving state and stopping Bottles/Wine:' \
    '  ./uninstall_*.sh --confirm-state-preserved --confirm-stopped'
  exit 2
fi

flatpak_bin="${{FLATPAK_EXECUTABLE:-}}"
if [[ -z "$flatpak_bin" ]]; then
  flatpak_bin="$(command -v flatpak || true)"
fi
[[ -n "$flatpak_bin" && -x "$flatpak_bin" ]] || \
  die 'No usable flatpak executable was found.'

python_bin="${{PYTHON_EXECUTABLE:-}}"
if [[ -z "$python_bin" ]]; then
  python_bin="$(command -v python3 || true)"
fi
[[ -n "$python_bin" && -x "$python_bin" ]] || \
  die 'python3 was not found; it is required to resolve bottles-path.'

ogv_bin="${{OGV_EXECUTABLE:-}}"
if [[ -z "$ogv_bin" ]]; then
  ogv_bin="$(command -v ogv || true)"
fi
[[ -n "$ogv_bin" && -x "$ogv_bin" ]] || \
  die 'ogv was not found. Set OGV_EXECUTABLE or remove the bottle from the GUI.'

app_id={_shell_quote(app_id)}
expected_ref={_shell_quote(backend.application_ref)}
expected_commit={_shell_quote(backend.application_commit)}
bottle_name={_shell_quote(bottle_name)}

if ! actual_ref="$("$flatpak_bin" info --show-ref "$app_id" 2>&1)"; then
  die "Could not query the Bottles Flatpak reference: $actual_ref"
fi
if ! actual_commit="$("$flatpak_bin" info --show-commit "$app_id" 2>&1)"; then
  die "Could not query the Bottles Flatpak commit: $actual_commit"
fi

[[ "$actual_ref" == "$expected_ref" ]] || \
  die "Unexpected Flatpak reference: $actual_ref"
[[ "$actual_commit" == "$expected_commit" ]] || \
  die "Unexpected Flatpak commit: $actual_commit"

if ! raw_path="$("$flatpak_bin" run --command=bottles-cli "$app_id" \
  --json info bottles-path 2>&1)"; then
  die "Could not obtain bottles-path: $raw_path"
fi

if ! bottles_path="$(printf '%s\\n' "$raw_path" | {_PATH_PARSER})"; then
  exit 2
fi

exec "$ogv_bin" remove-bottles-deployment \
  --bottles-path "$bottles_path" \
  --name "$bottle_name" \
  "$@"
"""


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def write_bottles_control(
    destination: Path,
    *,
    capsule_path: Path,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
    bottle_name: str,
    backend: SharedBackendRecord,
) -> tuple[Path, Path, Path]:
    """Create a lightweight control directory for one managed bottle."""

    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise BottlesControlError(
            "The Bottles control destination already exists"
        )
    parent = destination.parent
    if parent.is_symlink() or not parent.is_dir():
        raise BottlesControlError(
            "The Bottles control parent directory is not regular"
        )

    launcher_name, uninstaller_name = _script_names(capsule_path)
    staging = parent / (
        f".{destination.name}.ogv-control-{os.getpid()}-{secrets.token_hex(6)}"
    )
    try:
        staging.mkdir(mode=0o700)
        launcher = staging / launcher_name
        uninstaller = staging / uninstaller_name
        launcher.write_text(
            _launcher_text(
                bottle_name=bottle_name,
                runner_id=runner.runner_id,
                backend=backend,
            ),
            encoding="utf-8",
            newline="\n",
        )
        uninstaller.write_text(
            _uninstaller_text(bottle_name=bottle_name, backend=backend),
            encoding="utf-8",
            newline="\n",
        )
        launcher.chmod(0o755)
        uninstaller.chmod(0o755)

        receipt = staging / CONTROL_RECEIPT_NAME
        document = {
            "schema": 0,
            "operation": "bottles-single-copy-control",
            "generated_by": f"offline-game-vault-gui-{__version__}",
            "capsule_id": capsule_id,
            "profile_id": profile_id,
            "backend": "bottles",
            "runner": runner.runner_id,
            "runner_digest": runner.digest,
            "bottle_name": bottle_name,
            "deployment": "bottles-managed",
            "bottles_path_resolution": "bottles-cli-json-or-plain",
            "launcher_protocol": "direct-bottles-cli-v1",
            "uninstaller_protocol": "ogv-remove-bottles-deployment-v1",
            "application_ref": backend.application_ref,
            "application_commit": backend.application_commit,
            "launcher": launcher_name,
            "launcher_sha256": _sha256(launcher),
            "uninstaller": uninstaller_name,
            "uninstaller_sha256": _sha256(uninstaller),
            "complete": True,
        }
        receipt.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        receipt.chmod(0o644)

        for path in (launcher, uninstaller, receipt):
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        directory_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        os.rename(staging, destination)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return (
        destination / CONTROL_RECEIPT_NAME,
        destination / launcher_name,
        destination / uninstaller_name,
    )



def _atomic_replace_text(path: Path, text: str, mode: int) -> None:
    temporary = path.with_name(
        f".{path.name}.refresh-{os.getpid()}-{secrets.token_hex(6)}"
    )
    try:
        with temporary.open(
            "x",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def refresh_bottles_control(
    destination: Path,
    *,
    capsule_path: Path,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
    bottle_name: str,
    backend: SharedBackendRecord,
) -> tuple[Path, Path, Path]:
    """Refresh scripts in one already recognized lightweight control."""

    destination = Path(destination)
    current = validate_bottles_control(
        destination,
        capsule_id=capsule_id,
        profile_id=profile_id,
        runner=runner,
        bottle_name=bottle_name,
        backend=backend,
    )
    if current is None:
        raise BottlesControlError(
            "The existing Bottles control is not verifiable"
        )

    old_receipt, old_launcher, old_uninstaller = current
    launcher_name, uninstaller_name = _script_names(capsule_path)
    if (
        old_launcher.name != launcher_name
        or old_uninstaller.name != uninstaller_name
    ):
        raise BottlesControlError(
            "The existing script names do not match the capsule"
        )

    launcher_text = _launcher_text(
        bottle_name=bottle_name,
        runner_id=runner.runner_id,
        backend=backend,
    )
    uninstaller_text = _uninstaller_text(
        bottle_name=bottle_name,
        backend=backend,
    )

    temporary_launcher = destination / (
        f".{launcher_name}.refresh-{os.getpid()}-{secrets.token_hex(6)}"
    )
    temporary_uninstaller = destination / (
        f".{uninstaller_name}.refresh-{os.getpid()}-{secrets.token_hex(6)}"
    )
    temporary_receipt = destination / (
        f".{CONTROL_RECEIPT_NAME}.refresh-"
        f"{os.getpid()}-{secrets.token_hex(6)}"
    )

    try:
        temporary_launcher.write_text(
            launcher_text,
            encoding="utf-8",
            newline="\n",
        )
        temporary_uninstaller.write_text(
            uninstaller_text,
            encoding="utf-8",
            newline="\n",
        )
        temporary_launcher.chmod(0o755)
        temporary_uninstaller.chmod(0o755)

        document = {
            "schema": 0,
            "operation": "bottles-single-copy-control",
            "generated_by": f"offline-game-vault-gui-{__version__}",
            "capsule_id": capsule_id,
            "profile_id": profile_id,
            "backend": "bottles",
            "runner": runner.runner_id,
            "runner_digest": runner.digest,
            "bottle_name": bottle_name,
            "deployment": "bottles-managed",
            "bottles_path_resolution": "bottles-cli-json-or-plain",
            "launcher_protocol": "direct-bottles-cli-v1",
            "uninstaller_protocol": (
                "ogv-remove-bottles-deployment-v1"
            ),
            "application_ref": backend.application_ref,
            "application_commit": backend.application_commit,
            "launcher": launcher_name,
            "launcher_sha256": _sha256(temporary_launcher),
            "uninstaller": uninstaller_name,
            "uninstaller_sha256": _sha256(temporary_uninstaller),
            "complete": True,
        }
        temporary_receipt.write_text(
            json.dumps(
                document,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary_receipt.chmod(0o644)

        for path in (
            temporary_launcher,
            temporary_uninstaller,
            temporary_receipt,
        ):
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

        os.replace(temporary_launcher, old_launcher)
        os.replace(temporary_uninstaller, old_uninstaller)
        os.replace(temporary_receipt, old_receipt)

        directory_fd = os.open(
            destination,
            os.O_RDONLY | os.O_DIRECTORY,
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary_launcher.unlink(missing_ok=True)
        temporary_uninstaller.unlink(missing_ok=True)
        temporary_receipt.unlink(missing_ok=True)
        raise

    refreshed = validate_bottles_control(
        destination,
        capsule_id=capsule_id,
        profile_id=profile_id,
        runner=runner,
        bottle_name=bottle_name,
        backend=backend,
    )
    if refreshed is None:
        raise BottlesControlError(
            "The updated Bottles control is not verifiable"
        )
    return refreshed


def validate_bottles_control(
    destination: Path,
    *,
    capsule_id: str,
    profile_id: str,
    runner: RunnerRecord,
    bottle_name: str,
    backend: SharedBackendRecord | None = None,
) -> tuple[Path, Path, Path] | None:
    root = Path(destination)
    receipt = root / CONTROL_RECEIPT_NAME
    if receipt.is_symlink() or not receipt.is_file():
        return None
    try:
        document = _load_json(receipt, CONTROL_RECEIPT_NAME)
    except BottlesControlError:
        return None

    expected = {
        "schema": 0,
        "operation": "bottles-single-copy-control",
        "capsule_id": capsule_id,
        "profile_id": profile_id,
        "backend": "bottles",
        "runner": runner.runner_id,
        "runner_digest": runner.digest,
        "bottle_name": bottle_name,
        "deployment": "bottles-managed",
        "complete": True,
    }
    if any(document.get(key) != value for key, value in expected.items()):
        return None
    if backend is not None and (
        document.get("application_ref") != backend.application_ref
        or document.get("application_commit") != backend.application_commit
    ):
        return None

    launcher_name = document.get("launcher")
    uninstaller_name = document.get("uninstaller")
    if (
        not isinstance(launcher_name, str)
        or not isinstance(uninstaller_name, str)
        or not _SAFE_SCRIPT.fullmatch(launcher_name)
        or not _SAFE_SCRIPT.fullmatch(uninstaller_name)
    ):
        return None

    launcher = root / launcher_name
    uninstaller = root / uninstaller_name
    for path, digest_key in (
        (launcher, "launcher_sha256"),
        (uninstaller, "uninstaller_sha256"),
    ):
        if (
            path.is_symlink()
            or not path.is_file()
            or not os.access(path, os.X_OK)
            or document.get(digest_key) != _sha256(path)
        ):
            return None
    return receipt, launcher, uninstaller
