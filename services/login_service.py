import requests
from PySide6.QtCore import QThread, Signal

from auth.api_base import get_api_base
from auth.auth_storage import (
    clear_register_data,
    load_register_data,
    save_auth_data,
    save_register_data,
)


class ApiRequestWorker(QThread):
    done = Signal(object)

    def __init__(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None):
        super().__init__()
        self.method = method.upper()
        self.path = path
        self.json_body = json_body or {}
        self.params = params or {}

    def run(self):
        try:
            api_base = get_api_base()
            response = requests.request(
                self.method,
                f"{api_base}{self.path}",
                json=self.json_body if self.method != "GET" else None,
                params=self.params if self.method == "GET" else None,
                timeout=5,
            )
            try:
                payload = response.json()
            except ValueError:
                payload = None
            self.done.emit({"ok": True, "status_code": response.status_code, "data": payload})
        except Exception as exc:
            self.done.emit({"ok": False, "error": str(exc)})


class LoginService:
    def build_worker(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> ApiRequestWorker:
        return ApiRequestWorker(method, path, json_body=json_body, params=params)

    def persist_auth(
        self,
        token: str,
        username: str,
        status: str,
        sub_level: int,
        player_uuid: str | None = None,
    ) -> None:
        save_auth_data(token, username, status, sub_level, player_uuid)

    def persist_register_link(self, link_token: str, telegram_url: str) -> None:
        save_register_data(link_token, telegram_url)

    def load_saved_register_link(self) -> dict | None:
        return load_register_data()

    def clear_saved_register_link(self) -> None:
        clear_register_data()
