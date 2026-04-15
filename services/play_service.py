import base64
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.api_base import get_api_base
from auth.auth_storage import get_data_dir, load_auth_data, load_settings, save_settings
from auth.java_finder import find_java_candidates, get_java_version
from minecraft.mc_client import ensure_forge_version, prepare_version
from minecraft.mc_launch import build_launch_spec
from services.library_service import LibraryService
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


def _build_dir_has_payload(path: Path) -> bool:
    if not path.is_dir():
        return False
    for name in ("mods", "config", "resourcepacks", "shaderpacks", "saves"):
        if (path / name).exists():
            return True
    try:
        return any(child.name != "build.zip" for child in path.iterdir())
    except Exception:
        return False


def _logs_dir() -> Path:
    path = get_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _creationflags_no_window() -> int:
    if platform.system() == "Windows":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _prefer_java_21(java_path: str) -> str:
    if java_path and _is_executable(java_path):
        return java_path
    for candidate in find_java_candidates():
        version = get_java_version(candidate)
        if _java_version_is_21(version):
            return candidate
    return java_path


def _java_version_is_21(version: str) -> bool:
    normalized = str(version or "").lower()
    return 'version "21' in normalized or " 21." in normalized or " 21 " in normalized


def _safe_extract_zip(archive_path: Path, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            target_path = (dest_root / member.filename).resolve()
            if dest_root not in target_path.parents and target_path != dest_root:
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _safe_extract_tar(archive_path: Path, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        safe_members = []
        for member in archive.getmembers():
            target_path = (dest_root / member.name).resolve()
            if dest_root in target_path.parents or target_path == dest_root:
                safe_members.append(member)
        archive.extractall(dest_root, members=safe_members)


class PlayWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    ready = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            play_service = PlayService()
            play_service.ensure_latest_build_selected(status=self.status.emit, progress=self.progress.emit)
            java_path = play_service.ensure_oracle_java_21(status=self.status.emit, progress=self.progress.emit)

            settings = load_settings()
            if not java_path:
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
            java_path = _prefer_java_21(java_path)
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
    def ensure_latest_build_selected(self, status=None, progress=None) -> str | None:
        library_service = LibraryService(get_data_dir(), get_api_base)
        settings = load_settings()
        selected = str(settings.get("selected_build") or "").strip()
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()

        def emit_status(key: str):
            if status:
                status(t(key))

        if selected:
            selected_dir = library_service.paths.builds_dir / selected
            if _build_dir_has_payload(selected_dir):
                return selected
            try:
                catalog = library_service.load_catalog(token)
                for item in catalog.builds:
                    if library_service.build_key(item) == selected and library_service.is_build_installed(item):
                        return selected
            except Exception:
                pass

        emit_status("play_status_build_check")
        catalog = library_service.load_catalog(token)
        builds = [item for item in catalog.builds if isinstance(item, dict) and not item.get("is_instance")]
        if not builds:
            raise RuntimeError(t("play_error_build_unavailable"))
        latest = max(builds, key=self._build_latest_sort_key)
        build_key = library_service.build_key(latest)

        if not library_service.is_build_installed(latest):
            self._download_build_for_play(library_service, latest, token, status=status, progress=progress)

        settings = load_settings()
        settings["selected_build"] = build_key
        save_settings(settings)
        emit_status("play_status_build_selected")
        return build_key

    def _build_latest_sort_key(self, item: dict) -> tuple:
        def as_int(value) -> int:
            try:
                return int(value)
            except Exception:
                return 0

        version = str(item.get("version") or "")
        version_numbers = tuple(as_int(part) for part in version.replace("-", ".").split(".") if part.isdigit())
        return (
            as_int(item.get("updated_at") or item.get("created_at")),
            as_int(item.get("id")),
            version_numbers,
            str(item.get("name") or ""),
        )

    def _download_build_for_play(self, library_service: LibraryService, item: dict, token: str, status=None, progress=None) -> None:
        if not token:
            raise RuntimeError(t("play_error_build_auth"))
        try:
            build_id = int(item.get("id"))
        except Exception:
            raise RuntimeError(t("play_error_build_unavailable"))

        if status:
            status(t("play_status_build_download"))
        base_url = get_api_base()
        archive_path = library_service.build_archive_path(item)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.post(
            f"{base_url}/api/build/download",
            json={"token": token, "build_id": build_id},
            stream=True,
            timeout=120,
        ) as response:
            if response.status_code != 200:
                raise RuntimeError(t("library_download_failed").format(message=f"HTTP {response.status_code}"))
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with archive_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress and total > 0:
                        progress(max(0, min(100, int(downloaded * 100 / total))))

        if status:
            status(t("play_status_build_extract"))
        library_service.extract_build_archive(archive_path, library_service.build_install_dir(item))

    def ensure_oracle_java_21(self, status=None, progress=None) -> str:
        current = self._oracle_java_executable()
        if current and _is_executable(str(current)) and _java_version_is_21(get_java_version(str(current))):
            self._save_java_path(current)
            return str(current)

        if status:
            status(t("play_status_java_download"))
        url, archive_kind = self._oracle_java_download()
        java_root = get_data_dir() / "java"
        downloads_dir = get_data_dir() / "downloads"
        runtime_dir = java_root / "oracle-jdk-21"
        staging_dir = java_root / "oracle-jdk-21.tmp"
        archive_path = downloads_dir / Path(url).name
        java_root.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._download_file(url, archive_path, progress=progress)
            if status:
                status(t("play_status_java_extract"))
            if archive_kind == "zip":
                _safe_extract_zip(archive_path, staging_dir)
            else:
                _safe_extract_tar(archive_path, staging_dir)
            java_exe = self._find_extracted_java(staging_dir)
            if not java_exe:
                raise RuntimeError(t("play_error_java"))
            jdk_home = java_exe.parent.parent
            shutil.rmtree(runtime_dir, ignore_errors=True)
            shutil.move(str(jdk_home), str(runtime_dir))
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        current = self._oracle_java_executable()
        if not current or not _is_executable(str(current)):
            raise RuntimeError(t("play_error_java"))
        self._save_java_path(current)
        if status:
            status(t("play_status_java_ready"))
        return str(current)

    def _download_file(self, url: str, dest: Path, progress=None) -> None:
        with requests.get(url, stream=True, timeout=120) as response:
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}")
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with dest.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress and total > 0:
                        progress(max(0, min(100, int(downloaded * 100 / total))))

    def _oracle_java_download(self) -> tuple[str, str]:
        system = platform.system()
        machine = platform.machine().lower()
        is_arm = machine in {"arm64", "aarch64"}
        if system == "Windows":
            if is_arm:
                raise RuntimeError(t("play_error_java_platform"))
            return "https://download.oracle.com/java/21/latest/jdk-21_windows-x64_bin.zip", "zip"
        if system == "Darwin":
            arch = "aarch64" if is_arm else "x64"
            return f"https://download.oracle.com/java/21/latest/jdk-21_macos-{arch}_bin.tar.gz", "tar.gz"
        if system == "Linux":
            arch = "aarch64" if is_arm else "x64"
            return f"https://download.oracle.com/java/21/latest/jdk-21_linux-{arch}_bin.tar.gz", "tar.gz"
        raise RuntimeError(t("play_error_java_platform"))

    def _oracle_java_executable(self) -> Path:
        exe = "java.exe" if platform.system() == "Windows" else "java"
        return get_data_dir() / "java" / "oracle-jdk-21" / "bin" / exe

    def _find_extracted_java(self, root: Path) -> Path | None:
        exe = "java.exe" if platform.system() == "Windows" else "java"
        for path in root.rglob(exe):
            if path.parent.name.lower() == "bin":
                try:
                    if platform.system() != "Windows":
                        path.chmod(path.stat().st_mode | 0o755)
                except OSError:
                    pass
                return path
        return None

    def _save_java_path(self, java_path: Path) -> None:
        settings = load_settings()
        settings["java_path"] = str(java_path)
        save_settings(settings)

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
            creationflags=_creationflags_no_window(),
        )
