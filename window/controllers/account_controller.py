from PySide6.QtCore import QThread, QTimer, QUrl, Signal
from PySide6.QtWidgets import QFileDialog

from services.account_service import AccountService
from window.chrome import show_app_message
from window.i18n import t
from window.views.account_view import DiscordLinkDialog, SkinModelDialog


class SkinSyncWorker(QThread):
    done = Signal(object)

    def __init__(self, service: AccountService, parent=None):
        super().__init__(parent)
        self.service = service

    def run(self):
        try:
            self.done.emit(self.service.sync_skin_from_server())
        except Exception as exc:
            self.done.emit({"ok": False, "error": str(exc)})


class AccountController:
    def __init__(self, view, main_window, service: AccountService | None = None):
        self.view = view
        self.main_window = main_window
        self.service = service or AccountService()
        self._discord_dialog: DiscordLinkDialog | None = None
        self._skin_sync_worker: SkinSyncWorker | None = None
        self._discord_poll_timer = QTimer(self.view)
        self._discord_poll_timer.setInterval(3000)
        self._discord_poll_timer.timeout.connect(self._poll_discord_status)
        self._discord_token = ""
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.view.btn_back.clicked.connect(self.on_back)
        self.view.btn_change_skin.clicked.connect(self.on_change_skin)
        self.view.btn_link_discord.clicked.connect(self.on_link_discord)

    def refresh(self, *, remote_skin: bool = False) -> None:
        self._render_cached_profile()
        if remote_skin:
            self._refresh_skin_from_server()

    def _render_cached_profile(self) -> None:
        profile = self.service.load_profile()
        self.view.set_profile(
            username=str(profile.get("username") or "—"),
            sub_level=int(profile.get("sub_level") or 0),
            rank_name=str(profile.get("rank_name") or "—"),
            is_active=bool(profile.get("is_active")),
        )
        self.view.set_skin_path(str(self.service.skin_file()))

    def on_back(self) -> None:
        self.main_window.show_home()

    def on_change_skin(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self.view,
            t("dialog_select_skin"),
            "",
            t("dialog_png_files"),
        )
        if not file_path:
            return
        model_dialog = SkinModelDialog(self.view)
        if model_dialog.exec() != SkinModelDialog.Accepted:
            return
        selected_model = model_dialog.selected_model()
        try:
            payload = self.service.upload_skin(file_path, model=selected_model)
        except Exception:
            show_app_message(
                self.main_window,
                t("account_skin"),
                t("account_skin_upload_failed"),
                kind="error",
            )
            return

        data = payload.get("data") or {}
        if payload.get("status_code") != 200 or not data.get("ok"):
            error = str(data.get("error") or "").strip()
            if error == "skin_too_large":
                message = t("account_skin_too_large").format(max_human=str(data.get("max_human") or "16 KiB"))
            elif error == "bad_skin_dimensions":
                message = t("account_skin_bad_dimensions")
            elif error == "bad_skin_format":
                message = t("account_skin_bad_format")
            elif error in {"invalid_token", "no_token", "inactive"}:
                message = t("error_auth")
            else:
                message = t("account_skin_upload_failed")
            show_app_message(self.main_window, t("account_skin"), message, kind="error")
            return

        try:
            saved_path = self.service.save_skin(file_path, model=selected_model)
        except Exception as exc:
            show_app_message(
                self.main_window,
                t("account_skin"),
                t("account_skin_save_failed").format(error=exc),
                kind="error",
            )
            return
        self.view.set_skin_path(str(saved_path))
        self._render_cached_profile()
        show_app_message(self.main_window, t("account_skin"), t("account_skin_uploaded"))

    def _refresh_skin_from_server(self) -> None:
        if self._skin_sync_worker and self._skin_sync_worker.isRunning():
            return
        worker = SkinSyncWorker(self.service, self.view)
        self._skin_sync_worker = worker
        worker.done.connect(self._on_skin_synced)
        worker.finished.connect(lambda: self._clear_skin_sync_worker(worker))
        worker.start()

    def _on_skin_synced(self, payload: dict) -> None:
        if not isinstance(payload, dict) or not payload.get("ok"):
            return
        path = str(payload.get("path") or "").strip()
        if path:
            self.view.set_skin_path(path)

    def _clear_skin_sync_worker(self, worker) -> None:
        if self._skin_sync_worker is worker:
            self._skin_sync_worker = None

    def on_link_discord(self) -> None:
        token = self.service.auth_token()
        if not token:
            show_app_message(self.main_window, t("account_dialog_discord"), t("error_auth"), kind="warning")
            return
        try:
            payload = self.service.request_discord_link(token)
        except Exception:
            show_app_message(self.main_window, t("account_dialog_discord"), t("error_conn_refused"), kind="warning")
            return

        data = payload.get("data") or {}
        if payload.get("status_code") == 409 and str(data.get("error") or "").strip().lower() == "discord_already_linked":
            show_app_message(self.main_window, t("account_dialog_discord"), t("account_discord_already_linked"))
            return
        if payload.get("status_code") != 200 or not data.get("ok"):
            show_app_message(self.main_window, t("account_dialog_discord"), t("error_server"), kind="warning")
            return

        dialog = DiscordLinkDialog(QUrl(self.service.discord_bot_url()), self.view)
        dialog.set_command(str(data.get("discord_command") or "").strip())
        dialog.copy_button.clicked.connect(self._on_discord_command_copied)
        dialog.finished.connect(self._stop_discord_polling)
        self._discord_dialog = dialog
        self._discord_token = token
        self._discord_poll_timer.start()
        dialog.exec()

    def _poll_discord_status(self) -> None:
        if not self._discord_token:
            return
        try:
            payload = self.service.poll_discord_link(self._discord_token)
        except Exception:
            return
        data = payload.get("data") or {}
        if payload.get("status_code") != 200 or not data.get("ok"):
            return
        if str(data.get("status") or "").strip().lower() == "linked":
            self._stop_discord_polling()
            show_app_message(self.main_window, t("account_dialog_discord"), t("account_discord_linked"))
            if self._discord_dialog is not None:
                self._discord_dialog.accept()

    def _on_discord_command_copied(self) -> None:
        show_app_message(self.main_window, t("account_dialog_discord"), t("account_discord_command_copied"))

    def _stop_discord_polling(self, *_args) -> None:
        self._discord_poll_timer.stop()
        self._discord_token = ""
