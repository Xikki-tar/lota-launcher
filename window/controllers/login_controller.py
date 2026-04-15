from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from services.login_service import LoginService
from window.i18n import t


class RegisterOverlayController:
    def __init__(self, view, service: LoginService, show_toast, on_auth_success):
        self.view = view
        self.service = service
        self.show_toast = show_toast
        self.on_auth_success = on_auth_success
        self._poll_timer = QTimer(view)
        self._poll_timer.setInterval(3000)
        self._poll_timer.timeout.connect(self.poll_status)
        self._request_worker = None
        self._connect_signals()

    def shutdown(self) -> None:
        self._poll_timer.stop()
        worker = self._request_worker
        if worker and worker.isRunning():
            worker.wait()
        if not worker or not worker.isRunning():
            self._request_worker = None

    def _connect_signals(self):
        self.view.telegram_button.clicked.connect(self.request_telegram_link)
        self.view.open_link_button.clicked.connect(self.open_link)
        self.view.copy_link_button.clicked.connect(self.copy_telegram_link)
        self.view.complete_button.clicked.connect(self.complete_registration)

    def apply_language(self):
        self.view.apply_language()

    def show_panel(self):
        self.view.setGeometry(self.view.parentWidget().rect())
        saved = self.service.load_saved_register_link() or {}
        self.view._link_token = str(saved.get("link_token") or "").strip()
        self.view._telegram_url = str(saved.get("telegram_url") or saved.get("action_value") or "").strip()
        self.view.username_input.clear()
        self.view.hide_error()
        if self.view._link_token and self.view._telegram_url:
            self.view.show_wait_page()
            self._poll_timer.start()
        else:
            self._show_choice_page(reset_link=False)
        self.view.show()
        self.view.raise_()

    def on_hide(self):
        self._poll_timer.stop()

    def request_telegram_link(self):
        if self.view._link_token and self.view._telegram_url:
            self.view.show_wait_page()
            self.view.hide_error()
            self._poll_timer.start()
            return
        self.view.show_wait_page()
        self.view.show_error(t("register_creating_link"))
        self._start_request("POST", "/api/register/telegram-link", callback=self._handle_link_created)

    def poll_status(self):
        if not self.view._link_token or (self._request_worker and self._request_worker.isRunning()):
            return
        self._start_request(
            "GET",
            "/api/register/telegram-status",
            params={"link_token": self.view._link_token},
            callback=self._handle_status_polled,
        )

    def complete_registration(self):
        self._start_request(
            "POST",
            "/api/register/complete",
            json_body={"link_token": self.view._link_token, "username": self.view.username_input.text().strip()},
            callback=self._handle_complete_result,
        )

    def open_link(self):
        if not self.view._telegram_url:
            self.show_toast(t("register_link_missing"))
            self.view.hide()
            return
        QDesktopServices.openUrl(QUrl(self.view._telegram_url))

    def copy_telegram_link(self):
        if not self.view._telegram_url:
            self.show_toast(t("register_link_missing"))
            return
        self.view.copy_telegram_link_to_clipboard()
        self.show_toast(t("register_link_copied"))

    def _start_request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None, callback=None):
        if self._request_worker and self._request_worker.isRunning():
            return
        self.view.set_busy(True)
        worker = self.service.build_worker(method, path, json_body=json_body, params=params)
        self._request_worker = worker

        def done(result):
            self.view.set_busy(False)
            if callback:
                callback(result)

        worker.done.connect(done)
        worker.finished.connect(lambda: self._clear_request_worker(worker))
        worker.start()

    def _clear_request_worker(self, worker) -> None:
        if self._request_worker is worker:
            self._request_worker = None

    def _show_choice_page(self, *, reset_link: bool = True):
        self._poll_timer.stop()
        if reset_link:
            self.view._link_token = ""
            self.view._telegram_url = ""
            self.service.clear_saved_register_link()
        self.view.username_input.clear()
        self.view.hide_error()
        self.view.show_choice_page()

    def _handle_link_created(self, result: dict):
        if not result.get("ok"):
            self.show_toast(t("toast_no_connection"))
            self._show_choice_page()
            self.view.show_error(t("error_conn_refused"))
            return
        status_code = int(result.get("status_code") or 0)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if status_code == 429:
            self._show_choice_page()
            self.view.show_error(t("register_rate_limited"))
            return
        if status_code != 200 or not data.get("ok"):
            self._show_choice_page()
            self.view.show_error(t("error_server"))
            return
        self.view._link_token = str(data.get("link_token") or "").strip()
        self.view._telegram_url = str(data.get("telegram_url") or "").strip()
        if self.view._link_token and self.view._telegram_url:
            self.service.persist_register_link(self.view._link_token, self.view._telegram_url)
        self.view.hide_error()
        self._poll_timer.start()

    def _handle_status_polled(self, result: dict):
        if not result.get("ok"):
            self._poll_timer.stop()
            self.show_toast(t("toast_no_connection"))
            self.view.show_error(t("error_conn_refused"))
            return
        status_code = int(result.get("status_code") or 0)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if status_code == 404:
            self._show_choice_page()
            self.view.show_error(t("register_invalid_link"))
            return
        if status_code != 200 or not data.get("ok"):
            return
        status = self._registration_status_from_response(data)
        if status == "pending":
            self.view.hide_error()
            return
        if status in {"verified", "confirmed", "approved", "success"}:
            self._poll_timer.stop()
            self.view.hide_error()
            if not self.view.isVisible():
                self.view.setGeometry(self.view.parentWidget().rect())
                self.view.show()
                self.view.raise_()
            self.view.show_complete_page()
            return
        if status == "expired":
            self._show_choice_page()
            self.view.show_error(t("register_link_expired"))
            return
        if status == "denied":
            self._show_choice_page()
            self.view.show_error(t("register_denied"))
            return
        if status == "completed":
            self._show_choice_page()
            self.view.show_error(t("register_already_completed"))

    def _registration_status_from_response(self, data: dict) -> str:
        nested = data.get("data")
        if isinstance(nested, dict):
            data = {**data, **nested}
        for key in ("status", "state", "registration_status", "telegram_status"):
            value = str(data.get(key) or "").strip().lower()
            if value:
                return value
        for key in ("verified", "confirmed", "telegram_verified", "is_verified"):
            if data.get(key) is True:
                return "verified"
        if data.get("completed") is True:
            return "completed"
        return ""

    def _handle_complete_result(self, result: dict):
        if not result.get("ok"):
            self.show_toast(t("toast_no_connection"))
            self.view.show_error(t("error_conn_refused"))
            return
        status_code = int(result.get("status_code") or 0)
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        error = str(data.get("error") or "").strip().lower()
        if status_code == 200 and data.get("ok"):
            self.service.clear_saved_register_link()
            self.service.persist_auth(
                str(data.get("token") or ""),
                str(data.get("username") or ""),
                str(data.get("status") or "active"),
                int(data.get("sub_level") or 0),
            )
            self.view.hide()
            self.on_auth_success()
            return
        if status_code == 412:
            self.view.show_error(t("register_username_required"))
            return
        if status_code == 409 and error == "username_taken":
            self.view.show_error(t("register_username_taken"))
            return
        if status_code == 409 and error == "telegram_not_verified":
            self.view.show_error(t("register_not_verified"))
            return
        if status_code == 409 and error in {"telegram_already_registered", "link_token_used"}:
            self._show_choice_page()
            self.view.show_error(t("register_already_completed"))
            return
        if status_code == 410:
            self._show_choice_page()
            self.view.show_error(t("register_link_expired"))
            return
        if status_code == 404:
            self._show_choice_page()
            self.view.show_error(t("register_invalid_link"))
            return
        if status_code == 400 and error.startswith("bad_username"):
            self.view.show_error(t("register_username_invalid"))
            return
        self.view.show_error(t("error_server"))


class LoginController:
    def __init__(self, view, main_window_factory, service: LoginService, show_toast, overlay_controller: RegisterOverlayController):
        self.view = view
        self.main_window_factory = main_window_factory
        self.service = service
        self.show_toast = show_toast
        self.overlay_controller = overlay_controller
        self._login_worker = None
        self._connect_signals()

    def shutdown(self) -> None:
        worker = self._login_worker
        if worker and worker.isRunning():
            worker.wait()
        if not worker or not worker.isRunning():
            self._login_worker = None
        self.overlay_controller.shutdown()

    def _connect_signals(self):
        self.view.login_button.clicked.connect(self.on_login_clicked)
        self.view.register_button.clicked.connect(self.overlay_controller.show_panel)

    def apply_language(self):
        self.view.apply_language()
        self.overlay_controller.apply_language()

    def on_login_clicked(self):
        username = self.view.username_input.text().strip()
        code = self.view.code_input.text().strip()
        if not username:
            self.view.show_error(t("error_enter_login"))
            return
        if not code:
            self.view.show_error(t("error_enter_code"))
            return
        self.view.set_login_busy(True)
        self.view.hide_error()
        worker = self.service.build_worker("POST", "/api/login", json_body={"username": username, "code": code})
        self._login_worker = worker
        worker.done.connect(self._handle_login_response)
        worker.finished.connect(lambda: self._clear_login_worker(worker))
        worker.start()

    def _handle_login_response(self, result: dict):
        self.view.set_login_busy(False)
        if not result.get("ok"):
            self.show_toast(t("toast_no_connection"))
            self.view.show_error(t("error_conn_refused"))
            return
        status_code = int(result.get("status_code") or 0)
        data = result.get("data")
        if not isinstance(data, dict):
            self.view.show_error(t("error_bad_response"))
            return
        if status_code == 200 and data.get("ok"):
            self.service.persist_auth(
                str(data.get("token") or ""),
                str(data.get("username") or self.view.username_input.text().strip()),
                str(data.get("status") or "active"),
                int(data.get("sub_level") or 0),
            )
            self.view.hide_error()
            self.main_window_factory()
            return
        error = str(data.get("error") or "").strip().lower()
        if error == "missing_username":
            self.view.show_error(t("error_enter_login"))
            return
        if error == "missing_code":
            self.view.show_error(t("error_enter_code"))
            return
        if error == "user_not_found":
            self.view.show_error(t("error_bad_login"))
            return
        if error == "invalid_credentials":
            self.view.show_error(t("error_bad_code"))
            return
        if error == "inactive":
            self.view.show_error(t("error_inactive_account"))
            return
        if status_code >= 500:
            self.view.show_error(t("error_server"))
            return
        self.view.show_error(t("error_auth"))

    def _clear_login_worker(self, worker) -> None:
        if self._login_worker is worker:
            self._login_worker = None
