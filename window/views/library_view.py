from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from window.i18n import t
from window.ui_layout import apply_layout_overrides


class InstanceCreateOverlay(QFrame):
    def __init__(self, parent: QWidget, on_submit, image_picker):
        super().__init__(parent)
        self.setProperty("instanceOverlay", True)
        self.setVisible(False)
        self._on_submit = on_submit
        self._image_picker = image_picker
        self._applying_defaults = False
        self._name_dirty = False
        self._desc_dirty = False
        self._image_dirty = False
        self._fade = None
        self._editing_instance = None

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(28, 28, 28, 28)
        self.root_layout.addStretch()

        self.panel = QFrame()
        self.panel.setProperty("instancePanel", True)
        self.panel.setMaximumWidth(760)
        self.root_layout.addWidget(self.panel, alignment=Qt.AlignHCenter)
        self.root_layout.addStretch()

        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(18, 16, 18, 16)
        self.panel_layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setProperty("instanceTitle", True)
        self.title_label.setWordWrap(True)
        self.panel_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("caption", True)
        self.subtitle_label.setWordWrap(True)
        self.panel_layout.addWidget(self.subtitle_label)

        self.name_label = QLabel()
        self.name_label.setProperty("section", True)
        self.panel_layout.addWidget(self.name_label)
        self.name_input = QLineEdit()
        self.name_input.setProperty("instanceField", True)
        self.panel_layout.addWidget(self.name_input)

        self.desc_label = QLabel()
        self.desc_label.setProperty("section", True)
        self.panel_layout.addWidget(self.desc_label)
        self.desc_input = QTextEdit()
        self.desc_input.setProperty("instanceText", True)
        self.desc_input.setFixedHeight(76)
        self.panel_layout.addWidget(self.desc_input)

        self.image_label = QLabel()
        self.image_label.setProperty("section", True)
        self.panel_layout.addWidget(self.image_label)

        img_row = QHBoxLayout()
        img_row.setSpacing(8)
        self.image_input = QLineEdit()
        self.image_input.setProperty("instanceField", True)
        img_row.addWidget(self.image_input, 1)
        self.image_browse = QPushButton()
        self.image_browse.setProperty("ghost", True)
        self.image_browse.setProperty("instanceButton", True)
        img_row.addWidget(self.image_browse)
        self.panel_layout.addLayout(img_row)

        self.build_label = QLabel()
        self.build_label.setProperty("section", True)
        self.panel_layout.addWidget(self.build_label)
        self.build_combo = QComboBox()
        self.build_combo.setProperty("instanceField", True)
        self.panel_layout.addWidget(self.build_combo)

        self.dlc_label = QLabel()
        self.dlc_label.setProperty("section", True)
        self.panel_layout.addWidget(self.dlc_label)
        self.dlc_list = QListWidget()
        self.dlc_list.setProperty("instanceList", True)
        self.dlc_list.setFixedHeight(78)
        self.panel_layout.addWidget(self.dlc_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        self.cancel_btn = QPushButton()
        self.cancel_btn.setProperty("ghost", True)
        self.cancel_btn.setProperty("instanceButton", True)
        btn_row.addWidget(self.cancel_btn)
        self.delete_btn = QPushButton()
        self.delete_btn.setProperty("secondary", True)
        self.delete_btn.setProperty("instanceButton", True)
        self.delete_btn.hide()
        btn_row.addWidget(self.delete_btn)
        self.create_btn = QPushButton()
        self.create_btn.setProperty("accent", True)
        self.create_btn.setProperty("instanceButton", True)
        btn_row.addWidget(self.create_btn)
        self.panel_layout.addLayout(btn_row)

        self.image_browse.clicked.connect(self._browse_image)
        self.cancel_btn.clicked.connect(self.animate_close)
        self.create_btn.clicked.connect(self._handle_submit)
        self.delete_btn.clicked.connect(self._handle_delete)
        self.build_combo.currentIndexChanged.connect(self._apply_build_defaults)
        self.name_input.textEdited.connect(self._mark_name_dirty)
        self.desc_input.textChanged.connect(self._mark_desc_dirty)
        self.image_input.textEdited.connect(self._mark_image_dirty)

    def _browse_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("dialog_select_image"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            self.image_input.setText(path)

    def apply_random_default_image(self):
        if self._image_dirty or self.image_input.text().strip():
            return
        fallback = self._image_picker() if callable(self._image_picker) else ""
        if fallback:
            self.image_input.setText(fallback)

    def apply_text_defaults(self):
        build = self.build_combo.currentData()
        if not isinstance(build, dict):
            return
        fallback_name = str(build.get("name") or "").strip() or self.build_combo.currentText().strip()
        fallback_desc = str(build.get("description") or "").strip()
        self._applying_defaults = True
        if fallback_name and (not self._name_dirty or not self.name_input.text().strip()):
            self.name_input.setText(fallback_name)
        if fallback_desc and (not self._desc_dirty or not self.desc_input.toPlainText().strip()):
            self.desc_input.setPlainText(fallback_desc)
        self._applying_defaults = False

    def apply_language(self):
        self.title_label.setText(t("library_instance_title"))
        self.subtitle_label.setText(t("library_instance_subtitle"))
        self.name_label.setText(t("library_instance_name"))
        self.desc_label.setText(t("library_instance_desc"))
        self.image_label.setText(t("library_instance_image"))
        self.image_browse.setText(t("library_instance_browse"))
        self.build_label.setText(t("library_instance_build"))
        self.dlc_label.setText(t("library_instance_dlc"))
        self.cancel_btn.setText(t("library_instance_cancel"))
        self.delete_btn.setText(t("library_instance_delete"))
        self.create_btn.setText(t("library_instance_save") if self._editing_instance else t("library_instance_create"))
        apply_layout_overrides(self, "instance_overlay")

    def set_data(self, builds: list[dict], dlc: list[dict]):
        self._applying_defaults = True
        self.build_combo.clear()
        for item in builds:
            title = f"{item.get('name', '—')} {item.get('version', '')}".strip()
            self.build_combo.addItem(title, item)
        if self.build_combo.count() > 0:
            self.build_combo.setCurrentIndex(0)
            self._apply_build_defaults()
        self._applying_defaults = False

        self.dlc_list.clear()
        for item in dlc:
            title = f"{item.get('name', '—')} {item.get('version', '')}".strip()
            row = QListWidgetItem(title)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Unchecked)
            row.setData(Qt.UserRole, item)
            self.dlc_list.addItem(row)

    def set_edit_mode(self, instance: dict | None):
        self._editing_instance = instance if isinstance(instance, dict) else None
        self.delete_btn.setVisible(bool(self._editing_instance))
        self.build_combo.setEnabled(not self._editing_instance)
        self.create_btn.setText(t("library_instance_save") if self._editing_instance else t("library_instance_create"))

    def fill_from_instance(self, instance: dict):
        self.name_input.setText(str(instance.get("name") or ""))
        self.desc_input.setPlainText(str(instance.get("description") or ""))
        self.image_input.setText(str(instance.get("image") or ""))

    def prepare_create_mode(self, builds: list[dict], dlc: list[dict]):
        self._applying_defaults = True
        self.name_input.clear()
        self.desc_input.clear()
        self.image_input.clear()
        self._applying_defaults = False
        self.reset_dirty()
        self.set_edit_mode(None)
        self.set_data(builds, dlc)
        self.reset_dirty()
        self.apply_text_defaults()
        self._apply_build_defaults()
        self.apply_random_default_image()

    def reset_dirty(self):
        self._name_dirty = False
        self._desc_dirty = False
        self._image_dirty = False

    def _mark_name_dirty(self):
        if not self._applying_defaults:
            self._name_dirty = True

    def _mark_desc_dirty(self):
        if not self._applying_defaults:
            self._desc_dirty = True

    def _mark_image_dirty(self):
        if not self._applying_defaults:
            self._image_dirty = True

    def _handle_submit(self):
        payload = {
            "name": self.name_input.text().strip(),
            "description": self.desc_input.toPlainText().strip(),
            "image": self.image_input.text().strip(),
            "build": self.build_combo.currentData(),
        }
        if self._editing_instance:
            payload["_edit"] = True
            payload["instance"] = self._editing_instance
        if callable(self._on_submit):
            self._on_submit(payload)

    def _handle_delete(self):
        if callable(self._on_submit) and self._editing_instance:
            self._on_submit({"_delete": True, "instance": self._editing_instance})

    def _apply_build_defaults(self):
        build = self.build_combo.currentData()
        if not isinstance(build, dict):
            return
        self._applying_defaults = True
        name = str(build.get("name") or "").strip()
        if name and not self._name_dirty:
            self.name_input.setText(name)
        if not self._desc_dirty:
            self.desc_input.setPlainText(str(build.get("description") or ""))
        image = str(build.get("image") or "").strip()
        if image and not self._image_dirty:
            self.image_input.setText(image)
        self._applying_defaults = False
        self.apply_text_defaults()

    def animate_open(self):
        if self.isVisible():
            return
        self.setGraphicsEffect(QGraphicsOpacityEffect(self))
        self.graphicsEffect().setOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self.graphicsEffect(), b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._fade = anim
        anim.start()

    def animate_close(self):
        if not self.isVisible():
            return
        self.setGraphicsEffect(QGraphicsOpacityEffect(self))
        self.graphicsEffect().setOpacity(1.0)
        anim = QPropertyAnimation(self.graphicsEffect(), b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: (self.setGraphicsEffect(None), self.hide()))
        self._fade = anim
        anim.start()


class InstanceInfoCard(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("instanceInfoCard", True)
        self._raw_pixmap: QPixmap | None = None
        self._max_image_w = 520
        self._max_image_h = 220
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.title_label = QLabel("—")
        self.title_label.setProperty("instanceInfoTitle", True)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.version_label = QLabel("")
        self.version_label.setProperty("instanceInfoMeta", True)
        layout.addWidget(self.version_label)
        self.body_label = QLabel("")
        self.body_label.setProperty("instanceInfoBody", True)
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)
        self.image_label = QLabel()
        self.image_label.setProperty("instanceInfoImage", True)
        self.image_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.image_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout.addWidget(self.image_label)

    def set_content(self, title: str, version: str, body: str, image: QPixmap | None):
        self.title_label.setText(title or "—")
        self.version_label.setText(version or "")
        self.body_label.setText(body or "")
        if image is None or image.isNull():
            self._raw_pixmap = None
            self.image_label.clear()
            self.image_label.setFixedHeight(0)
            self.image_label.hide()
            return
        self._raw_pixmap = image
        self.image_label.show()
        self._refresh_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_image()

    def _refresh_image(self):
        if self._raw_pixmap is None or self._raw_pixmap.isNull():
            return
        layout = self.layout()
        if not layout:
            return
        margins = layout.contentsMargins()
        avail_w = max(1, self.width() - margins.left() - margins.right())
        raw_w = self._raw_pixmap.width()
        raw_h = self._raw_pixmap.height()
        if raw_w <= 0 or raw_h <= 0:
            return
        scale = min(1.0, min(self._max_image_w, avail_w) / raw_w, self._max_image_h / raw_h)
        target_w = max(1, int(raw_w * scale))
        target_h = max(1, int(raw_h * scale))
        pm = self._raw_pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pm)
        inset = 8
        self.image_label.setFixedHeight(pm.height() + inset * 2)
        self.image_label.setContentsMargins(inset, inset, inset, inset)


class LibraryView(QWidget):
    def __init__(self, parent: QWidget | None, overlay_submit, image_picker):
        super().__init__(parent)
        self._build_ui()
        self.instance_overlay = InstanceCreateOverlay(self, overlay_submit, image_picker)
        LibraryView.apply_language(self)

    def _build_ui(self):
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(24, 24, 24, 24)
        self.root_layout.setSpacing(20)

        self.left_widget = QWidget()
        self.left_widget.setProperty("panel", True)
        self.root_layout.addWidget(self.left_widget, 1)

        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(24, 24, 24, 24)
        self.left_layout.setSpacing(16)
        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.left_layout.addWidget(self.title_label)
        self.info_section = QLabel()
        self.info_section.setProperty("section", True)
        self.left_layout.addWidget(self.info_section)
        self.info_card = InstanceInfoCard()
        self.left_layout.addWidget(self.info_card)
        self.edit_instance_btn = QPushButton()
        self.edit_instance_btn.setProperty("accent", True)
        self.edit_instance_btn.hide()
        self.left_layout.addWidget(self.edit_instance_btn, alignment=Qt.AlignLeft)
        self.open_build_dir_btn = QPushButton()
        self.open_build_dir_btn.setProperty("ghost", True)
        self.open_build_dir_btn.hide()
        self.left_layout.addWidget(self.open_build_dir_btn, alignment=Qt.AlignLeft)
        self.info_action = QPushButton()
        self.info_action.setProperty("confirm", True)
        self.info_action.style().polish(self.info_action)
        self.info_action.hide()
        self.left_layout.addWidget(self.info_action, alignment=Qt.AlignLeft)
        self.left_layout.addStretch()

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.setProperty("panel2", True)
        self.root_layout.addWidget(self.sidebar, 0)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(6, 14, 12, 12)
        self.sidebar_layout.setSpacing(12)
        self.section_label = QLabel()
        self.section_label.setProperty("section", True)
        self.section_label.setStyleSheet("padding-left: 10px;")
        self.sidebar_layout.addWidget(self.section_label)

        builds_tab = QWidget()
        builds_layout = QVBoxLayout(builds_tab)
        builds_layout.setContentsMargins(0, 0, 0, 12)
        self.builds_list = QListWidget()
        self.builds_list.setProperty("panel2", True)
        self.builds_list.setFocusPolicy(Qt.NoFocus)
        self.builds_list.setUniformItemSizes(True)
        self.builds_list.setSpacing(6)
        self.builds_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.builds_list.setStyleSheet(
            "QListWidget { background: rgba(255,255,255,0.03); color: #E8DDC9; outline: none; "
            "border: 1px solid rgba(255,255,255,0.10); border-bottom-left-radius: 18px; "
            "border-bottom-right-radius: 18px; border-top-left-radius: 12px; border-top-right-radius: 12px; "
            "padding: 10px; margin-top: 0px; }"
            "QListWidget::item { padding: 10px 14px; margin: 6px 4px; border-radius: 12px; background: rgba(255,255,255,0.04); }"
            "QListWidget::item:selected { background: rgba(255,255,255,0.04); color: #E8DDC9; border: 1px solid rgba(255,255,255,0.08); outline: none; }"
            "QListWidget::item:focus { outline: none; }"
        )
        builds_layout.addWidget(self.builds_list)
        self.sidebar_layout.addWidget(builds_tab, 1)

        self.add_instance_btn = QPushButton()
        self.add_instance_btn.setProperty("accent", True)
        self.add_instance_btn.setFixedHeight(56)
        self.sidebar_layout.addWidget(self.add_instance_btn)
        self.btn_back = QPushButton()
        self.sidebar_layout.addWidget(self.btn_back)
        self.download_status = QLabel("")
        self.download_status.setProperty("caption", True)
        self.download_status.setWordWrap(True)
        self.download_status.hide()
        self.sidebar_layout.addWidget(self.download_status)
        self.download_progress = QProgressBar()
        self.download_progress.setRange(0, 100)
        self.download_progress.setValue(0)
        self.download_progress.hide()
        self.sidebar_layout.addWidget(self.download_progress)
        self.download_cancel_btn = QPushButton()
        self.download_cancel_btn.setProperty("ghost", True)
        self.download_cancel_btn.hide()
        self.sidebar_layout.addWidget(self.download_cancel_btn)
        apply_layout_overrides(self, "library")

    def apply_language(self):
        self.title_label.setText(t("library_title"))
        self.info_section.setText(t("library_info_section"))
        if self.info_card.title_label.text() in ("", "—"):
            self.info_card.set_content(
                title=t("library_info_empty_title"),
                version="",
                body=t("library_info_empty_body"),
                image=None,
            )
        self.section_label.setText(t("library_tab_builds"))
        self.add_instance_btn.setText(t("library_btn_add_instance").replace(" ", "\n", 1))
        self.edit_instance_btn.setText(t("library_btn_edit_instance"))
        self.open_build_dir_btn.setText(t("library_btn_open_folder"))
        self.btn_back.setText(t("btn_back"))
        self.download_cancel_btn.setText(t("library_btn_cancel_download"))
        self.instance_overlay.apply_language()
        apply_layout_overrides(self, "library")
