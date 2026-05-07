from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from window.i18n import t
from window.views.account_view import RANK_GRADIENTS, flowing_gradient


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _format_dt(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return text


class AddFriendDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(t("friends_add_dialog_title"))
        self.setObjectName("RootWindow")
        self.setFixedSize(420, 220)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        self.card = QFrame()
        self.card.setProperty("panel2", True)
        root.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setProperty("section", True)
        layout.addWidget(self.title_label)

        self.username_input = QLineEdit()
        self.username_input.setProperty("settingsField", True)
        layout.addWidget(self.username_input)

        self.status_label = QLabel("")
        self.status_label.setProperty("caption", True)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_cancel = QPushButton()
        self.btn_cancel.setProperty("secondary", True)
        self.btn_confirm = QPushButton()
        self.btn_confirm.setProperty("primary", True)

        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_confirm)
        layout.addLayout(buttons)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_confirm.clicked.connect(self.accept)
        self.username_input.returnPressed.connect(self.accept)
        self.apply_language()

    def apply_language(self) -> None:
        self.setWindowTitle(t("friends_add_dialog_title"))
        self.title_label.setText(t("friends_add_dialog_title"))
        self.username_input.setPlaceholderText(t("friends_search_placeholder"))
        self.btn_cancel.setText(t("friends_add_dialog_cancel"))
        self.btn_confirm.setText(t("friends_add_dialog_confirm"))

    def username(self) -> str:
        return self.username_input.text().strip()

    def set_busy(self, busy: bool) -> None:
        self.username_input.setEnabled(not busy)
        self.btn_cancel.setEnabled(not busy)
        self.btn_confirm.setEnabled(not busy)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)


RANK_TAGS = {
    1: "Б",
    2: "A",
    3: "И",
    4: "Т",
    5: "Eld",
    6: "Jr",
    7: "Tm",
    8: "Drk",
    9: "Own",
}


class RankTagLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._colors: tuple[QColor, QColor] | None = None
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(28)
        self.setMinimumWidth(42)

    def set_rank_level(self, sub_level: int) -> None:
        colors = RANK_GRADIENTS.get(sub_level)
        self._colors = tuple(QColor(color) for color in colors) if colors else None
        if self._colors:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 1) % 10000
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)

        if self._colors:
            gradient = flowing_gradient(rect, self._colors, self._phase)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(rect, 8, 8)
            text_color = QColor("#111827")
            max_luminance = max(
                0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
                for color in self._colors
            )
            if max_luminance <= 165:
                text_color = QColor("#FFFFFF")
            painter.setPen(text_color)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 20))
            painter.drawRoundedRect(rect, 8, 8)
            painter.setPen(QColor("#E5E7EB"))

        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())


class FriendCard(QFrame):
    def __init__(self, entry: dict, *, section: str, handlers: dict[str, object], parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("friendsCard", True)
        self.entry = dict(entry or {})
        self.user = self.entry.get("user") if isinstance(self.entry.get("user"), dict) else {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)

        sub_level = int(self.user.get("sub_level") or 0)
        self.rank_tag = RankTagLabel(RANK_TAGS.get(sub_level, "—"))
        self.rank_tag.setProperty("friendsRankTag", True)
        self.rank_tag.set_rank_level(sub_level)
        header.addWidget(self.rank_tag, 0, Qt.AlignTop)

        self.username_label = QLabel(str(self.user.get("username") or "—"))
        self.username_label.setProperty("friendsUserTitle", True)
        header.addWidget(self.username_label, 1, Qt.AlignVCenter)

        layout.addLayout(header)

        joined_at = _format_dt(str(self.user.get("joined_at") or self.entry.get("joined_at") or ""))
        created_at = _format_dt(str(self.entry.get("created_at") or ""))
        date_text = joined_at or created_at or "—"
        self.meta_label = QLabel(date_text)
        self.meta_label.setProperty("friendsDateMeta", True)
        self.meta_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.meta_label)

        actions = QHBoxLayout()
        actions.addStretch()
        self.buttons: list[QPushButton] = []
        for button in self._build_buttons(section, handlers):
            actions.addWidget(button)
            self.buttons.append(button)
        layout.addLayout(actions)

    def _build_buttons(self, section: str, handlers: dict[str, object]) -> list[QPushButton]:
        result: list[QPushButton] = []
        user_id = int(self.user.get("id") or 0)
        if section == "friends":
            btn = QPushButton(t("friends_remove"))
            btn.setProperty("secondary", True)
            result.append(self._bind_payload(btn, handlers.get("remove"), user_id))
        elif section == "incoming":
            accept_btn = QPushButton(t("friends_accept"))
            accept_btn.setProperty("confirm", True)
            decline_btn = QPushButton(t("friends_decline"))
            decline_btn.setProperty("secondary", True)
            result.append(self._bind_payload(accept_btn, handlers.get("accept"), user_id))
            result.append(self._bind_payload(decline_btn, handlers.get("decline"), user_id))
        elif section == "outgoing":
            btn = QPushButton(t("friends_cancel"))
            btn.setProperty("secondary", True)
            result.append(self._bind_payload(btn, handlers.get("remove"), user_id))
        return result

    def _bind_payload(self, button: QPushButton, callback, user_id: int) -> QPushButton:
        if callable(callback):
            button.clicked.connect(lambda _checked=False, value=user_id: callback(value))
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons:
            button.setEnabled(not busy)


class FriendSection(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("friendsSection", True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setProperty("section", True)
        header.addWidget(self.title_label)

        self.count_label = QLabel("0")
        self.count_label.setProperty("friendsCountBadge", True)
        self.count_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.count_label, 0, Qt.AlignRight)
        layout.addLayout(header)

        self.items_layout = QVBoxLayout()
        self.items_layout.setSpacing(10)
        layout.addLayout(self.items_layout)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_items(self, widgets: list[QWidget], empty_text: str) -> None:
        _clear_layout(self.items_layout)
        self.count_label.setText(str(len(widgets)))
        if not widgets:
            empty_label = QLabel(empty_text)
            empty_label.setProperty("caption", True)
            empty_label.setWordWrap(True)
            self.items_layout.addWidget(empty_label)
            return
        for widget in widgets:
            self.items_layout.addWidget(widget)


class FriendsView(QWidget):
    MODE_FRIENDS = "friends"
    MODE_REQUESTS = "requests"

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._tab_anim = None
        self._build_ui()
        self.apply_language()
        self.set_mode(self.MODE_FRIENDS)

    def _build_ui(self) -> None:
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(24, 24, 24, 24)
        self.root_layout.setSpacing(20)

        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.root_layout.addWidget(self.left_scroll, 1)

        self.left_widget = QWidget()
        self.left_widget.setProperty("panel", True)
        self.left_scroll.setWidget(self.left_widget)

        self.left_layout = QVBoxLayout(self.left_widget)
        self.left_layout.setContentsMargins(24, 24, 24, 24)
        self.left_layout.setSpacing(14)

        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.left_layout.addWidget(self.title_label)

        self.tab_title = QLabel()
        self.tab_title.setProperty("section", True)
        self.left_layout.addWidget(self.tab_title)

        self.content_stack = QStackedWidget()
        self.left_layout.addWidget(self.content_stack, 1)

        self.friends_page = QWidget()
        self.friends_page_layout = QVBoxLayout(self.friends_page)
        self.friends_page_layout.setContentsMargins(0, 0, 0, 0)
        self.friends_page_layout.setSpacing(14)
        self.friends_section = FriendSection("")
        self.friends_page_layout.addWidget(self.friends_section)
        self.friends_page_layout.addStretch()
        self.content_stack.addWidget(self.friends_page)

        self.requests_page = QWidget()
        self.requests_page_layout = QVBoxLayout(self.requests_page)
        self.requests_page_layout.setContentsMargins(0, 0, 0, 0)
        self.requests_page_layout.setSpacing(14)
        self.incoming_section = FriendSection("")
        self.outgoing_section = FriendSection("")
        self.requests_page_layout.addWidget(self.incoming_section)
        self.requests_page_layout.addWidget(self.outgoing_section)
        self.requests_page_layout.addStretch()
        self.content_stack.addWidget(self.requests_page)

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.setProperty("panel2", True)
        self.root_layout.addWidget(self.sidebar, 0)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(18, 20, 18, 18)
        self.sidebar_layout.setSpacing(12)

        self.sidebar_title = QLabel()
        self.sidebar_title.setProperty("section", True)
        self.sidebar_layout.addWidget(self.sidebar_title)

        self.btn_show_friends = QPushButton()
        self.btn_show_friends.setProperty("secondary", True)
        self.sidebar_layout.addWidget(self.btn_show_friends)

        self.btn_show_requests = QPushButton()
        self.btn_show_requests.setProperty("secondary", True)
        self.sidebar_layout.addWidget(self.btn_show_requests)

        self.btn_open_add_dialog = QPushButton()
        self.btn_open_add_dialog.setProperty("primary", True)
        self.sidebar_layout.addWidget(self.btn_open_add_dialog)

        self.sidebar_layout.addStretch()

        self.btn_back = QPushButton()
        self.btn_back.setProperty("primary", True)
        self.sidebar_layout.addWidget(self.btn_back)

    def apply_language(self) -> None:
        self.title_label.setText(t("friends_title"))
        self.sidebar_title.setText(t("friends_sidebar_title"))
        self.btn_show_friends.setText(t("friends_nav_friends"))
        self.btn_show_requests.setText(t("friends_nav_requests"))
        self.btn_open_add_dialog.setText(t("friends_nav_add"))
        self.btn_back.setText(t("btn_back"))
        self.friends_section.set_title(t("friends_section_friends"))
        self.incoming_section.set_title(t("friends_section_incoming"))
        self.outgoing_section.set_title(t("friends_section_outgoing"))

    def set_mode(self, mode: str) -> None:
        is_friends = mode == self.MODE_FRIENDS
        target = self.friends_page if is_friends else self.requests_page
        if self.content_stack.currentWidget() is not target:
            self.content_stack.setCurrentWidget(target)
            effect = QGraphicsOpacityEffect(target)
            effect.setOpacity(0.0)
            target.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: target.setGraphicsEffect(None))
            self._tab_anim = anim
            anim.start()
        self.tab_title.setText(t("friends_tab_friends") if is_friends else t("friends_tab_requests"))
        self._set_nav_button_state(self.btn_show_friends, active=is_friends)
        self._set_nav_button_state(self.btn_show_requests, active=not is_friends)

    def _set_nav_button_state(self, button: QPushButton, *, active: bool) -> None:
        button.setProperty("primary", not active)
        button.setProperty("secondary", active)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def set_last_updated(self, text: str) -> None:
        return None

    def set_action_status(self, text: str) -> None:
        return None

    def set_sections(self, friends: list[QWidget], incoming: list[QWidget], outgoing: list[QWidget]) -> None:
        self.friends_section.set_items(friends, t("friends_empty_friends"))
        self.incoming_section.set_items(incoming, t("friends_empty_incoming"))
        self.outgoing_section.set_items(outgoing, t("friends_empty_outgoing"))
