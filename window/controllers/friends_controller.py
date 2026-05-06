from datetime import datetime

from PySide6.QtCore import QTimer

from services.friends_service import FriendsService
from window.chrome import show_app_message
from window.i18n import t
from window.views.friends_view import AddFriendDialog, FriendCard, FriendsView


class FriendsController:
    def __init__(self, view, main_window, service: FriendsService | None = None):
        self.view = view
        self.main_window = main_window
        self.service = service or FriendsService()
        self._list_worker = None
        self._action_worker = None
        self._latest_payload = {"friends": [], "incoming": [], "outgoing": []}
        self._poll_timer = QTimer(self.view)
        self._poll_timer.setInterval(5000)
        self._poll_timer.timeout.connect(self.refresh)
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.view.btn_back.clicked.connect(self.on_back)
        self.view.btn_show_friends.clicked.connect(lambda: self.view.set_mode(FriendsView.MODE_FRIENDS))
        self.view.btn_show_requests.clicked.connect(lambda: self.view.set_mode(FriendsView.MODE_REQUESTS))
        self.view.btn_open_add_dialog.clicked.connect(self.open_add_dialog)

    def apply_language(self) -> None:
        self.view.apply_language()
        self._render_list()

    def refresh(self) -> None:
        if self._list_worker and self._list_worker.isRunning():
            return
        token = self.service.auth_token()
        if not token:
            self._poll_timer.stop()
            self.view.set_action_status(t("error_auth"))
            return
        worker = self.service.build_list_worker(parent=self.view)
        self._list_worker = worker
        self.view.set_action_status(t("friends_loading"))
        worker.done.connect(self._on_list_loaded)
        worker.finished.connect(lambda: self._clear_worker("_list_worker", worker))
        worker.start()
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def shutdown(self) -> None:
        self._poll_timer.stop()
        for worker in (self._list_worker, self._action_worker):
            if worker and worker.isRunning():
                worker.wait()

    def on_back(self) -> None:
        self.main_window.show_home()

    def open_add_dialog(self) -> None:
        dialog = AddFriendDialog(self.view)
        while True:
            if dialog.exec() != AddFriendDialog.Accepted:
                return
            username = dialog.username()
            if not username:
                dialog.set_status(t("friends_search_enter"))
                continue
            if self._action_worker and self._action_worker.isRunning():
                dialog.set_status(t("friends_action_sending"))
                continue
            self._send_request(username, dialog=dialog)
            return

    def on_accept(self, friend_user_id: int) -> None:
        self._send_action(self.service.build_respond_worker(friend_user_id, "accept", parent=self.view))

    def on_decline(self, friend_user_id: int) -> None:
        self._send_action(self.service.build_respond_worker(friend_user_id, "decline", parent=self.view))

    def on_remove(self, friend_user_id: int) -> None:
        self._send_action(self.service.build_remove_worker(friend_user_id, parent=self.view))

    def _send_request(self, username: str, *, dialog: AddFriendDialog | None = None) -> None:
        self.view.set_action_status(t("friends_action_sending"))
        if dialog is not None:
            dialog.set_busy(True)
            dialog.set_status(t("friends_action_sending"))
        self._send_action(
            self.service.build_request_worker(username, parent=self.view),
            success_text=t("friends_request_sent"),
            dialog=dialog,
        )

    def _send_action(self, worker, *, success_text: str | None = None, dialog: AddFriendDialog | None = None) -> None:
        if self._action_worker and self._action_worker.isRunning():
            return
        self._action_worker = worker
        worker.done.connect(lambda payload: self._on_action_done(payload, success_text=success_text, dialog=dialog))
        worker.finished.connect(lambda: self._clear_worker("_action_worker", worker))
        worker.start()

    def _on_list_loaded(self, payload: dict) -> None:
        if not payload.get("ok"):
            self.view.set_action_status(t("error_conn_refused"))
            self.main_window.show_toast(t("toast_no_connection"))
            return
        if payload.get("status_code") != 200 or not self._is_response_ok(payload):
            self.view.set_action_status(self._map_error(payload))
            return

        data = self._extract_result(payload)
        self._latest_payload = {
            "friends": self._normalize_items(data.get("friends")),
            "incoming": self._normalize_items(data.get("incoming")),
            "outgoing": self._normalize_items(data.get("outgoing")),
        }
        self._render_list()
        self.view.set_action_status(t("friends_loaded"))
        self.view.set_last_updated(t("friends_last_updated").format(value=datetime.now().strftime("%H:%M:%S")))

    def _on_action_done(self, payload: dict, *, success_text: str | None = None, dialog: AddFriendDialog | None = None) -> None:
        if dialog is not None:
            dialog.set_busy(False)
        if not payload.get("ok"):
            message = t("error_conn_refused")
            if dialog is not None:
                dialog.set_status(message)
            show_app_message(self.main_window, t("friends_title"), message, kind="warning")
            self.view.set_action_status(message)
            return
        if payload.get("status_code") != 200 or not self._is_response_ok(payload):
            message = self._map_error(payload)
            if dialog is not None:
                dialog.set_status(message)
            show_app_message(self.main_window, t("friends_title"), message, kind="warning")
            self.view.set_action_status(message)
            return
        message = success_text or t("friends_action_done")
        self.view.set_action_status(message)
        if dialog is not None:
            dialog.accept()
        self.refresh()

    def _render_list(self) -> None:
        handlers = {
            "accept": self.on_accept,
            "decline": self.on_decline,
            "remove": self.on_remove,
        }
        busy = bool(self._action_worker and self._action_worker.isRunning())
        friends = [FriendCard(item, section="friends", handlers=handlers) for item in self._latest_payload.get("friends", [])]
        incoming = [FriendCard(item, section="incoming", handlers=handlers) for item in self._latest_payload.get("incoming", [])]
        outgoing = [FriendCard(item, section="outgoing", handlers=handlers) for item in self._latest_payload.get("outgoing", [])]
        for card in friends + incoming + outgoing:
            card.set_busy(busy)
        self.view.set_sections(friends, incoming, outgoing)

    def _clear_worker(self, attr_name: str, worker) -> None:
        if getattr(self, attr_name) is worker:
            setattr(self, attr_name, None)
        self._render_list()

    def _normalize_items(self, value) -> list[dict]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def _extract_body(self, payload: dict) -> dict:
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _extract_result(self, payload: dict) -> dict:
        data = self._extract_body(payload)
        if isinstance(data.get("result"), dict):
            return data.get("result") or {}
        if isinstance(data.get("data"), dict):
            return data.get("data") or {}
        return data

    def _is_response_ok(self, payload: dict) -> bool:
        data = self._extract_body(payload)
        if isinstance(data, dict) and data.get("ok") is False:
            return False
        nested = data.get("data") if isinstance(data, dict) else None
        if isinstance(nested, dict) and nested.get("ok") is False:
            return False
        return True

    def _map_error(self, payload: dict) -> str:
        data = self._extract_body(payload)
        error = str(data.get("error") or payload.get("error") or "").strip().lower()
        return {
            "no_token": t("error_auth"),
            "invalid_token": t("error_auth"),
            "inactive": t("error_auth"),
            "user_not_found": t("friends_search_not_found"),
            "friend_not_found": t("friends_search_not_found"),
            "already_friends": t("friends_error_already_friends"),
            "request_already_sent": t("friends_error_request_sent"),
            "cannot_add_self": t("friends_error_self"),
            "self_request": t("friends_error_self"),
            "friendship_not_found": t("friends_error_not_found"),
        }.get(error, t("error_server"))
