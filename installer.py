import argparse
import hashlib
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar, QTextEdit, QVBoxLayout, QWidget

from desktop_integration import install_desktop_entry, set_windows_app_user_model_id
from desktop_integration import windows_hidden_subprocess_kwargs
from auth.api_base import get_api_base as resolve_api_base
from auth.auth_storage import get_data_dir
from window.chrome import AppWindow, asset_path
from window.style import build_app_qss


DEFAULT_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
REQUEST_TIMEOUT = 20


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    machine = aliases.get(machine, machine)
    return f"{system}-{machine}"


def default_install_dir() -> Path:
    return get_data_dir() / "runtime"


def resolve_install_dir(raw: str | None) -> Path:
    env_dir = os.getenv("LOTA_INSTALL_DIR", "").strip()
    value = raw or env_dir
    if value:
        return Path(value).expanduser().resolve()
    return default_install_dir().resolve()


def get_api_base() -> str:
    return resolve_api_base()


def log(message: str, install_dir: Path | None = None) -> None:
    line = message.rstrip()
    print(line)
    if install_dir is None:
        return
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        with (install_dir / "installer.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fetch_runtime_manifest(channel: str) -> dict:
    payload = {"platform": detect_platform(), "channel": channel}
    response = requests.post(
        f"{get_api_base()}/api/runtime/check",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(f"Invalid runtime payload: {data}")
    return data


def _artifact_target_path(install_dir: Path, artifact_name: str, artifact: dict) -> Path:
    default_names = {
        "launcher": "Lota-launcher.exe" if platform.system() == "Windows" else "Lota-launcher",
        "updater": "updater.exe" if platform.system() == "Windows" else "updater",
        "installer": "installer.exe" if platform.system() == "Windows" else "installer",
    }
    filename = str(artifact.get("filename") or default_names.get(artifact_name, artifact_name)).strip()
    if not filename:
        filename = default_names.get(artifact_name, artifact_name)
    return install_dir / filename


def _apply_exec_bits(path: Path) -> None:
    if platform.system() == "Windows":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_to_temp(
    url: str,
    sha256_hex: str,
    size: int,
    temp_dir: Path,
    progress_callback=None,
) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="lota_install_", dir=str(temp_dir))
    os.close(fd)
    temp_path = Path(name)
    digest = hashlib.sha256()
    total = 0

    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            total_bytes = int(response.headers.get("Content-Length") or 0) or size
            with temp_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    if progress_callback:
                        progress_callback(total, total_bytes)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    if size > 0 and total != size:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Size mismatch for downloaded file: expected {size}, got {total}")

    actual = digest.hexdigest()
    if sha256_hex and actual.lower() != sha256_hex.lower():
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("SHA256 mismatch for downloaded file")

    _apply_exec_bits(temp_path)
    return temp_path


def install_artifact(
    install_dir: Path,
    artifact_name: str,
    artifact: dict,
    progress_callback=None,
) -> Path:
    url = str(artifact.get("url") or "").strip()
    if not url:
        raise RuntimeError(f"Artifact {artifact_name} does not provide url")
    if url.startswith("/"):
        url = f"{get_api_base()}{url}"

    try:
        size = int(artifact.get("size") or 0)
    except Exception:
        size = 0
    sha256_hex = str(artifact.get("sha256") or "").strip()
    target_path = _artifact_target_path(install_dir, artifact_name, artifact)
    temp_path = _download_to_temp(
        url,
        sha256_hex,
        size,
        install_dir,
        progress_callback=progress_callback,
    )
    backup_path = target_path.with_name(f"{target_path.name}.bak")

    install_dir.mkdir(parents=True, exist_ok=True)
    backup_path.unlink(missing_ok=True)
    try:
        if target_path.exists():
            os.replace(target_path, backup_path)
        os.replace(temp_path, target_path)
        _apply_exec_bits(target_path)
        backup_path.unlink(missing_ok=True)
    except Exception:
        if backup_path.exists() and not target_path.exists():
            os.replace(backup_path, target_path)
        temp_path.unlink(missing_ok=True)
        raise

    return target_path


def write_launcher_version(install_dir: Path, version: str) -> None:
    (install_dir / "launcher.version").write_text((version or "").strip() + "\n", encoding="utf-8")


def _run_launcher_install_desktop(launcher_path: Path) -> bool:
    if platform.system() != "Linux":
        return False
    if not launcher_path.exists():
        return False
    try:
        proc = subprocess.run(
            [str(launcher_path), "--install-desktop"],
            cwd=str(launcher_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=12,
        )
        return proc.returncode == 0
    except Exception:
        return False


def install_launcher_shortcut(install_dir: Path, launcher_artifact: dict) -> None:
    launcher_path = _artifact_target_path(install_dir, "launcher", launcher_artifact)
    if _run_launcher_install_desktop(launcher_path):
        return
    install_desktop_entry(launcher_path, asset_path("logo.ico"))


def launch_updater(install_dir: Path, artifact: dict, passthrough_args: list[str]) -> int:
    updater_path = _artifact_target_path(install_dir, "updater", artifact)
    subprocess.Popen(
        [str(updater_path), *passthrough_args],
        cwd=str(install_dir),
        **windows_hidden_subprocess_kwargs(),
    )
    return 0


def install_runtime(
    install_dir: Path,
    channel: str,
    passthrough_args: list[str],
    progress_callback=None,
    status_callback=None,
    no_launch: bool = False,
) -> dict:
    def emit_status(text: str) -> None:
        log(text, install_dir)
        if status_callback:
            status_callback(text)

    emit_status("Получаем список файлов...")
    manifest = fetch_runtime_manifest(channel)
    artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
    if not isinstance(artifacts, dict):
        raise RuntimeError("Runtime manifest does not contain artifacts")

    launcher_artifact = artifacts.get("launcher")
    updater_artifact = artifacts.get("updater")
    if not isinstance(launcher_artifact, dict) or not isinstance(updater_artifact, dict):
        raise RuntimeError("Runtime manifest must contain launcher and updater artifacts")

    total_size = 0
    artifact_sizes: dict[str, int] = {}
    for name, artifact in (("updater", updater_artifact), ("launcher", launcher_artifact)):
        try:
            artifact_size = int(artifact.get("size") or 0)
        except Exception:
            artifact_size = 0
        artifact_sizes[name] = max(artifact_size, 0)
        total_size += artifact_sizes[name]

    downloaded_by_artifact = {"updater": 0, "launcher": 0}

    def emit_progress() -> None:
        if not progress_callback:
            return
        if total_size > 0:
            done = sum(downloaded_by_artifact.values())
            pct = max(0, min(100, int(done * 100 / total_size)))
            progress_callback(pct)

    def artifact_progress(artifact_name: str):
        def _inner(done: int, _total: int) -> None:
            downloaded_by_artifact[artifact_name] = max(done, downloaded_by_artifact.get(artifact_name, 0))
            emit_progress()
        return _inner

    emit_status("Скачиваем updater...")
    install_artifact(
        install_dir,
        "updater",
        updater_artifact,
        progress_callback=artifact_progress("updater"),
    )
    downloaded_by_artifact["updater"] = artifact_sizes["updater"]
    emit_progress()

    emit_status("Скачиваем launcher...")
    install_artifact(
        install_dir,
        "launcher",
        launcher_artifact,
        progress_callback=artifact_progress("launcher"),
    )
    downloaded_by_artifact["launcher"] = artifact_sizes["launcher"]
    emit_progress()

    emit_status("Финализируем установку...")
    write_launcher_version(install_dir, str(launcher_artifact.get("version") or "0.0.0"))
    install_launcher_shortcut(install_dir, launcher_artifact)
    if progress_callback:
        progress_callback(100)

    if no_launch:
        emit_status("Установка завершена.")
        return {"install_dir": install_dir, "launcher_artifact": launcher_artifact, "updater_artifact": updater_artifact}

    emit_status("Запускаем launcher...")
    launch_updater(install_dir, updater_artifact, passthrough_args)
    return {"install_dir": install_dir, "launcher_artifact": launcher_artifact, "updater_artifact": updater_artifact}


class InstallWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    failed = Signal(str)
    finished_ok = Signal()

    def __init__(self, install_dir: Path, channel: str, launcher_args: list[str], no_launch: bool):
        super().__init__()
        self.install_dir = install_dir
        self.channel = channel
        self.launcher_args = launcher_args
        self.no_launch = no_launch

    def run(self) -> None:
        try:
            install_runtime(
                self.install_dir,
                self.channel,
                self.launcher_args,
                progress_callback=self.progress.emit,
                status_callback=self.status.emit,
                no_launch=self.no_launch,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit()


class InstallerWindow(AppWindow):
    def __init__(self, install_dir: Path, channel: str, launcher_args: list[str], no_launch: bool):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle("LOTA Installer")
        self.set_locked_window_size(520, 360)

        self.install_dir = install_dir
        self.channel = channel
        self.launcher_args = launcher_args
        self.no_launch = no_launch
        self.worker: InstallWorker | None = None

        root = self.content_layout
        root.setContentsMargins(24, 24, 24, 24)

        card = QWidget()
        card.setProperty("panel", True)
        root.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self.title_label = QLabel("Установщик LOTA")
        self.title_label.setProperty("title", True)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("Скачаем launcher и updater, а затем сразу запустим игру.")
        self.subtitle_label.setProperty("installerText", True)
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.subtitle_label)

        self.target_label = QLabel(f"Папка установки: {self.install_dir}")
        self.target_label.setProperty("installerMeta", True)
        self.target_label.setWordWrap(True)
        self.target_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.target_label)

        self.status_label = QLabel("Готов к установке")
        self.status_label.setProperty("installerText", True)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setProperty("installerProgress", True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.style().polish(self.progress_bar)
        layout.addWidget(self.progress_bar)

        self.error_label = QTextEdit()
        self.error_label.setProperty("installerErrorBox", True)
        self.error_label.setReadOnly(True)
        self.error_label.setAcceptRichText(False)
        self.error_label.setLineWrapMode(QTextEdit.WidgetWidth)
        self.error_label.setFixedHeight(84)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addStretch()

        self.install_button = QPushButton("Скачать и запустить")
        self.install_button.setProperty("primary", True)
        self.install_button.setProperty("installerPrimary", True)
        self.install_button.style().polish(self.install_button)
        self.install_button.clicked.connect(self.start_install)
        layout.addWidget(self.install_button)

    def start_install(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.error_label.hide()
        self.progress_bar.setValue(0)
        self.status_label.setText("Подготавливаем установку...")
        self.install_button.setEnabled(False)
        self.install_button.setText("Устанавливаем...")

        worker = InstallWorker(self.install_dir, self.channel, self.launcher_args, self.no_launch)
        self.worker = worker
        worker.progress.connect(self._on_progress)
        worker.status.connect(self._on_status)
        worker.failed.connect(self._on_failed)
        worker.finished_ok.connect(self._on_finished)
        worker.start()

    def _on_progress(self, value: int) -> None:
        self.progress_bar.setValue(max(0, min(100, value)))

    def _on_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _on_failed(self, message: str) -> None:
        self.error_label.setPlainText(message or "Не удалось завершить установку.")
        self.error_label.show()
        self.status_label.setText("Установка прервана")
        self.install_button.setEnabled(True)
        self.install_button.setText("Повторить")

    def _on_finished(self) -> None:
        if self.no_launch:
            self.status_label.setText("Установка завершена")
            self.install_button.setEnabled(True)
            self.install_button.setText("Готово")
            self.show_toast("Файлы установлены")
            return

        self.status_label.setText("Launcher запущен. Закрываем установщик...")
        self.progress_bar.setValue(100)
        self.show_toast("Launcher запущен")
        QTimer.singleShot(900, self.close)


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def _resource_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def _build_app_font(font_family: str, pixel_size: int) -> QFont:
    font = QFont(font_family)
    font.setPixelSize(pixel_size)
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


def _setup_app_style(app: QApplication) -> None:
    asset_dir = _resource_dir() / "assets"
    logo_path = asset_path("logo.ico") if sys.platform.startswith("win") else asset_path("logo.png")
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))
    font_path = asset_dir / "fonts" / "Monocraft-ttf" / "Monocraft.ttf"
    if font_path.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(_build_app_font(families[0], 14))
    app.setStyleSheet(build_app_qss(str(asset_dir)))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install Lota launcher runtime")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    parser.add_argument("--install-dir", default="")
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("launcher_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    set_windows_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.Round
    )
    app = QApplication(argv)
    _setup_app_style(app)

    window = InstallerWindow(
        resolve_install_dir(args.install_dir),
        args.channel,
        args.launcher_args,
        args.no_launch,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
