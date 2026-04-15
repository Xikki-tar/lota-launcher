import base64
import io
import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.api_base import get_api_base
from auth.auth_storage import get_data_dir, load_auth_data, load_settings
from auth.java_finder import find_java_candidates, get_java_version
from minecraft.mc_client import ensure_forge_version, prepare_version
from minecraft.mc_launch import build_launch_spec
from window.i18n import t


def _is_executable(path: str) -> bool:
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return True
    return shutil.which(path) is not None


def _shared_game_dir() -> Path:
    return get_data_dir() / "minecraft"


def _shared_versions_dir() -> Path:
    return _shared_game_dir() / "versions"


def _pick_build_dir() -> Path | None:
    settings = load_settings()
    selected = str(settings.get("selected_build") or "").strip()
    base = get_data_dir() / "library"
    if not base.exists():
        return None
    if selected:
        candidate = base / selected
        if candidate.exists() and candidate.is_dir():
            return candidate
    candidates = []
    for path in base.iterdir():
        if not path.is_dir():
            continue
        if (path / "mods").exists() or (path / "config").exists() or (path / "resourcepacks").exists():
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def _logs_dir() -> Path:
    path = get_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prefer_java_17(java_path: str) -> str:
    if java_path and _is_executable(java_path):
        return java_path
    for candidate in find_java_candidates():
        version = get_java_version(candidate)
        if " 17." in version or version.startswith('openjdk version "17') or " 17.0" in version:
            return candidate
    return java_path


class PlayWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    ready = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            settings = load_settings()
            java_path = str(settings.get("java_path") or "").strip()
            if not java_path:
                candidates = find_java_candidates()
                java_path = candidates[0] if candidates else ""

            if not java_path or not _is_executable(java_path):
                self.failed.emit(t("play_error_java"))
                return

            try:
                mem_min = int(settings.get("mem_min_mb", 1024))
                mem_max = int(settings.get("mem_max_mb", 4096))
            except Exception:
                self.failed.emit(t("play_error_settings"))
                return

            if mem_min > mem_max:
                self.failed.emit(t("play_error_settings"))
                return

            jvm_args = settings.get("jvm_args") or ""
            java_path = _prefer_java_17(java_path)
            resolution_width = 854
            resolution_height = 480

            def on_status(message: str):
                status_map = {
                    "download_client": t("play_status_client"),
                    "download_libs": t("play_status_libs"),
                    "download_natives": t("play_status_natives"),
                    "download_asset_index": t("play_status_assets_index"),
                    "download_assets": t("play_status_assets"),
                    "download_forge_installer": t("play_status_forge_installer"),
                    "install_forge": t("play_status_forge_install"),
                }
                self.status.emit(status_map.get(message, message))

            def on_progress(done: int, total: int):
                if total <= 0:
                    return
                self.progress.emit(max(0, min(100, int(done * 100 / total))))

            game_dir = _pick_build_dir() or _shared_game_dir()
            version_id = ensure_forge_version(_shared_versions_dir(), java_path, _shared_game_dir(), status=on_status)
            prepared = prepare_version(version_id, progress=on_progress, status=on_status)

            auth = load_auth_data() or {}
            active = str(settings.get("active_account") or "").strip().lower()
            offline_name = str(settings.get("offline_username") or auth.get("username") or "").strip()
            username = offline_name or "Player" if active in {"", "offline"} else auth.get("username") or offline_name or "Player"

            is_linux = platform.system() == "Linux"
            disable_openal = settings.get("disable_openal", False)
            use_system_openal = bool(disable_openal) and is_linux
            system_openal_ok = os.path.exists("/usr/lib/libopenal.so.1") if is_linux else False

            if use_system_openal and system_openal_ok:
                try:
                    openal = prepared.natives_dir / "libopenal.so"
                    if openal.exists():
                        openal.rename(prepared.natives_dir / "libopenal.so.disabled")
                except Exception:
                    pass
                if "-Dorg.lwjgl.system.librarypath=" not in jvm_args:
                    jvm_args = (jvm_args + " -Dorg.lwjgl.system.librarypath=/usr/lib").strip()
                if "-Dorg.lwjgl.openal.libname=" not in jvm_args:
                    jvm_args = (jvm_args + " -Dorg.lwjgl.openal.libname=libopenal.so.1").strip()

            spec = build_launch_spec(
                prepared=prepared,
                username=username,
                java_path=java_path,
                mem_min_mb=mem_min,
                mem_max_mb=mem_max,
                jvm_args=jvm_args,
                game_dir_override=game_dir,
                resolution_width=resolution_width,
                resolution_height=resolution_height,
            )
            self.status.emit(t("play_launching"))
            self.ready.emit(spec)
        except Exception as exc:
            self.failed.emit(str(exc))


@dataclass
class BundleState:
    temp_dir: Path
    written: list[Path]
    backups: list[tuple[Path, Path]]


class PlayService:
    def bundle_manifest_path(self, game_dir: Path) -> Path:
        return game_dir / "cache" / "payload.json"

    def request_bundle_key(self, build_id: int) -> bytes | None:
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        if not token:
            return None
        try:
            response = requests.post(
                f"{get_api_base()}/api/bundle/key",
                json={"token": token, "build_id": build_id},
                timeout=10,
            )
        except Exception:
            return None
        if response.status_code != 200:
            return None
        data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
        if not isinstance(data, dict) or not data.get("ok"):
            return None
        try:
            return base64.b64decode(data.get("key") or "")
        except Exception:
            return None

    def decrypt_archive(self, encrypted_bytes: bytes, key32: bytes) -> bytes:
        if len(encrypted_bytes) < 2 + 4 + 12:
            raise ValueError("encrypted data too short")
        magic = encrypted_bytes[:4]
        version = encrypted_bytes[4:5]
        if magic != b"PACK" or version != b"\x01":
            raise ValueError("bad magic/version")
        iv = encrypted_bytes[5:17]
        ciphertext = encrypted_bytes[17:]
        aes = AESGCM(key32)
        return aes.decrypt(iv, ciphertext, b"PACK" + b"\x01")

    def prepare_bundle_files(self, game_dir: Path) -> BundleState | None:
        manifest_path = self.bundle_manifest_path(game_dir)
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(manifest, dict):
            return None
        encrypted_rel = str(manifest.get("archive") or "")
        build_id = manifest.get("build_id")
        if not encrypted_rel or not build_id:
            return None
        try:
            build_id_int = int(build_id)
        except Exception:
            return None

        encrypted_path = game_dir / encrypted_rel
        if not encrypted_path.exists():
            return None

        key32 = self.request_bundle_key(build_id_int)
        if not key32:
            raise RuntimeError(t("play_bundle_key_error"))

        plain_zip = self.decrypt_archive(encrypted_path.read_bytes(), key32)
        temp_dir = Path(tempfile.mkdtemp(prefix="bundle_"))
        with zipfile.ZipFile(io.BytesIO(plain_zip), "r") as archive:
            archive.extractall(temp_dir)

        written: list[Path] = []
        backups: list[tuple[Path, Path]] = []
        for root, _, files in os.walk(temp_dir):
            for filename in files:
                src = Path(root) / filename
                rel = src.relative_to(temp_dir)
                dst = game_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    backup = dst.with_suffix(dst.suffix + ".bak")
                    dst.replace(backup)
                    backups.append((backup, dst))
                shutil.copy2(src, dst)
                written.append(dst)
        return BundleState(temp_dir=temp_dir, written=written, backups=backups)

    def cleanup_bundle_files(self, bundle_state: BundleState | None) -> None:
        if not bundle_state:
            return
        for path in bundle_state.written:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
        for backup, dst in bundle_state.backups:
            try:
                if dst.exists():
                    dst.unlink()
                if backup.exists():
                    backup.replace(dst)
            except Exception:
                pass
        try:
            shutil.rmtree(bundle_state.temp_dir, ignore_errors=True)
        except Exception:
            pass

    def open_log_file(self, spec) -> tuple[Path, object]:
        log_name = datetime.now().strftime("launcher_%Y-%m-%d_%H-%M-%S.log")
        log_path = _logs_dir() / log_name
        handle = open(log_path, "w", encoding="utf-8")
        handle.write(t("play_log_header") + "\n")
        handle.write(f"Command: {' '.join(spec.argv)}\n")
        handle.write(f"CWD: {spec.cwd}\n")
        handle.flush()
        return log_path, handle

    def launch_process(self, spec, log_handle):
        return subprocess.Popen(
            spec.argv,
            cwd=str(spec.cwd),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
