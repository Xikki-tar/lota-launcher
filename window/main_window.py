from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QStackedWidget, QWidget

from auth.auth_service import AuthService
from window.account_window import AccountWindow
from window.chrome import AppWindow, ask_app_confirmation
from window.controllers.home_controller import HomeController
from window.friends_window import FriendsWindow
from window.i18n import t
from window.library_window import LibraryWindow
from window.settings_window import SettingsWindow
from window.views.home_view import HomeView


class AuthRefreshWorker(QThread):
    done = Signal(bool)

    def run(self):
        ok = AuthService.refresh()
        self.done.emit(ok)


class HomePage(HomeView):
    def __init__(self, main_window: "LauncherWindow"):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.controller = HomeController(self, main_window)

    def apply_language(self, is_mc_running: bool = False):
        if hasattr(self, "controller"):
            self.controller.apply_language()
            return
        super().apply_language(is_mc_running)

    def refresh_profile(self):
        self.controller.refresh_profile()

    def refresh_news_background(self):
        self.controller.refresh_news_background()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.controller.resize_event()


class LauncherWindow(AppWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("RootWindow")
        self.setWindowTitle(t("app_title_main"))
        self.set_locked_window_size(960, 640)

        self.stack = QStackedWidget()
        self.content_layout.addWidget(self.stack)

        self.home_page = HomePage(self)
        self.settings_page = SettingsWindow(self)
        self.library_page = LibraryWindow(self)
        self.account_page = AccountWindow(self)
        self.friends_page = FriendsWindow(self)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.library_page)
        self.stack.addWidget(self.account_page)
        self.stack.addWidget(self.friends_page)
        self.stack.setCurrentWidget(self.home_page)

        self._anim = None
        self._auth_refresh_worker = None
        self._closing = False
        self._close_confirmed = False
        self._auth_refresh_timer = QTimer(self)
        self._auth_refresh_timer.setInterval(5 * 60 * 1000)
        self._auth_refresh_timer.timeout.connect(self.refresh_auth_background)

        self.apply_language()
        QTimer.singleShot(0, self.refresh_auth_background)
        self._auth_refresh_timer.start()

    def _animate_to(self, widget: QWidget):
        if self.stack.currentWidget() is widget:
            return
        effect = QGraphicsOpacityEffect(self.stack)
        self.stack.setGraphicsEffect(effect)
        effect.setOpacity(0.0)
        self.stack.setCurrentWidget(widget)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(320)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.finished.connect(lambda: self.stack.setGraphicsEffect(None))
        self._anim = anim
        anim.start()

    def show_settings(self):
        self.settings_page.refresh()
        self._animate_to(self.settings_page)

    def show_account(self):
        self.account_page.refresh()
        self.refresh_auth_background()
        self._animate_to(self.account_page)

    def show_friends(self):
        self.friends_page.refresh()
        self._animate_to(self.friends_page)

    def show_library(self):
        self.library_page.refresh()
        self._animate_to(self.library_page)

    def show_home(self):
        self.home_page.refresh_profile()
        self._animate_to(self.home_page)

    def apply_language(self):
        self.setWindowTitle(t("app_title_main"))
        self.home_page.apply_language()
        self.settings_page.apply_language()
        self.library_page.apply_language()
        self.account_page.apply_language()
        self.friends_page.controller.apply_language()

    def refresh_auth_background(self):
        if self._closing:
            return
        if self._auth_refresh_worker and self._auth_refresh_worker.isRunning():
            return
        worker = AuthRefreshWorker(self)
        self._auth_refresh_worker = worker
        worker.done.connect(self._on_auth_refreshed)
        worker.finished.connect(lambda: self._clear_auth_refresh_worker(worker))
        worker.start()

    def _on_auth_refreshed(self, _ok: bool):
        if self._closing:
            return
        self.home_page.refresh_profile()
        self.account_page.refresh()

    def _clear_auth_refresh_worker(self, worker) -> None:
        if self._auth_refresh_worker is worker:
            self._auth_refresh_worker = None

    def on_exit_clicked(self):
        if ask_app_confirmation(self, t("exit_title"), t("exit_text")):
            self._close_confirmed = True
            QApplication.instance().quit()

    def closeEvent(self, event):
        if not self._close_confirmed:
            if not ask_app_confirmation(self, t("exit_title"), t("exit_text")):
                event.ignore()
                return
            self._close_confirmed = True
        self._closing = True
        self._auth_refresh_timer.stop()
        if hasattr(self, "home_page"):
            self.home_page.controller.shutdown()
        if hasattr(self, "library_page"):
            self.library_page.controller.shutdown()
        if hasattr(self, "friends_page"):
            self.friends_page.controller.shutdown()
        if self._auth_refresh_worker and self._auth_refresh_worker.isRunning():
            self._auth_refresh_worker.wait()
        if not self._auth_refresh_worker or not self._auth_refresh_worker.isRunning():
            self._auth_refresh_worker = None
        super().closeEvent(event)
