import os
import shutil
from pathlib import Path

import requests

from auth.api_base import get_api_base
from auth.auth_storage import get_skin_file, load_auth_data, save_skin_model
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

    def save_skin(self, source_path: str, model: str = "classic") -> Path:
        target_path = self.skin_file()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        save_skin_model(model)
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

    def sync_skin_from_server(self) -> dict:
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        player_uuid = str(auth.get("player_uuid") or "").strip()
        username = str(auth.get("username") or "").strip()
        if not token or (not player_uuid and not username):
            return {"ok": False, "error": "no_profile_identity"}

        profile_payloads = [
            {"player_uuid": player_uuid, "username": username},
            {"player_uuid": player_uuid},
            {"username": username},
        ]
        request_variants = [
            {"token": token, "profiles": [payload for payload in profile_payloads if any(payload.values())][:1]},
            {"token": token, "players": [payload for payload in profile_payloads if any(payload.values())][:1]},
            {"token": token, "player_uuid": player_uuid, "username": username},
            {"token": token, "uuid": player_uuid, "username": username},
        ]

        profile_data = None
        last_error = "profile_check_failed"
        for body in request_variants:
            try:
                response = requests.post(
                    f"{get_api_base()}/api/skins/profiles/check",
                    json=body,
                    timeout=10,
                )
            except Exception:
                continue
            if response.status_code != 200:
                last_error = f"http_{response.status_code}"
                continue
            try:
                data = response.json()
            except Exception:
                last_error = "bad_response"
                continue
            profile_data = self._extract_skin_profile(data)
            if profile_data:
                break

        if not profile_data:
            return {"ok": False, "error": last_error}

        skin_hash = str(profile_data.get("skin_hash") or profile_data.get("hash") or "").strip()
        if not skin_hash:
            return {"ok": False, "error": "skin_hash_missing"}

        model = str(profile_data.get("model") or profile_data.get("skin_model") or "classic").strip().lower()
        if model not in {"classic", "slim"}:
            model = "classic"

        try:
            response = requests.get(
                f"{get_api_base()}/api/skins/file/{skin_hash}",
                params={"token": token},
                timeout=15,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if response.status_code != 200:
            return {"ok": False, "error": f"skin_file_http_{response.status_code}"}

        target_path = self.skin_file()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(response.content)
        save_skin_model(model)
        return {"ok": True, "path": str(target_path), "model": model, "skin_hash": skin_hash}

    def _extract_skin_profile(self, data) -> dict | None:
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    profile = self._extract_skin_profile(item)
                    if profile:
                        return profile
            return None
        if not isinstance(data, dict):
            return None

        direct_hash = str(data.get("skin_hash") or data.get("hash") or "").strip()
        if direct_hash:
            return data

        for key in ("profile", "result", "data", "player", "entry"):
            candidate = data.get(key)
            if isinstance(candidate, dict):
                profile = self._extract_skin_profile(candidate)
                if profile:
                    return profile

        for key in ("profiles", "results", "players", "entries", "items"):
            candidate = data.get(key)
            if isinstance(candidate, list):
                for item in candidate:
                    if isinstance(item, dict):
                        profile = self._extract_skin_profile(item)
                        if profile:
                            return profile
        return None

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
