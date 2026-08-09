from __future__ import annotations

import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from audit_privacy import scan  # noqa: E402


def github_actions_home() -> str:
    """Build the CI home without embedding a private path in repository text."""
    return Path("/").joinpath("home", "runner").as_posix()


class PrivacyAuditTests(unittest.TestCase):
    def scan_text(
        self,
        text: str,
        *,
        home: str,
        username: str,
        hostname: str,
    ) -> list[str]:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sample.txt").write_text(
                text,
                encoding="utf-8",
            )

            with (
                patch.dict(
                    os.environ,
                    {
                        "HOME": home,
                        "USER": username,
                    },
                    clear=False,
                ),
                patch(
                    "audit_privacy.os.uname",
                    return_value=SimpleNamespace(
                        nodename=hostname,
                    ),
                ),
            ):
                return scan(root)

    def test_runner_is_a_generic_ci_identity(self) -> None:
        problems = self.scan_text(
            "Select the preserved runner from the catalog.\n",
            home=github_actions_home(),
            username="runner",
            hostname="runner",
        )

        self.assertEqual(problems, [])

    def test_absolute_runner_home_is_still_rejected(self) -> None:
        ci_home = github_actions_home()

        problems = self.scan_text(
            f"private={ci_home}/work/project\n",
            home=ci_home,
            username="runner",
            hostname="runner",
        )

        self.assertTrue(problems)
        self.assertTrue(
            any(
                "private host value" in problem
                or "private-path pattern" in problem
                for problem in problems
            )
        )

    def test_unique_username_is_still_rejected(self) -> None:
        problems = self.scan_text(
            "owner=private-ci-owner-8472\n",
            home="/tmp/neutral-home",
            username="private-ci-owner-8472",
            hostname="localhost",
        )

        self.assertEqual(len(problems), 1)
        self.assertIn(
            "private host value",
            problems[0],
        )


if __name__ == "__main__":
    unittest.main()
