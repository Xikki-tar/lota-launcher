from pathlib import Path

from PySide6.QtCore import QTimer

from auth.auth_storage import load_auth_data
from services.news_service import NewsService
from services.play_service import PlayService, PlayWorker
from window.chrome import ask_app_confirmation, show_app_message
from window.i18n import t
from window.views.home_view import HomeView, NewsCard


class HomeController:
    def __init__(self, view, main_window, news_service: NewsService | None = None, play_service: PlayService | None = None):
        self.view = view
        self.main_window = main_window
        self.news_service = news_service or NewsService()
        self.play_service = play_service or PlayService()
        self._play_worker = None
        self._mc_proc = None
        self._mc_log_file = None
        self._mc_running = False
        self._bundle_state = None
        self._news_manifest = None
        self._news_images: dict[str, bytes] = {}
        self._news_worker = None
        self._proc_timer = QTimer(self.view)
        self._proc_timer.setInterval(1000)
        self._proc_timer.timeout.connect(self._poll_proc)
        self._connect_signals()
        self._news_manifest = self.news_service.load_cached_manifest()
        self._render_news(self._news_manifest)
        QTimer.singleShot(0, self.refresh_news_background)
        self.refresh_profile()

    def shutdown(self) -> None:
        self._proc_timer.stop()
        for worker in (self._news_worker, self._play_worker):
            if worker and worker.isRunning():
                worker.wait()
        if not self._news_worker or not self._news_worker.isRunning():
            self._news_worker = None
        if not self._play_worker or not self._play_worker.isRunning():
            self._play_worker = None

    def _connect_signals(self):
        self.view.btn_account.clicked.connect(self.main_window.show_account)
        self.view.btn_library.clicked.connect(self.main_window.show_library)
        self.view.btn_friends.clicked.connect(self.main_window.show_friends)
        self.view.btn_settings.clicked.connect(self.main_window.show_settings)
        self.view.btn_exit.clicked.connect(self.main_window.on_exit_clicked)
        self.view.btn_play.clicked.connect(self.on_play_clicked)

    def apply_language(self):
        HomeView.apply_language(self.view, self._mc_running)
        self._render_news(self._news_manifest)

    def refresh_profile(self):
        auth = load_auth_data() or {}
        username = auth.get("username") or "—"
        self.view.set_username(username)
        ref_h = None
        account_page = getattr(self.main_window, "account_page", None)
        viewer = getattr(account_page, "skin_viewer", None)
        if viewer:
            ref_h = max(1, (viewer.height() or viewer.minimumHeight()) - 40)
        self.view.avatar.refresh(reference_rect_height=ref_h)

    def refresh_news_background(self):
        if self._news_worker and self._news_worker.isRunning():
            return
        worker = self.news_service.build_refresh_worker(parent=self.view)
        self._news_worker = worker
        worker.loaded.connect(self._on_news_loaded)
        worker.finished.connect(lambda: self._clear_news_worker(worker))
        worker.start()

    def _on_news_loaded(self, payload: dict):
        manifest = payload.get("manifest") if isinstance(payload, dict) else None
        images = payload.get("images") if isinstance(payload, dict) else None
        server_unreachable = bool(payload.get("server_unreachable")) if isinstance(payload, dict) else False
        if isinstance(images, dict):
            self._news_images = images
        if isinstance(manifest, dict):
            self._news_manifest = manifest
            self._render_news(manifest)
        if server_unreachable:
            self.main_window.show_toast(t("toast_no_connection"))

    def _clear_news_worker(self, worker) -> None:
        if self._news_worker is worker:
            self._news_worker = None

    def _render_news(self, manifest: dict | None):
        while self.view.news_box.count():
            item = self.view.news_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        items = self.news_service.sorted_items(manifest)
        if not items:
            self.view.show_news_empty()
            return

        for entry in items[:5]:
            payload = self.news_service.format_news_card_payload(entry)
            image = None
            if entry.get("image"):
                image = self.news_service.pixmap_from_cache(str(entry.get("image")), self._news_images)
            card = NewsCard(
                title=payload["title"],
                date=payload["date"],
                body=payload["body"],
                news_type_label=payload["type_label"],
                news_type_key=payload["type_key"],
                on_open=self._open_news_details,
                payload=payload,
                image=image,
            )
            self.view.news_box.addWidget(card)

    def _open_news_details(self, payload: dict):
        if not isinstance(payload, dict):
            return
        changes = payload.get("changes") or []
        changes_text = "\n".join([f"- {item}" for item in changes if isinstance(item, str)]) if changes else ""
        self.view.details_overlay.set_content(
            title=str(payload.get("title") or "—"),
            date=str(payload.get("date") or ""),
            body=str(payload.get("details") or payload.get("body") or ""),
            changes_text=changes_text,
        )
        self.view.details_overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        self.view.details_overlay.raise_()
        self.view.details_overlay.animate_open()

    def resize_event(self):
        if self.view.details_overlay.isVisible():
            self.view.details_overlay.setGeometry(0, 0, self.view.width(), self.view.height())

    def on_play_clicked(self):
        if self._mc_proc and self._mc_proc.poll() is None:
            try:
                self._mc_proc.terminate()
            except Exception:
                pass
            return
        if self._play_worker and self._play_worker.isRunning():
            return

        allow_build_update = True
        try:
            update_state = self.play_service.get_selected_build_update_state()
        except Exception:
            update_state = {"needs_update": False}
        if update_state.get("needs_update"):
            source_item = update_state.get("source_item") or update_state.get("selected_item") or {}
            build_name = str(source_item.get("name") or source_item.get("version") or update_state.get("selected") or "сборка")
            build_version = str(source_item.get("version") or "").strip()
            build_label = f"{build_name} {build_version}".strip()
            allow_build_update = ask_app_confirmation(
                self.main_window,
                t("build_update_title"),
                t("build_update_text").format(build=build_label),
                kind="warning",
            )

        self.view.set_play_preparing()
        worker = PlayWorker(allow_build_update=allow_build_update)
        self._play_worker = worker
        worker.status.connect(self.view.play_status.setText)
        worker.progress.connect(self.view.play_progress.setValue)
        worker.failed.connect(self._on_play_failed)
        worker.ready.connect(self._on_play_ready)
        worker.finished.connect(lambda: self._clear_play_worker(worker))
        worker.start()

    def _clear_play_worker(self, worker) -> None:
        if self._play_worker is worker:
            self._play_worker = None

    def _on_play_failed(self, message: str):
        self.view.play_status.setText(t("play_failed"))
        self.view.play_progress.hide()
        self.view.btn_play.setEnabled(True)
        show_app_message(self.main_window, t("play_error_title"), message, kind="error")

    def _on_play_ready(self, spec):
        try:
            self._bundle_state = self.play_service.prepare_bundle_files(Path(spec.cwd))
            _log_path, self._mc_log_file = self.play_service.open_log_file(spec)
            self._mc_proc = self.play_service.launch_process(spec, self._mc_log_file)
            self.view.clear_play_feedback()
            self._mc_running = True
            self.view.set_play_running_state(True)
            self._proc_timer.start()
            if hasattr(self.main_window, "enter_game_background_mode"):
                self.main_window.enter_game_background_mode()
        except Exception as exc:
            self._on_play_failed(str(exc))

    def _poll_proc(self):
        if self._mc_proc is None or self._mc_proc.poll() is None:
            return
        self._proc_timer.stop()
        self._mc_proc = None
        try:
            if self._mc_log_file:
                try:
                    self._mc_log_file.close()
                except Exception:
                    pass
                self._mc_log_file = None
            self.view.clear_play_feedback()
            self._mc_running = False
            self.view.set_play_running_state(False)
            self.play_service.cleanup_bundle_files(self._bundle_state)
            self._bundle_state = None
        finally:
            if hasattr(self.main_window, "leave_game_background_mode"):
                self.main_window.leave_game_background_mode()
