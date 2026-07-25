from __future__ import annotations

from pathlib import Path
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import __version__
from .config import resolve_collection_root
from .bottles_backend import (
    BottlesEnvironment,
    BottlesEnvironmentError,
    scan_bottles_environment,
)
from .catalog import CatalogError, scan_catalog
from .guard import (
    GuardError,
    bottle_deployment_name,
    resolve_destination,
    validate_request,
)
from .logging_model import FILTERS, make_record, matches_filter
from .model import (
    BackendId,
    ExecutionOutcome,
    GameRecord,
    LogRecord,
    MaterializationOutcome,
    MaterializationRequest,
    ProfileRecord,
    RunnerRecord,
    SaveSetRecord,
)
from .runners import RunnerCatalogError, scan_runners
from .save_sets import (
    SaveSetCatalogError,
    scan_save_sets,
)
from .shared_backend import (
    SharedBackendError,
    SharedBackendRecord,
    scan_shared_bottles_backend,
)
from .service import (
    ExecutionError,
    MaterializationError,
    execute,
    materialize,
)


_BACKEND_LABELS: dict[BackendId, str] = {
    "direct-wine": "Direct-Wine",
    "bottles": "Bottles",
    "windows": "Export for Windows",
    "base": "Base materialization only",
}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app)
        self.set_title(
            f"OfflineGameVault GUI {__version__}"
        )
        self.set_default_size(900, 840)

        self.collection_root = resolve_collection_root()
        self.games: tuple[GameRecord, ...] = ()
        self.runners: tuple[RunnerRecord, ...] = ()
        self.current_backends: tuple[BackendId, ...] = ()
        self.current_profiles: tuple[ProfileRecord, ...] = ()
        self.current_runners: tuple[RunnerRecord, ...] = ()
        self.current_save_sets: tuple[SaveSetRecord, ...] = ()
        self.save_sets_by_capsule: dict[
            str, tuple[SaveSetRecord, ...]
        ] = {}
        self.save_warnings_by_capsule: dict[
            str, tuple[str, ...]
        ] = {}
        self.bottles_environment: BottlesEnvironment | None = None
        self.bottles_backend: SharedBackendRecord | None = None
        self.bottles_error: str | None = None
        self.destination_parent: Path | None = None
        self.busy = False
        self.log_records: list[LogRecord] = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)
        root.append(Adw.HeaderBar())

        page_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
        )
        root.append(page_scroll)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=24,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        page_scroll.set_child(content)

        title = Gtk.Label(
            label="Materialize and run from the Vault",
            xalign=0,
        )
        title.add_css_class("title-1")
        content.append(title)

        subtitle = Gtk.Label(
            label=(
                "The backend and runner are independent selections. "
                "Choose a backend, profile, runner, and save set. "
                "The default is No save; a save set is restored "
                "only when selected explicitly."
            ),
            xalign=0,
            wrap=True,
        )
        subtitle.add_css_class("dim-label")
        content.append(subtitle)

        vault_group = Adw.PreferencesGroup(title="File")
        content.append(vault_group)
        vault_row = Adw.ActionRow(
            title="Read-only during materialization",
            subtitle=str(self.collection_root),
        )
        vault_row.add_prefix(
            Gtk.Image.new_from_icon_name(
                "changes-prevent-symbolic"
            )
        )
        vault_group.add(vault_row)

        selection_group = Adw.PreferencesGroup(title="Selection")
        content.append(selection_group)

        self.game_row = Adw.ComboRow(title="Game")
        self.game_row.connect(
            "notify::selected",
            self._on_game_selected,
        )
        selection_group.add(self.game_row)

        self.backend_row = Adw.ComboRow(title="Backend")
        self.backend_row.connect(
            "notify::selected",
            self._on_backend_selected,
        )
        selection_group.add(self.backend_row)

        self.profile_row = Adw.ComboRow(title="Source profile")
        self.profile_row.connect(
            "notify::selected",
            self._on_profile_selected,
        )
        selection_group.add(self.profile_row)

        self.runner_row = Adw.ComboRow(title="Runner")
        self.runner_row.connect(
            "notify::selected",
            self._on_runner_selected,
        )
        selection_group.add(self.runner_row)

        self.save_row = Adw.ComboRow(title="Save set")
        self.save_row.set_subtitle(
            "No save is the default"
        )
        self.save_row.connect(
            "notify::selected",
            self._on_save_selected,
        )
        selection_group.add(self.save_row)

        self.operation_row = Adw.ActionRow(
            title="Planned operation",
            subtitle="Waiting for selection",
        )
        selection_group.add(self.operation_row)

        destination_group = Adw.PreferencesGroup(title="Destination")
        content.append(destination_group)

        self.destination_row = Adw.ActionRow(
            title="Parent folder",
            subtitle="Not selected",
        )
        choose_button = Gtk.Button(
            label="Choose folder…",
            valign=Gtk.Align.CENTER,
        )
        choose_button.connect(
            "clicked",
            self._choose_destination,
        )
        self.destination_row.add_suffix(choose_button)
        self.destination_row.set_activatable_widget(
            choose_button
        )
        destination_group.add(self.destination_row)

        self.exact_destination_row = Adw.ActionRow(
            title="Exact destination",
            subtitle="Calculated from backend, profile, and runner",
        )
        destination_group.add(self.exact_destination_row)

        self.bottle_destination_row = Adw.ActionRow(
            title="Managed bottle",
            subtitle="Not applicable",
        )
        destination_group.add(self.bottle_destination_row)

        action_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.END,
        )
        content.append(action_box)

        self.spinner = Gtk.Spinner()
        action_box.append(self.spinner)

        self.materialize_button = Gtk.Button(
            label="Materialize"
        )
        self.materialize_button.add_css_class(
            "suggested-action"
        )
        self.materialize_button.connect(
            "clicked",
            self._start_materialization,
        )
        self.materialize_button.set_sensitive(False)
        action_box.append(self.materialize_button)

        self.execute_button = Gtk.Button(
            label="Run"
        )
        self.execute_button.connect(
            "clicked",
            self._start_execution,
        )
        self.execute_button.set_sensitive(False)
        action_box.append(self.execute_button)

        status_group = Adw.PreferencesGroup(title="Status")
        content.append(status_group)
        self.status_row = Adw.ActionRow(
            title="Inicializando",
            subtitle="Reading catalog and runners",
        )
        status_group.add(self.status_row)

        log_header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=10,
        )
        content.append(log_header)

        log_title = Gtk.Label(
            label="Live log",
            xalign=0,
            hexpand=True,
        )
        log_title.add_css_class("heading")
        log_header.append(log_title)

        log_header.append(Gtk.Label(label="Filtro:"))
        self.log_filter = Gtk.DropDown(
            model=Gtk.StringList.new(list(FILTERS))
        )
        self.log_filter.set_selected(0)
        self.log_filter.connect(
            "notify::selected",
            self._on_filter_changed,
        )
        log_header.append(self.log_filter)

        clear_button = Gtk.Button(label="Clear")
        clear_button.connect(
            "clicked",
            self._clear_log_clicked,
        )
        log_header.append(clear_button)

        self.log_view = Gtk.TextView(
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
            top_margin=10,
            bottom_margin=10,
            left_margin=10,
            right_margin=10,
        )
        log_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            min_content_height=260,
            vexpand=True,
        )
        log_scroll.set_child(self.log_view)
        log_frame = Gtk.Frame()
        log_frame.set_child(log_scroll)
        content.append(log_frame)

        privacy_note = Gtk.Label(
            label=(
                "The log is kept in memory for this session. "
                "Execution runs outside the materialization sandbox "
                "to preserve display, audio, and controller access; the Vault is "
                "resealed before and after execution."
            ),
            xalign=0,
            wrap=True,
        )
        privacy_note.add_css_class("dim-label")
        content.append(privacy_note)

        self._load_catalog()

    def _selected_filter(self) -> str:
        index = self.log_filter.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(FILTERS)
        ):
            return "TODOS"
        return FILTERS[index]

    def _append_to_buffer(self, text: str) -> None:
        buffer = self.log_view.get_buffer()
        end = buffer.get_end_iter()
        buffer.insert(end, text)
        end = buffer.get_end_iter()
        mark = buffer.create_mark(None, end, False)
        self.log_view.scroll_mark_onscreen(mark)
        buffer.delete_mark(mark)

    def _append_record(self, record: LogRecord) -> bool:
        self.log_records.append(record)
        if matches_filter(
            record,
            self._selected_filter(),
        ):
            self._append_to_buffer(record.render())
        return GLib.SOURCE_REMOVE

    def _internal_log(
        self,
        message: str,
        *,
        level: str = "INFO",
    ) -> None:
        self._append_record(
            make_record(message, level=level)
        )

    def _rebuild_log(self) -> None:
        selected = self._selected_filter()
        text = "".join(
            record.render()
            for record in self.log_records
            if matches_filter(record, selected)
        )
        self.log_view.get_buffer().set_text(text)

    def _on_filter_changed(
        self,
        *_args: object,
    ) -> None:
        self._rebuild_log()

    def _clear_log_clicked(
        self,
        _button: Gtk.Button,
    ) -> None:
        self.log_records.clear()
        self.log_view.get_buffer().set_text("")

    def _load_catalog(self) -> None:
        try:
            self.games, catalog_warnings = scan_catalog(
                self.collection_root
            )
            self.runners, runner_warnings = scan_runners(
                self.collection_root
            )
            save_warnings: list[str] = []
            self.save_sets_by_capsule = {}
            self.save_warnings_by_capsule = {}
            for game in self.games:
                try:
                    records, warnings = scan_save_sets(
                        self.collection_root,
                        capsule_path=game.capsule_path,
                        capsule_id=game.capsule_id,
                    )
                except SaveSetCatalogError as exc:
                    records = ()
                    warnings = (str(exc),)
                self.save_sets_by_capsule[game.capsule_id] = records
                self.save_warnings_by_capsule[
                    game.capsule_id
                ] = warnings
                save_warnings.extend(warnings)
        except (CatalogError, RunnerCatalogError) as exc:
            self.status_row.set_title("File unavailable")
            self.status_row.set_subtitle(str(exc))
            self._internal_log(str(exc), level="ERROR")
            return

        bottles_warnings: list[str] = []
        try:
            self.bottles_backend = scan_shared_bottles_backend(
                self.collection_root
            )
            self.bottles_environment = scan_bottles_environment()
            if (
                self.bottles_environment.application_ref
                != self.bottles_backend.application_ref
                or self.bottles_environment.application_commit
                != self.bottles_backend.application_commit
            ):
                raise BottlesEnvironmentError(
                    "The Flatpak installation does not match the "
                    "preserved Bottles shared backend"
                )
            self.bottles_error = None
            self._internal_log(
                (
                    "Bottles detected and bound to the vault: "
                    f"{self.bottles_environment.application_ref}; "
                    f"commit {self.bottles_environment.application_commit}; "
                    f"{len(self.bottles_environment.installed_runners)} "
                    "installed runner(s)."
                )
            )
            self._internal_log(
                (
                    "Shared-backend Bottles: "
                    f"{self.bottles_backend.digest}; "
                    f"{self.bottles_backend.version}."
                )
            )
            bottles_warnings.extend(
                self.bottles_environment.warnings
            )
        except (BottlesEnvironmentError, SharedBackendError) as exc:
            self.bottles_environment = None
            self.bottles_backend = None
            self.bottles_error = str(exc)
            bottles_warnings.append(
                "Bottles backend unavailable: " + str(exc)
            )

        self.game_row.set_model(
            Gtk.StringList.new(
                [game.label for game in self.games]
            )
        )
        self.game_row.set_selected(0)

        warnings = (
            *catalog_warnings,
            *runner_warnings,
            *save_warnings,
            *bottles_warnings,
        )
        self.status_row.set_title("Catalog loaded")
        self.status_row.set_subtitle(
            f"{len(self.games)} game(s); "
            f"{len(self.runners)} runner(s); "
            f"{sum(len(items) for items in self.save_sets_by_capsule.values())} "
            "save set(s); "
            f"{len(warnings)} warning(s)"
        )

        for warning in warnings:
            self._internal_log(warning, level="WARNING")
        if not warnings:
            self._internal_log(
                "Catalog, runners, save sets, and Bottles loaded without "
                "warnings."
            )

        self._update_backends()
        self._update_save_sets()
        self._update_destination()
        self._update_buttons()

    def _selected_game(self) -> GameRecord | None:
        index = self.game_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.games)
        ):
            return None
        return self.games[index]

    def _selected_backend(self) -> BackendId | None:
        index = self.backend_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.current_backends)
        ):
            return None
        return self.current_backends[index]

    def _selected_profile(self) -> ProfileRecord | None:
        index = self.profile_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.current_profiles)
        ):
            return None
        return self.current_profiles[index]

    def _selected_runner(self) -> RunnerRecord | None:
        backend = self._selected_backend()
        if backend not in {"direct-wine", "bottles"}:
            return None

        index = self.runner_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index >= len(self.current_runners)
        ):
            return None
        return self.current_runners[index]

    def _selected_save_set(self) -> SaveSetRecord | None:
        backend = self._selected_backend()
        if backend not in {"direct-wine", "bottles", "windows"}:
            return None

        index = self.save_row.get_selected()
        if (
            index == Gtk.INVALID_LIST_POSITION
            or index == 0
        ):
            return None

        record_index = index - 1
        if record_index >= len(self.current_save_sets):
            return None
        return self.current_save_sets[record_index]

    def _on_save_selected(
        self,
        *_args: object,
    ) -> None:
        self._update_destination()
        self._update_buttons()

    def _on_game_selected(
        self,
        *_args: object,
    ) -> None:
        self._update_backends()
        self._update_save_sets()
        self._update_destination()
        self._update_buttons()

    def _on_backend_selected(
        self,
        *_args: object,
    ) -> None:
        self._update_profiles()
        self._update_save_sets()
        self._update_destination()
        self._update_buttons()

    def _on_profile_selected(
        self,
        *_args: object,
    ) -> None:
        self._update_runners()
        self._update_destination()
        self._update_buttons()

    def _on_runner_selected(
        self,
        *_args: object,
    ) -> None:
        self._update_destination()
        self._update_buttons()

    def _update_backends(self) -> None:
        game = self._selected_game()
        backends: list[BackendId] = []

        if game and any(
            profile.backend_id == "direct-wine"
            for profile in game.profiles
        ):
            backends.append("direct-wine")
        if game and any(
            profile.backend_id == "bottles"
            for profile in game.profiles
        ):
            backends.append("bottles")
        if game and any(
            profile.backend_id == "windows"
            for profile in game.profiles
        ):
            backends.append("windows")
        if game:
            backends.append("base")

        self.current_backends = tuple(backends)
        self.backend_row.set_model(
            Gtk.StringList.new(
                [_BACKEND_LABELS[item] for item in self.current_backends]
            )
        )
        if self.current_backends:
            self.backend_row.set_selected(0)
        self._update_profiles()

    def _update_profiles(self) -> None:
        game = self._selected_game()
        backend = self._selected_backend()

        if not game or backend is None:
            profiles: tuple[ProfileRecord, ...] = ()
        elif backend in {"direct-wine", "bottles", "windows"}:
            profiles = tuple(
                profile
                for profile in game.profiles
                if profile.backend_id == backend
            )
        else:
            profiles = game.profiles

        self.current_profiles = profiles
        self.profile_row.set_model(
            Gtk.StringList.new(
                [profile.label for profile in profiles]
            )
        )
        if profiles:
            self.profile_row.set_selected(0)
        self._update_runners()

    def _update_runners(self) -> None:
        backend = self._selected_backend()
        profile = self._selected_profile()

        if backend in {"direct-wine", "bottles"}:
            runners = tuple(
                runner
                for runner in self.runners
                if runner.supports(backend)
            )
            self.current_runners = runners
            labels = []
            for runner in runners:
                label = runner.label
                if (
                    backend == "bottles"
                    and (
                        self.bottles_environment is None
                        or runner.runner_id
                        not in self.bottles_environment.installed_runners
                    )
                ):
                    label += " · not installed in Bottles"
                labels.append(label)
            if not labels:
                labels = [
                    (
                        "Bottles unavailable"
                        if backend == "bottles"
                        else "No compatible runners"
                    )
                ]
            self.runner_row.set_model(Gtk.StringList.new(labels))
            self.runner_row.set_sensitive(bool(runners) and not self.busy)

            selected = 0
            if profile and profile.default_runner_id:
                for index, runner in enumerate(runners):
                    if runner.runner_id == profile.default_runner_id:
                        selected = index
                        break
            if runners:
                self.runner_row.set_selected(selected)
        else:
            self.current_runners = ()
            self.runner_row.set_model(
                Gtk.StringList.new(["Not applicable"])
            )
            self.runner_row.set_selected(0)
            self.runner_row.set_sensitive(False)

    def _update_save_sets(self) -> None:
        game = self._selected_game()
        backend = self._selected_backend()

        if game is None:
            records: tuple[SaveSetRecord, ...] = ()
        else:
            records = self.save_sets_by_capsule.get(
                game.capsule_id,
                (),
            )

        self.current_save_sets = records
        baseline_clean = (
            game is None or game.baseline_state == "clean"
        )
        default_label = (
            "No save (default)"
            if baseline_clean
            else "State included in source"
        )
        labels = [
            default_label,
            *[record.label for record in records],
        ]
        self.save_row.set_model(Gtk.StringList.new(labels))
        self.save_row.set_selected(0)
        self.save_row.set_sensitive(
            backend in {"direct-wine", "bottles", "windows"}
            and bool(records)
            and not self.busy
        )

        if game is None:
            subtitle = "No game selected"
        elif backend not in {"direct-wine", "bottles", "windows"}:
            subtitle = "Not applicable to base materialization"
        elif records:
            state_label = (
                "No save by default"
                if game.baseline_state == "clean"
                else "source state may be included"
            )
            subtitle = (
                f"{len(records)} save set(s) available; {state_label}"
            )
        else:
            subtitle = (
                "No save sets registered; clean baseline"
                if game.baseline_state == "clean"
                else "No save sets registered; source state unclassified"
            )

        self.save_row.set_subtitle(subtitle)

    def _candidate_destination(self) -> Path | None:
        game = self._selected_game()
        backend = self._selected_backend()
        profile = self._selected_profile()
        runner = self._selected_runner()
        save_set = self._selected_save_set()

        if (
            self.destination_parent is None
            or game is None
            or backend is None
            or profile is None
        ):
            return None
        if backend in {"direct-wine", "bottles"} and runner is None:
            return None

        try:
            return resolve_destination(
                self.destination_parent.resolve(strict=True),
                capsule_id=game.capsule_id,
                profile_id=profile.profile_id,
                backend_id=backend,
                runner=runner,
                save_set_id=(
                    save_set.save_set_id
                    if save_set is not None
                    else None
                ),
            )
        except (GuardError, OSError):
            return None

    def _update_destination(self) -> None:
        destination = self._candidate_destination()
        if self.destination_parent is not None:
            self.destination_row.set_subtitle(
                str(self.destination_parent)
            )
        else:
            self.destination_row.set_subtitle(
                "Not selected"
            )

        if destination is not None:
            self.exact_destination_row.set_subtitle(
                str(destination)
            )
        else:
            self.exact_destination_row.set_subtitle(
                "Calculated from backend, profile, and runner"
            )

        backend = self._selected_backend()
        game = self._selected_game()
        profile = self._selected_profile()
        runner = self._selected_runner()
        save_set = self._selected_save_set()
        if (
            backend == "bottles"
            and game is not None
            and profile is not None
            and runner is not None
            and self.bottles_environment is not None
        ):
            try:
                name = bottle_deployment_name(
                    capsule_id=game.capsule_id,
                    profile_id=profile.profile_id,
                    runner_id=runner.runner_id,
                    save_set_id=(
                        save_set.save_set_id
                        if save_set is not None
                        else None
                    ),
                )
                managed = self.bottles_environment.bottles_path / name
                self.bottle_destination_row.set_subtitle(str(managed))
            except GuardError as exc:
                self.bottle_destination_row.set_subtitle(str(exc))
        elif backend == "bottles" and self.bottles_error:
            self.bottle_destination_row.set_subtitle(self.bottles_error)
        else:
            self.bottle_destination_row.set_subtitle("Not applicable")

    def _make_request(
        self,
    ) -> MaterializationRequest | None:
        game = self._selected_game()
        backend = self._selected_backend()
        profile = self._selected_profile()
        runner = self._selected_runner()
        save_set = self._selected_save_set()
        destination = self._candidate_destination()

        if (
            game is None
            or backend is None
            or profile is None
            or destination is None
        ):
            return None
        if backend in {"direct-wine", "bottles"} and runner is None:
            return None
        if backend == "bottles" and self.bottles_environment is None:
            return None

        return MaterializationRequest(
            collection_root=self.collection_root,
            capsule_path=game.capsule_path,
            capsule_id=game.capsule_id,
            profile_id=profile.profile_id,
            backend_id=backend,
            runner=runner,
            destination=destination,
            bottles_path=(
                self.bottles_environment.bottles_path
                if backend == "bottles"
                and self.bottles_environment is not None
                else None
            ),
            bottles_backend=(
                self.bottles_backend
                if backend == "bottles"
                else None
            ),
            save_set=save_set,
        )

    def _update_buttons(self) -> None:
        request = self._make_request()
        materialize_allowed = False
        execute_allowed = False
        message = ""
        profile = self._selected_profile()
        backend = self._selected_backend()
        runner = self._selected_runner()
        save_set = self._selected_save_set()
        save_label = (
            save_set.display_name
            if save_set is not None
            else "No save"
        )

        if backend == "direct-wine" and profile and runner:
            self.operation_row.set_subtitle(
                f"Direct-Wine · {runner.runner_id} · {save_label} · playable"
            )
        elif backend == "bottles" and profile and runner:
            self.operation_row.set_subtitle(
                f"Bottles · {runner.runner_id} · {save_label} · playable"
            )
        elif backend == "windows" and profile:
            self.operation_row.set_subtitle(
                f"Windows · {save_label} · candidate export"
            )
        elif backend == "base" and profile:
            self.operation_row.set_subtitle(
                "Base: copy and verify objects; no execution"
            )
        else:
            self.operation_row.set_subtitle(
                "Waiting for selection"
            )

        if backend == "bottles" and self.bottles_environment is None:
            message = self.bottles_error or (
                "Bottles is not available on this host"
            )
        elif (
            backend == "bottles"
            and runner is not None
            and self.bottles_environment is not None
            and runner.runner_id
            not in self.bottles_environment.installed_runners
        ):
            message = (
                f"Runner {runner.runner_id} is preserved, "
                "but is not installed in Bottles."
            )
        elif request and not self.busy:
            try:
                validated = validate_request(request)
                materialize_allowed = True
                execute_allowed = (
                    validated.backend_id in {"direct-wine", "bottles"}
                    and validated.reusable
                )

                if validated.reusable:
                    message = (
                        "Recognized destination. It can be verified, "
                        "reused, or run."
                    )
                elif validated.backend_id == "bottles":
                    if validated.overlay_required:
                        message = (
                            f"Bottles with {runner.runner_id}: "
                            "derived variant; it does not inherit acceptance from "
                            f"{validated.default_runner_id}."
                        )
                    else:
                        message = (
                            f"Bottles with {runner.runner_id}: runner "
                            "declared by the capsule."
                        )
                elif validated.backend_id == "windows":
                    message = (
                        "A candidate Windows export will be created. "
                        "It will not be run or marked as verified."
                    )
                elif validated.mode == "base":
                    message = (
                        "Base materialization available; it creates no scripts "
                        "and enables no execution."
                    )
                elif validated.overlay_required:
                    message = (
                        f"Direct-Wine with {runner.runner_id}: "
                        "derived and untested combination; it does not inherit acceptance "
                        f"from {validated.default_runner_id}."
                    )
                else:
                    message = (
                        f"Direct-Wine with {runner.runner_id}: original "
                        "capsule contract."
                    )
            except GuardError as exc:
                message = str(exc)

        self.materialize_button.set_sensitive(materialize_allowed)
        self.execute_button.set_sensitive(execute_allowed)

        if message and not self.busy:
            self.status_row.set_title("Request review")
            self.status_row.set_subtitle(message)

        if not self.busy:
            self.game_row.set_sensitive(True)
            self.backend_row.set_sensitive(True)
            self.profile_row.set_sensitive(True)
            self.runner_row.set_sensitive(
                backend in {"direct-wine", "bottles"}
                and bool(self.current_runners)
            )
            self.save_row.set_sensitive(
                backend in {"direct-wine", "bottles", "windows"}
                and bool(self.current_save_sets)
            )

    def _choose_destination(
        self,
        _button: Gtk.Button,
    ) -> None:
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog()
            dialog.set_title(
                "Choose parent folder"
            )
            dialog.select_folder(
                self,
                None,
                self._folder_selected,
            )
            return

        chooser = Gtk.FileChooserNative(
            title="Choose parent folder",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            accept_label="Choose",
            cancel_label="Cancel",
        )
        chooser.connect(
            "response",
            self._legacy_folder_selected,
        )
        chooser.show()

    def _folder_selected(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
    ) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        self._accept_folder(folder)

    def _legacy_folder_selected(
        self,
        chooser: Gtk.FileChooserNative,
        response: int,
    ) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            self._accept_folder(chooser.get_file())
        chooser.destroy()

    def _accept_folder(
        self,
        folder: Gio.File | None,
    ) -> None:
        if folder is None:
            return

        path = folder.get_path()
        if not path:
            self.status_row.set_title(
                "Non-local destination"
            )
            self.status_row.set_subtitle(
                f"{__version__} accepts local directories only"
            )
            return

        self.destination_parent = Path(path)
        self._update_destination()
        self._update_buttons()

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        if value:
            self.spinner.start()
            self.game_row.set_sensitive(False)
            self.backend_row.set_sensitive(False)
            self.profile_row.set_sensitive(False)
            self.runner_row.set_sensitive(False)
            self.save_row.set_sensitive(False)
            self.materialize_button.set_sensitive(False)
            self.execute_button.set_sensitive(False)
        else:
            self.spinner.stop()
            self._update_buttons()

    def _start_materialization(
        self,
        _button: Gtk.Button,
    ) -> None:
        request = self._make_request()
        if request is None:
            return

        try:
            selected = validate_request(request)
        except GuardError as exc:
            self.status_row.set_title("Request rejected")
            self.status_row.set_subtitle(str(exc))
            return

        self.log_records.clear()
        self.log_view.get_buffer().set_text("")
        if selected.backend_id == "bottles":
            label = "Starting Bottles deployment."
        elif selected.backend_id == "windows":
            label = "Starting candidate Windows export."
        elif selected.mode == "playable":
            label = "Starting playable materialization."
        else:
            label = "Starting base materialization."
        self._internal_log(label)
        self._set_busy(True)
        self.status_row.set_title(
            "Deploying to Bottles"
            if selected.backend_id == "bottles"
            else (
                "Exporting for Windows"
                if selected.backend_id == "windows"
                else "Materializing"
            )
        )
        self.status_row.set_subtitle(
            "Live stdout and stderr output"
        )

        threading.Thread(
            target=self._materialization_worker,
            args=(request,),
            daemon=True,
        ).start()

    def _materialization_worker(
        self,
        request: MaterializationRequest,
    ) -> None:
        def on_log(record: LogRecord) -> None:
            GLib.idle_add(
                self._append_record,
                record,
            )

        try:
            outcome = materialize(
                request,
                on_log=on_log,
            )
        except (
            GuardError,
            MaterializationError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Materialization failed",
                str(exc),
            )
            return

        GLib.idle_add(
            self._finish_materialization_success,
            outcome,
        )

    def _start_execution(
        self,
        _button: Gtk.Button,
    ) -> None:
        request = self._make_request()
        if request is None:
            return

        try:
            selected = validate_request(request)
        except GuardError as exc:
            self.status_row.set_title("Execution rejected")
            self.status_row.set_subtitle(str(exc))
            return
        if not selected.reusable:
            self.status_row.set_title("Execution rejected")
            self.status_row.set_subtitle(
                "This variant must be materialized first"
            )
            return

        runner = selected.runner
        assert runner is not None
        backend_label = _BACKEND_LABELS[selected.backend_id]
        self._internal_log(
            f"Starting {backend_label} with {runner.runner_id}."
        )
        self._set_busy(True)
        self.status_row.set_title("Running")
        self.status_row.set_subtitle(
            f"{backend_label} · {runner.runner_id}"
        )

        threading.Thread(
            target=self._execution_worker,
            args=(request,),
            daemon=True,
        ).start()

    def _execution_worker(
        self,
        request: MaterializationRequest,
    ) -> None:
        def on_log(record: LogRecord) -> None:
            GLib.idle_add(
                self._append_record,
                record,
            )

        try:
            outcome = execute(
                request,
                on_log=on_log,
            )
        except (
            GuardError,
            ExecutionError,
            OSError,
            RuntimeError,
        ) as exc:
            GLib.idle_add(
                self._finish_error,
                "Execution failed",
                str(exc),
            )
            return

        GLib.idle_add(
            self._finish_execution_success,
            outcome,
        )

    def _finish_error(
        self,
        title: str,
        message: str,
    ) -> bool:
        self._set_busy(False)
        self.status_row.set_title(title)
        self.status_row.set_subtitle(message)
        self._internal_log(message, level="ERROR")
        return GLib.SOURCE_REMOVE

    def _finish_materialization_success(
        self,
        outcome: MaterializationOutcome,
    ) -> bool:
        self._set_busy(False)
        if outcome.backend_id == "bottles":
            self.status_row.set_title("Single-instance Bottles deployment prepared")
            self.status_row.set_subtitle(str(outcome.destination))
        elif outcome.backend_id == "windows":
            self.status_row.set_title("Candidate Windows export created")
            self.status_row.set_subtitle(str(outcome.destination))
        else:
            self.status_row.set_title(
                (
                    "Playable materialization created"
                    if outcome.mode == "playable"
                    else "Base materialization created"
                )
            )
            self.status_row.set_subtitle(str(outcome.destination))
        self._internal_log(f"Receipt: {outcome.receipt_path}")

        if outcome.backend_id == "bottles":
            self._internal_log(f"Backend: {outcome.backend_id}")
            self._internal_log(f"Runner: {outcome.runner_id}")
            self._internal_log(f"Bottle: {outcome.bottle_name}")
            self._internal_log(
                f"Game data: {outcome.deployment_path}"
            )
            self._internal_log(
                f"Control and launcher: {outcome.destination}"
            )
            self._internal_log(f"Play: {outcome.launcher_path}")
            self._internal_log(
                f"Uninstall: {outcome.uninstaller_path}"
            )
        elif outcome.backend_id == "windows":
            self._internal_log("Backend: Windows (export, not run)")
            self._internal_log(f"Launcher: {outcome.launcher_path}")
            self._internal_log(
                f"State installer: {outcome.destination / 'INSTALL_STATE.ps1'}"
            )
        elif outcome.mode == "playable":
            self._internal_log(f"Backend: {outcome.backend_id}")
            self._internal_log(f"Runner: {outcome.runner_id}")
            self._internal_log(f"Play: {outcome.launcher_path}")
            self._internal_log(
                f"Uninstall: {outcome.uninstaller_path}"
            )
        else:
            self._internal_log(
                "Base result: no launchers were expected.",
                level="WARNING",
            )

        self._update_destination()
        return GLib.SOURCE_REMOVE

    def _finish_execution_success(
        self,
        outcome: ExecutionOutcome,
    ) -> bool:
        self._set_busy(False)
        self.status_row.set_title("Execution finished")
        backend_label = _BACKEND_LABELS[outcome.backend_id]
        self.status_row.set_subtitle(
            f"{backend_label} · {outcome.runner_id} · normal exit"
        )
        self._internal_log(
            f"Game process rc: {outcome.game_process_rc}"
        )
        if outcome.wineserver_wait_rc is not None:
            self._internal_log(
                f"Wineserver wait rc: {outcome.wineserver_wait_rc}"
            )
        self._update_buttons()
        return GLib.SOURCE_REMOVE


class VaultApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=(
                "io.github.pbano."
                "OfflineGameVault.Gui"
            ),
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self)
        window.present()


def main() -> int:
    app = VaultApplication()
    return int(app.run(None))
