import os
import platform

from auth.auth_storage import load_settings, save_settings
from auth.java_finder import find_java_candidates, get_java_version


class SettingsService:
    def load(self) -> dict:
        return load_settings()

    def save(self, data: dict) -> None:
        save_settings(data)

    def default_jvm_args(self, current_value: str = "") -> str:
        value = str(current_value or "").strip()
        if value:
            return value
        if platform.system() == "Linux" and os.environ.get("WAYLAND_DISPLAY") is None:
            return "-Dorg.lwjgl.glfw.backend=x11"
        return ""

    def get_java_candidates(self) -> list[str]:
        return find_java_candidates()

    def get_java_version_text(self, java_path: str) -> str:
        path = str(java_path or "").strip()
        if not path:
            return ""
        return get_java_version(path)
