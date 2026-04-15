import os

import requests
from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics, QPixmap
from PySide6.QtWidgets import QListWidgetItem

from auth.api_base import get_api_base
from auth.auth_storage import load_auth_data, load_settings, save_settings
from services.library_service import LibraryService
from window.chrome import show_app_message
from window.i18n import t
from window.views.library_view import LibraryView


class DownloadWorker(QThread):
    progress = Signal(int)
    finished = Signal(str)
    failed = Signal(str)
    canceled = Signal()

    def __init__(self, base_url: str, token: str, build_id: int, dest: str, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.token = token
        self.build_id = build_id
        self.dest = dest
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self):
        try:
            with requests.post(
                f"{self.base_url}/api/build/download",
                json={"token": self.token, "build_id": self.build_id},
                stream=True,
                timeout=120,
            ) as response:
                if response.status_code != 200:
                    self.failed.emit(f"HTTP {response.status_code}")
                    return
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                os.makedirs(os.path.dirname(self.dest), exist_ok=True)
                with open(self.dest, "wb") as output:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if self._cancel_requested:
                            output.close()
                            try:
                                os.remove(self.dest)
                            except OSError:
                                pass
                            self.canceled.emit()
                            return
                        if not chunk:
                            continue
                        output.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(int(downloaded * 100 / total))
                self.finished.emit(self.dest)
        except Exception as exc:
            self.failed.emit(str(exc))


class LibraryController:
    def __init__(self, view, main_window, library_service: LibraryService):
        self.view = view
        self.main_window = main_window
        self.library_service = library_service
        self._builds: list[dict] = []
        self._dlc: list[dict] = []
        self._library_base_dir = self.library_service.local_asset_dir()
        self._current_item = None
        self._current_is_build = False
        self._download_worker = None
        self._download_target = None
        self._connect_signals()
        self.refresh()

    def shutdown(self) -> None:
        worker = self._download_worker
        if worker and worker.isRunning():
            try:
                worker.cancel()
                worker.wait()
            except Exception:
                pass
        if not worker or not worker.isRunning():
            self._download_worker = None
            self._download_target = None

    def _connect_signals(self):
        self.view.btn_back.clicked.connect(self.on_back)
        self.view.builds_list.itemClicked.connect(self.on_build_clicked)
        self.view.info_action.clicked.connect(self.on_info_action_clicked)
        self.view.open_build_dir_btn.clicked.connect(self.on_open_build_dir_clicked)
        self.view.add_instance_btn.clicked.connect(self.open_add_instance)
        self.view.edit_instance_btn.clicked.connect(self.open_edit_instance)
        self.view.download_cancel_btn.clicked.connect(self.cancel_download)

    def refresh(self):
        self._load_items()
        self._populate_lists()

    def apply_language(self):
        LibraryView.apply_language(self.view)
        self._refresh_action_button()

    def on_back(self):
        self.main_window.show_home()

    def resize(self):
        width = max(160, int(self.view.left_widget.width() * 0.5) - 24)
        self.view.info_action.setFixedWidth(width)
        self.view.edit_instance_btn.setFixedWidth(width)
        self.view.open_build_dir_btn.setFixedWidth(width)
        if self.view.instance_overlay.isVisible():
            self.view.instance_overlay.setGeometry(0, 0, self.view.width(), self.view.height())

    def random_cached_image(self) -> str:
        return self.library_service.pick_random_cached_image()

    def _load_items(self):
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        try:
            catalog = self.library_service.load_catalog(token)
        except Exception:
            if hasattr(self.main_window, "show_toast"):
                self.main_window.show_toast(t("toast_no_connection"))
            catalog = self.library_service.load_catalog("")
        self._builds = catalog.builds
        self._dlc = catalog.dlc
        self._library_base_dir = catalog.base_dir

    def _populate_lists(self):
        self.view.builds_list.clear()

        def sort_key(item: dict) -> int:
            try:
                return int(item.get("id") or 0)
            except Exception:
                return int(item.get("created_at") or 0)

        builds_sorted = sorted(self._builds, key=sort_key, reverse=True)
        max_width = max(80, self.view.builds_list.viewport().width() - 46)
        metrics = QFontMetrics(self.view.builds_list.font())
        for item in builds_sorted:
            title = self._format_title(item)
            title = metrics.elidedText(title, Qt.ElideRight, max_width)
            row = QListWidgetItem(title)
            row_data = dict(item)
            row_data["_installed"] = self.library_service.is_build_installed(item)
            row.setData(Qt.UserRole, row_data)
            self.view.builds_list.addItem(row)

    def on_build_clicked(self, item: QListWidgetItem):
        if item is None:
            return
        data = item.data(Qt.UserRole) or {}
        self._current_item = data
        self._current_is_build = True
        pixmap = self._load_info_pixmap(data)
        self.view.info_card.set_content(
            title=self._format_title(data),
            version=str(data.get("version") or ""),
            body=str(data.get("description") or ""),
            image=pixmap,
        )
        self.view.edit_instance_btn.setVisible(bool(data.get("is_instance")))
        self._refresh_action_button()

    def on_info_action_clicked(self):
        if not self._current_is_build or not isinstance(self._current_item, dict):
            return
        item = self._current_item
        if not self.library_service.is_build_installed(item):
            self._on_download_clicked(item)
            self._refresh_action_button()
            return
        self._set_selected_build(self.library_service.build_key(item))
        self._refresh_action_button()

    def on_open_build_dir_clicked(self):
        build_dir = self._current_build_dir()
        if build_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(build_dir))

    def open_add_instance(self):
        base_builds = [build for build in self._builds if not build.get("is_instance")]
        self.view.instance_overlay.prepare_create_mode(base_builds, self._dlc)
        self.view.instance_overlay.apply_language()
        self.view.instance_overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        self.view.instance_overlay.raise_()
        self.view.instance_overlay.animate_open()

    def open_edit_instance(self):
        if not isinstance(self._current_item, dict) or not self._current_item.get("is_instance"):
            return
        self.view.instance_overlay.set_data([self._current_item], self._dlc)
        self.view.instance_overlay.reset_dirty()
        self.view.instance_overlay.set_edit_mode(self._current_item)
        self.view.instance_overlay.fill_from_instance(self._current_item)
        self.view.instance_overlay.apply_language()
        self.view.instance_overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        self.view.instance_overlay.raise_()
        self.view.instance_overlay.animate_open()

    def handle_overlay_submit(self, payload: dict):
        if payload.get("_edit") and isinstance(payload.get("instance"), dict):
            self._update_instance(payload["instance"], payload)
            self.view.instance_overlay.animate_close()
            return
        if payload.get("_delete") and isinstance(payload.get("instance"), dict):
            self._delete_instance(payload["instance"])
            self.view.instance_overlay.animate_close()
            return

        name = str(payload.get("name") or "").strip()
        build = payload.get("build") or {}
        if not name:
            show_app_message(self.main_window, t("library_instance_title"), t("library_instance_error_name"), kind="warning")
            return
        if not isinstance(build, dict) or not build.get("id"):
            show_app_message(self.main_window, t("library_instance_title"), t("library_instance_error_build"), kind="warning")
            return

        instances = self.library_service.load_instances()
        instance = self.library_service.create_instance(payload)
        instances.insert(0, instance)
        self.library_service.save_instances(instances)
        self.view.instance_overlay.animate_close()
        self.refresh()
        self._download_instance_build(instance, build)

    def cancel_download(self):
        if self._download_worker and self._download_worker.isRunning():
            try:
                self._download_worker.cancel()
                self._download_worker.wait(2000)
            except Exception:
                pass
        self._handle_download_canceled()

    def _on_download_clicked(self, item: dict):
        if item.get("_installed"):
            self._delete_build(item)
            return
        if item.get("is_instance"):
            source_build = {"id": item.get("_source_build_id")}
            self._download_instance_build(item, source_build)
            return
        if item.get("id"):
            self._download_build_from_server(item)
            return
        url = item.get("download_url")
        if url:
            QDesktopServices.openUrl(QUrl(str(url)))

    def _download_build_from_server(self, item: dict):
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        build_id = item.get("id")
        if not token or not build_id:
            return
        dest = str(self.library_service.build_archive_path(item))
        self.view.download_progress.setValue(0)
        self.view.download_progress.show()
        self.view.download_cancel_btn.show()
        self.view.download_status.setText(t("library_download_status").format(build_id=build_id))
        try:
            base_url = get_api_base()
        except Exception:
            self._handle_download_failed(t("error_conn_refused"))
            return
        try:
            build_id_int = int(build_id)
        except (TypeError, ValueError):
            self._handle_download_failed(t("library_instance_error_build"))
            return
        worker = DownloadWorker(base_url, token, build_id_int, dest, self.view)
        self._download_worker = worker
        self._download_target = item
        worker.progress.connect(self.view.download_progress.setValue)
        worker.finished.connect(lambda path: self._finalize_download(item, path))
        worker.failed.connect(self._handle_download_failed)
        worker.canceled.connect(self._handle_download_canceled)
        worker.start()

    def _download_instance_build(self, instance: dict, source_build: dict):
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        build_id = source_build.get("id")
        if not token or not build_id:
            return
        dest = str(self.library_service.build_archive_path(instance))
        self.view.download_progress.setValue(0)
        self.view.download_progress.show()
        self.view.download_status.show()
        self.view.download_cancel_btn.show()
        self.view.download_status.setText(t("library_download_status").format(build_id=build_id))
        try:
            base_url = get_api_base()
        except Exception:
            self._handle_download_failed(t("error_conn_refused"))
            return
        try:
            build_id_int = int(build_id)
        except (TypeError, ValueError):
            self._handle_download_failed(t("library_instance_error_build"))
            return
        worker = DownloadWorker(base_url, token, build_id_int, dest, self.view)
        self._download_worker = worker
        self._download_target = instance
        worker.progress.connect(self.view.download_progress.setValue)
        worker.finished.connect(lambda path: self._finalize_download(instance, path))
        worker.failed.connect(self._handle_download_failed)
        worker.canceled.connect(self._handle_download_canceled)
        worker.start()

    def _finalize_download(self, item: dict, path: str):
        self.view.download_status.setText("")
        self.view.download_progress.hide()
        self.view.download_cancel_btn.hide()
        try:
            self.library_service.extract_build_archive(
                self.library_service.build_archive_path(item),
                self.library_service.build_install_dir(item),
            )
            try:
                os.remove(path)
            except Exception:
                pass
        except Exception:
            pass
        self._download_target = None
        self.refresh()
        self._refresh_action_button()

    def _handle_download_failed(self, message: str):
        self.view.download_status.setText(t("library_download_failed").format(message=message))
        self.view.download_progress.hide()
        self.view.download_cancel_btn.hide()
        self._download_target = None
        if hasattr(self.main_window, "show_toast"):
            self.main_window.show_toast(t("toast_no_connection"))

    def _handle_download_canceled(self):
        self.view.download_progress.hide()
        self.view.download_cancel_btn.hide()
        self.view.download_status.setText(t("library_download_canceled"))
        self._download_target = None

    def _delete_build(self, item: dict):
        try:
            self.library_service.delete_build_files(item)
        except Exception:
            return
        selected = self._get_selected_build()
        if selected and selected == self.library_service.build_key(item):
            self._set_selected_build("")
        self._populate_lists()

    def _load_info_pixmap(self, item: dict) -> QPixmap | None:
        img_path = self.library_service.resolve_image_path(self._library_base_dir, item)
        if not img_path:
            return None
        pixmap = QPixmap(str(img_path))
        return pixmap if not pixmap.isNull() else None

    def _current_build_dir(self) -> str | None:
        if not self._current_is_build or not isinstance(self._current_item, dict):
            return None
        build_dir = self.library_service.build_install_dir(self._current_item)
        return str(build_dir) if build_dir.is_dir() else None

    def _refresh_action_button(self):
        if not self._current_is_build or not isinstance(self._current_item, dict):
            self.view.open_build_dir_btn.hide()
            self.view.info_action.hide()
            return
        item = self._current_item
        installed = self.library_service.is_build_installed(item)
        selected = self._get_selected_build()
        build_key = self.library_service.build_key(item)
        self.view.info_action.show()
        self.view.open_build_dir_btn.setVisible(installed)
        if not installed:
            downloading = self._download_worker is not None and self._download_target == item
            self.view.info_action.setEnabled(not downloading)
            self.view.info_action.setText(t("library_btn_downloading") if downloading else t("library_btn_download"))
            return
        if selected and selected == build_key:
            self.view.info_action.setEnabled(False)
            self.view.info_action.setText(t("library_btn_selected"))
            return
        self.view.info_action.setEnabled(True)
        self.view.info_action.setText(t("library_btn_select"))

    def _format_title(self, item: dict) -> str:
        name = str(item.get("name") or "—")
        if item.get("is_instance"):
            return name
        return f"{name} {str(item.get('version') or '')}".strip()

    def _get_selected_build(self) -> str:
        settings = load_settings()
        return str(settings.get("selected_build") or "").strip()

    def _set_selected_build(self, value: str):
        settings = load_settings()
        settings["selected_build"] = value or ""
        save_settings(settings)

    def _update_instance(self, instance: dict, payload: dict):
        self.library_service.update_instance(instance.get("id"), payload)
        self.refresh()

    def _delete_instance(self, instance: dict):
        target_id = instance.get("id")
        try:
            self.library_service.delete_instance(target_id)
            self.library_service.delete_build_files(instance)
        except Exception:
            pass
        if isinstance(self._current_item, dict) and self._current_item.get("id") == target_id:
            self._current_item = None
            self._current_is_build = False
            self.view.info_card.set_content(
                title=t("library_info_empty_title"),
                version="",
                body=t("library_info_empty_body"),
                image=None,
            )
            self.view.edit_instance_btn.hide()
            self.view.info_action.hide()
        self.refresh()
