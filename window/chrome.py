from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget


class AppMessageDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        message: str,
        *,
        kind: str = "info",
        confirm: bool = False,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setProperty("appDialog", True)
        self.setProperty("dialogKind", kind)
        self.setMinimumWidth(440)
        self.setMaximumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        icon = QLabel("!")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(30, 30)
        icon.setProperty("appDialogIcon", True)
        icon.setProperty("dialogKind", kind)
        header.addWidget(icon)

        title_label = QLabel(title or "")
        title_label.setProperty("appDialogTitle", True)
        title_label.setWordWrap(True)
        header.addWidget(title_label, 1)
        root.addLayout(header)

        text = str(message or "")
        if len(text) > 180 or "\n" in text:
            body = QTextEdit()
            body.setReadOnly(True)
            body.setPlainText(text)
            body.setMinimumHeight(120)
            body.setMaximumHeight(220)
            body.setProperty("appDialogTextBox", True)
            root.addWidget(body)
        else:
            body_label = QLabel(text)
            body_label.setWordWrap(True)
            body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            body_label.setProperty("appDialogText", True)
            root.addWidget(body_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if confirm:
            cancel_btn = QPushButton("Нет")
            cancel_btn.setProperty("secondary", True)
            cancel_btn.clicked.connect(self.reject)
            buttons.addWidget(cancel_btn)

            ok_btn = QPushButton("Да")
            ok_btn.setProperty("primary", True)
            ok_btn.clicked.connect(self.accept)
            buttons.addWidget(ok_btn)
        else:
            ok_btn = QPushButton("OK")
            ok_btn.setProperty("primary", True)
            ok_btn.clicked.connect(self.accept)
            buttons.addWidget(ok_btn)
        root.addLayout(buttons)


def show_app_message(parent: QWidget, title: str, message: str, kind: str = "info") -> None:
    AppMessageDialog(parent, title, message, kind=kind, confirm=False).exec()


def ask_app_confirmation(parent: QWidget, title: str, message: str, kind: str = "warning") -> bool:
    return AppMessageDialog(parent, title, message, kind=kind, confirm=True).exec() == QDialog.Accepted


class ToastPopup(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("toastPopup", True)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self.label = QLabel("")
        self.label.setProperty("toastLabel", True)
        layout.addWidget(self.label)
class WindowTitleBar(QFrame):
    def __init__(self, host: QWidget):
        super().__init__(host)
        self._host = host
        self._drag_offset = None
        self._drag_active = False
        self._maximize_enabled = True
        self.setProperty("windowTitleBar", True)
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, -5, 6, 9)
        layout.setSpacing(4)

        self.title_label = QLabel(host.windowTitle() or "")
        self.title_label.setProperty("windowTitleLabel", True)
        self.title_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)
        layout.addStretch()

        self.min_btn = QPushButton("-")
        self.max_btn = QPushButton("[]")
        self.close_btn = QPushButton("X")

        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setProperty("windowControl", True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(24, 18)
            layout.addWidget(btn)

        self.close_btn.setProperty("windowClose", True)

        self.min_btn.clicked.connect(host.showMinimized)
        self.max_btn.clicked.connect(self._toggle_maximized)
        self.close_btn.clicked.connect(host.close)
        self._sync_state()

    def set_title(self, title: str):
        self.title_label.setText(title or "")

    def _toggle_maximized(self):
        if not self._maximize_enabled:
            return
        if self._host.isMaximized():
            self._host.showNormal()
        else:
            self._host.showMaximized()
        self._sync_state()

    def _sync_state(self):
        self.max_btn.setText("o" if self._host.isMaximized() else "[]")
        self.max_btn.setEnabled(self._maximize_enabled)
        self.max_btn.setVisible(self._maximize_enabled)

    def set_maximize_enabled(self, enabled: bool):
        self._maximize_enabled = enabled
        self._sync_state()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._host.frameGeometry().topLeft()
            self._drag_active = True
            window_handle = self._host.windowHandle()
            if window_handle is not None:
                try:
                    if window_handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and self._drag_offset is not None and event.buttons() & Qt.LeftButton and not self._host.isMaximized():
            self._host.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self._drag_active = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and self._maximize_enabled:
            self._toggle_maximized()
        super().mouseDoubleClickEvent(event)


class AppWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = WindowTitleBar(self)
        root.addWidget(self.title_bar)

        self.content = QWidget()
        self.content.setProperty("windowContent", True)
        root.addWidget(self.content, 1)

        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

        self._toast = ToastPopup(self)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._toast.hide)

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        if hasattr(self, "title_bar"):
            self.title_bar.set_title(title)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar._sync_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_toast") and self._toast.isVisible():
            self._position_toast()

    def _position_toast(self):
        if not hasattr(self, "_toast"):
            return
        self._toast.adjustSize()
        margin = 16
        x = max(margin, self.width() - self._toast.width() - margin)
        y = self.title_bar.height() + margin
        self._toast.move(x, y)

    def show_toast(self, text: str, duration_ms: int = 2600):
        if not text:
            return
        self._toast.label.setText(text)
        self._position_toast()
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(duration_ms)

    def set_locked_window_size(self, width: int, height: int):
        self._apply_locked_window_size(width, height)
        if hasattr(self, "title_bar"):
            self.title_bar.set_maximize_enabled(False)

    def set_launcher_window_size(self, width: int, height: int):
        self._apply_locked_window_size(width, height)

    def fit_launcher_window_to_content(self, *, min_width: int = 0, min_height: int = 0):
        target = self.sizeHint()
        width = max(target.width(), min_width or self.width())
        height = max(target.height(), min_height or self.height())
        self._apply_locked_window_size(width, height)

    def _apply_locked_window_size(self, width: int, height: int):
        self.setMinimumSize(width, height)
        self.setMaximumSize(width, height)
        self.resize(width, height)
