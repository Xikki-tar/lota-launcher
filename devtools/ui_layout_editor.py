from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from auth.settings import DEFAULT_STEVE
from window.chrome import AppWindow
from window.i18n import set_language
from window.style import build_app_qss
from window.ui_layout import (
    SCREEN_SPECS,
    SOURCE_DEFAULTS_PATH,
    apply_layout_overrides,
    clear_runtime_overrides,
    effective_layout_map,
    iter_fields,
    load_runtime_overrides,
    offset_for_target,
    read_field_value,
    runtime_overrides_path,
    save_runtime_overrides,
    save_source_defaults,
    set_target_offset,
)
from window.i18n import t
from window.views.account_view import AccountView, DiscordLinkDialog
from window.views.home_view import HomeView, NewsCard
from window.views.library_view import LibraryView
from window.views.login_view import LoginView, RegisterLinksOverlay
from window.views.settings_view import SettingsView


def _build_app_font(font_family: str, pixel_size: int) -> QFont:
    font = QFont(font_family)
    font.setPixelSize(pixel_size)
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


class LayoutEditorWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle("Lota UI Layout Editor")
        self.resize(1480, 920)
        self.runtime_overrides = load_runtime_overrides()
        self.current_screen = "home"
        self.preview_page: QWidget | None = None
        self.preview_stage: QWidget | None = None
        self.preview_target = None
        self.preview_shell_host: PreviewStageHost | None = None
        self.selected_widget: QWidget | None = None
        self.selected_target_map: dict[str, dict[str, bool]] = {}
        self.control_widgets: dict[str, object] = {}
        self._build_ui()
        self._refresh_screen()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(16)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        title = QLabel("Runtime UI layout editor")
        title.setProperty("title", True)
        toolbar.addWidget(title)

        toolbar.addStretch()

        self.screen_combo = QComboBox()
        for screen_key, spec in SCREEN_SPECS.items():
            self.screen_combo.addItem(spec["title"], screen_key)
        self.screen_combo.setCurrentText(SCREEN_SPECS[self.current_screen]["title"])
        self.screen_combo.currentIndexChanged.connect(self._on_screen_changed)
        toolbar.addWidget(self.screen_combo)

        self.save_btn = QPushButton("Save Runtime Overrides")
        self.save_btn.setProperty("primary", True)
        self.save_btn.clicked.connect(self._save_runtime)
        toolbar.addWidget(self.save_btn)

        self.reset_btn = QPushButton("Reset Current Screen")
        self.reset_btn.setProperty("secondary", True)
        self.reset_btn.clicked.connect(self._reset_current_screen)
        toolbar.addWidget(self.reset_btn)

        self.reload_btn = QPushButton("Reload From Disk")
        self.reload_btn.clicked.connect(self._reload_from_disk)
        toolbar.addWidget(self.reload_btn)

        self.sync_btn = QPushButton("Sync To Source Defaults")
        self.sync_btn.setProperty("accent", True)
        self.sync_btn.clicked.connect(self._sync_to_source_defaults)
        toolbar.addWidget(self.sync_btn)

        for btn in (self.save_btn, self.reset_btn, self.reload_btn, self.sync_btn):
            btn.style().polish(btn)

        root.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, stretch=1)

        preview_column = QVBoxLayout()
        preview_column.setSpacing(10)
        body.addLayout(preview_column, stretch=2)

        preview_title = QLabel("Preview")
        preview_title.setProperty("section", True)
        preview_column.addWidget(preview_title)

        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QFrame.NoFrame)
        preview_column.addWidget(preview_scroll, stretch=1)

        preview_host = QWidget()
        self.preview_host_layout = QVBoxLayout(preview_host)
        self.preview_host_layout.setContentsMargins(20, 20, 20, 20)
        self.preview_host_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        preview_scroll.setWidget(preview_host)

        controls_column = QVBoxLayout()
        controls_column.setSpacing(10)
        body.addLayout(controls_column, stretch=1)

        controls_title = QLabel("Controls")
        controls_title.setProperty("section", True)
        controls_column.addWidget(controls_title)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setFrameShape(QFrame.NoFrame)
        controls_column.addWidget(controls_scroll, stretch=1)

        controls_host = QWidget()
        self.controls_layout = QVBoxLayout(controls_host)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(12)
        self.controls_layout.setAlignment(Qt.AlignTop)
        controls_scroll.setWidget(controls_host)

        self.status_label = QLabel("")
        self.status_label.setProperty("caption", True)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _on_screen_changed(self) -> None:
        self.current_screen = str(self.screen_combo.currentData() or "home")
        self._refresh_screen()

    def _refresh_screen(self) -> None:
        self._rebuild_preview()
        self._rebuild_controls()
        self._update_status("Editing preview values in memory.")

    def _rebuild_preview(self) -> None:
        while self.preview_host_layout.count():
            item = self.preview_host_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        builder = SCREEN_BUILDERS[self.current_screen]
        stage, target = builder()
        apply_layout_overrides(target, self.current_screen, self.runtime_overrides)

        self.preview_page = stage
        self.preview_stage = stage
        self.preview_target = target
        self.selected_widget = None
        self.preview_shell_host = PreviewStageHost(
            stage,
            on_widget_selected=self._select_widget,
            on_widget_resized=self._resize_selected_widget,
            is_widget_resizable=self._is_widget_resizable,
            on_widget_context_menu=self._open_widget_context_menu,
        )
        self.preview_host_layout.addWidget(self.preview_shell_host, alignment=Qt.AlignHCenter | Qt.AlignTop)
        self._rebuild_selection_map()

    def _rebuild_controls(self) -> None:
        self.control_widgets.clear()
        while self.controls_layout.count():
            item = self.controls_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        values = effective_layout_map(self.runtime_overrides).get(self.current_screen, {})
        for field in iter_fields(self.current_screen):
            card = QGroupBox(field.label)
            card.setProperty("settingsGroup", True)
            form = QFormLayout(card)
            form.setSpacing(8)
            current_value = values.get(field.key)
            if current_value is None and self.preview_target is not None:
                current_value = read_field_value(self.preview_target, field)
            if field.kind == "margins":
                spinboxes = self._create_margin_editor(current_value, field.minimum, field.maximum)
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                for label, spinbox in zip(("L", "T", "R", "B"), spinboxes):
                    row_layout.addWidget(QLabel(label))
                    row_layout.addWidget(spinbox)
                    spinbox.valueChanged.connect(lambda _=None, key=field.key, boxes=spinboxes: self._set_margin_value(key, boxes))
                form.addRow(row)
                self.control_widgets[field.key] = spinboxes
            elif field.kind in {"text", "placeholder_text"}:
                line_edit = QLineEdit()
                line_edit.setText("" if current_value is None else str(current_value))
                line_edit.textChanged.connect(lambda value, key=field.key: self._set_text_value(key, value))
                form.addRow(line_edit)
                self.control_widgets[field.key] = line_edit
            else:
                spinbox = self._create_spinbox(int(current_value or 0), field.minimum, field.maximum, field.step)
                spinbox.valueChanged.connect(lambda value, key=field.key: self._set_scalar_value(key, value))
                form.addRow(spinbox)
                self.control_widgets[field.key] = spinbox
            self.controls_layout.addWidget(card)
        self.controls_layout.addStretch()

    def _create_margin_editor(
        self,
        value: list[int] | tuple[int, int, int, int] | None,
        minimum: int,
        maximum: int,
    ) -> tuple[QSpinBox, QSpinBox, QSpinBox, QSpinBox]:
        values = list(value) if isinstance(value, (list, tuple)) and len(value) == 4 else [0, 0, 0, 0]
        return tuple(self._create_spinbox(part, minimum, maximum, 1) for part in values)  # type: ignore[return-value]

    def _create_spinbox(self, value: int, minimum: int, maximum: int, step: int) -> QSpinBox:
        spinbox = QSpinBox()
        spinbox.setRange(minimum, maximum)
        spinbox.setSingleStep(step)
        spinbox.setValue(value)
        spinbox.setButtonSymbols(QSpinBox.PlusMinus)
        return spinbox

    def _set_margin_value(self, key: str, boxes: tuple[QSpinBox, QSpinBox, QSpinBox, QSpinBox]) -> None:
        self.runtime_overrides.setdefault(self.current_screen, {})[key] = [box.value() for box in boxes]
        self._apply_current_values()

    def _set_scalar_value(self, key: str, value: int) -> None:
        self.runtime_overrides.setdefault(self.current_screen, {})[key] = value
        self._apply_current_values()

    def _set_text_value(self, key: str, value: str) -> None:
        self.runtime_overrides.setdefault(self.current_screen, {})[key] = value
        self._apply_current_values()

    def _apply_current_values(self) -> None:
        if self.preview_target is None:
            return
        apply_layout_overrides(self.preview_target, self.current_screen, self.runtime_overrides)
        self.preview_target.updateGeometry()
        if self.preview_shell_host is not None:
            self.preview_shell_host.sync_stage_size()
            if self.selected_widget is not None:
                self.preview_shell_host.select_widget(self.selected_widget)

    def _rebuild_selection_map(self) -> None:
        self.selected_target_map = {}
        if self.preview_target is None:
            return
        for field in iter_fields(self.current_screen):
            target = self._resolve_editor_target(field.target)
            if isinstance(target, QWidget):
                meta = self.selected_target_map.setdefault(field.target, {"width": False, "height": False})
                if field.kind == "fixed_width":
                    meta["width"] = True
                if field.kind == "fixed_height":
                    meta["height"] = True

    def _resolve_editor_target(self, target_path: str):
        current = self.preview_target
        for chunk in target_path.split("."):
            current = getattr(current, chunk, None)
            if current is None:
                return None
        return current

    def _find_registered_target_path(self, widget: QWidget | None) -> str | None:
        current = widget
        while isinstance(current, QWidget):
            target_path = self._target_path_for_widget(current)
            if target_path:
                return target_path
            current = current.parentWidget()
        return None

    def _select_widget(self, widget: QWidget | None) -> QWidget | None:
        if widget is None:
            self.selected_widget = None
            self._update_status("Selected widget is not resizable in this screen.")
            return None
        target_path = self._find_registered_target_path(widget)
        if target_path:
            resolved = self._resolve_editor_target(target_path)
            if not isinstance(resolved, QWidget):
                return None
            self.selected_widget = resolved
            meta = self.selected_target_map.get(target_path) or {}
            if meta.get("width") or meta.get("height"):
                self._update_status(f"Selected `{target_path}`. Drag the handle to resize this element.")
            else:
                self._update_status(f"Selected `{target_path}`. This element is editable from the controls panel.")
            return resolved
        self.selected_widget = None
        self._update_status("This widget has no editable width/height in the current screen.")
        return None

    def _target_path_for_widget(self, widget: QWidget | None) -> str | None:
        if widget is None:
            return None
        for target_path in self.selected_target_map:
            if self._resolve_editor_target(target_path) is widget:
                return target_path
        return None

    def _resize_selected_widget(self, widget: QWidget, width: int, height: int) -> None:
        target_path = self._target_path_for_widget(widget)
        if not target_path:
            return
        has_width = False
        has_height = False
        for field in iter_fields(self.current_screen):
            if field.target != target_path:
                continue
            if field.kind == "fixed_width":
                value = max(field.minimum, min(field.maximum, width))
                self.runtime_overrides.setdefault(self.current_screen, {})[field.key] = value
                has_width = True
                spin = self.control_widgets.get(field.key)
                if isinstance(spin, QSpinBox):
                    spin.blockSignals(True)
                    spin.setValue(value)
                    spin.blockSignals(False)
            if field.kind == "fixed_height":
                value = max(field.minimum, min(field.maximum, height))
                self.runtime_overrides.setdefault(self.current_screen, {})[field.key] = value
                has_height = True
                spin = self.control_widgets.get(field.key)
                if isinstance(spin, QSpinBox):
                    spin.blockSignals(True)
                    spin.setValue(value)
                    spin.blockSignals(False)
        if has_width or has_height:
            self._apply_current_values()

    def _is_widget_resizable(self, widget: QWidget | None) -> bool:
        target_path = self._target_path_for_widget(widget)
        if not target_path:
            return False
        meta = self.selected_target_map.get(target_path) or {}
        return bool(meta.get("width") or meta.get("height"))

    def _open_widget_context_menu(self, widget: QWidget, global_pos) -> None:
        target_path = self._target_path_for_widget(widget)
        if not target_path:
            return
        menu = QMenu(self)
        menu.setStyleSheet(self.styleSheet())

        current_x, current_y = offset_for_target(self.current_screen, target_path, self.runtime_overrides)
        title = menu.addAction(f"{target_path} ({current_x}, {current_y})")
        title.setEnabled(False)
        menu.addSeparator()

        self._add_nudge_action(menu, "Left 1px", target_path, -1, 0)
        self._add_nudge_action(menu, "Right 1px", target_path, 1, 0)
        self._add_nudge_action(menu, "Up 1px", target_path, 0, -1)
        self._add_nudge_action(menu, "Down 1px", target_path, 0, 1)
        menu.addSeparator()
        self._add_nudge_action(menu, "Left 5px", target_path, -5, 0)
        self._add_nudge_action(menu, "Right 5px", target_path, 5, 0)
        self._add_nudge_action(menu, "Up 5px", target_path, 0, -5)
        self._add_nudge_action(menu, "Down 5px", target_path, 0, 5)
        menu.addSeparator()
        reset_action = menu.addAction("Reset Offset")
        reset_action.triggered.connect(lambda: self._set_widget_offset(target_path, 0, 0, absolute=True))
        menu.exec(global_pos)

    def _add_nudge_action(self, menu: QMenu, label: str, target_path: str, dx: int, dy: int) -> None:
        action = menu.addAction(label)
        action.triggered.connect(lambda: self._set_widget_offset(target_path, dx, dy, absolute=False))

    def _set_widget_offset(self, target_path: str, dx: int, dy: int, *, absolute: bool) -> None:
        current_x, current_y = offset_for_target(self.current_screen, target_path, self.runtime_overrides)
        if absolute:
            next_x, next_y = dx, dy
        else:
            next_x, next_y = current_x + dx, current_y + dy
        set_target_offset(self.runtime_overrides, self.current_screen, target_path, x=next_x, y=next_y)
        self._apply_current_values()
        self._update_status(f"Offset for `{target_path}` set to ({next_x}, {next_y}).")

    def _save_runtime(self) -> None:
        path = save_runtime_overrides(self.runtime_overrides)
        self._update_status(f"Saved runtime overrides to {path}.")

    def _reload_from_disk(self) -> None:
        self.runtime_overrides = load_runtime_overrides()
        self._refresh_screen()
        self._update_status("Reloaded runtime overrides from disk.")

    def _reset_current_screen(self) -> None:
        self.runtime_overrides.pop(self.current_screen, None)
        clear_runtime_overrides(self.current_screen)
        self._refresh_screen()
        self._update_status(f"Removed runtime overrides for {self.current_screen}.")

    def _sync_to_source_defaults(self) -> None:
        merged = effective_layout_map(self.runtime_overrides)
        save_source_defaults(merged)
        self._update_status(f"Synchronized source defaults to {SOURCE_DEFAULTS_PATH}.")
        QMessageBox.information(
            self,
            "Source defaults updated",
            "Current layout values were written into window/ui_layout_defaults.json.",
        )

    def _update_status(self, prefix: str) -> None:
        runtime_path = runtime_overrides_path()
        self.status_label.setText(
            f"{prefix}\nRuntime file: {runtime_path}\nSource defaults: {SOURCE_DEFAULTS_PATH}"
        )


class ResizeGripHandle(QFrame):
    def __init__(self, parent: QWidget, on_drag):
        super().__init__(parent)
        self._on_drag = on_drag
        self._drag_origin: QPoint | None = None
        self._base_size = None
        self.setFixedSize(18, 18)
        self.setStyleSheet(
            "background: rgba(245, 180, 73, 0.85); border: 1px solid rgba(255,255,255,0.25); border-radius: 5px;"
        )
        self.setCursor(Qt.SizeFDiagCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            host = self.parentWidget()
            self._base_size = host.selected_widget.size() if isinstance(host, PreviewStageHost) and host.selected_widget else None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and self._base_size is not None and callable(self._on_drag):
            delta = event.globalPosition().toPoint() - self._drag_origin
            self._on_drag(self._base_size.width() + delta.x(), self._base_size.height() + delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        self._base_size = None
        super().mouseReleaseEvent(event)


class PreviewStageHost(QFrame):
    def __init__(self, stage_widget: QWidget, on_widget_selected, on_widget_resized, is_widget_resizable, on_widget_context_menu):
        super().__init__()
        self.stage_widget = stage_widget
        self._on_widget_selected = on_widget_selected
        self._on_widget_resized = on_widget_resized
        self._is_widget_resizable = is_widget_resizable
        self._on_widget_context_menu = on_widget_context_menu
        self.selected_widget: QWidget | None = None
        self.setProperty("panel2", True)
        self.setFrameShape(QFrame.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stage_widget)
        self.selection_frame = QFrame(self)
        self.selection_frame.hide()
        self.selection_frame.setStyleSheet("background: transparent; border: 2px solid rgba(245, 180, 73, 0.95);")
        self.resize_handle = ResizeGripHandle(self, self._handle_resize)
        self.resize_handle.hide()
        self._install_select_filters(stage_widget)
        self.sync_stage_size()

    def _install_select_filters(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and isinstance(watched, QWidget) and watched is not self.resize_handle:
            if event.button() == Qt.RightButton:
                selected_widget = None
                if callable(self._on_widget_selected):
                    selected_widget = self._on_widget_selected(watched)
                resolved = selected_widget if isinstance(selected_widget, QWidget) else None
                self.select_widget(resolved)
                if resolved is not None and callable(self._on_widget_context_menu):
                    self._on_widget_context_menu(resolved, event.globalPosition().toPoint())
                return True
            selected_widget = None
            if callable(self._on_widget_selected):
                selected_widget = self._on_widget_selected(watched)
            self.select_widget(selected_widget if isinstance(selected_widget, QWidget) else None)
            return False
        return super().eventFilter(watched, event)

    def select_widget(self, widget: QWidget | None) -> None:
        self.selected_widget = widget
        if widget is None or widget is self.stage_widget:
            self.selection_frame.hide()
            self.resize_handle.hide()
            return
        rect = self._widget_rect(widget)
        if rect.width() < 8 or rect.height() < 8:
            self.selection_frame.hide()
            self.resize_handle.hide()
            return
        self.selection_frame.setGeometry(rect)
        self.selection_frame.show()
        self.selection_frame.raise_()
        can_resize = callable(self._is_widget_resizable) and self._is_widget_resizable(widget)
        if can_resize:
            self.resize_handle.show()
            self.resize_handle.move(rect.right() - self.resize_handle.width() + 1, rect.bottom() - self.resize_handle.height() + 1)
            self.resize_handle.raise_()
        else:
            self.resize_handle.hide()

    def sync_stage_size(self) -> None:
        self.stage_widget.setParent(self)
        self.stage_widget.setFixedSize(self.stage_widget.size())
        self.setFixedSize(self.stage_widget.width(), self.stage_widget.height())
        if self.selected_widget is not None:
            self.select_widget(self.selected_widget)
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.selected_widget is not None:
            self.select_widget(self.selected_widget)

    def _widget_rect(self, widget: QWidget) -> QRect:
        top_left = widget.mapTo(self, QPoint(0, 0))
        return QRect(top_left, widget.size())

    def _handle_resize(self, width: int, height: int) -> None:
        if self.selected_widget is not None and callable(self._on_widget_resized):
            self._on_widget_resized(self.selected_widget, max(12, width), max(12, height))


def _wrap_login_shell(page: QWidget) -> AppWindow:
    shell = AppWindow()
    shell.setObjectName("RootWindow")
    shell.setWindowTitle(t("app_title_login"))
    shell.set_locked_window_size(480, 360)
    shell.content_layout.setContentsMargins(24, 24, 24, 24)
    shell.content_layout.addWidget(page)
    _finalize_preview_shell(shell, page)
    return shell


def _wrap_launcher_shell(page: QWidget) -> AppWindow:
    shell = AppWindow()
    shell.setObjectName("RootWindow")
    shell.setWindowTitle(t("app_title_main"))
    shell.set_locked_window_size(960, 640)
    shell.content_layout.addWidget(page)
    _finalize_preview_shell(shell, page)
    return shell


def _finalize_preview_shell(shell: AppWindow, page: QWidget) -> None:
    shell.layout().activate()
    shell.content_layout.activate()
    shell.ensurePolished()
    QApplication.processEvents()
    shell.content.resize(shell.content.size())
    page.resize(shell.content.size())
    page.setMinimumSize(shell.content.size())
    page.updateGeometry()


def build_login_preview() -> tuple[QWidget, QWidget]:
    view = LoginView()
    view.username_input.setText("lota_player")
    view.code_input.setText("123456")
    shell = _wrap_login_shell(view)
    return shell, view


def build_register_overlay_preview() -> tuple[QWidget, QWidget]:
    view = LoginView()
    view.username_input.setText("lota_player")
    view.code_input.setText("123456")
    shell = _wrap_login_shell(view)
    overlay = RegisterLinksOverlay(shell.content, lambda: None, lambda *_: None)
    overlay.show_complete_page()
    overlay._telegram_url = "https://t.me/example"
    overlay._link_token = "token"
    overlay.setGeometry(shell.content.rect())
    overlay.raise_()
    overlay.show()
    return shell, overlay


def build_home_preview() -> tuple[QWidget, QWidget]:
    view = HomeView()
    view.set_username("xikki")
    samples = [
        ("Season Restart", "2026-04-09", "Новый сезон уже доступен на сервере.", "update", "update"),
        ("Event Weekend", "2026-04-07", "На выходных будет двойной дроп и бонусный опыт.", "event", "event"),
    ]
    for title, date, body, label, key in samples:
        card = NewsCard(title, date, body, label, key, lambda *_: None, {"title": title})
        view.news_box.addWidget(card)
    shell = _wrap_launcher_shell(view)
    return shell, view


def build_news_overlay_preview() -> tuple[QWidget, QWidget]:
    view = HomeView()
    card = NewsCard("Season Restart", "2026-04-09", "Новый сезон уже доступен на сервере.", "update", "update", lambda *_: None, {})
    view.news_box.addWidget(card)
    shell = _wrap_launcher_shell(view)
    overlay = view.details_overlay
    overlay.set_content("Season Restart", "2026-04-09", "Полный текст новости для проверки переноса строк.", "- Улучшения\n- Исправления")
    view.resize(shell.content.size())
    overlay.setGeometry(view.rect())
    overlay.raise_()
    overlay.show()
    return shell, overlay


def build_settings_preview() -> tuple[QWidget, QWidget]:
    view = SettingsView()
    view.mem_min.setValue(2048)
    view.mem_max.setValue(4096)
    view.java_path_edit.setText("/usr/lib/jvm/java-21-openjdk/bin/java")
    for name in ("Java 17", "Java 21", "GraalVM"):
        QListWidgetItem(name, view.java_list)
    view.set_java_version_text("Version: 21.0.2")
    shell = _wrap_launcher_shell(view)
    return shell, view


def build_library_preview() -> tuple[QWidget, QWidget]:
    view = LibraryView(parent=None, overlay_submit=lambda *_: None, image_picker=lambda: "")
    for title in ("Lota 1.20.1", "Builder Pack", "Hardcore Instance"):
        QListWidgetItem(title, view.builds_list)
    view.info_card.set_content(
        title="Lota 1.20.1",
        version="1.20.1",
        body="Сборка с базовыми модами и рекомендованной конфигурацией для сервера.",
        image=None,
    )
    view.edit_instance_btn.show()
    view.open_build_dir_btn.show()
    view.info_action.show()
    shell = _wrap_launcher_shell(view)
    return shell, view


def build_instance_overlay_preview() -> tuple[QWidget, QWidget]:
    view = LibraryView(parent=None, overlay_submit=lambda *_: None, image_picker=lambda: "")
    shell = _wrap_launcher_shell(view)
    overlay = view.instance_overlay
    overlay.prepare_create_mode(
        [{"id": 1, "name": "Lota", "version": "1.20.1", "description": "Base build"}],
        [{"id": 10, "name": "Voice Chat", "version": "2.5"}],
    )
    view.resize(shell.content.size())
    overlay.setGeometry(view.rect())
    overlay.raise_()
    overlay.show()
    return shell, overlay


def build_account_preview() -> tuple[QWidget, QWidget]:
    view = AccountView(str(DEFAULT_STEVE))
    view.set_profile("xikki", "Legend", True)
    shell = _wrap_launcher_shell(view)
    return shell, view


def build_discord_dialog_preview() -> tuple[QWidget, QWidget]:
    dialog = DiscordLinkDialog("https://discord.gg/example")
    dialog.set_command("/link discord 123456")
    dialog.resize(560, 320)
    return dialog, dialog


SCREEN_BUILDERS = {
    "login": build_login_preview,
    "register_overlay": build_register_overlay_preview,
    "home": build_home_preview,
    "news_overlay": build_news_overlay_preview,
    "settings": build_settings_preview,
    "library": build_library_preview,
    "instance_overlay": build_instance_overlay_preview,
    "account": build_account_preview,
    "discord_dialog": build_discord_dialog_preview,
}


def build_application(argv: list[str]) -> QApplication:
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    app = QApplication(argv)
    set_language()

    asset_dir = PROJECT_ROOT / "assets"
    font_path = asset_dir / "fonts" / "Monocraft-ttf" / "Monocraft.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(_build_app_font(families[0], 14))
    app.setStyleSheet(build_app_qss(str(asset_dir)))
    return app


def main(argv: list[str]) -> int:
    app = build_application(argv)
    window = LayoutEditorWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
