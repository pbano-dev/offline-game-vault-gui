#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


def safe_relative(value: str, label: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"{label} is not a safe relative path")
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a capsule and emit the state declarations associated "
            "with one profile. This helper never modifies the capsule."
        )
    )
    parser.add_argument("--capsule", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    capsule = load_json(args.capsule)
    profiles = capsule.get("profiles", [])
    matches = [
        item
        for item in profiles
        if isinstance(item, dict) and item.get("id") == args.profile
    ]
    if len(matches) != 1:
        raise SystemExit("profile is absent or duplicated")

    profile = matches[0]
    state = profile.get("state", {})
    if not isinstance(state, dict):
        state = {}
    declarations = state.get("paths", [])
    normalized: list[str] = []
    if isinstance(declarations, list):
        for number, value in enumerate(declarations):
            if isinstance(value, str):
                normalized.append(
                    safe_relative(value, f"state.paths[{number}]")
                )

    payload = {
        "capsule_id": capsule.get("capsule_id"),
        "profile_id": args.profile,
        "state_paths": normalized,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for value in normalized:
            print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
