#!/usr/bin/env -S python3 -S
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys


def option(arguments: list[str], name: str) -> str | None:
    try:
        index = arguments.index(name)
    except ValueError:
        return None
    if index + 1 >= len(arguments):
        raise SystemExit(f"missing value for {name}")
    return arguments[index + 1]


def write_log(arguments: list[str]) -> None:
    raw = os.environ.get("FAKE_CORE_LOG")
    if raw:
        with Path(raw).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(arguments) + "\n")


def operation(path: Path, name: str, output: str) -> None:
    target = path / name
    target.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n"
        f"printf '%s\\n' {json.dumps(output)}\n",
        encoding="utf-8",
    )
    target.chmod(0o755)


arguments = sys.argv[1:]
write_log(arguments)

if arguments == ["--version"]:
    print("ogv 0.11.4")
    raise SystemExit(0)

if len(arguments) == 2 and arguments[1] == "--help":
    if arguments[0] in {
        "discover-bottles-path",
        "list-preserved-runners",
        "list-shared-umu-runtimes",
        "compose",
    }:
        print(f"usage: ogv {arguments[0]}")
        raise SystemExit(0)
    raise SystemExit(2)

if arguments and arguments[0] == "list-preserved-runners":
    print(
        json.dumps(
            {
                "schema": 0,
                "runners": [
                    {
                        "runner_id": "wine-runner",
                        "digest": "sha256:" + "1" * 64,
                        "archive_path": "objects/sha256/11/" + "1" * 64,
                        "size": 100,
                        "format": "tar.zst",
                        "source_root": "wine-runner",
                        "wine_path": "bin/wine",
                        "wineserver_path": "bin/wineserver",
                        "compatible_backends": ["direct-wine", "bottles"],
                        "metadata_source": "synthetic",
                        "proton_path": None,
                        "kind": "wine",
                    },
                    {
                        "runner_id": "Proton-9.0-203",
                        "digest": "sha256:" + "2" * 64,
                        "archive_path": "objects/sha256/22/" + "2" * 64,
                        "size": 200,
                        "format": "tar.zst",
                        "source_root": "Proton-9.0-203",
                        "wine_path": "files/bin/wine",
                        "wineserver_path": "files/bin/wineserver",
                        "compatible_backends": [
                            "direct-wine",
                            "bottles",
                            "umu",
                        ],
                        "metadata_source": "synthetic",
                        "proton_path": "proton",
                        "kind": "proton",
                    },
                ],
                "warnings": ["synthetic warning"],
            }
        )
    )
    raise SystemExit(0)

if arguments and arguments[0] == "list-shared-umu-runtimes":
    print(
        json.dumps(
            {
                "schema": 0,
                "component_sets": [
                    {
                        "component_set_id": "umu-component-set-test",
                        "component_set_digest": "sha256:" + "3" * 64,
                        "backend_component_id": "umu-backend",
                        "runtime_component_id": "steamrt4-runtime",
                        "backend_entrypoint": (
                            "engine/python-portable/"
                            "umu-run-fully-local"
                        ),
                        "runtime_var": (
                            "engine/xdg-data/umu/steamrt4/var"
                        ),
                        "runtime_family": "steamrt4",
                        "platform_prefix": "steamrt4",
                        "platform_directory": "steamrt4_platform_test",
                    }
                ],
            }
        )
    )
    raise SystemExit(0)

if arguments and arguments[0] == "discover-bottles-path":
    print(
        json.dumps(
            {
                "schema": 0,
                "flatpak_app": "com.usebottles.bottles",
                "bottles_path": os.environ["FAKE_BOTTLES_PATH"],
            }
        )
    )
    raise SystemExit(0)

if arguments and arguments[0] == "compose":
    backend = option(arguments, "--backend")
    runner = option(arguments, "--runner")
    capsule = Path(option(arguments, "--capsule") or "")
    if backend == "bottles":
        destination = (
            Path(os.environ["FAKE_BOTTLES_PATH"])
            / (option(arguments, "--bottle-name") or "missing")
        )
    else:
        destination = Path(option(arguments, "--destination") or "")
    destination.mkdir(parents=True, exist_ok=False)
    operation(destination, "JUGAR.sh", "played")
    operation(destination, "VERIFICAR.sh", "verified")
    operation(destination, "DESINSTALAR.sh", "removed")
    profile_id = option(arguments, "--source-profile") or "resolved-source"
    print(
        json.dumps(
            {
                "schema": 0,
                "capsule_id": "game",
                "backend": backend,
                "runner_id": runner,
                "profile_id": profile_id,
                "destination": str(destination),
                "materialized": True,
                "played": "--play" in arguments,
                "play_complete": True if "--play" in arguments else None,
                "backend_result": (
                    {
                        "component_set_id": "umu-component-set-test",
                        "backend_component_id": "umu-backend",
                        "runtime_component_id": "steamrt4-runtime",
                        "backend_entrypoint": (
                            "engine/python-portable/"
                            "umu-run-fully-local"
                        ),
                    }
                    if backend == "umu"
                    else {}
                ),
            }
        )
    )
    raise SystemExit(0)

print("unsupported fake-core command", file=sys.stderr)
raise SystemExit(2)
