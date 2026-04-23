import os
import shutil
from pathlib import Path

import requests

from auth.api_base import get_api_base
from auth.auth_storage import get_skin_file, load_auth_data
from window.i18n import t


class AccountService:
    MAX_SKIN_UPLOAD_BYTES = 4 * 1024

    RANK_NAMES = {
        1: "Барон",
        2: "Аристократ",
        3: "Инвестор",
        4: "Тестер",
        5: "Старейшина",
        6: "Junior",
        7: "Team",
        8: "Дракон",
        9: "Автор",
    }

    def load_profile(self) -> dict:
        auth = load_auth_data() or {}
        username = auth.get("username", t("account_unknown_user"))
        sub_level = auth.get("sub_level", 0)
        rank_name = self.RANK_NAMES.get(sub_level, t("account_no_subscription"))
        status = str(auth.get("status") or "").lower()
        return {
            "username": username,
            "sub_level": sub_level,
            "rank_name": rank_name,
            "is_active": status == "active",
        }

    def skin_file(self) -> Path:
        return get_skin_file()

    def save_skin(self, source_path: str) -> Path:
        target_path = self.skin_file()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        return target_path

    def upload_skin(self, source_path: str, model: str = "classic") -> dict:
        path = Path(source_path)
        if not path.exists():
            return {"status_code": 0, "data": {"ok": False, "error": "skin_file_missing"}}
        if path.stat().st_size > self.MAX_SKIN_UPLOAD_BYTES:
            return {
                "status_code": 413,
                "data": {
                    "ok": False,
                    "error": "skin_too_large",
                    "max_bytes": self.MAX_SKIN_UPLOAD_BYTES,
                    "max_human": "4 KiB",
                },
            }
        token = self.auth_token()
        if not token:
            return {"status_code": 401, "data": {"ok": False, "error": "no_token"}}
        with path.open("rb") as file_obj:
            response = requests.post(
                f"{get_api_base()}/api/skins/upload",
                data={"token": token, "model": model},
                files={"file": ("skin.png", file_obj, "image/png")},
                timeout=15,
            )
        try:
            data = response.json()
        except Exception:
            data = {"ok": False, "error": "bad_response"}
        return {"status_code": response.status_code, "data": data}

    def auth_token(self) -> str:
        auth = load_auth_data() or {}
        return str(auth.get("token") or "").strip()

    def request_discord_link(self, token: str) -> dict:
        response = requests.post(
            f"{get_api_base()}/api/account/discord-link",
            json={"token": token},
            timeout=5,
        )
        return {
            "status_code": response.status_code,
            "data": response.json(),
        }

    def poll_discord_link(self, token: str) -> dict:
        response = requests.post(
            f"{get_api_base()}/api/account/discord-link-status",
            json={"token": token},
            timeout=5,
        )
        return {
            "status_code": response.status_code,
            "data": response.json(),
        }

    def discord_bot_url(self) -> str:
        return os.getenv("DISCORD_BOT_URL", "https://discord.gg/zZ2KHxaGNv")
