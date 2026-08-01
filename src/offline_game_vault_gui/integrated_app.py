from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import threading
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .catalog import CatalogError, scan_catalog
from .config import (
    ConfigurationError,
    resolve_collection_root,
    resolve_destination_parent,
)
from .experimental_selection import (
    BACKEND_LABELS,
    BACKENDS,
    compatible_runners,
    derivative_name,
    source_profiles,
)
from .experimental_service import (
    ExperimentalServiceError,
    discover_bottles_path,
    list_preserved_runners,
    materialize_experimental,
    remove_experimental,
    run_experimental,
    target_occupied,
    target_recognized,
    validate_core,
    verify_experimental,
    write_local_receipt,
)
from .model import (
    ExperimentalRequest,
    GameRecord,
    LogRecord,
    OperationResult,
    ProfileRecord,
    RunnerRecord,
    SaveSetRecord,
)
from .save_sets import SaveSetError, scan_save_sets


class IntegratedMainWindow(Adw.ApplicationWindow):
    """User-requested experimental materialization controller.

    Acceptance and profile status are descriptive. They never authorize or
    prohibit an operation. The only hard gates are the presence and integrity
    of the pieces required by the selected backend.
    """

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title("OfflineGameVault")
        self.set_default_size(960, 820)

        self.busy = False
        self.log_records: list[LogRecord] = []
        self.games: tuple[GameRecord, ...] = ()
        self.runners: tuple[RunnerRecord, ...] = ()
        self.current_source_profiles: tuple[ProfileRecord, ...] = ()
        self.current_runners: tuple[RunnerRecord, ...] = ()
        self.current_save_sets: tuple[SaveSetRecord, ...] = ()
        self.destination_parent: Path | None = None
        self.bottles_path: Path | None = None
        self.core_label: str | None = None
        self.startup_error: str | None = None

        try:
            self.collection_root = (
                resolve_collection_root().expanduser().resolve(strict=True)
            )
            self.destination_parent = resolve_destination_parent().expanduser()
            self.destination_parent.mkdir(parents=True, exist_ok=True)
            self.destination_parent = self.destination_parent.resolve(strict=True)
            self.games, catalog_warnings = scan_catalog(self.collection_root)
        except (
            ConfigurationError,
            CatalogError,
            OSError,
        ) as exc:
            self.collection_root = resolve_collection_root().expanduser()
            catalog_warnings = ()
            self.startup_error = str(exc)

        self._build_ui()
        self._connect_signals()

        self.game_row.set_model(
            Gtk.StringList.new([game.label for game in self.games])
        )
        if self.games:
            self.game_row.set_selected(0)

        for warning in catalog_warnings:
            self._internal_log(warning, level="WARNING")

        if self.startup_error is None:
            self._reload_core_catalog()
        else:
            self.status_row.set_title("Collection unavailable")
            self.status_row.set_subtitle(self.startup_error)
            self._internal_log(self.startup_error, level="ERROR")

        self._update_all()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(
                title="OfflineGameVault",
                subtitle="Experimental materialization and gameplay",
            )
        )
        self.reload_button = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text="Reload Vault and core catalogs",
        )
        header.pack_end(self.reload_button)
        toolbar.add_top_bar(header)

        page = Adw.PreferencesPage()

        environment_group = Adw.PreferencesGroup(
            title="Environment",
            description=(
                "The GUI uses one compatible offline-game-vault core for all "
                "backends. No runner is downloaded or taken from the host."
            ),
        )
        self.collection_row = Adw.ActionRow(
            title="Vault",
            subtitle=str(self.collection_root),
        )
        self.core_row = Adw.ActionRow(
            title="Core",
            subtitle="Not validated",
        )
        self.core_choose_button = Gtk.Button(
            label="Select checkout…",
            valign=Gtk.Align.CENTER,
        )
        self.core_row.add_suffix(self.core_choose_button)
        self.core_row.set_activatable_widget(self.core_choose_button)
        environment_group.add(self.collection_row)
        environment_group.add(self.core_row)
        page.add(environment_group)

        selection_group = Adw.PreferencesGroup(
            title="Experimental variant",
            description=(
                "Every game may be assembled with Bottles, Direct-Wine, or "
                "UMU when the required preserved pieces exist. Contract status "
                "is shown as evidence, never as a permission gate."
            ),
        )
        self.game_row = Adw.ComboRow(title="Game")
        self.backend_row = Adw.ComboRow(title="Backend")
        self.backend_row.set_model(
            Gtk.StringList.new([BACKEND_LABELS[item] for item in BACKENDS])
        )
        self.backend_row.set_selected(0)

        self.profile_row = Adw.ComboRow(
            title="Source profile",
            subtitle="Automatic compatible source is recommended",
        )
        self.runner_row = Adw.ComboRow(
            title="Preserved runner",
            subtitle="Only verified Vault objects are listed",
        )
        self.save_row = Adw.ComboRow(
            title="State",
            subtitle="No persistent state selected",
        )

        self.destination_row = Adw.ActionRow(title="Output parent")
        self.destination_choose_button = Gtk.Button(
            label="Choose folder…",
            valign=Gtk.Align.CENTER,
        )
        self.destination_row.add_suffix(self.destination_choose_button)
        self.destination_row.set_activatable_widget(
            self.destination_choose_button
        )

        self.bottles_row = Adw.ActionRow(
            title="Bottles managed directory",
            subtitle="Detected from bottles-cli; it cannot be overridden",
        )

        self.exact_target_row = Adw.ActionRow(
            title="Exact target",
            subtitle="Select a complete material combination",
        )
        self.operation_row = Adw.ActionRow(
            title="Operation",
            subtitle="No executable request",
        )

        for row in (
            self.game_row,
            self.backend_row,
            self.profile_row,
            self.runner_row,
            self.save_row,
            self.destination_row,
            self.bottles_row,
            self.exact_target_row,
            self.operation_row,
        ):
            selection_group.add(row)

        buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
        )
        buttons.set_halign(Gtk.Align.END)
        self.materialize_button = Gtk.Button(label="Materialize")
        self.materialize_play_button = Gtk.Button(
            label="Materialize & Play"
        )
        self.verify_button = Gtk.Button(label="Verify")
        self.play_button = Gtk.Button(label="Play")
        self.remove_button = Gtk.Button(label="Remove")
        self.materialize_play_button.add_css_class("suggested-action")
        self.remove_button.add_css_class("destructive-action")
        for button in (
            self.materialize_button,
            self.materialize_play_button,
            self.verify_button,
            self.play_button,
            self.remove_button,
        ):
            buttons.append(button)
        actions_row = Adw.ActionRow(title="Actions")
        actions_row.add_suffix(buttons)
        selection_group.add(actions_row)
        page.add(selection_group)

        status_group = Adw.PreferencesGroup(title="Status")
        self.status_row = Adw.ActionRow(
            title="Ready",
            subtitle="No operation in progress",
        )
        status_group.add(self.status_row)
        page.add(status_group)

        log_group = Adw.PreferencesGroup(title="Operation log")
        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(280)
        scroller.set_vexpand(True)
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.set_child(self.log_view)
        log_group.add(scroller)
        page.add(log_group)

        toolbar.set_content(page)
        self.set_content(toolbar)

    def _connect_signals(self) -> None:
        self.reload_button.connect("clicked", self._reload_clicked)
        self.core_choose_button.connect(
            "clicked", self._choose_core_checkout
        )
        self.game_row.connect(
            "notify::selected", self._selection_changed
        )
        self.backend_row.connect(
            "notify::selected", self._backend_changed
        )
        self.profile_row.connect(
            "notify::selected", self._leaf_changed
        )
        self.runner_row.connect(
            "notify::selected", self._leaf_changed
        )
        self.save_row.connect(
            "notify::selected", self._leaf_changed
        )
        self.destination_choose_button.connect(
            "clicked", self._choose_destination_parent
        )
        self.materialize_button.connect(
            "clicked", self._start_materialization, False
        )
        self.materialize_play_button.connect(
            "clicked", self._start_materialization, True
        )
        self.verify_button.connect(
            "clicked", self._start_verification
        )
        self.play_button.connect("clicked", self._start_play)
        self.remove_button.connect("clicked", self._start_removal)

    def _reload_clicked(self, _button: Gtk.Button) -> None:
        if self.busy:
            return
        try:
            self.games, warnings = scan_catalog(self.collection_root)
        except (CatalogError, OSError) as exc:
            self._finish_error("Vault reload failed", str(exc))
            return
        self.game_row.set_model(
            Gtk.StringList.new([game.label for game in self.games])
        )
        if self.games:
            self.game_row.set_selected(0)
        for warning in warnings:
            self._internal_log(warning, level="WARNING")
        self._reload_core_catalog()
        self._update_all()

    def _reload_core_catalog(self) -> None:
        try:
            self.core_label = validate_core()
            self.runners, runner_warnings = list_preserved_runners(
                self.collection_root
            )
        except (ExperimentalServiceError, OSError) as exc:
            self.core_label = None
            self.runners = ()
            self.core_row.set_subtitle(str(exc))
            self._internal_log(str(exc), level="ERROR")
            return

        self.core_row.set_subtitle(self.core_label)
        self._internal_log(
            f"Core validated: {self.core_label}"
        )
        self._internal_log(
            f"Preserved runners: {len(self.runners)}."
        )
        for warning in runner_warnings:
            self._internal_log(warning, level="WARNING")

        self.bottles_path = None
        try:
            self.bottles_path = discover_bottles_path()
        except (ExperimentalServiceError, OSError) as exc:
            self._internal_log(
                f"Bottles unavailable: {exc}",
                level="WARNING",
            )
        else:
            self._internal_log(
                f"Bottles managed directory detected: {self.bottles_path}"
            )

    def _selected_game(self) -> GameRecord | None:
        index = self.game_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.games)
        ):
            return None
        return self.games[index]

    def _selected_backend(self) -> str | None:
        index = self.backend_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(BACKENDS)
        ):
            return None
        return BACKENDS[index]

    def _selected_source_profile(self) -> ProfileRecord | None:
        index = self.profile_row.get_selected()
        if index in (Gtk.INVALID_LIST_POSITION, 0):
            return None
        position = index - 1
        if position >= len(self.current_source_profiles):
            return None
        return self.current_source_profiles[position]

    def _selected_runner(self) -> RunnerRecord | None:
        index = self.runner_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.current_runners)
        ):
            return None
        return self.current_runners[index]

    def _selected_save_set(self) -> SaveSetRecord | None:
        if self._selected_backend() != "direct-wine":
            return None
        index = self.save_row.get_selected()
        if index in (Gtk.INVALID_LIST_POSITION, 0):
            return None
        position = index - 1
        if position >= len(self.current_save_sets):
            return None
        return self.current_save_sets[position]

    def _selection_changed(self, *_args: object) -> None:
        self._update_source_profiles()
        self._update_save_sets()
        self._update_runners()
        self._update_target()
        self._update_buttons()

    def _backend_changed(self, *_args: object) -> None:
        self._update_runners()
        self._update_save_sets()
        self._update_visibility()
        self._update_target()
        self._update_buttons()

    def _leaf_changed(self, *_args: object) -> None:
        self._update_target()
        self._update_buttons()

    def _update_all(self) -> None:
        self._update_source_profiles()
        self._update_runners()
        self._update_save_sets()
        self._update_visibility()
        self._update_target()
        self._update_buttons()

    def _update_source_profiles(self) -> None:
        game = self._selected_game()
        self.current_source_profiles = (
            source_profiles(game) if game is not None else ()
        )
        labels = ["Automatic compatible source"]
        labels.extend(
            f"{profile.profile_id} · {profile.adapter or 'unknown'} · "
            f"{profile.status or 'unspecified'}"
            for profile in self.current_source_profiles
        )
        self.profile_row.set_model(Gtk.StringList.new(labels))
        self.profile_row.set_selected(0)
        self.profile_row.set_sensitive(
            bool(game) and not self.busy
        )

    def _update_runners(self) -> None:
        backend = self._selected_backend()
        self.current_runners = (
            compatible_runners(self.runners, backend)
            if backend is not None
            else ()
        )
        labels = [runner.label for runner in self.current_runners]
        if not labels:
            labels = ["No compatible preserved runner"]
        self.runner_row.set_model(Gtk.StringList.new(labels))
        self.runner_row.set_sensitive(
            bool(self.current_runners) and not self.busy
        )
        if self.current_runners:
            self.runner_row.set_selected(0)

    def _update_save_sets(self) -> None:
        game = self._selected_game()
        if game is None:
            saves: tuple[SaveSetRecord, ...] = ()
            warnings: tuple[str, ...] = ()
        else:
            try:
                saves, warnings = scan_save_sets(
                    self.collection_root,
                    game.capsule_id,
                )
            except (SaveSetError, OSError) as exc:
                saves = ()
                warnings = (str(exc),)

        self.current_save_sets = saves
        labels = ["No persistent state"]
        labels.extend(item.label for item in saves)
        self.save_row.set_model(Gtk.StringList.new(labels))
        self.save_row.set_selected(0)

        direct_wine = self._selected_backend() == "direct-wine"
        self.save_row.set_sensitive(
            direct_wine and bool(saves) and not self.busy
        )
        if direct_wine:
            self.save_row.set_subtitle(
                (
                    f"{len(saves)} preserved save set(s)"
                    if saves
                    else "No persistent state registered"
                )
            )
        else:
            self.save_row.set_subtitle(
                "State selection is currently exposed for Direct-Wine only"
            )
        for warning in warnings:
            self._internal_log(warning, level="WARNING")

    def _update_visibility(self) -> None:
        backend = self._selected_backend()
        self.bottles_row.set_visible(backend == "bottles")
        self.destination_row.set_visible(backend != "bottles")

        self.destination_row.set_subtitle(
            (
                str(self.destination_parent)
                if self.destination_parent is not None
                else "No output parent selected"
            )
        )
        self.bottles_row.set_subtitle(
            (
                str(self.bottles_path)
                if self.bottles_path is not None
                else "Bottles managed directory unavailable"
            )
        )

    def _safe_collection_path(self, value: str) -> Path | None:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        candidate = self.collection_root / relative
        try:
            candidate.resolve(strict=False).relative_to(
                self.collection_root.resolve(strict=True)
            )
        except ValueError:
            return None
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate.resolve(strict=True)
        return None

    def _state_backup(self, save: SaveSetRecord | None) -> Path | None:
        if save is None or not save.source:
            return None
        for key in (
            "state_backup",
            "accepted_state",
            "backup_path",
        ):
            value = save.source.get(key)
            if isinstance(value, str) and value:
                candidate = self._safe_collection_path(value)
                if candidate is not None:
                    return candidate
        return None

    def _candidate_name(self) -> str | None:
        game = self._selected_game()
        backend = self._selected_backend()
        runner = self._selected_runner()
        if game is None or backend is None or runner is None:
            return None
        save = self._selected_save_set()
        source = self._selected_source_profile()
        return derivative_name(
            capsule_id=game.capsule_id,
            backend=backend,
            runner_id=runner.runner_id,
            source_profile_id=(
                source.profile_id if source is not None else None
            ),
            save_set_id=(
                save.save_set_id if save is not None else None
            ),
        )

    def _make_request(self) -> ExperimentalRequest | None:
        game = self._selected_game()
        backend = self._selected_backend()
        runner = self._selected_runner()
        name = self._candidate_name()
        if (
            self.core_label is None
            or game is None
            or backend is None
            or runner is None
            or name is None
        ):
            return None

        destination: Path | None
        bottles_path: Path | None
        bottle_name: str | None
        if backend == "bottles":
            if self.bottles_path is None:
                return None
            destination = None
            bottles_path = self.bottles_path
            bottle_name = name
        else:
            if self.destination_parent is None:
                return None
            destination = self.destination_parent / name
            bottles_path = None
            bottle_name = None

        source = self._selected_source_profile()
        save = self._selected_save_set()
        return ExperimentalRequest(
            collection_root=self.collection_root,
            capsule_path=game.capsule_path,
            capsule_id=game.capsule_id,
            backend_id=backend,  # type: ignore[arg-type]
            runner=runner,
            destination=destination,
            source_profile_id=(
                source.profile_id if source is not None else None
            ),
            save_set=save,
            state_backup=self._state_backup(save),
            bottles_path=bottles_path,
            bottle_name=bottle_name,
        )

    def _update_target(self) -> None:
        request = self._make_request()
        target = request.target if request is not None else None
        self.exact_target_row.set_subtitle(
            str(target)
            if target is not None
            else "Select a complete set of preserved pieces"
        )

    def _missing_reason(self) -> str:
        if self.core_label is None:
            return "A compatible offline-game-vault 0.11.3+ core is required."
        if self._selected_game() is None:
            return "Select a game."
        backend = self._selected_backend()
        if backend is None:
            return "Select a backend."
        if not self.current_runners:
            return (
                f"No preserved runner is structurally compatible with "
                f"{BACKEND_LABELS[backend]}."
            )
        if backend == "bottles" and self.bottles_path is None:
            return "Bottles managed directory could not be discovered."
        if backend != "bottles" and self.destination_parent is None:
            return "Select an output parent."
        return "Select a complete set of preserved pieces."

    def _update_buttons(self) -> None:
        request = self._make_request()
        occupied = (
            request is not None and target_occupied(request)
        )
        recognized = (
            request is not None and target_recognized(request)
        )

        self.materialize_button.set_sensitive(
            request is not None and not occupied and not self.busy
        )
        self.materialize_play_button.set_sensitive(
            request is not None and not occupied and not self.busy
        )
        self.verify_button.set_sensitive(
            request is not None and recognized and not self.busy
        )
        self.play_button.set_sensitive(
            request is not None and recognized and not self.busy
        )
        self.remove_button.set_sensitive(
            request is not None and recognized and not self.busy
        )

        if request is None:
            title = "Incomplete material combination"
            message = self._missing_reason()
            operation = "No executable request"
        elif recognized:
            title = "Existing experimental derivative"
            message = (
                "The selected target has a recognized core receipt. "
                "Verify or play it; contract acceptance is not inherited."
            )
            operation = (
                f"{BACKEND_LABELS[request.backend_id]} · "
                f"{request.runner.runner_id} · existing"
            )
        elif occupied:
            title = "Target collision"
            message = (
                "The selected target already exists but is not recognized "
                "as this backend derivative. It will not be overwritten."
            )
            operation = (
                f"{BACKEND_LABELS[request.backend_id]} · collision"
            )
        else:
            title = "Ready to materialize"
            message = (
                "The GUI will ask the core to synthesize an experimental "
                "profile from preserved Vault pieces. No acceptance is "
                "inherited and no component is downloaded."
            )
            operation = (
                f"{BACKEND_LABELS[request.backend_id]} · "
                f"{request.runner.runner_id} · experimental"
            )
        self.operation_row.set_subtitle(operation)
        if not self.busy:
            self.status_row.set_title(title)
            self.status_row.set_subtitle(message)

    def _choose_folder(
        self,
        *,
        title: str,
        initial: Path | None,
        callback: Callable[[Path], None],
    ) -> None:
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog()
            dialog.set_title(title)
            if initial is not None:
                try:
                    dialog.set_initial_folder(
                        Gio.File.new_for_path(str(initial))
                    )
                except (AttributeError, TypeError):
                    pass

            def selected(
                file_dialog: Gtk.FileDialog,
                result: Gio.AsyncResult,
            ) -> None:
                try:
                    folder = file_dialog.select_folder_finish(result)
                except GLib.Error:
                    return
                raw = folder.get_path() if folder is not None else None
                if raw:
                    callback(Path(raw))

            dialog.select_folder(self, None, selected)
            return

        chooser = Gtk.FileChooserNative(
            title=title,
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label="Choose",
            cancel_label="Cancel",
        )
        if initial is not None:
            try:
                chooser.set_current_folder(
                    Gio.File.new_for_path(str(initial))
                )
            except (AttributeError, TypeError):
                pass

        def response(
            native: Gtk.FileChooserNative,
            response_id: int,
        ) -> None:
            if response_id == Gtk.ResponseType.ACCEPT:
                selected_file = native.get_file()
                raw = (
                    selected_file.get_path()
                    if selected_file is not None
                    else None
                )
                if raw:
                    callback(Path(raw))
            native.destroy()

        chooser.connect("response", response)
        chooser.show()

    def _validated_directory(
        self,
        candidate: Path,
        *,
        outside_vault: bool,
    ) -> Path:
        if candidate.is_symlink() or not candidate.is_dir():
            raise OSError("The selected path is not a regular directory")
        resolved = candidate.expanduser().resolve(strict=True)
        if outside_vault:
            try:
                resolved.relative_to(
                    self.collection_root.resolve(strict=True)
                )
            except ValueError:
                pass
            else:
                raise OSError(
                    "The selected directory must be outside the Vault"
                )
        return resolved

    def _choose_destination_parent(
        self,
        _button: Gtk.Button,
    ) -> None:
        self._choose_folder(
            title="Choose output parent",
            initial=self.destination_parent,
            callback=self._accept_destination_parent,
        )

    def _accept_destination_parent(self, candidate: Path) -> None:
        try:
            self.destination_parent = self._validated_directory(
                candidate,
                outside_vault=True,
            )
        except OSError as exc:
            self._finish_error("Output parent rejected", str(exc))
            return
        self._internal_log(
            f"Output parent selected: {self.destination_parent}"
        )
        self._update_visibility()
        self._update_target()
        self._update_buttons()

    def _choose_core_checkout(self, _button: Gtk.Button) -> None:
        configured = os.environ.get("OGV_SOURCE_ROOT")
        initial = Path(configured).expanduser() if configured else None
        self._choose_folder(
            title="Choose offline-game-vault source checkout",
            initial=initial,
            callback=self._accept_core_checkout,
        )

    def _accept_core_checkout(self, candidate: Path) -> None:
        try:
            resolved = candidate.expanduser().resolve(strict=True)
            if (
                resolved.is_symlink()
                or not (resolved / "pyproject.toml").is_file()
                or not (
                    resolved
                    / "src"
                    / "offline_game_vault"
                    / "cli.py"
                ).is_file()
            ):
                raise OSError(
                    "The selected folder is not an offline-game-vault checkout"
                )
        except OSError as exc:
            self._finish_error("Core checkout rejected", str(exc))
            return

        os.environ.pop("OGV_EXECUTABLE", None)
        os.environ["OGV_SOURCE_ROOT"] = str(resolved)
        self._internal_log(
            "Core checkout selected for this session."
        )
        self._reload_core_catalog()
        self._update_all()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (
            self.reload_button,
            self.core_choose_button,
            self.game_row,
            self.backend_row,
            self.profile_row,
            self.runner_row,
            self.save_row,
            self.destination_choose_button,
        ):
            widget.set_sensitive(not busy)
        if busy:
            for button in (
                self.materialize_button,
                self.materialize_play_button,
                self.verify_button,
                self.play_button,
                self.remove_button,
            ):
                button.set_sensitive(False)
        else:
            self._update_visibility()
            self._update_buttons()

    def _internal_log(
        self,
        message: str,
        *,
        level: str = "INFO",
    ) -> None:
        record = LogRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            stream="internal",
            level=level,
            message=message,
        )
        self.log_records.append(record)
        buffer = self.log_view.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert(end, record.render())

    def _start_materialization(
        self,
        _button: Gtk.Button,
        play: bool,
    ) -> None:
        request = self._make_request()
        if request is None:
            return
        self._set_busy(True)
        self.status_row.set_title(
            "Materializing and playing" if play else "Materializing"
        )
        self.status_row.set_subtitle(
            f"{BACKEND_LABELS[request.backend_id]} · "
            f"{request.runner.runner_id}"
        )
        self._internal_log(
            f"Starting experimental {request.backend_id} materialization."
        )
        self._internal_log(
            f"Runner: {request.runner.runner_id}; "
            f"source profile: {request.source_profile_id or 'automatic'}."
        )
        self._internal_log(
            "Acceptance inherited: no.",
            level="WARNING",
        )
        threading.Thread(
            target=self._materialization_worker,
            args=(request, play),
            daemon=True,
        ).start()

    def _materialization_worker(
        self,
        request: ExperimentalRequest,
        play: bool,
    ) -> None:
        try:
            outcome = materialize_experimental(
                request,
                play=play,
            )
            write_local_receipt(request, outcome)
        except (
            ExperimentalServiceError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Materialization failed",
                str(exc),
            )
            return
        GLib.idle_add(self._finish_operation, outcome)

    def _start_verification(self, _button: Gtk.Button) -> None:
        request = self._make_request()
        if request is None or not target_recognized(request):
            return
        self._set_busy(True)
        self.status_row.set_title("Verifying derivative")
        self.status_row.set_subtitle(str(request.target))
        threading.Thread(
            target=self._verification_worker,
            args=(request,),
            daemon=True,
        ).start()

    def _verification_worker(
        self,
        request: ExperimentalRequest,
    ) -> None:
        try:
            outcome = verify_experimental(request)
        except (
            ExperimentalServiceError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Verification failed",
                str(exc),
            )
            return
        GLib.idle_add(self._finish_operation, outcome)

    def _start_play(self, _button: Gtk.Button) -> None:
        request = self._make_request()
        if request is None or not target_recognized(request):
            return
        self._set_busy(True)
        self.status_row.set_title("Playing")
        self.status_row.set_subtitle(str(request.target))
        self._internal_log(
            f"Starting {request.backend_id} gameplay test."
        )
        threading.Thread(
            target=self._play_worker,
            args=(request,),
            daemon=True,
        ).start()

    def _play_worker(self, request: ExperimentalRequest) -> None:
        try:
            outcome = run_experimental(request)
        except (
            ExperimentalServiceError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Gameplay failed",
                str(exc),
            )
            return
        GLib.idle_add(self._finish_operation, outcome)

    def _start_removal(self, _button: Gtk.Button) -> None:
        request = self._make_request()
        if request is None or not target_recognized(request):
            return
        dialog = Adw.AlertDialog(
            heading="Remove experimental derivative?",
            body=(
                "Continue only after preserving any mutable state. "
                "The immutable Vault will not be modified."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "State preserved — remove")
        dialog.set_response_appearance(
            "remove",
            Adw.ResponseAppearance.DESTRUCTIVE,
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.choose(
            self,
            None,
            self._removal_confirmed,
            request,
        )

    def _removal_confirmed(
        self,
        dialog: Adw.AlertDialog,
        result: Gio.AsyncResult,
        request: ExperimentalRequest,
    ) -> None:
        if dialog.choose_finish(result) != "remove":
            return
        self._set_busy(True)
        self.status_row.set_title("Removing derivative")
        self.status_row.set_subtitle(str(request.target))
        threading.Thread(
            target=self._removal_worker,
            args=(request,),
            daemon=True,
        ).start()

    def _removal_worker(
        self,
        request: ExperimentalRequest,
    ) -> None:
        try:
            outcome = remove_experimental(request)
        except (
            ExperimentalServiceError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Removal failed",
                str(exc),
            )
            return
        GLib.idle_add(self._finish_operation, outcome)

    def _finish_operation(
        self,
        outcome: OperationResult,
    ) -> bool:
        self._set_busy(False)
        self.status_row.set_title(
            f"{outcome.operation.replace('-', ' ').title()} complete"
        )
        self.status_row.set_subtitle(str(outcome.destination))
        self._internal_log(
            f"{outcome.operation}: {outcome.backend_id}: "
            f"{outcome.destination}"
        )
        if outcome.runner_id:
            self._internal_log(f"Runner: {outcome.runner_id}")
        played = outcome.payload.get("played")
        if isinstance(played, bool):
            self._internal_log(f"Played: {'yes' if played else 'no'}")
        play_complete = outcome.payload.get("play_complete")
        if isinstance(play_complete, bool):
            self._internal_log(
                f"Play completed: {'yes' if play_complete else 'NO'}",
                level="INFO" if play_complete else "WARNING",
            )
        self._update_target()
        self._update_buttons()
        return GLib.SOURCE_REMOVE

    def _finish_error(
        self,
        title: str,
        detail: str,
    ) -> bool:
        self._set_busy(False)
        self.status_row.set_title(title)
        self.status_row.set_subtitle(detail)
        self._internal_log(detail, level="ERROR")
        return GLib.SOURCE_REMOVE


class VaultApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="io.github.pbano.OfflineGameVault.Gui",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = IntegratedMainWindow(self)
        window.present()


def main() -> int:
    application = VaultApplication()
    return int(application.run(None))


if __name__ == "__main__":
    raise SystemExit(main())
