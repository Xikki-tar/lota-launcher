from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from window.i18n import t
from window.ui_layout import apply_layout_overrides


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()
        self.apply_language()

    def _build_ui(self) -> None:
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(24, 24, 24, 24)
        self.root_layout.setSpacing(20)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.root_layout.addWidget(left_scroll, 1)

        self.left_widget = QWidget()
        self.left_widget.setProperty("panel", True)
        left_scroll.setWidget(self.left_widget)

        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(24, 24, 24, 24)
        self.left_layout.setSpacing(14)

        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.left_layout.addWidget(self.title_label)

        self.gb_lang = QGroupBox()
        self.gb_lang.setProperty("settingsGroup", True)
        lang_layout = QVBoxLayout(self.gb_lang)
        self.lang_combo = QComboBox()
        self.lang_combo.setProperty("settingsField", True)
        self.lang_combo.addItems(["Українська", "Русский", "English"])
        lang_layout.addWidget(self.lang_combo)
        self.left_layout.addWidget(self.gb_lang)

        self.gb_java = QGroupBox()
        self.gb_java.setProperty("settingsGroup", True)
        self.java_layout = QVBoxLayout(self.gb_java)
        self.java_layout.setSpacing(8)

        mem_row = QGridLayout()
        mem_row.setHorizontalSpacing(12)
        mem_row.setVerticalSpacing(6)

        self.mem_min_label = QLabel()
        self.mem_min_label.setProperty("settingsCaption", True)
        self.mem_min_label.setWordWrap(True)
        self.mem_min_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        mem_row.addWidget(self.mem_min_label, 0, 0)

        self.mem_min = QSpinBox()
        self.mem_min.setProperty("settingsField", True)
        self.mem_min.setRange(256, 65536)
        self.mem_min.setSingleStep(256)
        mem_row.addWidget(self.mem_min, 1, 0)

        self.mem_max_label = QLabel()
        self.mem_max_label.setProperty("settingsCaption", True)
        self.mem_max_label.setWordWrap(True)
        self.mem_max_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        mem_row.addWidget(self.mem_max_label, 0, 1)

        self.mem_max = QSpinBox()
        self.mem_max.setProperty("settingsField", True)
        self.mem_max.setRange(512, 65536)
        self.mem_max.setSingleStep(256)
        mem_row.addWidget(self.mem_max, 1, 1)

        self.java_layout.addLayout(mem_row)

        self.java_path_edit = QLineEdit()
        self.java_path_edit.setProperty("settingsField", True)
        self.java_layout.addWidget(self.java_path_edit)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addStretch()

        self.btn_browse = QPushButton()
        self.btn_browse.setProperty("settingsButton", True)
        path_row.addWidget(self.btn_browse)

        self.btn_auto = QPushButton()
        self.btn_auto.setProperty("settingsButton", True)
        path_row.addWidget(self.btn_auto)

        self.java_layout.addLayout(path_row)

        self.auto_java_version = QCheckBox()
        self.auto_java_version.setProperty("settingsCheck", True)
        self.java_layout.addWidget(self.auto_java_version)

        self.java_list = QListWidget()
        self.java_list.setFixedHeight(140)
        self.java_layout.addWidget(self.java_list)

        self.java_selected_info = QLabel()
        self.java_selected_info.setProperty("caption", True)
        self.java_layout.addWidget(self.java_selected_info)

        self.java_recommended = QLabel()
        self.java_recommended.setProperty("caption", True)
        self.java_layout.addWidget(self.java_recommended)

        self.jvm_args_label = QLabel()
        self.jvm_args_label.setProperty("settingsCaption", True)
        self.java_layout.addWidget(self.jvm_args_label)

        self.jvm_args_edit = QLineEdit()
        self.jvm_args_edit.setProperty("settingsField", True)
        self.jvm_args_edit.setPlaceholderText("-XX:+UseG1GC -Dfile.encoding=UTF-8 ...")
        self.java_layout.addWidget(self.jvm_args_edit)

        self.disable_openal = QCheckBox()
        self.disable_openal.setProperty("settingsCheck", True)
        self.java_layout.addWidget(self.disable_openal)

        self.left_layout.addWidget(self.gb_java)
        self.left_layout.addStretch()

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.setProperty("panel2", True)
        self.root_layout.addWidget(self.sidebar, 0)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(18, 20, 18, 18)
        self.sidebar_layout.setSpacing(12)

        self.btn_themes = QPushButton()
        self.btn_themes.setProperty("settingsButton", True)
        self.btn_themes.setProperty("settingsSidebarButton", True)

        self.btn_save = QPushButton()
        self.btn_save.setProperty("primary", True)
        self.btn_save.setProperty("settingsButton", True)
        self.btn_save.setProperty("settingsSidebarButton", True)
        self.btn_save.style().polish(self.btn_save)

        self.btn_back = QPushButton()
        self.btn_back.setProperty("settingsButton", True)
        self.btn_back.setProperty("settingsSidebarButton", True)

        self.sidebar_layout.addWidget(self.btn_themes)
        self.sidebar_layout.addStretch()
        self.sidebar_layout.addWidget(self.btn_save)
        self.sidebar_layout.addWidget(self.btn_back)

        self._apply_sidebar_button_style()
        apply_layout_overrides(self, "settings")

    def set_java_version_text(self, value: str) -> None:
        self.java_selected_info.setText(value)

    def selected_language(self) -> str:
        return self.lang_combo.currentText()

    def settings_payload(self) -> dict:
        return {
            "language": self.selected_language(),
            "mem_min_mb": self.mem_min.value(),
            "mem_max_mb": self.mem_max.value(),
            "java_path": self.java_path_edit.text().strip(),
            "auto_java_version": self.auto_java_version.isChecked(),
            "jvm_args": self.jvm_args_edit.text().strip(),
            "disable_openal": self.disable_openal.isChecked(),
        }

    def apply_language(self) -> None:
        self.title_label.setText(t("settings_title"))
        self.gb_lang.setTitle(t("settings_group_language"))
        self.gb_java.setTitle(t("settings_group_java"))
        self.mem_min_label.setText(t("settings_min_mem"))
        self.mem_max_label.setText(t("settings_max_mem"))
        self.java_path_edit.setPlaceholderText(t("settings_java_path_placeholder"))
        self.btn_browse.setText(t("btn_browse"))
        self.btn_auto.setText(t("btn_auto_detect"))
        self.auto_java_version.setText(t("settings_auto_java"))
        placeholder_texts = {
            "Версия: —",
            "Version: —",
            "Версія: —",
            "Версия: Java не найдена",
            "Version: Java not found",
            "Версія: Java не знайдено",
            "Версия: выберите Java из списка ниже",
            "Version: pick Java from the list below",
            "Версія: оберіть Java зі списку нижче",
        }
        if self.java_selected_info.text() in placeholder_texts:
            self.java_selected_info.setText(t("settings_java_version"))
        self.java_recommended.setText(t("settings_java_recommended"))
        self.jvm_args_label.setText(t("settings_jvm_args"))
        self.disable_openal.setText(t("settings_disable_openal"))
        self.btn_themes.setText(t("btn_themes"))
        self.btn_save.setText(t("btn_save"))
        self.btn_back.setText(t("btn_back"))
        self._apply_sidebar_button_style()
        apply_layout_overrides(self, "settings")

    def _apply_sidebar_button_style(self) -> None:
        sidebar_style = "font-size: 16px; padding: 6px 10px; min-height: 24px;"
        self.btn_themes.setStyleSheet(sidebar_style)
        self.btn_save.setStyleSheet(sidebar_style)
        self.btn_back.setStyleSheet(sidebar_style)
