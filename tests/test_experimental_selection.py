from __future__ import annotations

import unittest
from pathlib import Path

from offline_game_vault_gui.experimental_selection import (
    BACKENDS,
    compatible_runners,
    derivative_name,
    source_profiles,
)
from offline_game_vault_gui.model import (
    GameRecord,
    ProfileRecord,
    RunnerRecord,
)


def runner(
    runner_id: str,
    backends: tuple[str, ...],
    kind: str = "wine",
) -> RunnerRecord:
    return RunnerRecord(
        runner_id=runner_id,
        digest="a" * 64,
        archive_path="objects/sha256/aa/aa/" + "a" * 64,
        size=1,
        format="tar.gz",
        source_root=runner_id,
        wine_path="files/bin/wine",
        wineserver_path="files/bin/wineserver",
        compatible_backends=backends,
        metadata_source="test",
        proton_path="proton" if kind == "proton" else None,
        kind=kind,  # type: ignore[arg-type]
    )


class ExperimentalSelectionTests(unittest.TestCase):
    def test_every_game_exposes_the_three_linux_backends(self) -> None:
        self.assertEqual(
            BACKENDS,
            ("bottles", "direct-wine", "umu"),
        )

    def test_runner_filter_is_structural_not_acceptance_based(self) -> None:
        proton = runner(
            "proton-test",
            ("bottles", "direct-wine", "umu"),
            "proton",
        )
        wine = runner(
            "wine-test",
            ("bottles", "direct-wine"),
        )
        self.assertEqual(
            compatible_runners((proton, wine), "umu"),
            (proton,),
        )
        self.assertEqual(
            compatible_runners((proton, wine), "bottles"),
            (proton, wine),
        )

    def test_all_linux_profiles_are_optional_sources_regardless_of_status(
        self,
    ) -> None:
        profiles = (
            ProfileRecord(
                profile_id="candidate",
                platform="linux",
                adapter="wine",
                status="candidate",
                mode="base",
                backend_id="direct-wine",
                default_runner_id=None,
            ),
            ProfileRecord(
                profile_id="unavailable",
                platform="linux",
                adapter="umu",
                status="unavailable",
                mode="base",
                backend_id="umu",
                default_runner_id=None,
            ),
            ProfileRecord(
                profile_id="windows",
                platform="windows",
                adapter="windows",
                status="verified",
                mode="playable",
                backend_id="windows",
                default_runner_id=None,
            ),
        )
        game = GameRecord(
            capsule_id="game",
            title="Game",
            preserved_version="1",
            capsule_path=Path("capsule.json"),
            profiles=profiles,
        )
        self.assertEqual(
            [profile.profile_id for profile in source_profiles(game)],
            ["candidate", "unavailable"],
        )

    def test_derivative_name_is_portable_and_identifies_variant(self) -> None:
        self.assertEqual(
            derivative_name(
                capsule_id="The Sims 2: Legacy Collection",
                backend="direct-wine",
                runner_id="GE-Proton 11-1",
            ),
            "The-Sims-2-Legacy-Collection--direct-wine--GE-Proton-11-1",
        )


    def test_derivative_name_distinguishes_source_and_state(self) -> None:
        value = derivative_name(
            capsule_id="game",
            backend="umu",
            runner_id="proton",
            source_profile_id="linux-bottles",
            save_set_id="save-1",
        )
        self.assertEqual(
            value,
            "game--umu--proton--source-linux-bottles--state-save-1",
        )


if __name__ == "__main__":
    unittest.main()
