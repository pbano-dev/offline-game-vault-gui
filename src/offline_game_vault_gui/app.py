from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys
import threading
import traceback
from typing import Any, Callable

from .config import Preferences
from .core import CoreClient, CoreError
from .model import Backend, CompositionRequest, GameRecord, RunnerRecord
from .service import CompositionService, ServiceError


APP_ID = "io.github.pbano.OfflineGameVault.Gui"


def _gtk() -> tuple[Any, Any, Any]:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, GLib, Gtk
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "GTK4, libadwaita 1, and PyGObject are required to run the GUI"
        ) from exc
    return Adw, GLib, Gtk


class MainWindow:
    def __init__(
        self,
        application: Any,
        service: CompositionService,
        core_description: str,
    ) -> None:
        Adw, GLib, Gtk = _gtk()
        self.Adw = Adw
        self.GLib = GLib
        self.Gtk = Gtk
        self.service = service
        self.preferences = Preferences.load()
        self.games: tuple[GameRecord, ...] = ()
        self.runners: tuple[RunnerRecord, ...] = ()
        self.visible_runners: tuple[RunnerRecord, ...] = ()
        self.last_destination: Path | None = None

        self.window = Adw.ApplicationWindow(application=application)
        self.window.set_title("Offline Game Vault")
        self.window.set_default_size(940, 760)

        header = Adw.HeaderBar()
        self.refresh_button = Gtk.Button(label="Refresh")
        self.refresh_button.connect("clicked", self._refresh)
        header.pack_end(self.refresh_button)

        page = Adw.PreferencesPage()
        setup = Adw.PreferencesGroup(title="Vault and core")
        page.add(setup)

        self.collection_row = Adw.EntryRow(title="Collection root")
        self.collection_row.set_text(self.preferences.collection_root)
        setup.add(self.collection_row)

        self.destination_parent_row = Adw.EntryRow(
            title="Default destination parent"
        )
        self.destination_parent_row.set_text(
            self.preferences.destination_parent
        )
        setup.add(self.destination_parent_row)

        core_row = Adw.ActionRow(
            title="Selected core",
            subtitle=core_description,
        )
        setup.add(core_row)

        selection = Adw.PreferencesGroup(title="Composition request")
        page.add(selection)

        self.game_row = Adw.ComboRow(title="Game")
        self.game_model = Gtk.StringList()
        self.game_row.set_model(self.game_model)
        self.game_row.connect("notify::selected", self._game_changed)
        selection.add(self.game_row)

        self.backend_row = Adw.ComboRow(title="Backend")
        self.backend_model = Gtk.StringList.new(
            ["Bottles", "Direct-Wine", "UMU/Proton"]
        )
        self.backend_row.set_model(self.backend_model)
        self.backend_row.set_selected(0)
        self.backend_row.connect("notify::selected", self._backend_changed)
        selection.add(self.backend_row)

        self.profile_row = Adw.ComboRow(
            title="Source layout",
            subtitle="Optional override; Auto lets the core resolve it",
        )
        self.profile_model = Gtk.StringList()
        self.profile_row.set_model(self.profile_model)
        selection.add(self.profile_row)

        self.runner_row = Adw.ComboRow(title="Preserved runner")
        self.runner_model = Gtk.StringList()
        self.runner_row.set_model(self.runner_model)
        selection.add(self.runner_row)

        self.umu_row = Adw.ActionRow(
            title="Resolved UMU component sets",
            subtitle="Loaded when UMU is selected; diagnostic only",
        )
        selection.add(self.umu_row)

        target = Adw.PreferencesGroup(title="Writable target")
        page.add(target)

        self.destination_row = Adw.EntryRow(
            title="Direct-Wine / UMU destination"
        )
        target.add(self.destination_row)

        self.bottle_name_row = Adw.EntryRow(title="Bottles derivative name")
        target.add(self.bottle_name_row)

        self.bottles_path_row = Adw.ActionRow(
            title="Managed Bottles directory",
            subtitle="Discovered by the core",
        )
        target.add(self.bottles_path_row)

        self.state_backup_row = Adw.EntryRow(
            title="Optional Direct-Wine state backup"
        )
        target.add(self.state_backup_row)

        self.arguments_row = Adw.EntryRow(
            title="Additional Direct-Wine / UMU play arguments"
        )
        target.add(self.arguments_row)

        self.removal_arguments_row = Adw.EntryRow(
            title="Generated Remove arguments",
        )
        self.removal_arguments_row.set_text("")
        target.add(self.removal_arguments_row)

        actions = Adw.PreferencesGroup(title="Operations")
        page.add(actions)
        buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        buttons.set_margin_top(8)
        buttons.set_margin_bottom(8)
        buttons.set_margin_start(12)
        buttons.set_margin_end(12)

        for label, callback in (
            ("Materialize", lambda _button: self._compose(False)),
            ("Materialize & Play", lambda _button: self._compose(True)),
            ("Verify", lambda _button: self._operation("verify")),
            ("Play", lambda _button: self._operation("play")),
            ("Remove", lambda _button: self._operation("remove")),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            buttons.append(button)
        actions.add(buttons)

        log_group = Adw.PreferencesGroup(title="Result")
        page.add(log_group)
        self.status_row = Adw.ActionRow(
            title="Status",
            subtitle="Ready",
        )
        log_group.add(self.status_row)

        self.log = Gtk.TextView(
            editable=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        self.log.set_vexpand(True)
        scroller = Gtk.ScrolledWindow(
            min_content_height=220,
            child=self.log,
        )
        scroller.set_margin_top(8)
        scroller.set_margin_bottom(12)
        scroller.set_margin_start(12)
        scroller.set_margin_end(12)
        log_group.add(scroller)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
        )
        content.append(header)
        content.append(page)
        self.window.set_content(content)
        self._backend_changed()
        self._refresh()

    def present(self) -> None:
        self.window.present()

    def _set_log(self, text: str) -> None:
        self.log.get_buffer().set_text(text)

    def _set_status(self, text: str) -> None:
        self.status_row.set_subtitle(text)

    def _run_worker(
        self,
        label: str,
        function: Callable[[], Any],
        complete: Callable[[Any], None],
    ) -> None:
        self._set_status(label)
        self.refresh_button.set_sensitive(False)

        def worker() -> None:
            try:
                result = function()
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.GLib.idle_add(self._worker_failed, detail)
            else:
                self.GLib.idle_add(self._worker_complete, complete, result)

        threading.Thread(target=worker, daemon=True).start()

    def _worker_failed(self, detail: str) -> bool:
        self.refresh_button.set_sensitive(True)
        self._set_status("Operation failed")
        self._set_log(detail)
        return False

    def _worker_complete(
        self,
        callback: Callable[[Any], None],
        result: Any,
    ) -> bool:
        self.refresh_button.set_sensitive(True)
        callback(result)
        return False

    def _refresh(self, *_args: Any) -> None:
        raw = self.collection_row.get_text().strip()
        if not raw:
            self._set_status("Select a collection root")
            return
        collection = Path(raw).expanduser()
        self.preferences.collection_root = str(collection)
        self.preferences.destination_parent = (
            self.destination_parent_row.get_text().strip()
        )
        self.preferences.save()

        def load() -> Any:
            return self.service.load(collection)

        def loaded(result: Any) -> None:
            games, runners, warnings = result
            self.games = games
            self.runners = runners
            self.game_model.splice(
                0,
                self.game_model.get_n_items(),
                [game.label for game in games],
            )
            if games:
                self.game_row.set_selected(0)
            self._game_changed()
            self._backend_changed()
            self._set_status(
                f"Loaded {len(games)} games and {len(runners)} runners"
            )
            self._set_log("\n".join(warnings) if warnings else "No warnings.")

        self._run_worker("Loading Vault catalogs…", load, loaded)

    def _selected_backend(self) -> Backend:
        index = self.backend_row.get_selected()
        if index == self.Gtk.INVALID_LIST_POSITION or index > 2:
            return "bottles"
        return ("bottles", "direct-wine", "umu")[index]

    def _game_changed(self, *_args: Any) -> None:
        index = self.game_row.get_selected()
        self.profile_model.splice(
            0,
            self.profile_model.get_n_items(),
            [],
        )
        self.profile_model.append("Auto")
        if index < len(self.games):
            for profile in self.games[index].source_profiles:
                self.profile_model.append(profile.label)
        self.profile_row.set_selected(0)

    def _backend_changed(self, *_args: Any) -> None:
        backend = self._selected_backend()
        self.visible_runners = self.service.compatible_runners(
            self.runners,
            backend,
        )
        self.runner_model.splice(
            0,
            self.runner_model.get_n_items(),
            [runner.label for runner in self.visible_runners],
        )
        if self.visible_runners:
            self.runner_row.set_selected(0)
        self.destination_row.set_visible(backend != "bottles")
        self.bottle_name_row.set_visible(backend == "bottles")
        self.bottles_path_row.set_visible(backend == "bottles")
        self.state_backup_row.set_visible(backend == "direct-wine")
        self.arguments_row.set_visible(backend != "bottles")
        self.umu_row.set_visible(backend == "umu")
        if backend == "bottles":
            self._load_bottles_path()
        elif backend == "umu":
            self._load_component_sets()

    def _load_bottles_path(self) -> None:
        def loaded(path: Path) -> None:
            self.bottles_path_row.set_subtitle(str(path))

        self._run_worker(
            "Discovering Bottles path…",
            self.service.bottles_path,
            loaded,
        )

    def _load_component_sets(self) -> None:
        raw = self.collection_row.get_text().strip()
        if not raw:
            return

        def loaded(values: Any) -> None:
            summary = (
                "\n".join(item.label for item in values)
                if values
                else "No compatible UMU component set"
            )
            self.umu_row.set_subtitle(summary)
            self._set_status(f"Resolved {len(values)} UMU component set(s)")

        self._run_worker(
            "Resolving UMU components…",
            lambda: self.service.component_sets(Path(raw)),
            loaded,
        )

    def _request(self, play: bool) -> CompositionRequest:
        game_index = self.game_row.get_selected()
        runner_index = self.runner_row.get_selected()
        if game_index >= len(self.games):
            raise ServiceError("Select a game")
        if runner_index >= len(self.visible_runners):
            raise ServiceError("Select a compatible preserved runner")
        game = self.games[game_index]
        runner = self.visible_runners[runner_index]
        backend = self._selected_backend()
        profile_index = self.profile_row.get_selected()
        source_profile = None
        if profile_index > 0:
            source_profile = game.source_profiles[profile_index - 1].profile_id
        arguments: tuple[str, ...] = ()
        raw_arguments = self.arguments_row.get_text().strip()
        if raw_arguments:
            try:
                arguments = tuple(shlex.split(raw_arguments))
            except ValueError as exc:
                raise ServiceError(f"Invalid arguments: {exc}") from exc
        destination = None
        bottle_name = None
        bottles_path = None
        state_backup = None
        if backend == "bottles":
            bottle_name = self.bottle_name_row.get_text().strip()
            raw_bottles = self.bottles_path_row.get_subtitle()
            bottles_path = Path(raw_bottles) if raw_bottles else None
        else:
            raw_destination = self.destination_row.get_text().strip()
            if not raw_destination:
                parent = self.destination_parent_row.get_text().strip()
                if parent:
                    raw_destination = str(
                        Path(parent) / f"{game.capsule_id}-{backend}"
                    )
                    self.destination_row.set_text(raw_destination)
            destination = Path(raw_destination) if raw_destination else None
            if backend == "direct-wine":
                raw_backup = self.state_backup_row.get_text().strip()
                state_backup = Path(raw_backup) if raw_backup else None
        return CompositionRequest(
            collection_root=Path(self.collection_row.get_text().strip()),
            capsule_path=game.capsule_path,
            backend=backend,
            runner_id=runner.runner_id,
            source_profile_id=source_profile,
            destination=destination,
            state_backup=state_backup,
            bottles_path=bottles_path,
            bottle_name=bottle_name,
            play=play,
            arguments=arguments,
        )

    def _compose(self, play: bool) -> None:
        try:
            request = self._request(play)
        except Exception as exc:
            self._worker_failed(str(exc))
            return

        def complete(result: Any) -> None:
            self.last_destination = result.destination
            self._set_status("Materialization complete")
            self._set_log(
                "\n".join(
                    (
                        f"Capsule: {result.capsule_id}",
                        f"Backend: {result.backend}",
                        f"Runner: {result.runner_id}",
                        f"Profile: {result.profile_id}",
                        f"Destination: {result.destination}",
                        f"Played: {result.played}",
                        f"Play complete: {result.play_complete}",
                    )
                )
            )

        self._run_worker(
            "Materializing composition…",
            lambda: self.service.compose(request),
            complete,
        )

    def _operation_destination(self) -> Path:
        backend = self._selected_backend()
        if backend == "bottles":
            managed = self.bottles_path_row.get_subtitle().strip()
            name = self.bottle_name_row.get_text().strip()
            if managed and name:
                return Path(managed) / name
        else:
            raw = self.destination_row.get_text().strip()
            if raw:
                return Path(raw)
        if self.last_destination is not None:
            return self.last_destination
        raise ServiceError("No materialization target is selected")

    def _operation(self, operation: str) -> None:
        try:
            destination = self._operation_destination()
            arguments: tuple[str, ...] = ()
            if operation == "play":
                raw = self.arguments_row.get_text().strip()
            elif operation == "remove":
                raw = self.removal_arguments_row.get_text().strip()
            else:
                raw = ""
            if raw:
                arguments = tuple(shlex.split(raw))
        except (ServiceError, ValueError) as exc:
            self._worker_failed(str(exc))
            return

        def complete(process: Any) -> None:
            self._set_status(
                f"{operation.capitalize()} returned {process.returncode}"
            )
            self._set_log(
                (process.stdout or "")
                + ("\n" if process.stdout and process.stderr else "")
                + (process.stderr or "")
            )
            if operation == "remove" and process.returncode == 0:
                self.last_destination = None

        self._run_worker(
            f"Running generated {operation} operation…",
            lambda: self.service.run_operation(
                destination,
                operation,
                arguments,
            ),
            complete,
        )


def main(argv: list[str] | None = None) -> int:
    try:
        Adw, _GLib, _Gtk = _gtk()
    except RuntimeError as exc:
        print(f"ogv-gui: {exc}", file=sys.stderr)
        return 2

    class Application(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID)
            self.window: MainWindow | None = None

        def do_activate(self) -> None:
            try:
                core = CoreClient.resolve()
                probe = core.probe()
                service = CompositionService(core)
                if self.window is None:
                    self.window = MainWindow(
                        self,
                        service,
                        f"{probe.version} — {probe.description}",
                    )
                self.window.present()
            except (CoreError, ServiceError, RuntimeError) as exc:
                print(f"ogv-gui: {exc}", file=sys.stderr)
                self.quit()

    application = Application()
    return int(application.run(argv or sys.argv))
