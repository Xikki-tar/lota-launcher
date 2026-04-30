from dataclasses import dataclass

import requests

from auth.api_base import build_api_url
from auth.auth_storage import load_auth_data, save_auth_data


@dataclass(frozen=True)
class AuthRefreshResult:
    ok: bool
    rejected: bool = False
    status_code: int | None = None
    error: str = ""


class AuthService:
    @staticmethod
    def refresh(timeout: int = 5) -> AuthRefreshResult:
        auth = load_auth_data()
        if not auth or not auth.get("token"):
            return AuthRefreshResult(ok=False, rejected=True, error="no_token")

        token = auth["token"]

        try:
            resp = requests.post(
                build_api_url("/api/check-token"),
                json={"token": token},
                timeout=timeout
            )
        except Exception:
            return AuthRefreshResult(ok=False, error="network")

        if resp.status_code != 200:
            return AuthRefreshResult(ok=False, rejected=True, status_code=resp.status_code, error="http_error")

        try:
            data = resp.json()
        except ValueError:
            return AuthRefreshResult(ok=False, rejected=True, status_code=resp.status_code, error="bad_response")

        if not data.get("ok"):
            return AuthRefreshResult(
                ok=False,
                rejected=True,
                status_code=resp.status_code,
                error=str(data.get("error") or "token_rejected"),
            )

        save_auth_data(
            data.get("token", token),
            data.get("username", auth.get("username")),
            data.get("status", auth.get("status")),
            data.get("sub_level", auth.get("sub_level")),
            data.get("player_uuid", auth.get("player_uuid")),
        )
        return AuthRefreshResult(ok=True, status_code=resp.status_code)
