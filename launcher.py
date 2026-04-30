import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication

from desktop_integration import install_desktop_entry, set_windows_app_user_model_id, windows_hidden_subprocess_kwargs
from auth.auth_storage import get_config_dir, get_data_dir, load_auth_data
from services.login_service import LoginService
from window.chrome import AppWindow, asset_path
from window.controllers.login_controller import LoginController, RegisterOverlayController
from window.i18n import set_language, t
from window.main_window import LauncherWindow
from window.views.login_view import LoginView, RegisterLinksOverlay


SKIP_UPDATER_ARG = "--skip-updater"


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _updater_binary_name() -> str:
    return "updater.exe" if sys.platform.startswith("win") else "updater"


def _updater_path() -> Path:
    return (_runtime_dir() / _updater_binary_name()).resolve()


def _updater_source_path() -> Path:
    return (_runtime_dir() / "updater.py").resolve()


def _launcher_args(argv: list[str]) -> list[str]:
    return [arg for arg in argv[1:] if arg != SKIP_UPDATER_ARG]


def _launch_updater(argv: list[str]) -> bool:
    if SKIP_UPDATER_ARG in argv[1:] or os.getenv("LOTA_LAUNCHER_SKIP_UPDATER", "").strip() == "1":
        return False

    updater_path = _updater_path()
    if updater_path.exists():
        cmd = [str(updater_path), *_launcher_args(argv)]
    elif not getattr(sys, "frozen", False) and _updater_source_path().exists():
        cmd = [sys.executable, str(_updater_source_path()), *_launcher_args(argv)]
    else:
        return False

    try:
        subprocess.Popen(
            cmd,
            cwd=str(_runtime_dir()),
            **windows_hidden_subprocess_kwargs(),
        )
    except Exception:
        return False
    return True


def _refresh_desktop_entry(argv: list[str]) -> None:
    try:
        executable = Path(sys.executable)
        args: list[str] = []
        if Path(argv[0]).suffix == ".py":
            args = [str(Path(argv[0]).resolve())]
        install_desktop_entry(executable, asset_path("logo.ico"), args=args)
    except Exception:
        pass


def _build_app_font(font_family: str, pixel_size: int) -> QFont:
    font = QFont(font_family)
    font.setPixelSize(pixel_size)
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


class LoginWindow(AppWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle(t("app_title_login"))
        self.set_locked_window_size(480, 360)

        self.login_view = LoginView(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.addWidget(self.login_view)

        self.register_overlay = RegisterLinksOverlay(
            self.content,
            on_auth_success=self.open_main_window,
            show_toast=self.show_toast,
        )
        service = LoginService()
        self.register_controller = RegisterOverlayController(
            view=self.register_overlay,
            service=service,
            show_toast=self.show_toast,
            on_auth_success=self.open_main_window,
        )
        self.controller = LoginController(
            view=self.login_view,
            main_window_factory=self.open_main_window,
            service=service,
            show_toast=self.show_toast,
            overlay_controller=self.register_controller,
        )
        self.apply_language()

    def open_main_window(self):
        self.main_window = LauncherWindow(on_auth_invalid=LoginWindow)
        self.main_window.show()
        self.close()

    def apply_language(self):
        self.setWindowTitle(t("app_title_login"))
        self.controller.apply_language()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "register_overlay"):
            self.register_overlay.setGeometry(self.content.rect())

    def closeEvent(self, event):
        if hasattr(self, "controller"):
            self.controller.shutdown()
        super().closeEvent(event)


def main(argv: list[str]) -> int:
    get_config_dir()
    get_data_dir()

    if "--install-desktop" in argv:
        executable = Path(sys.executable)
        args: list[str] = []
        if Path(argv[0]).suffix == ".py":
            args = [str(Path(argv[0]).resolve())]
        desktop_path = install_desktop_entry(executable, asset_path("logo.ico"), args=args)
        if desktop_path:
            print(f"Desktop entry installed: {desktop_path}")
        else:
            print("Desktop entry is not supported on this platform.")
        return 0

    if _launch_updater(argv):
        return 0

    argv = [argv[0], *_launcher_args(argv)]

    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    set_windows_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    app = QApplication(argv)
    asset_dir = asset_path("logo.png").parent
    logo_path = asset_path("logo.ico") if sys.platform.startswith("win") else asset_path("logo.png")
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    font_path = asset_dir / "fonts" / "Monocraft-ttf" / "Monocraft.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(_build_app_font(families[0], 14))

    set_language()
    from window.style import build_app_qss

    app.setStyleSheet(build_app_qss(str(asset_dir)))
    if sys.platform.startswith("win") or sys.platform.startswith("linux"):
        _refresh_desktop_entry(argv)
    auth = load_auth_data()
    start_window = LauncherWindow(on_auth_invalid=LoginWindow) if auth and auth.get("token") else LoginWindow()
    if logo_path.exists():
        start_window.setWindowIcon(QIcon(str(logo_path)))
    start_window.apply_language()
    start_window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
