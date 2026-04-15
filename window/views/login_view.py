from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from window.i18n import t
from window.ui_layout import apply_layout_overrides


class RegisterLinksOverlay(QFrame):
    def __init__(self, parent: QWidget, on_auth_success, show_toast):
        super().__init__(parent)
        self._on_auth_success = on_auth_success
        self._show_toast = show_toast
        self._request_worker = None
        self._link_token = ""
        self._telegram_url = ""

        self.setProperty("registerOverlay", True)
        self.setVisible(False)

        asset_dir = Path(__file__).resolve().parents[2] / "assets"

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(28, 28, 28, 28)
        self.root_layout.addStretch()

        self.panel = QFrame()
        self.panel.setProperty("registerPanel", True)
        self.panel.setMaximumWidth(420)
        self.panel.setMinimumWidth(360)
        self.root_layout.addWidget(self.panel, alignment=Qt.AlignHCenter)
        self.root_layout.addStretch()

        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(22, 22, 22, 18)
        self.panel_layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("caption", True)
        self.subtitle_label.setWordWrap(True)
        self.stack = QStackedWidget()
        self.panel_layout.addWidget(self.title_label)
        self.panel_layout.addWidget(self.subtitle_label)
        self.panel_layout.addWidget(self.stack)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px;")
        self.error_label.hide()
        self.panel_layout.addWidget(self.error_label)

        self.close_button = QPushButton()
        self.close_button.setProperty("secondary", True)
        self.close_button.style().polish(self.close_button)
        self.panel_layout.addWidget(self.close_button)

        self.choice_page = QWidget()
        choice_layout = QVBoxLayout(self.choice_page)
        choice_layout.setContentsMargins(0, 0, 0, 0)
        choice_layout.setSpacing(12)
        self.telegram_button = QPushButton()
        self.telegram_button.setProperty("registerService", "telegram")
        self.telegram_button.setProperty("authButton", True)
        self.telegram_button.setProperty("authPlatformButton", True)
        self.telegram_button.setIcon(QIcon(str(asset_dir / "Telegram_logo.png")))
        self.telegram_button.setIconSize(QSize(18, 18))
        self.telegram_button.setCursor(Qt.PointingHandCursor)
        choice_layout.addWidget(self.telegram_button)
        self.stack.addWidget(self.choice_page)

        self.wait_page = QWidget()
        wait_layout = QVBoxLayout(self.wait_page)
        wait_layout.setContentsMargins(0, 0, 0, 0)
        self.open_link_button = QPushButton()
        self.open_link_button.setProperty("primary", True)
        self.open_link_button.setProperty("authButton", True)
        self.open_link_button.style().polish(self.open_link_button)
        wait_layout.addWidget(self.open_link_button)
        self.copy_link_button = QPushButton()
        self.copy_link_button.setProperty("secondary", True)
        self.copy_link_button.setProperty("authButton", True)
        self.copy_link_button.style().polish(self.copy_link_button)
        wait_layout.addWidget(self.copy_link_button)
        self.stack.addWidget(self.wait_page)

        self.complete_page = QWidget()
        complete_layout = QVBoxLayout(self.complete_page)
        complete_layout.setContentsMargins(0, 0, 0, 0)
        complete_layout.setSpacing(10)
        self.verified_label = QLabel()
        self.verified_label.setProperty("caption", True)
        self.verified_label.setWordWrap(True)
        complete_layout.addWidget(self.verified_label)
        self.username_input = QLineEdit()
        self.username_input.setProperty("authField", True)
        self.username_input.setMinimumHeight(30)
        complete_layout.addWidget(self.username_input)
        self.complete_button = QPushButton()
        self.complete_button.setProperty("primary", True)
        self.complete_button.setProperty("authButton", True)
        self.complete_button.setMinimumHeight(36)
        self.complete_button.style().polish(self.complete_button)
        complete_layout.addWidget(self.complete_button)
        self.stack.addWidget(self.complete_page)

        self.close_button.clicked.connect(self.hide)
        self.apply_language()

    def set_busy(self, busy: bool) -> None:
        self.telegram_button.setEnabled(not busy)
        self.copy_link_button.setEnabled(not busy and bool(self._telegram_url))
        self.open_link_button.setEnabled(not busy and bool(self._telegram_url))
        self.complete_button.setEnabled(not busy and bool(self._link_token))

    def show_choice_page(self) -> None:
        self.stack.setCurrentWidget(self.choice_page)

    def show_wait_page(self) -> None:
        self.stack.setCurrentWidget(self.wait_page)

    def show_complete_page(self) -> None:
        self.stack.setCurrentWidget(self.complete_page)
        self.username_input.setFocus()

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def hide_error(self) -> None:
        self.error_label.hide()

    def copy_telegram_link_to_clipboard(self) -> None:
        if self._telegram_url:
            QApplication.clipboard().setText(self._telegram_url)

    def apply_language(self):
        self.title_label.setText(t("register_links_title"))
        self.subtitle_label.clear()
        self.subtitle_label.hide()
        self.telegram_button.setText(t("register_telegram"))
        self.open_link_button.setText(t("register_open_link"))
        self.copy_link_button.setText(t("register_copy_link"))
        self.verified_label.setText(t("register_verified_text"))
        self.username_input.setPlaceholderText(t("register_username_placeholder"))
        self.complete_button.setText(t("register_complete_button"))
        self.close_button.setText(t("btn_close"))
        apply_layout_overrides(self, "register_overlay")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.panel.geometry().contains(event.position().toPoint()):
            self.hide()
            event.accept()
            return
        super().mousePressEvent(event)


class LoginView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(24, 20, 24, 20)
        self.root_layout.addStretch()

        self.card = QWidget()
        self.card.setProperty("panel", True)
        self.card.setMaximumWidth(384)
        self.root_layout.addWidget(self.card, alignment=Qt.AlignHCenter)
        self.root_layout.addStretch()

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(22, 20, 22, 18)
        self.card_layout.setSpacing(8)

        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.subtitle_label = QLabel()
        self.subtitle_label.setProperty("caption", True)
        self.subtitle_label.setWordWrap(True)
        self.card_layout.addWidget(self.title_label)
        self.card_layout.addWidget(self.subtitle_label)

        self.username_input = QLineEdit()
        self.username_input.setProperty("authField", True)
        self.card_layout.addWidget(self.username_input)

        self.code_input = QLineEdit()
        self.code_input.setProperty("authField", True)
        self.card_layout.addWidget(self.code_input)

        self.card_layout.addSpacing(4)
        self.login_button = QPushButton()
        self.login_button.setProperty("primary", True)
        self.login_button.setProperty("authButton", True)
        self.login_button.style().polish(self.login_button)
        self.card_layout.addWidget(self.login_button)

        self.register_button = QPushButton()
        self.register_button.setProperty("secondary", True)
        self.register_button.setProperty("compact", True)
        self.register_button.setProperty("authCompactButton", True)
        self.register_button.style().polish(self.register_button)
        self.card_layout.addWidget(self.register_button, alignment=Qt.AlignHCenter)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; padding-top: 6px;")
        self.error_label.hide()
        self.card_layout.addWidget(self.error_label)
        self.card_layout.addStretch()
        apply_layout_overrides(self, "login")

    def set_login_busy(self, busy: bool) -> None:
        self.username_input.setEnabled(not busy)
        self.code_input.setEnabled(not busy)
        self.login_button.setEnabled(not busy)
        self.register_button.setEnabled(not busy)

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def hide_error(self) -> None:
        self.error_label.hide()

    def apply_language(self):
        self.title_label.setText(t("login_title"))
        self.subtitle_label.setText(t("login_subtitle"))
        self.login_button.setText(t("login_button"))
        self.username_input.setPlaceholderText(t("login_placeholder_username"))
        self.code_input.setPlaceholderText(t("login_placeholder_code"))
        self.register_button.setText(t("register_button"))
        apply_layout_overrides(self, "login")
