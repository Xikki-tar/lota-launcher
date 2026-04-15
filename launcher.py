import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QApplication

from auth.auth_storage import get_config_dir, get_data_dir, load_auth_data
from services.login_service import LoginService
from window.chrome import AppWindow
from window.controllers.login_controller import LoginController, RegisterOverlayController
from window.i18n import set_language, t
from window.main_window import LauncherWindow
from window.views.login_view import LoginView, RegisterLinksOverlay


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
        self.main_window = LauncherWindow()
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

    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.Round)

    app = QApplication(argv)
    base_dir = Path(__file__).resolve().parent
    asset_dir = base_dir / "assets"

    font_path = asset_dir / "fonts" / "Monocraft-ttf" / "Monocraft.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id != -1:
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(_build_app_font(families[0], 14))

    set_language()
    from window.style import build_app_qss

    app.setStyleSheet(build_app_qss(str(asset_dir)))
    auth = load_auth_data()
    start_window = LauncherWindow() if auth and auth.get("token") else LoginWindow()
    start_window.apply_language()
    start_window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
