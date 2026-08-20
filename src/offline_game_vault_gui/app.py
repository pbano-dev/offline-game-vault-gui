from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys
from typing import Any, Callable

try:
    from PySide6.QtCore import (
        QObject,
        QRunnable,
        QRect,
        QSize,
        Qt,
        QThreadPool,
        Signal,
        Slot,
    )
    from PySide6.QtGui import (
        QCloseEvent,
        QFont,
        QFontMetrics,
        QPainter,
        QPalette,
    )
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListView,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QStyle,
        QStyledItemDelegate,
        QStyleFactory,
        QStyleOptionComboBox,
        QStyleOptionViewItem,
        QStylePainter,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - host dependency
    raise RuntimeError(
        "PySide6 is required to run the Qt Widgets GUI"
    ) from exc

from . import __version__
from .config import Preferences
from .core import CoreClient, CoreError, CoreProbe
from .model import (
    Backend,
    CompositionRequest,
    GameRecord,
    RunnerRecord,
    SourceProfile,
    StateSelectionRecord,
)
from .service import CompositionService, ServiceError


APP_ID = "io.github.pbano.OfflineGameVault.Gui"
PRIMARY_ROLE = int(Qt.ItemDataRole.UserRole) + 1
SECONDARY_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class RichItemDelegate(QStyledItemDelegate):
    """Two-line popup delegate with wrapping and no ellipsis."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: Any,
    ) -> None:
        local = QStyleOptionViewItem(option)
        self.initStyleOption(local, index)
        primary = (
            index.data(PRIMARY_ROLE)
            or index.data(Qt.ItemDataRole.DisplayRole)
            or ""
        )
        secondary = index.data(SECONDARY_ROLE) or ""
        local.text = ""
        style = (
            local.widget.style()
            if local.widget is not None
            else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            local,
            painter,
            local.widget,
        )
        selected = bool(
            local.state & QStyle.StateFlag.State_Selected
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if selected
            else QPalette.ColorRole.Text
        )
        secondary_role = (
            QPalette.ColorRole.HighlightedText
            if selected
            else QPalette.ColorRole.PlaceholderText
        )
        rect = local.rect.adjusted(10, 6, -10, -6)
        painter.save()

        primary_font = QFont(local.font)
        primary_font.setBold(True)
        painter.setFont(primary_font)
        painter.setPen(local.palette.color(role))
        metrics = QFontMetrics(primary_font)
        measured = metrics.boundingRect(
            QRect(0, 0, max(rect.width(), 80), 10_000),
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.TextFlag.TextWordWrap),
            str(primary),
        )
        primary_rect = QRect(
            rect.x(),
            rect.y(),
            rect.width(),
            measured.height(),
        )
        painter.drawText(
            primary_rect,
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.AlignmentFlag.AlignTop)
            | int(Qt.TextFlag.TextWordWrap),
            str(primary),
        )

        if secondary:
            secondary_font = QFont(local.font)
            secondary_font.setPointSizeF(
                max(secondary_font.pointSizeF() - 1.0, 7.0)
            )
            painter.setFont(secondary_font)
            painter.setPen(local.palette.color(secondary_role))
            secondary_rect = QRect(
                rect.x(),
                primary_rect.bottom() + 4,
                rect.width(),
                max(rect.height() - primary_rect.height() - 4, 1),
            )
            painter.drawText(
                secondary_rect,
                int(Qt.AlignmentFlag.AlignLeft)
                | int(Qt.AlignmentFlag.AlignTop)
                | int(Qt.TextFlag.TextWordWrap),
                str(secondary),
            )
        painter.restore()

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: Any,
    ) -> QSize:
        primary = str(
            index.data(PRIMARY_ROLE)
            or index.data(Qt.ItemDataRole.DisplayRole)
            or ""
        )
        secondary = str(index.data(SECONDARY_ROLE) or "")
        width = 520
        if option.widget is not None:
            width = max(option.widget.width() - 28, 260)

        primary_font = QFont(option.font)
        primary_font.setBold(True)
        primary_height = QFontMetrics(primary_font).boundingRect(
            QRect(0, 0, width, 10_000),
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.TextFlag.TextWordWrap),
            primary,
        ).height()

        secondary_height = 0
        if secondary:
            secondary_font = QFont(option.font)
            secondary_font.setPointSizeF(
                max(secondary_font.pointSizeF() - 1.0, 7.0)
            )
            secondary_height = QFontMetrics(
                secondary_font
            ).boundingRect(
                QRect(0, 0, width, 10_000),
                int(Qt.AlignmentFlag.AlignLeft)
                | int(Qt.TextFlag.TextWordWrap),
                secondary,
            ).height() + 4
        return QSize(
            width + 20,
            max(42, primary_height + secondary_height + 12),
        )


class RichComboBox(QComboBox):
    """Combo box whose selected value and popup preserve full labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        view = QListView(self)
        view.setWordWrap(True)
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setUniformItemSizes(False)
        view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        view.setItemDelegate(RichItemDelegate(view))
        self.setView(view)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(24)
        self.setMinimumWidth(280)
        self.currentIndexChanged.connect(self._update_height)
        self._update_height()

    def add_rich_item(
        self,
        primary: str,
        secondary: str = "",
        payload: object | None = None,
    ) -> None:
        self.addItem(primary, payload)
        index = self.count() - 1
        self.setItemData(index, primary, PRIMARY_ROLE)
        self.setItemData(index, secondary, SECONDARY_ROLE)
        tooltip = primary if not secondary else f"{primary}\n{secondary}"
        self.setItemData(
            index,
            tooltip,
            Qt.ItemDataRole.ToolTipRole,
        )
        self._update_height()

    def current_payload(self) -> object | None:
        return self.currentData(Qt.ItemDataRole.UserRole)

    def showPopup(self) -> None:
        self.view().setMinimumWidth(max(self.width(), 540))
        super().showPopup()

    def _update_height(self, *_args: object) -> None:
        primary = str(
            self.currentData(PRIMARY_ROLE) or self.currentText()
        )
        width = max(self.width() - 58, 260)
        font = QFont(self.font())
        font.setBold(True)
        rect = QFontMetrics(font).boundingRect(
            QRect(0, 0, width, 10_000),
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.TextFlag.TextWordWrap),
            primary,
        )
        self.setMinimumHeight(max(rect.height() + 18, 40))
        self.updateGeometry()
        self.update()

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        option.currentText = ""
        painter.drawComplexControl(
            QStyle.ComplexControl.CC_ComboBox,
            option,
        )
        edit = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        ).adjusted(2, 2, -2, -2)
        primary = str(
            self.currentData(PRIMARY_ROLE) or self.currentText()
        )
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(
            self.palette().color(QPalette.ColorRole.Text)
        )
        painter.drawText(
            edit,
            int(Qt.AlignmentFlag.AlignLeft)
            | int(Qt.AlignmentFlag.AlignVCenter)
            | int(Qt.TextFlag.TextWordWrap),
            primary,
        )


class PathEdit(QWidget):
    def __init__(
        self,
        *,
        placeholder: str = "",
        button_text: str = "Browse…",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(placeholder)
        self.button = QToolButton(self)
        self.button.setText(button_text)
        self.button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:
        self.edit.setText(value)

    def setPlaceholderText(self, value: str) -> None:
        self.edit.setPlaceholderText(value)

    def setReadOnly(self, value: bool) -> None:
        self.edit.setReadOnly(value)
        self.button.setEnabled(not value)


class WorkerSignals(QObject):
    result = Signal(object)
    failed = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function: Callable[[], object]) -> None:
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            value = self.function()
        except Exception as exc:
            self.signals.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )
        else:
            self.signals.result.emit(value)
        finally:
            self.signals.finished.emit()


class MainWindow(QMainWindow):
    def __init__(
        self,
        preferences: Preferences,
        service: CompositionService | None,
        probe: CoreProbe | None,
        startup_error: str | None,
    ) -> None:
        super().__init__()
        self.preferences = preferences
        self.service = service
        self.probe = probe
        self.games: tuple[GameRecord, ...] = ()
        self.runners: tuple[RunnerRecord, ...] = ()
        self.visible_runners: tuple[RunnerRecord, ...] = ()
        self.state_selections: tuple[StateSelectionRecord, ...] = ()
        self.last_destination: Path | None = None
        self._bottle_name_manual = False
        self._busy_depth = 0
        self._workers: set[Worker] = set()
        self._rows: dict[str, tuple[QLabel, QWidget]] = {}

        self.setWindowTitle(
            f"Offline Game Vault GUI {__version__}"
        )
        self.resize(980, 860)
        self.setMinimumSize(720, 620)
        self._build_ui()
        self._connect_signals()
        self._set_core_status()
        self._backend_changed()

        if startup_error:
            self._set_status("Core unavailable")
            self._set_log(startup_error)
        elif (
            self.service is not None
            and self.collection_edit.text().strip()
        ):
            self._refresh()
        else:
            self._set_status("Ready")

    def _build_ui(self) -> None:
        page = QWidget(self)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Offline Game Vault", page)
        title_font = QFont(title.font())
        title_font.setPointSizeF(
            title_font.pointSizeF() + 4
        )
        title_font.setBold(True)
        title.setFont(title_font)
        self.refresh_button = QPushButton("Refresh", page)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.refresh_button)
        outer.addLayout(header)

        setup = QGroupBox("Vault and core", page)
        setup_form = self._new_form(setup)
        self.collection_edit = PathEdit(
            placeholder="Collection root",
            parent=setup,
        )
        self.collection_edit.setText(
            self.preferences.collection_root
        )
        self.destination_parent_edit = PathEdit(
            placeholder="Default destination parent",
            parent=setup,
        )
        self.destination_parent_edit.setText(
            self.preferences.destination_parent
        )

        core_widget = QWidget(setup)
        core_layout = QHBoxLayout(core_widget)
        core_layout.setContentsMargins(0, 0, 0, 0)
        self.core_value = QLabel("Not selected", core_widget)
        self.core_value.setWordWrap(True)
        self.core_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.core_button = QPushButton(
            "Select checkout…",
            core_widget,
        )
        core_layout.addWidget(self.core_value, 1)
        core_layout.addWidget(self.core_button)

        self._add_row(
            setup_form,
            "Collection root",
            self.collection_edit,
            "collection",
        )
        self._add_row(
            setup_form,
            "Default destination parent",
            self.destination_parent_edit,
            "destination_parent",
        )
        self._add_row(
            setup_form,
            "Selected core",
            core_widget,
            "core",
        )
        outer.addWidget(setup)

        request_group = QGroupBox(
            "Composition request",
            page,
        )
        request_form = self._new_form(request_group)
        self.game_combo = RichComboBox(request_group)
        self.backend_combo = QComboBox(request_group)
        self.backend_combo.addItem("Bottles", "bottles")
        self.backend_combo.addItem(
            "Direct-Wine",
            "direct-wine",
        )
        self.backend_combo.addItem("UMU/Proton", "umu")
        self.profile_combo = RichComboBox(request_group)
        self.runner_combo = RichComboBox(request_group)
        self.save_combo = RichComboBox(request_group)
        self.umu_value = QLabel(
            "Loaded when UMU is selected; diagnostic only",
            request_group,
        )
        self.umu_value.setWordWrap(True)
        self.umu_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._add_row(
            request_form,
            "Game",
            self.game_combo,
            "game",
        )
        self._add_row(
            request_form,
            "Backend",
            self.backend_combo,
            "backend",
        )
        self._add_row(
            request_form,
            "Source layout (Auto recommended)",
            self.profile_combo,
            "profile",
        )
        self._add_row(
            request_form,
            "Preserved runner",
            self.runner_combo,
            "runner",
        )
        self._add_row(
            request_form,
            "Initial game state",
            self.save_combo,
            "save",
        )
        self._add_row(
            request_form,
            "Resolved UMU component sets",
            self.umu_value,
            "umu",
        )
        outer.addWidget(request_group)

        target_group = QGroupBox("Writable target", page)
        target_form = self._new_form(target_group)
        self.destination_edit = PathEdit(
            placeholder="New writable materialization destination",
            parent=target_group,
        )
        self.bottle_name_edit = QLineEdit(target_group)
        self.bottle_name_edit.setPlaceholderText(
            "Portable Bottles derivative name"
        )
        self.bottles_path_value = QLabel(
            "Discovered by the core",
            target_group,
        )
        self.bottles_path_value.setWordWrap(True)
        self.bottles_path_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.state_backup_edit = PathEdit(
            placeholder=(
                "Verified state backup, when required "
                "by the capsule"
            ),
            parent=target_group,
        )
        self.arguments_edit = QLineEdit(target_group)
        self.arguments_edit.setPlaceholderText(
            "Additional Direct-Wine / UMU play arguments"
        )
        self.removal_arguments_edit = QLineEdit(
            target_group
        )
        self.removal_arguments_edit.setPlaceholderText(
            "Generated Remove arguments"
        )

        self._add_row(
            target_form,
            "Materialization destination",
            self.destination_edit,
            "destination",
        )
        self._add_row(
            target_form,
            "Bottles derivative name",
            self.bottle_name_edit,
            "bottle_name",
        )
        self._add_row(
            target_form,
            "Managed Bottles directory",
            self.bottles_path_value,
            "bottles_path",
        )
        self._add_row(
            target_form,
            "Selected state backup",
            self.state_backup_edit,
            "state_backup",
        )
        self._add_row(
            target_form,
            "Additional play arguments",
            self.arguments_edit,
            "arguments",
        )
        self._add_row(
            target_form,
            "Generated Remove arguments",
            self.removal_arguments_edit,
            "removal_arguments",
        )
        outer.addWidget(target_group)

        actions_group = QGroupBox("Operations", page)
        actions = QHBoxLayout(actions_group)
        actions.setContentsMargins(12, 12, 12, 12)
        actions.setSpacing(8)
        self.materialize_button = QPushButton(
            "Materialize",
            actions_group,
        )
        self.materialize_play_button = QPushButton(
            "Materialize & Play",
            actions_group,
        )
        self.verify_button = QPushButton(
            "Verify",
            actions_group,
        )
        self.play_button = QPushButton(
            "Play",
            actions_group,
        )
        self.remove_button = QPushButton(
            "Remove",
            actions_group,
        )
        for button in (
            self.materialize_button,
            self.materialize_play_button,
            self.verify_button,
            self.play_button,
            self.remove_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        outer.addWidget(actions_group)

        result_group = QGroupBox("Result", page)
        result_layout = QVBoxLayout(result_group)
        result_layout.setContentsMargins(12, 12, 12, 12)
        self.status_label = QLabel("Ready", result_group)
        status_font = QFont(self.status_label.font())
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        self.status_label.setWordWrap(True)
        self.log = QPlainTextEdit(result_group)
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        monospace = QFont("monospace")
        monospace.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(monospace)
        self.log.setMinimumHeight(230)
        result_layout.addWidget(self.status_label)
        result_layout.addWidget(self.log, 1)
        outer.addWidget(result_group, 1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        self.setCentralWidget(scroll)

    def _new_form(self, parent: QWidget) -> QFormLayout:
        form = QFormLayout(parent)
        form.setContentsMargins(12, 12, 12, 12)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows
        )
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
        )
        return form

    def _add_row(
        self,
        form: QFormLayout,
        title: str,
        widget: QWidget,
        key: str,
    ) -> None:
        label = QLabel(title, widget.parentWidget())
        label.setWordWrap(True)
        form.addRow(label, widget)
        self._rows[key] = (label, widget)

    def _set_row_visible(
        self,
        key: str,
        visible: bool,
    ) -> None:
        label, widget = self._rows[key]
        label.setVisible(visible)
        widget.setVisible(visible)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self._refresh)
        self.collection_edit.button.clicked.connect(
            self._choose_collection
        )
        self.destination_parent_edit.button.clicked.connect(
            self._choose_destination_parent
        )
        self.destination_edit.button.clicked.connect(
            self._choose_destination
        )
        self.state_backup_edit.button.clicked.connect(
            self._choose_state_backup
        )
        self.core_button.clicked.connect(self._choose_core)
        self.game_combo.currentIndexChanged.connect(
            self._game_changed
        )
        self.backend_combo.currentIndexChanged.connect(
            self._backend_changed
        )
        self.bottle_name_edit.textEdited.connect(
            self._bottle_name_edited
        )
        self.save_combo.currentIndexChanged.connect(
            self._save_changed
        )
        self.materialize_button.clicked.connect(
            lambda: self._compose(False)
        )
        self.materialize_play_button.clicked.connect(
            lambda: self._compose(True)
        )
        self.verify_button.clicked.connect(
            lambda: self._operation("verify")
        )
        self.play_button.clicked.connect(
            lambda: self._operation("play")
        )
        self.remove_button.clicked.connect(
            lambda: self._operation("remove")
        )

    def _choose_collection(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Offline Game Vault collection",
            self.collection_edit.text() or str(Path.home()),
        )
        if selected:
            self.collection_edit.setText(selected)
            self._refresh()

    def _choose_destination_parent(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select default destination parent",
            self.destination_parent_edit.text()
            or str(Path.home()),
        )
        if selected:
            self.destination_parent_edit.setText(selected)
            self.preferences.destination_parent = selected
            self.preferences.save()
            self._update_default_target()

    def _choose_destination(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select destination parent",
            self.destination_parent_edit.text()
            or str(Path.home()),
        )
        if not selected:
            return
        game = self._selected_game()
        backend = self._selected_backend()
        name = (
            f"{game.capsule_id}-{backend}"
            if game is not None
            else "ogv-derived-game"
        )
        self.destination_edit.setText(
            str(Path(selected) / name)
        )

    def _choose_state_backup(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select verified state backup",
            self.state_backup_edit.text() or str(Path.home()),
        )
        if selected:
            self.state_backup_edit.setText(selected)

    def _choose_core(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select offline-game-vault checkout",
            self.preferences.core_source_root
            or str(Path.home()),
        )
        if not selected:
            return

        def load_core() -> tuple[CoreClient, CoreProbe]:
            client = CoreClient.resolve(
                source_root=Path(selected)
            )
            return client, client.probe()

        def loaded(value: object) -> None:
            client, probe = value  # type: ignore[misc]
            self.service = CompositionService(client)
            self.probe = probe
            self.preferences.core_source_root = selected
            self.preferences.save()
            self._set_core_status()
            self._set_status("Core selected")
            if self.collection_edit.text().strip():
                self._refresh()

        self._run_worker(
            "Validating selected core…",
            load_core,
            loaded,
        )

    def _refresh(self) -> None:
        if self.service is None:
            self._worker_failed(
                "Select a compatible offline-game-vault core first"
            )
            return
        raw = self.collection_edit.text().strip()
        if not raw:
            self._worker_failed("Select a collection root")
            return
        collection = Path(raw)

        def loaded(value: object) -> None:
            games, runners, warnings = value  # type: ignore[misc]
            self.games = tuple(games)
            self.runners = tuple(runners)
            self.game_combo.blockSignals(True)
            self.game_combo.clear()
            for game in self.games:
                self.game_combo.add_rich_item(
                    game.title,
                    game.capsule_id,
                    game,
                )
            self.game_combo.blockSignals(False)
            self.preferences.collection_root = str(
                collection.expanduser()
            )
            self.preferences.destination_parent = (
                self.destination_parent_edit.text().strip()
            )
            self.preferences.save()
            self._set_log("\n".join(warnings))
            self._game_changed()
            self._set_status(
                f"Loaded {len(self.games)} game(s) and "
                f"{len(self.runners)} runner(s)"
            )

        self._run_worker(
            "Scanning collection and preserved runners…",
            lambda: self.service.load(collection),
            loaded,
        )

    def _selected_game(self) -> GameRecord | None:
        value = self.game_combo.current_payload()
        return value if isinstance(value, GameRecord) else None

    def _selected_profile(self) -> SourceProfile | None:
        value = self.profile_combo.current_payload()
        return (
            value if isinstance(value, SourceProfile) else None
        )

    def _selected_runner(self) -> RunnerRecord | None:
        value = self.runner_combo.current_payload()
        return (
            value if isinstance(value, RunnerRecord) else None
        )

    def _selected_state_selection(
        self,
    ) -> StateSelectionRecord | None:
        value = self.save_combo.current_payload()
        return (
            value
            if isinstance(value, StateSelectionRecord)
            else None
        )

    def _selected_backend(self) -> Backend:
        value = self.backend_combo.currentData(
            Qt.ItemDataRole.UserRole
        )
        if value not in {
            "bottles",
            "direct-wine",
            "umu",
        }:
            return "bottles"
        return value

    def _game_changed(self, *_args: object) -> None:
        game = self._selected_game()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.add_rich_item(
            "Auto (recommended)",
            "Let the core select a source layout compatible with the backend",
            None,
        )
        if game is not None:
            for profile in game.source_profiles:
                self.profile_combo.add_rich_item(
                    profile.profile_id,
                    ", ".join(
                        item
                        for item in (
                            profile.platform,
                            profile.adapter,
                            profile.playable_backend,
                        )
                        if item
                    ),
                    profile,
                )
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self._update_default_target()
        self._load_save_sets()

    def _load_save_sets(self) -> None:
        game = self._selected_game()
        raw = self.collection_edit.text().strip()
        self.state_selections = ()
        self.save_combo.blockSignals(True)
        self.save_combo.clear()
        self.save_combo.add_rich_item(
            "Start a new game",
            (
                "Do not restore preserved state; "
                "materialize explicitly with --no-state"
            ),
            None,
        )
        self.save_combo.blockSignals(False)
        if (
            game is None
            or not raw
            or self.service is None
        ):
            return

        def loaded(value: object) -> None:
            selections, warnings = value  # type: ignore[misc]
            self.state_selections = tuple(selections)
            self.save_combo.blockSignals(True)
            self.save_combo.clear()
            self.save_combo.add_rich_item(
                "Start a new game",
                (
                    "Do not restore preserved state; "
                    "materialize explicitly with --no-state"
                ),
                None,
            )
            for item in self.state_selections:
                availability = (
                    f"{item.backup.present_count}/"
                    f"{item.backup.item_count} present"
                )
                if item.backup.missing_count:
                    availability += (
                        f"; {item.backup.missing_count} missing"
                    )
                secondary = " • ".join(
                    value
                    for value in (
                        item.backup.content_label,
                        availability,
                        item.backup.backup_kind,
                        item.save_set_id,
                        item.backup.backup_id,
                    )
                    if value
                )
                self.save_combo.add_rich_item(
                    item.display_name,
                    secondary,
                    item,
                )
            self.save_combo.blockSignals(False)
            if warnings:
                self._set_log("\n".join(warnings))
            self._save_changed()

        self._run_worker(
            "Discovering and verifying persistent-state backups…",
            lambda: self.service.state_selections(
                Path(raw),
                game,
            ),
            loaded,
        )

    def _backend_changed(self, *_args: object) -> None:
        backend = self._selected_backend()
        bottles = backend == "bottles"
        umu = backend == "umu"
        destination_label, _destination_widget = self._rows[
            "destination"
        ]
        if bottles:
            destination_label.setText(
                "External Bottles materialization destination"
            )
            self.destination_edit.setPlaceholderText(
                "New external Bottles materialization"
            )
        else:
            destination_label.setText("Materialization destination")
            self.destination_edit.setPlaceholderText(
                "New writable materialization destination"
            )
        self._set_row_visible("destination", True)
        self._set_row_visible("bottle_name", bottles)
        self._set_row_visible("bottles_path", bottles)
        self._set_row_visible("save", True)
        self._set_row_visible("state_backup", True)
        self._set_row_visible("arguments", not bottles)
        self._set_row_visible("umu", umu)
        self._filter_runners()
        self._update_default_target()

        if bottles and self.service is not None:
            self._load_bottles_path()
        elif umu and self.service is not None:
            self._load_component_sets()

    def _bottle_name_edited(self, text: str) -> None:
        self._bottle_name_manual = bool(text.strip())

    def _filter_runners(self) -> None:
        backend = self._selected_backend()
        if self.service is None:
            self.visible_runners = ()
        else:
            self.visible_runners = (
                self.service.compatible_runners(
                    self.runners,
                    backend,
                )
            )
        self.runner_combo.blockSignals(True)
        self.runner_combo.clear()
        for runner in self.visible_runners:
            self.runner_combo.add_rich_item(
                runner.runner_id,
                (
                    f"{runner.kind}; {runner.size} bytes; "
                    f"{runner.digest}"
                ),
                runner,
            )
        self.runner_combo.blockSignals(False)

    def _update_default_target(self) -> None:
        game = self._selected_game()
        if game is None:
            return
        backend = self._selected_backend()
        if backend == "bottles" and not self._bottle_name_manual:
            self.bottle_name_edit.setText(
                f"{game.capsule_id}-bottle"
            )

        parent = self.destination_parent_edit.text().strip()
        if parent:
            self.destination_edit.setText(
                str(
                    Path(parent)
                    / f"{game.capsule_id}-{backend}"
                )
            )

    def _load_bottles_path(self) -> None:
        assert self.service is not None

        def loaded(value: object) -> None:
            self.bottles_path_value.setText(str(value))

        self._run_worker(
            "Discovering Bottles path…",
            self.service.bottles_path,
            loaded,
        )

    def _load_component_sets(self) -> None:
        raw = self.collection_edit.text().strip()
        if not raw or self.service is None:
            return

        def loaded(value: object) -> None:
            values = tuple(value)  # type: ignore[arg-type]
            summary = (
                "\n".join(item.label for item in values)
                if values
                else "No compatible UMU component set"
            )
            self.umu_value.setText(summary)
            self._set_status(
                f"Resolved {len(values)} UMU component set(s)"
            )

        self._run_worker(
            "Resolving UMU components…",
            lambda: self.service.component_sets(Path(raw)),
            loaded,
        )

    def _save_changed(self, *_args: object) -> None:
        selection = self._selected_state_selection()
        if selection is None:
            self.state_backup_edit.setText("")
            return
        self.state_backup_edit.setText(
            str(selection.backup.path)
        )
        provenance = (
            f"; save set {selection.save_set_id}"
            if selection.save_set_id
            else ""
        )
        self._set_status(
            f"Verified state backup {selection.backup.backup_id}"
            + provenance
        )

    def _request(self, play: bool) -> CompositionRequest:
        if self.service is None:
            raise ServiceError("No compatible core is selected")

        game = self._selected_game()
        profile = self._selected_profile()
        runner = self._selected_runner()
        if game is None:
            raise ServiceError("Select a game")
        if runner is None:
            raise ServiceError(
                "Select a compatible preserved runner"
            )

        collection_raw = self.collection_edit.text().strip()
        if not collection_raw:
            raise ServiceError("Select a collection root")

        backend = self._selected_backend()
        raw_destination = self.destination_edit.text().strip()
        if not raw_destination:
            raise ServiceError(
                "Select a new writable destination"
            )
        destination = Path(raw_destination)
        bottles_path: Path | None = None
        bottle_name: str | None = None

        if backend == "bottles":
            bottle_name = self.bottle_name_edit.text().strip()
            managed = self.bottles_path_value.text().strip()
            if managed and managed != "Discovered by the core":
                bottles_path = Path(managed)

        selection = self._selected_state_selection()
        save_set_id: str | None = None
        state_backup: Path | None = None
        raw_backup = self.state_backup_edit.text().strip()
        if raw_backup:
            state_backup = Path(raw_backup)
            if selection is not None:
                if (
                    state_backup.expanduser().resolve(
                        strict=False
                    )
                    == selection.backup.path
                ):
                    save_set_id = selection.save_set_id
        elif selection is not None:
            state_backup = selection.backup.path
            save_set_id = selection.save_set_id

        arguments: tuple[str, ...] = ()
        raw_arguments = self.arguments_edit.text().strip()
        if raw_arguments:
            arguments = tuple(shlex.split(raw_arguments))

        return CompositionRequest(
            collection_root=Path(collection_raw),
            capsule_path=game.capsule_path,
            backend=backend,
            runner_id=runner.runner_id,
            source_profile_id=(
                profile.profile_id if profile is not None else None
            ),
            destination=destination,
            state_backup=state_backup,
            save_set_id=save_set_id,
            no_state=state_backup is None,
            bottles_path=bottles_path,
            bottle_name=bottle_name,
            play=play,
            arguments=arguments,
        )

    def _compose(self, play: bool) -> None:
        try:
            request = self._request(play)
        except (ServiceError, ValueError) as exc:
            self._worker_failed(str(exc))
            return

        assert self.service is not None

        def complete(value: object) -> None:
            result = value
            self.last_destination = (
                result.destination  # type: ignore[attr-defined]
            )
            self._set_status(
                "Materialized"
                + (" and played" if play else "")
                + f": {self.last_destination}"
            )
            self._set_log(
                f"capsule={result.capsule_id}\n"  # type: ignore[attr-defined]
                f"backend={result.backend}\n"  # type: ignore[attr-defined]
                f"runner={result.runner_id}\n"  # type: ignore[attr-defined]
                f"profile={result.profile_id}\n"  # type: ignore[attr-defined]
                f"destination={result.destination}\n"  # type: ignore[attr-defined]
                f"played={result.played}\n"  # type: ignore[attr-defined]
                f"play_complete={result.play_complete}"  # type: ignore[attr-defined]
            )

        self._run_worker(
            "Composing writable derivative…",
            lambda: self.service.compose(request),
            complete,
        )

    def _operation(self, operation: str) -> None:
        if self.service is None:
            self._worker_failed(
                "No compatible core is selected"
            )
            return

        destination = self.last_destination
        if destination is None:
            raw = self.destination_edit.text().strip()
            if raw:
                destination = Path(raw)
        if destination is None:
            self._worker_failed(
                "No writable derivative is selected"
            )
            return

        try:
            arguments: tuple[str, ...] = ()
            if operation == "play":
                raw = self.arguments_edit.text().strip()
            elif operation == "remove":
                raw = self.removal_arguments_edit.text().strip()
            else:
                raw = ""
            if raw:
                arguments = tuple(shlex.split(raw))
        except ValueError as exc:
            self._worker_failed(str(exc))
            return

        if operation == "remove":
            answer = QMessageBox.question(
                self,
                "Remove writable derivative",
                (
                    "Run the generated DESINSTALAR.sh operation for:\n\n"
                    f"{destination}\n\n"
                    "The generated script remains authoritative for "
                    "confirmation and state preservation."
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        def complete(value: object) -> None:
            process = value
            self._set_status(
                f"{operation.capitalize()} returned "
                f"{process.returncode}"  # type: ignore[attr-defined]
            )
            stdout = process.stdout or ""  # type: ignore[attr-defined]
            stderr = process.stderr or ""  # type: ignore[attr-defined]
            self._set_log(
                stdout
                + ("\n" if stdout and stderr else "")
                + stderr
            )
            if (
                operation == "remove"
                and process.returncode == 0  # type: ignore[attr-defined]
            ):
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

    def _run_worker(
        self,
        label: str,
        function: Callable[[], object],
        complete: Callable[[object], None],
    ) -> None:
        self._begin_busy(label)
        worker = Worker(function)
        self._workers.add(worker)
        worker.signals.result.connect(complete)
        worker.signals.failed.connect(
            self._worker_failed
        )
        worker.signals.finished.connect(
            lambda: self._worker_finished(worker)
        )
        QThreadPool.globalInstance().start(worker)

    def _worker_finished(self, worker: Worker) -> None:
        self._workers.discard(worker)
        self._end_busy()

    def _worker_failed(self, detail: str) -> None:
        self._set_status("Operation failed")
        self._set_log(detail)
        QMessageBox.critical(
            self,
            "Offline Game Vault",
            detail,
        )

    def _begin_busy(self, label: str) -> None:
        self._busy_depth += 1
        self._set_status(label)
        self._set_actions_enabled(False)

    def _end_busy(self) -> None:
        self._busy_depth = max(0, self._busy_depth - 1)
        if self._busy_depth == 0:
            self._set_actions_enabled(True)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for widget in (
            self.refresh_button,
            self.core_button,
            self.materialize_button,
            self.materialize_play_button,
            self.verify_button,
            self.play_button,
            self.remove_button,
        ):
            widget.setEnabled(enabled)

    def _set_core_status(self) -> None:
        if self.probe is None:
            self.core_value.setText("Not selected")
            return
        self.core_value.setText(
            f"{self.probe.version} — {self.probe.description}"
        )

    def _set_status(self, value: str) -> None:
        self.status_label.setText(value)

    def _set_log(self, value: str) -> None:
        self.log.setPlainText(value)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.preferences.collection_root = (
            self.collection_edit.text().strip()
        )
        self.preferences.destination_parent = (
            self.destination_parent_edit.text().strip()
        )
        try:
            self.preferences.save()
        except OSError:
            pass
        event.accept()


def _configure_application() -> QApplication:
    application = QApplication(sys.argv)
    application.setApplicationName("Offline Game Vault")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("pbano-dev")
    application.setDesktopFileName(APP_ID)

    requested_style = os.environ.get("OGV_QT_STYLE", "").strip()
    if requested_style:
        available = {
            value.casefold(): value
            for value in QStyleFactory.keys()
        }
        canonical = available.get(requested_style.casefold())
        if canonical:
            application.setStyle(canonical)

    stylesheet = os.environ.get(
        "OGV_QT_STYLESHEET",
        "",
    ).strip()
    if stylesheet:
        path = Path(stylesheet).expanduser()
        if path.is_file() and not path.is_symlink():
            application.setStyleSheet(
                path.read_text(encoding="utf-8")
            )
    return application


def main() -> int:
    application = _configure_application()
    preferences = Preferences.load()
    service: CompositionService | None = None
    probe: CoreProbe | None = None
    startup_error: str | None = None

    try:
        source = (
            Path(preferences.core_source_root)
            if preferences.core_source_root
            else None
        )
        client = CoreClient.resolve(source_root=source)
        probe = client.probe()
        service = CompositionService(client)
    except (CoreError, OSError) as exc:
        startup_error = str(exc)

    window = MainWindow(
        preferences=preferences,
        service=service,
        probe=probe,
        startup_error=startup_error,
    )
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
