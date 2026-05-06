import hashlib
import os
import platform
import shlex
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

from auth.api_base import get_api_base as resolve_api_base
from auth.auth_storage import get_data_dir
from desktop_integration import set_windows_app_user_model_id, windows_hidden_subprocess_kwargs
from window.chrome import AppWindow, ask_app_confirmation, asset_path
from window.style import build_app_qss


DEFAULT_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
REQUEST_TIMEOUT = 15
SKIP_UPDATER_ARG = "--skip-updater"
SKIP_SELF_UPDATE_ARG = "--skip-self-update"
DOWNLOAD_PROGRESS_START = 27


def _download_progress_percent(value: int) -> int:
    value = max(0, min(100, int(value)))
    return DOWNLOAD_PROGRESS_START + int(value * (100 - DOWNLOAD_PROGRESS_START) / 100)


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        path = (get_data_dir() / "runtime").resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    return _runtime_dir() / "updater.log"


def _launcher_binary_name() -> str:
    return "Lota-launcher.exe" if platform.system() == "Windows" else "Lota-launcher"


def _updater_binary_name() -> str:
    return "updater.exe" if platform.system() == "Windows" else "updater"


def _launcher_path() -> Path:
    raw = os.getenv("LOTA_LAUNCHER_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_runtime_dir() / _launcher_binary_name()).resolve()


def _launcher_source_path() -> Path:
    return (_runtime_dir() / "launcher.py").resolve()


def _updater_path() -> Path:
    if getattr(sys, "frozen", False):
        return (_runtime_dir() / _updater_binary_name()).resolve()
    return (_runtime_dir() / "updater.py").resolve()


def _windows_pythonw_executable() -> str:
    if platform.system() != "Windows":
        return sys.executable
    current = Path(sys.executable)
    candidate = current.with_name("pythonw.exe")
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _launcher_version_path() -> Path:
    raw = os.getenv("LOTA_LAUNCHER_VERSION_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_runtime_dir() / "launcher.version").resolve()


def _updater_version_path() -> Path:
    return (_runtime_dir() / "updater.version").resolve()


def _launcher_backup_path() -> Path:
    launcher = _launcher_path()
    return launcher.with_name(f"{launcher.name}.old")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    line = f"[{_now_text()}] {message}\n"
    try:
        _log_path().parent.mkdir(parents=True, exist_ok=True)
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        if sys.stderr:
            sys.stderr.write(line)
    except Exception:
        pass


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine_aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    machine = machine_aliases.get(machine, machine)
    return f"{system}-{machine}"


def launcher_exists() -> bool:
    return _launcher_path().exists() or (not getattr(sys, "frozen", False) and _launcher_source_path().exists())


def _read_version_file(path: Path, fallback_env: str) -> str:
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip() or "0.0.0"
        except Exception as exc:
            log(f"Failed to read version file {path}: {exc}")
    return os.getenv(fallback_env, "0.0.0").strip() or "0.0.0"


def read_local_version() -> str:
    return _read_version_file(_launcher_version_path(), "LOTA_LAUNCHER_VERSION")


def read_local_updater_version() -> str:
    return _read_version_file(_updater_version_path(), "LOTA_UPDATER_VERSION")


def write_local_version(version: str) -> None:
    path = _launcher_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((version or "").strip() + "\n", encoding="utf-8")


def write_local_updater_version(version: str) -> None:
    path = _updater_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((version or "").strip() + "\n", encoding="utf-8")


def get_api_base() -> str:
    return resolve_api_base()


def fetch_runtime_manifest() -> dict | None:
    payload = {"platform": detect_platform(), "channel": DEFAULT_CHANNEL}
    try:
        response = requests.post(
            f"{get_api_base()}/api/runtime/check",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log(f"Runtime manifest check failed: {exc}")
        return None
    if response.status_code != 200:
        log(f"Runtime manifest check returned HTTP {response.status_code}")
        return None
    try:
        data = response.json()
    except ValueError as exc:
        log(f"Runtime manifest returned invalid JSON: {exc}")
        return None
    if not isinstance(data, dict) or data.get("ok") is not True:
        log(f"Runtime manifest error: {data}")
        return None
    return data


def check_for_update() -> dict | None:
    payload = {
        "platform": detect_platform(),
        "version": read_local_version(),
        "channel": DEFAULT_CHANNEL,
    }
    try:
        response = requests.post(
            f"{get_api_base()}/api/launcher/check",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log(f"Update check failed: {exc}")
        return None

    if response.status_code != 200:
        log(f"Update check returned HTTP {response.status_code}")
        return None

    try:
        data = response.json()
    except ValueError as exc:
        log(f"Update check returned invalid JSON: {exc}")
        return None

    if not isinstance(data, dict):
        log("Update check returned non-dict payload")
        return None
    if data.get("ok") is not True:
        log(f"Update check error: {data.get('error')}")
        return None
    return data


def _apply_executable_bits(path: Path) -> None:
    if platform.system() == "Windows":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 256)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_to_temp(url: str, expected_sha256: str, expected_size: int, *, progress_callback=None) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix="launcher_update_", dir=str(_runtime_dir()))
    os.close(fd)
    tmp_path = Path(tmp_name)

    sha256 = hashlib.sha256()
    total = 0

    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            total_bytes = int(response.headers.get("Content-Length") or 0) or expected_size
            with tmp_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    sha256.update(chunk)
                    total += len(chunk)
                    if callable(progress_callback):
                        progress_callback(total, total_bytes)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if expected_size > 0 and total != expected_size:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded size mismatch: expected {expected_size}, got {total}")

    actual_sha256 = sha256.hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded sha256 mismatch")

    _apply_executable_bits(tmp_path)
    return tmp_path


def replace_binary(current_path: Path, new_path: Path) -> None:
    backup_path = _launcher_backup_path()
    backup_path.unlink(missing_ok=True)
    current_path.parent.mkdir(parents=True, exist_ok=True)

    restored = False
    try:
        if current_path.exists():
            os.replace(current_path, backup_path)
        os.replace(new_path, current_path)
        restored = True
    except Exception:
        if not current_path.exists() and backup_path.exists():
            os.replace(backup_path, current_path)
        raise
    finally:
        if restored and backup_path.exists():
            backup_path.unlink(missing_ok=True)


def get_updater_update_info() -> dict | None:
    if not getattr(sys, "frozen", False):
        return None
    manifest = fetch_runtime_manifest()
    if not isinstance(manifest, dict):
        return None
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    updater_artifact = artifacts.get("updater")
    if not isinstance(updater_artifact, dict):
        return None

    remote_version = str(updater_artifact.get("version") or "").strip()
    remote_sha256 = str(updater_artifact.get("sha256") or "").strip().lower()
    local_version = read_local_updater_version()
    updater_path = _updater_path()

    if remote_version and remote_version != "0.0.0" and local_version != "0.0.0":
        if remote_version != local_version:
            return updater_artifact
        return None

    if remote_sha256 and updater_path.exists():
        try:
            local_sha256 = _sha256_file(updater_path).lower()
        except Exception as exc:
            log(f"Failed to hash updater binary: {exc}")
            return updater_artifact
        if local_sha256 != remote_sha256:
            return updater_artifact
    return None


def install_update(update_info: dict, *, status_callback=None, progress_callback=None) -> bool:
    launcher_path = _launcher_path()
    launcher_url = str(update_info.get("url") or "").strip()
    if not launcher_url:
        log("Update payload does not contain a file URL")
        return False

    if launcher_url.startswith("/"):
        launcher_url = f"{get_api_base()}{launcher_url}"

    version = str(update_info.get("version") or "").strip()
    sha256 = str(update_info.get("sha256") or "").strip()
    size = int(update_info.get("size") or 0)
    temp_path: Path | None = None

    try:
        if callable(status_callback):
            status_callback(f"Скачиваю обновление {version or ''}".strip())
        log(f"Downloading launcher update {version or '<unknown>'} from {launcher_url}")
        temp_path = _download_to_temp(launcher_url, sha256, size, progress_callback=progress_callback)
        if callable(status_callback):
            status_callback("Устанавливаю обновление...")
        replace_binary(launcher_path, temp_path)
        write_local_version(version)
        log(f"Launcher updated to version {version}")
        if callable(progress_callback):
            progress_callback(size or 1, size or 1)
        return True
    except Exception as exc:
        log(f"Failed to install launcher update: {exc}")
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        return False


def _restart_updater_args(launch_args: list[str]) -> list[str]:
    args = [arg for arg in launch_args if arg != SKIP_SELF_UPDATE_ARG]
    args.append(SKIP_SELF_UPDATE_ARG)
    return args


def _schedule_windows_self_replace(current_path: Path, temp_path: Path, relaunch_args: list[str]) -> None:
    cmdline_args = subprocess.list2cmdline(relaunch_args)
    restart_cmd = f'"{current_path}" {cmdline_args}'.strip()
    script = "\n".join(
        [
            "@echo off",
            "setlocal",
            f'set "TARGET={current_path}"',
            f'set "SOURCE={temp_path}"',
            f'set "BACKUP={current_path.with_suffix(current_path.suffix + ".old")}"',
            ":retry",
            'move /Y "%TARGET%" "%BACKUP%" >nul 2>nul',
            'if not exist "%BACKUP%" (',
            "  timeout /t 1 /nobreak >nul",
            "  goto retry",
            ")",
            'move /Y "%SOURCE%" "%TARGET%" >nul 2>nul',
            'if errorlevel 1 (',
            '  move /Y "%BACKUP%" "%TARGET%" >nul 2>nul',
            "  timeout /t 1 /nobreak >nul",
            "  goto retry",
            ")",
            'del /f /q "%BACKUP%" >nul 2>nul',
            f'start "" /D "{current_path.parent}" {restart_cmd}',
            'del /f /q "%~f0" >nul 2>nul',
        ]
    )
    script_path = current_path.parent / "updater_self_replace.cmd"
    script_path.write_text(script, encoding="utf-8")
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        cwd=str(current_path.parent),
        **windows_hidden_subprocess_kwargs(),
    )


def _schedule_posix_self_replace(current_path: Path, temp_path: Path, relaunch_args: list[str]) -> None:
    quoted_args = " ".join(shlex.quote(arg) for arg in relaunch_args)
    script = "\n".join(
        [
            "#!/bin/sh",
            f'TARGET="{current_path}"',
            f'SOURCE="{temp_path}"',
            f'BACKUP="{current_path}.old"',
            "while ! mv \"$TARGET\" \"$BACKUP\" 2>/dev/null; do sleep 1; done",
            "if ! mv \"$SOURCE\" \"$TARGET\" 2>/dev/null; then",
            "  mv \"$BACKUP\" \"$TARGET\" 2>/dev/null",
            "  exit 1",
            "fi",
            "chmod +x \"$TARGET\" 2>/dev/null",
            "rm -f \"$BACKUP\"",
            f'exec "$TARGET" {quoted_args}',
        ]
    )
    script_fd, script_name = tempfile.mkstemp(prefix="updater_self_replace_", dir=str(current_path.parent))
    os.close(script_fd)
    script_path = Path(script_name)
    script_path.write_text(script, encoding="utf-8")
    _apply_executable_bits(script_path)
    subprocess.Popen([str(script_path)], cwd=str(current_path.parent))


def schedule_self_update(update_info: dict, launch_args: list[str], *, status_callback=None, progress_callback=None) -> bool:
    current_path = _updater_path()
    if not getattr(sys, "frozen", False) or not current_path.exists():
        return False

    updater_url = str(update_info.get("url") or "").strip()
    if not updater_url:
        log("Updater payload does not contain a file URL")
        return False
    if updater_url.startswith("/"):
        updater_url = f"{get_api_base()}{updater_url}"

    version = str(update_info.get("version") or "").strip()
    sha256 = str(update_info.get("sha256") or "").strip()
    size = int(update_info.get("size") or 0)

    try:
        if callable(status_callback):
            status_callback(f"Скачиваю обновление апдейтера {version or ''}".strip())
        log(f"Downloading updater update {version or '<unknown>'} from {updater_url}")
        temp_path = _download_to_temp(updater_url, sha256, size, progress_callback=progress_callback)
        relaunch_args = _restart_updater_args(launch_args)
        if platform.system() == "Windows":
            _schedule_windows_self_replace(current_path, temp_path, relaunch_args)
        else:
            _schedule_posix_self_replace(current_path, temp_path, relaunch_args)
        write_local_updater_version(version or read_local_updater_version())
        if callable(progress_callback):
            progress_callback(size or 1, size or 1)
        return True
    except Exception as exc:
        log(f"Failed to schedule updater self-update: {exc}")
        return False


def launch_launcher(args: list[str]) -> int:
    launcher_path = _launcher_path()
    launch_args = [arg for arg in args if arg != SKIP_UPDATER_ARG]
    launch_args.append(SKIP_UPDATER_ARG)
    if launcher_path.exists():
        cmd = [str(launcher_path), *launch_args]
    elif not getattr(sys, "frozen", False) and _launcher_source_path().exists():
        cmd = [_windows_pythonw_executable(), str(_launcher_source_path()), *launch_args]
    else:
        log(f"Launcher binary not found at {launcher_path}")
        return 1

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(_runtime_dir()),
            **windows_hidden_subprocess_kwargs(),
        )
    except Exception as exc:
        log(f"Failed to launch launcher: {exc}")
        return 1

    log(f"Launcher started with PID {process.pid}")
    return 0


class UpdateCheckWorker(QThread):
    status_changed = Signal(str)
    progress_mode_changed = Signal(bool)
    progress_changed = Signal(int)
    checked = Signal(object)

    def __init__(self, launch_args: list[str], *, skip_self_update: bool = False, parent=None):
        super().__init__(parent)
        self.launch_args = list(launch_args)
        self.skip_self_update = skip_self_update

    def run(self):
        if not launcher_exists():
            log("Launcher is missing locally; updater will still try to fetch metadata")

        self.progress_mode_changed.emit(False)
        self.progress_changed.emit(5)
        self.status_changed.emit("Проверяю обновления...")
        updater_update_info = None if self.skip_self_update or SKIP_SELF_UPDATE_ARG in self.launch_args else get_updater_update_info()
        update_info = check_for_update()
        self.progress_changed.emit(18)
        self.checked.emit({"launcher": update_info, "updater": updater_update_info})


class SelfUpdateWorker(QThread):
    status_changed = Signal(str)
    progress_mode_changed = Signal(bool)
    progress_changed = Signal(int)
    scheduled = Signal(bool)

    def __init__(self, update_info: dict, launch_args: list[str], parent=None):
        super().__init__(parent)
        self.update_info = dict(update_info or {})
        self.launch_args = list(launch_args)

    def run(self):
        self.progress_mode_changed.emit(False)
        self.progress_changed.emit(DOWNLOAD_PROGRESS_START)
        self.status_changed.emit("Найдено обновление апдейтера. Подготавливаю установку...")

        def on_status(text: str):
            self.status_changed.emit(text)

        def on_progress(done: int, total: int):
            if total <= 0:
                return
            value = max(0, min(100, int(done * 100 / total)))
            self.progress_changed.emit(_download_progress_percent(value))

        ok = schedule_self_update(
            self.update_info,
            self.launch_args,
            status_callback=on_status,
            progress_callback=on_progress,
        )
        if ok:
            self.status_changed.emit("Апдейтер обновлен. Перезапускаю апдейтер...")
            self.progress_changed.emit(100)
        else:
            self.status_changed.emit("Не удалось обновить апдейтер. Продолжаю с текущей версией...")
            self.progress_mode_changed.emit(True)
        self.scheduled.emit(ok)


class UpdateInstallWorker(QThread):
    status_changed = Signal(str)
    progress_mode_changed = Signal(bool)
    progress_changed = Signal(int)
    finished_ok = Signal(bool)

    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = dict(update_info or {})

    def run(self):
        self.progress_mode_changed.emit(False)
        self.progress_changed.emit(DOWNLOAD_PROGRESS_START)
        self.status_changed.emit("Найдено обновление. Подготавливаю установку...")

        def on_status(text: str):
            self.status_changed.emit(text)

        def on_progress(done: int, total: int):
            if total <= 0:
                return
            value = max(0, min(100, int(done * 100 / total)))
            self.progress_changed.emit(_download_progress_percent(value))

        ok = install_update(self.update_info, status_callback=on_status, progress_callback=on_progress)
        if ok:
            self.status_changed.emit("Обновление установлено.")
            self.progress_changed.emit(100)
        else:
            self.status_changed.emit("Не удалось обновить лаунчер. Запускаю текущую версию...")
            self.progress_mode_changed.emit(True)
        self.finished_ok.emit(ok)


class UpdaterWindow(AppWindow):
    def __init__(self, launch_args: list[str]):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle("LOTA Launcher Updater")
        self.set_locked_window_size(480, 240)

        self.panel = QWidget()
        self.panel.setProperty("panel", True)
        self.content_layout.setContentsMargins(14, 14, 14, 14)
        self.content_layout.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(9)

        self.title_label = QLabel("Обновление лаунчера")
        self.title_label.setProperty("installerText", True)
        title_font = self.title_label.font()
        title_font.setPixelSize(18)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)

        self.status_label = QLabel("Подготовка...")
        self.status_label.setProperty("installerText", True)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setProperty("installerProgress", True)
        self.progress.setFixedHeight(26)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        layout.addWidget(self.progress)

        self.meta_label = QLabel("Проверяем актуальную версию и при необходимости скачиваем обновление.")
        self.meta_label.setProperty("installerMeta", True)
        self.meta_label.setWordWrap(True)
        layout.addWidget(self.meta_label)
        layout.addStretch()

        self.launch_args = list(launch_args)
        self._worker = None
        self._skip_self_update_check = False
        self._start_check()

    def _start_check(self) -> None:
        worker = UpdateCheckWorker(self.launch_args, skip_self_update=self._skip_self_update_check, parent=self)
        self._worker = worker
        worker.status_changed.connect(self.status_label.setText)
        worker.progress_mode_changed.connect(self._set_busy_progress)
        worker.progress_changed.connect(self.progress.setValue)
        worker.checked.connect(self._on_checked)
        worker.start()

    def _start_install(self, update_info: dict) -> None:
        worker = UpdateInstallWorker(update_info, self)
        self._worker = worker
        worker.status_changed.connect(self.status_label.setText)
        worker.progress_mode_changed.connect(self._set_busy_progress)
        worker.progress_changed.connect(self.progress.setValue)
        worker.finished_ok.connect(self._on_install_finished)
        worker.start()

    def _start_self_update(self, update_info: dict) -> None:
        worker = SelfUpdateWorker(update_info, self.launch_args, self)
        self._worker = worker
        worker.status_changed.connect(self.status_label.setText)
        worker.progress_mode_changed.connect(self._set_busy_progress)
        worker.progress_changed.connect(self.progress.setValue)
        worker.scheduled.connect(self._on_self_update_finished)
        worker.start()

    def _set_busy_progress(self, busy: bool) -> None:
        if busy:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)

    def _on_checked(self, payload: dict | None) -> None:
        payload = payload or {}
        updater_update_info = payload.get("updater") if isinstance(payload, dict) else None
        launcher_update_info = payload.get("launcher") if isinstance(payload, dict) else None
        updater_skipped = False

        if updater_update_info:
            version = str(updater_update_info.get("version") or "").strip() or "новая версия"
            approved = ask_app_confirmation(
                self,
                "Обновление апдейтера",
                f"Доступно обновление апдейтера: {version}.\nУстановить его сейчас?",
                kind="warning",
            )
            if approved:
                self._start_self_update(updater_update_info)
                return
            self.status_label.setText("Обновление апдейтера пропущено пользователем.")
            updater_skipped = True

        if launcher_update_info and launcher_update_info.get("update_available") is True:
            version = str(launcher_update_info.get("version") or "").strip() or "новая версия"
            approved = ask_app_confirmation(
                self,
                "Обновление лаунчера",
                f"Доступно обновление лаунчера: {version}.\nУстановить его сейчас?",
                kind="warning",
            )
            if approved:
                self._start_install(launcher_update_info)
                return
            self.status_label.setText("Обновление лаунчера пропущено пользователем.")
            self.progress.setValue(100)
            self._launch_launcher()
            return

        if updater_skipped:
            self.progress.setValue(100)
            self._launch_launcher()
            return

        self.status_label.setText("Обновлений не найдено.")
        self.progress.setValue(100)
        self._launch_launcher()

    def _on_self_update_finished(self, ok: bool) -> None:
        if ok:
            QTimer.singleShot(400, QApplication.instance().quit)
            return
        self._skip_self_update_check = True
        self._start_check()

    def _on_install_finished(self, _ok: bool) -> None:
        self._launch_launcher()

    def _launch_launcher(self) -> None:
        self.status_label.setText("Запускаю лаунчер...")
        code = launch_launcher(self.launch_args)
        if code == 0:
            QTimer.singleShot(400, QApplication.instance().quit)
            return
        self.status_label.setText("Не удалось запустить лаунчер. Подробности смотри в updater.log")
        self.progress.setRange(0, 100)
        self.progress.setValue(100)


def _build_app_font(font_family: str, pixel_size: int) -> QFont:
    font = QFont(font_family)
    font.setPixelSize(pixel_size)
    return font


def main(argv: list[str]) -> int:
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    set_windows_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    app = QApplication(argv)
    logo_path = asset_path("logo.ico") if sys.platform.startswith("win") else asset_path("logo.png")
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    asset_dir = asset_path("logo.png").parent
    font_path = asset_dir / "fonts" / "Monocraft-ttf" / "Monocraft.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(_build_app_font(families[0], 14))
    app.setStyleSheet(build_app_qss(str(asset_dir)))

    window = UpdaterWindow(argv[1:])
    if logo_path.exists():
        window.setWindowIcon(QIcon(str(logo_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
