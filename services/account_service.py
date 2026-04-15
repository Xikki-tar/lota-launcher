import os
import shutil
from pathlib import Path

import requests

from auth.api_base import get_api_base
from auth.auth_storage import get_skin_file, load_auth_data
from window.i18n import t


class AccountService:
    RANK_NAMES = {1: "Барон", 2: "Аристократ", 3: "Спонсор"}

    def load_profile(self) -> dict:
        auth = load_auth_data() or {}
        username = auth.get("username", t("account_unknown_user"))
        sub_level = auth.get("sub_level", 0)
        rank_name = self.RANK_NAMES.get(sub_level, t("account_no_subscription"))
        status = str(auth.get("status") or "").lower()
        return {
            "username": username,
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
