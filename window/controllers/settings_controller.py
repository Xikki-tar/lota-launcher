from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import QFileDialog, QListWidgetItem

from services.settings_service import SettingsService
from window.chrome import show_app_message
from window.i18n import set_language, t


class JavaVersionWorker(QThread):
    done = Signal(str, str)

    def __init__(self, service: SettingsService, java_path: str, parent=None):
        super().__init__(parent)
        self.service = service
        self.java_path = str(java_path or "").strip()

    def run(self) -> None:
        version_text = self.service.get_java_version_text(self.java_path)
        self.done.emit(self.java_path, version_text)


class SettingsController:
    def __init__(self, view, main_window, service: SettingsService | None = None):
        self.view = view
        self.main_window = main_window
        self.service = service or SettingsService()
        self._java_version_worker: JavaVersionWorker | None = None
        self._java_version_path = ""
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.view.btn_back.clicked.connect(self.on_back)
        self.view.btn_save.clicked.connect(self.on_save)
        self.view.btn_themes.clicked.connect(self.on_themes)
        self.view.btn_browse.clicked.connect(self.on_browse_java)
        self.view.btn_auto.clicked.connect(self.on_auto_detect_java)
        self.view.java_list.itemClicked.connect(self.on_java_item_clicked)

    def load_into_ui(self) -> None:
        settings = self.service.load()

        language = settings.get("language", "Русский")
        index = self.view.lang_combo.findText(language)
        self.view.lang_combo.setCurrentIndex(index if index >= 0 else 1)

        self.view.mem_min.setValue(int(settings.get("mem_min_mb", 1024)))
        self.view.mem_max.setValue(int(settings.get("mem_max_mb", 4096)))
        self.view.java_path_edit.setText(settings.get("java_path", ""))
        self.view.auto_java_version.setChecked(settings.get("auto_java_version", True))
        self.view.jvm_args_edit.setText(self.service.default_jvm_args(settings.get("jvm_args", "")))
        self.view.disable_openal.setChecked(settings.get("disable_openal", False))

        java_path = self.view.java_path_edit.text().strip()
        self._show_selected_java_version(java_path)

    def refresh(self) -> None:
        self.load_into_ui()

    def on_save(self) -> None:
        if self.view.mem_min.value() > self.view.mem_max.value():
            show_app_message(self.main_window, t("settings_memory_title"), t("settings_memory_warning"), kind="warning")
            return

        data = self.service.load()
        data.update(self.view.settings_payload())
        self.service.save(data)
        set_language(data.get("language"))
        self.main_window.apply_language()
        show_app_message(self.main_window, t("settings_saved_title"), t("settings_saved_text"))

    def on_back(self) -> None:
        self.main_window.show_home()

    def on_themes(self) -> None:
        show_app_message(
            self.main_window,
            t("settings_themes_title"),
            t("settings_themes_text"),
        )

    def on_browse_java(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self.view,
            t("settings_group_java"),
            "",
            t("dialog_all_files"),
        )
        if not path:
            return
        self.view.java_path_edit.setText(path)
        self._show_selected_java_version(path)

    def on_auto_detect_java(self) -> None:
        self.view.java_list.clear()
        candidates = self.service.get_java_candidates()
        if not candidates:
            self.view.set_java_version_text(t("settings_java_not_found"))
            return

        show_versions = self.view.auto_java_version.isChecked()
        for path in candidates:
            version = self.service.get_java_version_text(path)
            text = f"{path}  |  {version}" if show_versions else path
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, path)
            self.view.java_list.addItem(item)

        best_path = str(candidates[0] or "").strip()
        if best_path:
            self.view.java_path_edit.setText(best_path)
            self._show_selected_java_version(best_path)
            self.view.java_list.setCurrentRow(0)
            return

        self.view.set_java_version_text(t("settings_java_pick"))

    def on_java_item_clicked(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.UserRole) or "").strip()
        self.view.java_path_edit.setText(path)
        self._show_selected_java_version(path)

    def _show_selected_java_version(self, java_path: str) -> None:
        java_path = str(java_path or "").strip()
        if not java_path:
            self.view.set_java_version_text(t("settings_java_version"))
            return
        version_prefix = t("settings_java_version").split(":")[0]
        self._java_version_path = java_path
        self.view.set_java_version_text(f"{version_prefix}: ...")
        worker = JavaVersionWorker(self.service, java_path, self.view)
        self._java_version_worker = worker
        worker.done.connect(self._on_java_version_loaded)
        worker.finished.connect(lambda: self._clear_java_version_worker(worker))
        worker.start()

    def _on_java_version_loaded(self, java_path: str, version_text: str) -> None:
        if str(java_path or "").strip() != self._java_version_path:
            return
        version_prefix = t("settings_java_version").split(":")[0]
        self.view.set_java_version_text(f"{version_prefix}: {version_text}")

    def _clear_java_version_worker(self, worker: JavaVersionWorker) -> None:
        if self._java_version_worker is worker:
            self._java_version_worker = None
