import base64
import hashlib
import io
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

import requests
from PySide6.QtCore import QThread, Signal
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.api_base import get_api_base
from auth.auth_storage import get_data_dir, load_auth_data, load_settings, save_settings
from auth.java_finder import JAVA_EXECUTABLE_NAMES, find_java_candidates, get_java_major_version, get_java_version, is_safe_java_path
from minecraft.mc_client import ensure_forge_version, prepare_version, report_download_bytes
from minecraft.mc_launch import build_launch_spec
from services.build_sync import (
    CLOSED_DIR,
    HIDDEN_SUFFIX,
    closed_units,
    decrypt_pack_file,
    extract_zip,
    is_link,
    link_dir,
    load_state,
    remove_closed_links,
    remove_link,
)
from services.library_service import LibraryService
from services.play_errors import JavaError, PlayError
from desktop_integration import windows_hidden_subprocess_kwargs
from window.i18n import t


DOWNLOAD_PROGRESS_START = 27


def _download_progress_percent(value: int) -> int:
    value = max(0, min(100, int(value)))
    return DOWNLOAD_PROGRESS_START + int(value * (100 - DOWNLOAD_PROGRESS_START) / 100)


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


def _write_skin_mod_config(game_dir: Path, auth: dict, username: str) -> Path:
    api_base = get_api_base().rstrip("/")
    token = str(auth.get("token") or "").strip()
    player_uuid = str(auth.get("player_uuid") or "").strip()
    username = str(username or auth.get("username") or "Player").strip() or "Player"
    config_path = (game_dir / "config" / "lota-skins-client.json").resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "protocol_version": 1,
        "enabled": bool(token and api_base and username),
        "api_base": api_base,
        "token": token,
        "player_uuid": player_uuid,
        "username": username,
        "max_batch_size": 50,
        "min_check_interval_seconds": 120,
        "endpoints": {
            "check_profiles": "/api/skins/profiles/check",
            "skin_file": "/api/skins/file/{skin_hash}",
        },
        "cache": {
            "hash_algorithm": "sha256",
            "skin_dimensions": ["64x32", "64x64"],
            "max_skin_bytes": 4096,
        },
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return config_path


def _creationflags_no_window() -> int:
    return int(windows_hidden_subprocess_kwargs().get("creationflags", 0) or 0)


MIN_JAVA_MAJOR = 17
GRAALVM_DIR = "graalvm-21"
LEGACY_ORACLE_JDK_DIR = "oracle-jdk-21"
GRAALVM_CE_21_VERSION = "21.0.2"
SYSTEM_OPENAL_CANDIDATES = (
    "/usr/lib/libopenal.so.1",
    "/usr/lib64/libopenal.so.1",
    "/usr/lib/x86_64-linux-gnu/libopenal.so.1",
    "/usr/lib/aarch64-linux-gnu/libopenal.so.1",
)


GPU_PREFERENCES_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
GPU_HIGH_PERFORMANCE = "GpuPreference=2;"


def prefer_high_performance_gpu(java_path: str) -> list[str]:
    if platform.system() != "Windows" or not java_path:
        return []
    try:
        import winreg
    except ImportError:
        return []
    java = Path(shutil.which(java_path) or java_path).resolve()
    targets = [java.parent / name for name in ("java.exe", "javaw.exe") if (java.parent / name).is_file()]
    results = []
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, GPU_PREFERENCES_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE)
    except OSError as exc:
        return [f"registry unavailable: {exc}"]
    with key:
        for target in targets:
            name = str(target)
            try:
                current, _type = winreg.QueryValueEx(key, name)
                if current == GPU_HIGH_PERFORMANCE:
                    results.append(f"{target.name}: high performance GPU already set")
                else:
                    results.append(f"{target.name}: kept user choice {current!r}")
                continue
            except FileNotFoundError:
                pass
            except OSError as exc:
                results.append(f"{target.name}: read failed: {exc}")
                continue
            try:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, GPU_HIGH_PERFORMANCE)
                results.append(f"{target.name}: set high performance GPU")
            except OSError as exc:
                results.append(f"{target.name}: write failed: {exc}")
    return results


def resolve_custom_java(java_path: str) -> str:
    java_path = str(java_path or "").strip()
    if java_path.lower() in JAVA_EXECUTABLE_NAMES:
        java_path = shutil.which(java_path) or ""
    if not java_path or not is_safe_java_path(java_path):
        raise JavaError(t("play_error_java"), java_path)
    major = get_java_major_version(java_path)
    if major is not None and major < MIN_JAVA_MAJOR:
        raise JavaError(
            t("play_error_java_old").format(major=major, required=MIN_JAVA_MAJOR),
            f"{java_path}: {get_java_version(java_path)}",
        )
    return java_path


def system_openal_jvm_args(jvm_args: str) -> str:
    if platform.system() != "Linux" or "-Dorg.lwjgl.openal.libname=" in jvm_args:
        return jvm_args
    lib = next((path for path in SYSTEM_OPENAL_CANDIDATES if os.path.exists(path)), None)
    if not lib:
        return jvm_args
    return f"{jvm_args} -Dorg.lwjgl.openal.libname={lib}".strip()


def _prefer_java_21(java_path: str) -> str:
    current_major = get_java_major_version(java_path) if java_path and _is_executable(java_path) else None
    if current_major == 21:
        return java_path
    for candidate in find_java_candidates():
        candidate_major = get_java_major_version(candidate)
        if candidate_major == 21:
            return candidate
    if current_major is not None and current_major >= 17:
        return java_path
    for candidate in find_java_candidates():
        candidate_major = get_java_major_version(candidate)
        if candidate_major is not None and candidate_major >= 17:
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

    def __init__(self, *, allow_build_update: bool = True, parent=None):
        super().__init__(parent)
        self.allow_build_update = allow_build_update

    def run(self):
        try:
            play_service = PlayService()
            progress_state = {"value": 0}

            def emit_progress(value: int) -> None:
                value = max(0, min(100, int(value)))
                if value < progress_state["value"]:
                    value = progress_state["value"]
                progress_state["value"] = value
                self.progress.emit(value)

            emit_progress(5)

            def on_download_progress(value: int) -> None:
                emit_progress(_download_progress_percent(value))

            emit_progress(DOWNLOAD_PROGRESS_START)
            play_service.ensure_latest_build_selected(
                status=self.status.emit,
                progress=on_download_progress,
                allow_build_update=self.allow_build_update,
            )
            java_path = play_service.ensure_graalvm_21(status=self.status.emit, progress=on_download_progress)

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
                on_download_progress(max(0, min(100, int(done * 100 / total))))

            game_dir = _pick_build_dir() or _shared_game_dir()
            version_id = ensure_forge_version(_shared_versions_dir(), java_path, _shared_game_dir(), status=on_status)
            emit_progress(DOWNLOAD_PROGRESS_START)
            prepared = prepare_version(version_id, progress=on_progress, status=on_status)

            auth = load_auth_data() or {}
            active = str(settings.get("active_account") or "").strip().lower()
            offline_name = str(settings.get("offline_username") or auth.get("username") or "").strip()
            username = offline_name or "Player" if active in {"", "offline"} else auth.get("username") or offline_name or "Player"
            skin_config_path = _write_skin_mod_config(game_dir, auth, username)

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
                extra_jvm_args=[
                    f"-Dlota.skinConfig={skin_config_path}",
                ],
                game_dir_override=game_dir,
                resolution_width=resolution_width,
                resolution_height=resolution_height,
            )
            self.status.emit(t("play_launching"))
            self.ready.emit(spec)
        except Exception as exc:
            self.failed.emit(str(exc))


BUNDLE_DISABLED_SUFFIX = ".lota-disabled"


@dataclass
class BundleState:
    temp_dir: Path
    written: list[Path]
    backups: list[tuple[Path, Path]]
    disabled: list[tuple[Path, Path]]
    game_args: list[str]
    links: list[Path] = field(default_factory=list)
    hidden: list[tuple[Path, Path]] = field(default_factory=list)


def _random_name() -> str:
    return secrets.token_hex(6)


def _session_file() -> Path:
    return get_data_dir() / "cache" / "session.json"


def _load_session_dirs() -> list[Path]:
    try:
        data = json.loads(_session_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [Path(item) for item in data if isinstance(item, str)]


def _save_session_dirs(dirs: list[Path]) -> None:
    path = _session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([str(d) for d in dirs]), encoding="utf-8")


def _remove_temp_dir(path: Path) -> None:
    try:
        if path.resolve().parent != Path(tempfile.gettempdir()).resolve():
            return
    except OSError:
        return
    shutil.rmtree(path, ignore_errors=True)


def _remove_stale_bundle_dirs() -> None:
    stale = _load_session_dirs()
    for path in stale:
        _remove_temp_dir(path)
    if stale:
        print(f"[bundle] removed {len(stale)} leftover temp dirs from a previous session", flush=True)
    _save_session_dirs([])


def _restore_disabled_mods(mods_dir: Path) -> None:
    if not mods_dir.is_dir():
        return
    for path in mods_dir.glob(f"*{BUNDLE_DISABLED_SUFFIX}"):
        original = path.with_name(path.name[: -len(BUNDLE_DISABLED_SUFFIX)])
        if not original.exists():
            try:
                path.replace(original)
                print(f"[bundle] restored mod left disabled by a previous session: {original.name}", flush=True)
            except OSError as exc:
                print(f"[bundle] failed to restore disabled mod {original.name}: {exc}", flush=True)




class PlayService:
    def get_selected_build_update_state(self) -> dict:
        library_service = LibraryService(get_data_dir(), get_api_base)
        settings = load_settings()
        selected = str(settings.get("selected_build") or "").strip()
        if not selected:
            return {"selected": "", "needs_update": False}

        selected_dir = library_service.paths.builds_dir / selected
        can_launch_current = _build_dir_has_payload(selected_dir)
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()

        try:
            catalog = library_service.load_catalog(token, prefer_remote=False)
        except Exception:
            return {
                "selected": selected,
                "needs_update": False,
                "can_launch_current": can_launch_current,
            }

        selected_item = next(
            (item for item in catalog.builds if library_service.build_key(item) == selected),
            None,
        )
        source_item = self._source_item_for_selected(catalog.builds, selected_item)
        if selected_item is None:
            return {
                "selected": selected,
                "needs_update": False,
                "can_launch_current": can_launch_current,
            }

        needs_update = can_launch_current and not library_service.is_build_up_to_date(
            selected_item,
            source_item=source_item,
        )
        return {
            "selected": selected,
            "selected_item": selected_item,
            "source_item": source_item,
            "needs_update": needs_update,
            "can_launch_current": can_launch_current,
        }

    def ensure_latest_build_selected(self, status=None, progress=None, *, allow_build_update: bool = True) -> str | None:
        library_service = LibraryService(get_data_dir(), get_api_base)
        settings = load_settings()
        selected = str(settings.get("selected_build") or "").strip()
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()

        def emit_status(key: str):
            if status:
                status(t(key))

        emit_status("play_status_build_check")
        catalog = library_service.load_catalog(token)
        print(f"[play] build check: selected={selected or '-'}, catalog has {len(catalog.builds)} builds, logged in={bool(token)}", flush=True)

        if selected:
            selected_item, resolved = library_service.resolve_selected(catalog.builds, selected)
            if resolved != selected:
                settings["selected_build"] = resolved
                save_settings(settings)
                selected = resolved

        if selected:
            selected_source_item = self._source_item_for_selected(catalog.builds, selected_item)
            selected_dir = (
                library_service.build_install_dir(selected_item)
                if selected_item is not None
                else library_service.paths.builds_dir / selected
            )

            if selected_item is not None:
                expected = library_service.expected_build_updated_at(selected_source_item or selected_item)
                installed = library_service.load_build_meta(selected_item).get("updated_at")
                if library_service.is_build_up_to_date(selected_item, source_item=selected_source_item):
                    print(f"[play] selected build {selected} is up to date (updated_at {installed or '-'})", flush=True)
                    return selected
                if not allow_build_update and _build_dir_has_payload(selected_dir):
                    print(f"[play] selected build {selected} is outdated but updates are not allowed, launching installed files", flush=True)
                    return selected
                print(f"[play] selected build {selected} needs download: installed {installed or 'nothing'}, server {expected or '-'}", flush=True)
                self._download_build_for_play(
                    library_service,
                    selected_item,
                    token,
                    status=status,
                    progress=progress,
                    source_item=selected_source_item,
                )
                return selected

            if _build_dir_has_payload(selected_dir):
                print(f"[play] selected build {selected} is not in the catalog, launching installed files", flush=True)
                return selected
            print(f"[play] selected build {selected} is not in the catalog and not installed, falling back to latest", flush=True)

        builds = [
            item
            for item in catalog.builds
            if isinstance(item, dict) and not item.get("is_instance") and not library_service.is_server_build(item)
        ]
        if not builds:
            print("[play] no builds in the catalog", flush=True)
            raise PlayError(t("play_error_build_unavailable"), kind="build")
        latest = max(builds, key=self._build_latest_sort_key)
        build_key = library_service.build_key(latest)
        print(f"[play] latest build: {build_key} (id {latest.get('id')})", flush=True)

        if not library_service.is_build_up_to_date(latest):
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

    def _source_item_for_selected(self, builds: list[dict], item: dict | None) -> dict | None:
        if not isinstance(item, dict):
            return None
        if not item.get("is_instance"):
            return item
        source_build_id = item.get("_source_build_id")
        for candidate in builds:
            if candidate.get("is_instance"):
                continue
            if candidate.get("id") == source_build_id:
                return candidate
        return None

    def _download_build_for_play(
        self,
        library_service: LibraryService,
        item: dict,
        token: str,
        status=None,
        progress=None,
        source_item: dict | None = None,
    ) -> None:
        if not token:
            print("[play] build download impossible: not logged in", flush=True)
            raise PlayError(t("play_error_build_auth"), kind="auth")
        try:
            int((source_item or item).get("id"))
        except (TypeError, ValueError) as exc:
            print(f"[play] build download impossible: bad build id {(source_item or item).get('id')!r}", flush=True)
            raise PlayError(t("play_error_build_unavailable"), f"build id: {(source_item or item).get('id')!r}", kind="build") from exc

        if status:
            status(t("play_status_build_download"))

        def on_progress(name: str, delta: int, done: int, total: int):
            if delta > 0 and name:
                report_download_bytes(name, delta)
            if progress and total > 0:
                progress(max(0, min(100, int(done * 100 / total))))

        library_service.sync_build(item, token=token, source_item=source_item, progress=on_progress)

    def ensure_graalvm_21(self, status=None, progress=None) -> str:
        current = self._graalvm_executable()
        executable = _is_executable(str(current))
        version = get_java_version(str(current)) if executable else "missing"
        if executable and _java_version_is_21(version):
            print(f"[java] launcher JDK ready: {current} ({version})", flush=True)
            self._save_java_path(current)
            return str(current)

        print(f"[java] launcher JDK 21 not usable at {current} ({version}), downloading", flush=True)
        if status:
            status(t("play_status_java_download"))
        java_root = get_data_dir() / "java"
        downloads_dir = get_data_dir() / "downloads"
        java_root.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)

        failures = []
        for url in self._graalvm_21_urls():
            try:
                self._install_java_archive(url, java_root, downloads_dir, status=status, progress=progress)
                break
            except Exception as exc:
                failures.append(f"{url}\n  {type(exc).__name__}: {exc}")
        else:
            raise JavaError(t("play_error_java_download"), "\n".join(failures))

        current = self._graalvm_executable()
        if get_java_major_version(str(current)) != 21:
            print(f"[java] installed JDK is not usable: {current}", flush=True)
            raise JavaError(t("play_error_java_start"), f"{current}: {get_java_version(str(current))}")
        print(f"[java] launcher JDK installed: {current} ({get_java_version(str(current))})", flush=True)
        shutil.rmtree(java_root / LEGACY_ORACLE_JDK_DIR, ignore_errors=True)
        self._save_java_path(current)
        if status:
            status(t("play_status_java_ready"))
        return str(current)

    def _install_java_archive(self, url: str, java_root: Path, downloads_dir: Path, status=None, progress=None) -> None:
        expected_sha256 = self._fetch_sha256(url)
        archive_path = downloads_dir / Path(url).name
        runtime_dir = java_root / GRAALVM_DIR
        staging_dir = java_root / f"{GRAALVM_DIR}.tmp"
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        try:
            actual_sha256 = self._download_file(url, archive_path, progress=progress)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(f"sha256 mismatch: expected {expected_sha256}, got {actual_sha256}")
            if status:
                status(t("play_status_java_extract"))
            if url.endswith(".zip"):
                _safe_extract_zip(archive_path, staging_dir)
            else:
                _safe_extract_tar(archive_path, staging_dir)
            java_exe = self._find_extracted_java(staging_dir)
            if not java_exe:
                print(f"[java] no bin/java found in extracted {archive_path.name}", flush=True)
                raise RuntimeError("java executable not found in archive")
            jdk_home = java_exe.parent.parent
            print(f"[java] installing {jdk_home.name} into {runtime_dir}", flush=True)
            shutil.rmtree(runtime_dir, ignore_errors=True)
            shutil.move(str(jdk_home), str(runtime_dir))
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
            archive_path.unlink(missing_ok=True)

    def _fetch_sha256(self, url: str) -> str:
        response = requests.get(f"{url}.sha256", timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"sha256 file: HTTP {response.status_code}")
        value = (response.text.split() or [""])[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise RuntimeError("sha256 file: invalid content")
        return value

    def _download_file(self, url: str, dest: Path, progress=None) -> str:
        print(f"[download] GET {url} -> {dest}", flush=True)
        started = time.monotonic()
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=120) as response:
            if response.status_code != 200:
                print(f"[download] {url} failed: HTTP {response.status_code}", flush=True)
                raise RuntimeError(f"HTTP {response.status_code}")
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with dest.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    report_download_bytes(dest.name, len(chunk))
                    if progress and total > 0:
                        progress(max(0, min(100, int(downloaded * 100 / total))))
        print(f"[download] {dest.name}: {downloaded} of {total or '?'} bytes in {time.monotonic() - started:.1f}s", flush=True)
        return digest.hexdigest()

    def _graalvm_21_urls(self) -> list[str]:
        system = platform.system()
        arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
        if system == "Windows":
            if arch != "x64":
                raise JavaError(t("play_error_java_platform"))
            suffix = "windows-x64_bin.zip"
        elif system == "Darwin":
            suffix = f"macos-{arch}_bin.tar.gz"
        elif system == "Linux":
            suffix = f"linux-{arch}_bin.tar.gz"
        else:
            raise JavaError(t("play_error_java_platform"))
        ce = GRAALVM_CE_21_VERSION
        return [
            f"https://download.oracle.com/graalvm/21/latest/graalvm-jdk-21_{suffix}",
            f"https://github.com/graalvm/graalvm-ce-builds/releases/download/jdk-{ce}/graalvm-community-jdk-{ce}_{suffix}",
        ]

    def _graalvm_executable(self) -> Path:
        exe = "java.exe" if platform.system() == "Windows" else "java"
        return get_data_dir() / "java" / GRAALVM_DIR / "bin" / exe

    def _find_extracted_java(self, root: Path) -> Path | None:
        exe = "java.exe" if platform.system() == "Windows" else "java"
        for path in sorted(root.rglob(exe), key=lambda p: len(p.parts)):
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

    def request_bundle_key(self, build_id: int) -> bytes:
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        if not token:
            print("[bundle] key request skipped: no token", flush=True)
            raise PlayError(t("play_error_build_auth"), kind="auth")
        base = get_api_base()
        try:
            response = requests.post(
                f"{base}/api/bundle/key",
                json={"token": token, "build_id": build_id},
                timeout=10,
            )
        except Exception as exc:
            print(f"[bundle] key request failed: {type(exc).__name__}: {exc}", flush=True)
            raise
        try:
            data = response.json()
        except ValueError:
            data = None
        error = str(data.get("error") or "") if isinstance(data, dict) else ""
        details = f"bundle key: HTTP {response.status_code} {error}".strip()
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("ok"):
            reason = data.get("error") if isinstance(data, dict) else (response.text or "")[:200]
            print(f"[bundle] key request rejected by {base}: HTTP {response.status_code}, build {build_id}: {reason}", flush=True)
        if response.status_code == 401:
            raise PlayError(t("play_error_session"), details, kind="auth")
        if response.status_code == 403:
            raise PlayError(t("play_error_build_forbidden"), details, kind="build")
        if response.status_code >= 500 or response.status_code == 429:
            raise PlayError(t("play_error_server"), details, kind="server")
        if response.status_code != 200 or not isinstance(data, dict) or not data.get("ok"):
            raise PlayError(t("play_bundle_key_error"), details, kind="server")
        try:
            key = base64.b64decode(data.get("key") or "", validate=True)
        except ValueError as exc:
            print(f"[bundle] key for build {build_id} is not valid base64: {type(exc).__name__}", flush=True)
            raise PlayError(t("play_bundle_key_error"), "bundle key: invalid base64", kind="server") from exc
        if len(key) not in (16, 24, 32):
            raise PlayError(t("play_bundle_key_error"), f"bundle key: unexpected length {len(key)}", kind="server")
        print(f"[bundle] key received for build {build_id} ({len(key) * 8}-bit)", flush=True)
        return key

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

    def _legacy_bundle(self, game_dir: Path) -> tuple[Path, int] | None:
        manifest_path = self.bundle_manifest_path(game_dir)
        if not manifest_path.exists():
            return None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            encrypted_path = game_dir / str(manifest.get("archive") or "")
            build_id = int(manifest.get("build_id"))
        except Exception:
            return None
        if not manifest.get("archive") or not encrypted_path.is_file():
            return None
        return encrypted_path, build_id

    def _overlay_tree(self, root: Path, game_dir: Path, maven_dir: Path, group: str, coords: list[str], state: BundleState) -> None:
        mods_dir = game_dir / "mods"
        for src in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = src.relative_to(root)
            if len(rel.parts) == 2 and rel.parts[0].lower() == "mods" and src.suffix.lower() == ".jar":
                artifact = _random_name()
                dst = maven_dir / group / artifact / "1" / f"{artifact}-1.jar"
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)
                coords.append(f"{group}:{artifact}:1")
                duplicate = mods_dir / src.name
                if duplicate.is_file():
                    disabled = duplicate.with_name(duplicate.name + BUNDLE_DISABLED_SUFFIX)
                    duplicate.replace(disabled)
                    state.disabled.append((disabled, duplicate))
                continue

            dst = game_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                backup = dst.with_suffix(dst.suffix + ".bak")
                dst.replace(backup)
                state.backups.append((backup, dst))
            shutil.copy2(src, dst)
            state.written.append(dst)

    def _link_closed_dir(self, link: Path, target: Path, state: BundleState) -> None:
        target.mkdir(parents=True, exist_ok=True)
        link.parent.mkdir(parents=True, exist_ok=True)
        if is_link(link):
            remove_link(link)
        if link.exists():
            hidden = link.with_name(link.name + HIDDEN_SUFFIX)
            if hidden.exists():
                raise RuntimeError(f"{link} and {hidden} both exist")
            link.replace(hidden)
            state.hidden.append((hidden, link))
        link_dir(link, target)
        state.links.append(link)

    def prepare_bundle_files(self, game_dir: Path, hide=None) -> BundleState | None:
        _remove_stale_bundle_dirs()
        _restore_disabled_mods(game_dir / "mods")
        remove_closed_links(game_dir)

        closed = closed_units(game_dir)
        legacy = self._legacy_bundle(game_dir)
        if not closed and legacy is None:
            print("[bundle] build has no protected content", flush=True)
            return None
        try:
            build_id = legacy[1] if legacy else int(load_state(game_dir).get("build_id"))
        except (TypeError, ValueError) as exc:
            print("[bundle] protected content present but build id is unknown", flush=True)
            raise PlayError(t("play_error_build_broken"), f"build state: {game_dir}", kind="build") from exc
        print(f"[bundle] build {build_id}: {len(closed)} closed units" + (", legacy archive" if legacy else ""), flush=True)

        key32 = self.request_bundle_key(build_id)

        state = BundleState(
            temp_dir=Path(tempfile.mkdtemp(prefix="")),
            written=[],
            backups=[],
            disabled=[],
            game_args=[],
        )
        if hide:
            hide(state.temp_dir)
        _save_session_dirs([state.temp_dir])
        maven_dir = state.temp_dir / _random_name()
        group = _random_name()
        coords: list[str] = []
        try:
            if legacy:
                payload_dir = state.temp_dir / _random_name()
                files = extract_zip(io.BytesIO(self.decrypt_archive(legacy[0].read_bytes(), key32)), payload_dir)
                print(f"[bundle] legacy archive {legacy[0].name}: {len(files)} files", flush=True)
                self._overlay_tree(payload_dir, game_dir, maven_dir, group, coords, state)
                shutil.rmtree(payload_dir, ignore_errors=True)

            for path, entry in closed:
                rel = PurePosixPath(path)
                root = state.temp_dir / _random_name()
                plain = state.temp_dir / _random_name()
                decrypt_pack_file(game_dir / CLOSED_DIR / str(entry["payload"]), key32, plain)
                files = extract_zip(plain, root)
                plain.unlink(missing_ok=True)
                if entry.get("type") == "dir" and rel.parts[0].lower() != "mods":
                    self._link_closed_dir(game_dir.joinpath(*rel.parts), root.joinpath(*rel.parts), state)
                    mode = "linked"
                else:
                    self._overlay_tree(root, game_dir, maven_dir, group, coords, state)
                    mode = "overlay"
                print(f"[bundle] closed unit {path} ({entry.get('type') or 'file'}): {len(files)} files, {mode}", flush=True)
        except Exception as exc:
            print(f"[bundle] preparing protected content failed: {type(exc).__name__}: {exc}", flush=True)
            self.cleanup_bundle_files(state)
            raise

        if coords:
            state.game_args = ["--fml.mavenRoots", str(maven_dir), "--fml.mods", ",".join(coords)]
        print(f"[bundle] ready: {len(coords)} protected mods, {len(state.written)} overlay files, {len(state.links)} linked dirs", flush=True)
        return state

    def cleanup_bundle_files(self, bundle_state: BundleState | None) -> None:
        if not bundle_state:
            return
        failures: list[str] = []
        for link in bundle_state.links:
            try:
                remove_link(link)
            except OSError as exc:
                failures.append(f"remove link {link}: {exc}")
        for hidden, original in bundle_state.hidden:
            try:
                if hidden.exists() and not original.exists():
                    hidden.replace(original)
            except OSError as exc:
                failures.append(f"restore {original}: {exc}")
        for path in bundle_state.written:
            try:
                if path.exists():
                    path.unlink()
            except Exception as exc:
                failures.append(f"remove overlay file {path}: {exc}")
        for backup, dst in bundle_state.backups:
            try:
                if dst.exists():
                    dst.unlink()
                if backup.exists():
                    backup.replace(dst)
            except Exception as exc:
                failures.append(f"restore backup {dst}: {exc}")
        for disabled, original in bundle_state.disabled:
            try:
                if disabled.exists() and not original.exists():
                    disabled.replace(original)
            except Exception as exc:
                failures.append(f"re-enable mod {original.name}: {exc}")
        _remove_temp_dir(bundle_state.temp_dir)
        try:
            _save_session_dirs([d for d in _load_session_dirs() if d != bundle_state.temp_dir])
        except Exception as exc:
            failures.append(f"update session file: {exc}")
        print(
            f"[bundle] cleanup: {len(bundle_state.links)} links, {len(bundle_state.hidden)} hidden dirs, "
            f"{len(bundle_state.written)} overlay files, {len(bundle_state.backups)} backups, "
            f"{len(bundle_state.disabled)} disabled mods, {len(failures)} failures",
            flush=True,
        )
        for failure in failures:
            print(f"[bundle] cleanup failed: {failure}", flush=True)

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
