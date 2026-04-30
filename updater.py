import hashlib
import os
import platform
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
from desktop_integration import set_windows_app_user_model_id, windows_hidden_subprocess_kwargs
from window.chrome import AppWindow, asset_path
from window.style import build_app_qss


DEFAULT_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
REQUEST_TIMEOUT = 15
SKIP_UPDATER_ARG = "--skip-updater"


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    return _runtime_dir() / "updater.log"


def _launcher_binary_name() -> str:
    return "Lota-launcher.exe" if platform.system() == "Windows" else "Lota-launcher"


def _launcher_path() -> Path:
    raw = os.getenv("LOTA_LAUNCHER_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_runtime_dir() / _launcher_binary_name()).resolve()


def _launcher_source_path() -> Path:
    return (_runtime_dir() / "launcher.py").resolve()


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


def read_local_version() -> str:
    path = _launcher_version_path()
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip() or "0.0.0"
        except Exception as exc:
            log(f"Failed to read version file {path}: {exc}")
    return os.getenv("LOTA_LAUNCHER_VERSION", "0.0.0").strip() or "0.0.0"


def write_local_version(version: str) -> None:
    path = _launcher_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((version or "").strip() + "\n", encoding="utf-8")


def get_api_base() -> str:
    return resolve_api_base()


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


class UpdaterWorker(QThread):
    status_changed = Signal(str)
    progress_mode_changed = Signal(bool)
    progress_changed = Signal(int)
    finished_with_code = Signal(int)

    def __init__(self, launch_args: list[str], parent=None):
        super().__init__(parent)
        self.launch_args = list(launch_args)

    def run(self):
        if not launcher_exists():
            log("Launcher is missing locally; updater will still try to fetch metadata")

        self.progress_mode_changed.emit(True)
        self.progress_changed.emit(0)
        self.status_changed.emit("Проверяю обновления...")
        update_info = check_for_update()

        if update_info and update_info.get("update_available") is True:
            self.progress_mode_changed.emit(False)
            self.progress_changed.emit(0)
            self.status_changed.emit("Найдено обновление. Подготавливаю установку...")

            def on_status(text: str):
                self.status_changed.emit(text)

            def on_progress(done: int, total: int):
                if total <= 0:
                    return
                value = max(0, min(100, int(done * 100 / total)))
                self.progress_changed.emit(value)

            ok = install_update(update_info, status_callback=on_status, progress_callback=on_progress)
            if not ok:
                self.status_changed.emit("Не удалось обновить лаунчер. Запускаю текущую версию...")
                self.progress_mode_changed.emit(True)
            else:
                self.status_changed.emit("Обновление установлено.")
                self.progress_changed.emit(100)
        else:
            self.status_changed.emit("Обновлений не найдено.")
            self.progress_mode_changed.emit(True)

        self.status_changed.emit("Запускаю лаунчер...")
        code = launch_launcher(self.launch_args)
        self.finished_with_code.emit(code)


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

        self._worker = UpdaterWorker(launch_args, self)
        self._worker.status_changed.connect(self.status_label.setText)
        self._worker.progress_mode_changed.connect(self._set_busy_progress)
        self._worker.progress_changed.connect(self.progress.setValue)
        self._worker.finished_with_code.connect(self._on_finished)
        self._worker.start()

    def _set_busy_progress(self, busy: bool) -> None:
        if busy:
            self.progress.setRange(0, 0)
            return
        self.progress.setRange(0, 100)

    def _on_finished(self, code: int) -> None:
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
