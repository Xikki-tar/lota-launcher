import requests
from auth.auth_storage import load_auth_data, save_auth_data
from auth.api_base import build_api_url

class AuthService:
    @staticmethod
    def refresh(timeout: int = 5) -> bool:
        auth = load_auth_data()
        if not auth or not auth.get("token"):
            return False

        token = auth["token"]

        try:
            resp = requests.post(
                build_api_url("/api/check-token"),
                json={"token": token},
                timeout=timeout
            )
        except Exception:
            return False

        if resp.status_code != 200:
            return False

        try:
            data = resp.json()
        except ValueError:
            return False

        if not data.get("ok"):
            return False

        save_auth_data(
            data.get("token", token),
            data.get("username", auth.get("username")),
            data.get("status", auth.get("status")),
            data.get("sub_level", auth.get("sub_level")),
            data.get("player_uuid", auth.get("player_uuid")),
        )
        return True
