import requests
from PySide6.QtCore import QThread, Signal

from auth.api_base import get_api_base
from auth.auth_storage import load_auth_data


class FriendsRequestWorker(QThread):
    done = Signal(object)

    def __init__(self, path: str, payload: dict, parent=None):
        super().__init__(parent)
        self.path = path
        self.payload = dict(payload or {})

    def run(self):
        try:
            response = requests.post(
                f"{get_api_base()}{self.path}",
                json=self.payload,
                timeout=10,
            )
            try:
                data = response.json()
            except ValueError:
                data = None
            self.done.emit({"ok": True, "status_code": response.status_code, "data": data})
        except Exception as exc:
            self.done.emit({"ok": False, "error": str(exc)})


class FriendsService:
    def auth_token(self) -> str:
        auth = load_auth_data() or {}
        return str(auth.get("token") or "").strip()

    def build_worker(self, path: str, payload: dict, *, parent=None) -> FriendsRequestWorker:
        return FriendsRequestWorker(path, payload, parent=parent)

    def build_list_worker(self, *, parent=None) -> FriendsRequestWorker:
        return self.build_worker("/api/friends/list", {"token": self.auth_token()}, parent=parent)

    def build_find_worker(self, username: str, *, parent=None) -> FriendsRequestWorker:
        return self.build_worker(
            "/api/friends/find",
            {"token": self.auth_token(), "username": str(username or "").strip()},
            parent=parent,
        )

    def build_request_worker(self, username: str, *, parent=None) -> FriendsRequestWorker:
        return self.build_worker(
            "/api/friends/request",
            {"token": self.auth_token(), "username": str(username or "").strip()},
            parent=parent,
        )

    def build_respond_worker(self, friend_user_id: int, action: str, *, parent=None) -> FriendsRequestWorker:
        return self.build_worker(
            "/api/friends/respond",
            {
                "token": self.auth_token(),
                "friend_user_id": int(friend_user_id),
                "action": str(action or "").strip().lower(),
            },
            parent=parent,
        )

    def build_remove_worker(self, friend_user_id: int, *, parent=None) -> FriendsRequestWorker:
        return self.build_worker(
            "/api/friends/remove",
            {
                "token": self.auth_token(),
                "friend_user_id": int(friend_user_id),
            },
            parent=parent,
        )
