from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from window.i18n import t
from window.skin_render import render_head_pixmap
from window.ui_layout import apply_layout_overrides


class HeadAvatar(QLabel):
    def __init__(self, size: int = 44, parent: QWidget | None = None):
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("avatar", True)

    def refresh(self, reference_rect_height: int | None = None):
        self.setPixmap(render_head_pixmap(self._size, reference_rect_height=reference_rect_height))


class NewsCard(QFrame):
    def __init__(
        self,
        title: str,
        date: str,
        body: str,
        news_type_label: str,
        news_type_key: str,
        on_open,
        payload,
        image: QPixmap | None = None,
    ):
        super().__init__()
        self.setProperty("newsCard", True)
        self._on_open = on_open
        self._payload = payload
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        self.type_label = QLabel(news_type_label)
        self.type_label.setProperty("newsTypeBadge", True)
        self.type_label.setProperty("newsTypeKey", news_type_key)
        self.type_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.type_label)

        self.title_label = QLabel(title or "—")
        self.title_label.setProperty("newsTitle", True)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.date_label = QLabel(date or "")
        self.date_label.setProperty("newsDate", True)
        layout.addWidget(self.date_label)

        self.body_label = QLabel(body or "")
        self.body_label.setProperty("newsBody", True)
        self.body_label.setWordWrap(True)
        self.body_label.setMaximumHeight(96)
        layout.addWidget(self.body_label)

        self.image_label = QLabel()
        self.image_label.setFixedSize(420, 180)
        self.image_label.setProperty("newsImage", True)
        self.image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.image_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.more_btn = QPushButton(t("news_more"))
        self.more_btn.setProperty("ghost", True)
        self.more_btn.clicked.connect(self._handle_open)
        btn_row.addWidget(self.more_btn)
        layout.addLayout(btn_row)

        self.set_image(image)

    def set_image(self, image: QPixmap | None) -> None:
        if image is None or image.isNull():
            self.image_label.clear()
            return
        target = self.image_label.size()
        if target.width() < 2 or target.height() < 2:
            target = self.image_label.sizeHint()
        if target.width() < 2 or target.height() < 2:
            target = QSize(420, 180)
        self.image_label.setPixmap(image.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _handle_open(self):
        if callable(self._on_open):
            self._on_open(self._payload)


class NewsDetailOverlay(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("newsOverlay", True)
        self.setVisible(False)
        self._fade = None

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(40, 40, 40, 40)
        self.root_layout.addStretch()

        self.panel = QFrame()
        self.panel.setProperty("newsDetailPanel", True)
        self.root_layout.addWidget(self.panel)
        self.root_layout.addStretch()

        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(20, 18, 20, 18)
        self.panel_layout.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setProperty("newsDetailTitle", True)
        self.title_label.setWordWrap(True)
        self.panel_layout.addWidget(self.title_label)

        self.date_label = QLabel()
        self.date_label.setProperty("newsDetailDate", True)
        self.panel_layout.addWidget(self.date_label)

        self.body_label = QLabel()
        self.body_label.setProperty("newsDetailText", True)
        self.body_label.setWordWrap(True)
        self.panel_layout.addWidget(self.body_label)

        self.changes_title = QLabel(t("news_changes"))
        self.changes_title.setProperty("newsDetailSection", True)
        self.panel_layout.addWidget(self.changes_title)

        self.changes_label = QLabel()
        self.changes_label.setProperty("newsDetailText", True)
        self.changes_label.setWordWrap(True)
        self.panel_layout.addWidget(self.changes_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.close_btn = QPushButton(t("btn_close"))
        self.close_btn.setProperty("ghost", True)
        self.close_btn.clicked.connect(self.animate_close)
        btn_row.addWidget(self.close_btn)
        self.panel_layout.addLayout(btn_row)
        apply_layout_overrides(self, "news_overlay")

    def set_content(self, title: str, date: str, body: str, changes_text: str):
        self.title_label.setText(title or "—")
        self.date_label.setText(date or "")
        self.body_label.setText(body or "")
        self.changes_title.setVisible(bool(changes_text))
        self.changes_label.setVisible(bool(changes_text))
        self.changes_label.setText(changes_text or "")

    def animate_open(self):
        if self.isVisible():
            return
        self.setGraphicsEffect(QGraphicsOpacityEffect(self))
        self.graphicsEffect().setOpacity(0.0)
        self.show()
        anim = QPropertyAnimation(self.graphicsEffect(), b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._fade = anim
        anim.start()

    def animate_close(self):
        if not self.isVisible():
            return
        self.setGraphicsEffect(QGraphicsOpacityEffect(self))
        self.graphicsEffect().setOpacity(1.0)
        anim = QPropertyAnimation(self.graphicsEffect(), b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: (self.setGraphicsEffect(None), self.hide()))
        self._fade = anim
        anim.start()


class HomeView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._build_ui()
        self.apply_language(False)

    def _build_ui(self) -> None:
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(24, 24, 24, 24)
        self.root_layout.setSpacing(20)

        self.content_panel = QWidget()
        self.content_panel.setProperty("panel", True)
        self.root_layout.addWidget(self.content_panel, stretch=1)

        self.content_layout = QVBoxLayout(self.content_panel)
        self.content_layout.setContentsMargins(24, 24, 24, 24)
        self.content_layout.setSpacing(16)

        self.title_label = QLabel()
        self.title_label.setProperty("title", True)
        self.content_layout.addWidget(self.title_label)

        self.news_title = QLabel()
        self.news_title.setProperty("section", True)
        self.content_layout.addWidget(self.news_title)

        self.news_scroll = QScrollArea()
        self.news_scroll.setWidgetResizable(True)
        self.news_scroll.setFrameShape(QFrame.NoFrame)
        self.news_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.news_scroll.setLayoutDirection(Qt.RightToLeft)
        self.content_layout.addWidget(self.news_scroll, stretch=1)

        self.news_container = QWidget()
        self.news_container.setLayoutDirection(Qt.LeftToRight)
        self.news_scroll.setWidget(self.news_container)
        self.news_box = QVBoxLayout(self.news_container)
        self.news_box.setContentsMargins(0, 0, 0, 0)
        self.news_box.setSpacing(16)

        self.details_overlay = NewsDetailOverlay(self)

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.setProperty("panel2", True)
        self.root_layout.addWidget(self.sidebar, stretch=0)

        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(18, 20, 18, 18)
        self.sidebar_layout.setSpacing(14)

        self.header_label = QLabel()
        self.header_label.setProperty("section", True)
        self.sidebar_layout.addWidget(self.header_label)

        self.btn_play = QPushButton()
        self.btn_play.setProperty("primary", True)
        self.btn_play.style().polish(self.btn_play)

        self.btn_account = QPushButton()
        self.btn_library = QPushButton()
        self.btn_friends = QPushButton()
        self.btn_settings = QPushButton()
        self.btn_exit = QPushButton()

        self.sidebar_layout.addWidget(self.btn_play)

        self.play_status = QLabel("")
        self.play_status.setProperty("caption", True)
        self.play_status.setWordWrap(True)
        self.sidebar_layout.addWidget(self.play_status)

        self.play_progress = QProgressBar()
        self.play_progress.setRange(0, 100)
        self.play_progress.setValue(0)
        self.play_progress.hide()
        self.sidebar_layout.addWidget(self.play_progress)

        self.sidebar_layout.addWidget(self.btn_account)
        self.sidebar_layout.addWidget(self.btn_library)
        self.sidebar_layout.addWidget(self.btn_friends)
        self.sidebar_layout.addWidget(self.btn_settings)
        self.sidebar_layout.addStretch()

        self.profile_card = QWidget()
        self.profile_card.setProperty("panel2", True)
        self.profile_layout = QHBoxLayout(self.profile_card)
        self.profile_layout.setContentsMargins(10, 8, 10, 8)
        self.profile_layout.setSpacing(10)

        self.avatar = HeadAvatar(40)
        self.profile_layout.addWidget(self.avatar)

        self.username_label = QLabel("—")
        self.username_label.setStyleSheet("font-size: 12px; color: #F3E7D6;")
        self.profile_layout.addWidget(self.username_label)
        self.profile_layout.addStretch()

        self.sidebar_layout.addWidget(self.profile_card)
        self.sidebar_layout.addWidget(self.btn_exit)
        apply_layout_overrides(self, "home")

    def apply_language(self, is_mc_running: bool):
        self.title_label.setText(t("home_title"))
        self.news_title.setText(t("news_title"))
        self.header_label.setText(t("nav_header"))
        self.btn_play.setText(t("btn_close") if is_mc_running else t("btn_play"))
        self.btn_account.setText(t("btn_account"))
        self.btn_library.setText(t("btn_library"))
        self.btn_friends.setText(t("btn_friends"))
        self.btn_settings.setText(t("btn_settings"))
        self.btn_exit.setText(t("btn_exit"))
        apply_layout_overrides(self, "home")

    def set_username(self, username: str) -> None:
        self.username_label.setText(username or "—")

    def set_play_running_state(self, running: bool) -> None:
        self.btn_play.setText(t("btn_close") if running else t("btn_play"))
        self.btn_play.setEnabled(True)
        self.btn_play.setProperty("primary", not running)
        self.btn_play.setProperty("secondary", running)
        self.btn_play.style().polish(self.btn_play)

    def set_play_preparing(self):
        self.play_status.setText(t("play_preparing"))
        self.play_progress.setValue(0)
        self.play_progress.show()
        self.btn_play.setEnabled(False)

    def clear_play_feedback(self):
        self.play_status.setText("")
        self.play_progress.hide()

    def show_news_empty(self):
        empty = QLabel(t("news_empty"))
        empty.setProperty("caption", True)
        self.news_box.addWidget(empty)
