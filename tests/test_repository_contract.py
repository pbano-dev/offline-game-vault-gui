from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryContractTests(unittest.TestCase):
    def test_python_files_parse(self) -> None:
        files = sorted(
            path
            for directory in ("src", "tests", "tools")
            for path in (ROOT / directory).rglob("*.py")
        )
        self.assertTrue(files)
        for path in files:
            compile(path.read_bytes(), str(path), "exec")

    def test_version_contract(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        namespace: dict[str, object] = {}
        exec(
            compile(
                (
                    ROOT
                    / "src/offline_game_vault_gui/__init__.py"
                ).read_bytes(),
                "__init__.py",
                "exec",
            ),
            namespace,
        )
        self.assertEqual(
            project["project"]["version"],
            namespace["__version__"],
        )
        self.assertEqual(project["project"]["version"], "0.5.0a1")

    def test_pyside6_is_runtime_dependency(self) -> None:
        project = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = project["project"]["dependencies"]
        self.assertTrue(
            any(item.startswith("PySide6") for item in dependencies)
        )

    def test_shell_scripts_are_executable(self) -> None:
        for path in (ROOT / "scripts").glob("*.sh"):
            self.assertTrue(path.stat().st_mode & 0o100, path.name)


if __name__ == "__main__":
    unittest.main()
