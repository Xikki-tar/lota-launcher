import math
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from auth.settings import DEFAULT_STEVE
from window.i18n import t
from window.ui_layout import apply_layout_overrides


RANK_GRADIENTS = {
    1: ("#269ff5", "#005eff"),
    2: ("#fff600", "#9e9300"),
    3: ("#e26bff", "#06ff76"),
    4: ("#c8ff6b", "#9fc1ff"),
    5: ("#d363ff", "#7600b0"),
    6: ("#0e2f29", "#79d8bb"),
    7: ("#00719a", "#5ce8f4"),
    8: ("#6112f4", "#4c168e"),
}


def flowing_gradient(rect, colors: tuple[QColor, QColor], phase: int) -> QLinearGradient:
    angle = math.sin(phase / 60) * 0.25
    cx = rect.center().x()
    cy = rect.center().y()
    length = max(1, rect.width() + rect.height()) * 0.75
    dx = math.cos(angle) * length
    dy = math.sin(angle) * length
    gradient = QLinearGradient(cx - dx, cy - dy, cx + dx, cy + dy)
    gradient.setColorAt(0.0, colors[0])
    gradient.setColorAt(1.0, colors[1])
    return gradient


class GradientNickLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._colors: tuple[QColor, QColor] | None = None
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)
        self.setMinimumHeight(54)

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

        rect = self.rect()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 10))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 10, 10)

        text = self.text()
        if not text:
            return

        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        x = 16
        y = (rect.height() + metrics.ascent() - metrics.descent()) / 2

        if not self._colors:
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(x, 0, -x, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            return

        path = QPainterPath()
        path.addText(x, y, self.font(), text)
        gradient = flowing_gradient(path.boundingRect(), self._colors, self._phase)
        painter.fillPath(path, gradient)


class RankBadgeLabel(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._colors: tuple[QColor, QColor] | None = None
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(45)
        self._timer.timeout.connect(self._tick)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(42)

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

    def _text_color(self) -> QColor:
        if not self._colors:
            return QColor("#E5E7EB")
        max_luminance = max(
            0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
            for color in self._colors
        )
        return QColor("#111827") if max_luminance > 165 else QColor("#FFFFFF")

    def _text_outline_color(self, text_color: QColor) -> QColor:
        is_dark_text = text_color.lightness() < 128
        return QColor(255, 255, 255, 120) if is_dark_text else QColor(0, 0, 0, 130)

    def paintEvent(self, event):
        if not self._colors:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        gradient = flowing_gradient(rect, self._colors, self._phase)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 10, 10)

        text_color = self._text_color()
        painter.setFont(self.font())
        painter.setPen(self._text_outline_color(text_color))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(rect.translated(dx, dy), self.alignment(), self.text())
        painter.setPen(text_color)
        painter.drawText(rect, self.alignment(), self.text())


class SkinViewer(QWidget):
    def __init__(self, skin_path=None, parent=None):
        super().__init__(parent)
        self._skin: QImage | None = None
        self.setMinimumSize(220, 360)
        self.setProperty("panel2", True)
        self.set_skin_path(skin_path)

    def set_skin_path(self, path: str | None):
        img_path = path if path and os.path.exists(path) else DEFAULT_STEVE
        img = QImage(img_path)
        self._skin = None if img.isNull() else img
        self.update()

    def _crop(self, x, y, w, h) -> QImage | None:
        if not self._skin:
            return None
        if self._skin.width() < x + w or self._skin.height() < y + h:
            return None
        return self._skin.copy(x, y, w, h)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        rect = self.rect().adjusted(20, 20, -20, -20)

        if not self._skin:
            painter.setPen(Qt.white)
            painter.drawText(rect, Qt.AlignCenter, t("skin_no_skin"))
            return

        if self._skin.width() < 64 or self._skin.height() < 32:
            pm = QPixmap.fromImage(self._skin).scaled(rect.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
            painter.drawPixmap(rect.center().x() - pm.width() // 2, rect.center().y() - pm.height() // 2, pm)
            return

        head_img = self._crop(8, 8, 8, 8)
        body_img = self._crop(20, 20, 8, 12)
        arm_img = self._crop(44, 20, 4, 12)
        leg_img = self._crop(4, 20, 4, 12)
        has_overlay = self._skin.height() >= 64

        head_ov_img = self._crop(40, 8, 8, 8) if has_overlay else None
        body_ov_img = self._crop(20, 36, 8, 12) if has_overlay else None
        arm_ov_img = self._crop(44, 36, 4, 12) if has_overlay else None
        leg_ov_img = self._crop(4, 36, 4, 12) if has_overlay else None

        if not all([head_img, body_img, arm_img, leg_img]):
            pm = QPixmap.fromImage(self._skin).scaled(rect.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
            painter.drawPixmap(rect.center().x() - pm.width() // 2, rect.center().y() - pm.height() // 2, pm)
            return

        pix_total_h = 8 + 12 + 12
        scale = min(max(1, rect.height() // pix_total_h), 16)
        head_h, body_h, limb_h = 8 * scale, 12 * scale, 12 * scale
        head_w, body_w, limb_w = 8 * scale, 8 * scale, 4 * scale

        model_pm = QPixmap(limb_w + body_w + limb_w, head_h + body_h + limb_h)
        model_pm.fill(Qt.transparent)
        mp = QPainter(model_pm)
        mp.setRenderHint(QPainter.Antialiasing, False)
        mp.setRenderHint(QPainter.SmoothPixmapTransform, False)

        def scale_img(img: QImage | None, w_px: int, h_px: int) -> QPixmap | None:
            if img is None:
                return None
            return QPixmap.fromImage(img).scaled(w_px, h_px, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        head = scale_img(head_img, head_w, head_h)
        body = scale_img(body_img, body_w, body_h)
        arm = scale_img(arm_img, limb_w, limb_h)
        leg = scale_img(leg_img, limb_w, limb_h)

        pad = max(0, int(scale * 0.2))
        head_ov = scale_img(head_ov_img, head_w + 2 * pad, head_h + 2 * pad)
        body_ov = scale_img(body_ov_img, body_w + 2 * pad, body_h + 2 * pad)
        arm_ov = scale_img(arm_ov_img, limb_w + 2 * pad, limb_h + 2 * pad)
        leg_ov = scale_img(leg_ov_img, limb_w + 2 * pad, limb_h + 2 * pad)

        def draw_part(x, y, base_pm: QPixmap, ov_pm: QPixmap | None):
            mp.drawPixmap(x, y, base_pm)
            if ov_pm:
                mp.drawPixmap(x - pad, y - pad, ov_pm)

        x_body = limb_w
        y_body = head_h
        y_leg = head_h + body_h
        draw_part(x_body, 0, head, head_ov)
        draw_part(x_body, y_body, body, body_ov)
        draw_part(0, y_body, arm, arm_ov)
        draw_part(limb_w + body_w, y_body, arm, arm_ov)
        draw_part(x_body, y_leg, leg, leg_ov)
        draw_part(x_body + limb_w, y_leg, leg, leg_ov)
        mp.end()

        x = rect.center().x() - model_pm.width() // 2
        y = rect.center().y() - model_pm.height() // 2
        painter.drawPixmap(x, y, model_pm)


class DiscordLinkDialog(QDialog):
    def __init__(self, discord_url: str, parent=None):
        super().__init__(parent)
        self._command = ""
        self._discord_url = discord_url

        self.setWindowTitle(t("account_discord_link_title"))
        self.setModal(True)
        self.setFixedSize(560, 320)
        self.setObjectName("RootWindow")

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(20, 20, 20, 20)
        self.root_layout.setSpacing(0)

        self.card = QFrame()
        self.card.setProperty("panel2", True)
        self.root_layout.addWidget(self.card)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(20, 20, 20, 20)
        self.card_layout.setSpacing(12)

        self.info_label = QLabel()
        self.info_label.setProperty("caption", True)
        self.info_label.setWordWrap(True)
        self.card_layout.addWidget(self.info_label)

        self.command_label = QLabel("")
        self.command_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.command_label.setWordWrap(True)
        self.command_label.setStyleSheet(
            "color:#F3E7D6; font-size:14px; background-color: #20170F;"
            "border:1px solid #4A3523; border-radius:12px; padding:8px 12px; min-height:24px;"
        )
        self.card_layout.addWidget(self.command_label)

        self.open_button = QPushButton()
        self.open_button.setProperty("secondary", True)
        self.copy_button = QPushButton()
        self.copy_button.setProperty("primary", True)
        self.close_button = QPushButton()
        self.close_button.setProperty("secondary", True)
        for btn in (self.open_button, self.copy_button, self.close_button):
            btn.style().polish(btn)
            self.card_layout.addWidget(btn)
        self.card_layout.addStretch()

        self.open_button.clicked.connect(self._open_discord)
        self.copy_button.clicked.connect(self.copy_command)
        self.close_button.clicked.connect(self.reject)
        self.apply_language()

    def set_command(self, command: str) -> None:
        self._command = str(command or "").strip()
        self.command_label.setText(self._command)

    def copy_command(self):
        if not self._command:
            return
        QApplication.clipboard().setText(self._command)

    def apply_language(self):
        self.info_label.setText(t("account_discord_link_text"))
        self.open_button.setText(t("account_discord_open"))
        self.copy_button.setText(t("account_discord_copy"))
        self.close_button.setText(t("btn_close"))
        apply_layout_overrides(self, "discord_dialog")

    def _open_discord(self):
        QDesktopServices.openUrl(self._discord_url)


class AccountView(QWidget):
    def __init__(self, skin_path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.skin_path = skin_path
        self._build_ui()
        self.apply_language()

    def _build_ui(self) -> None:
        self.root_layout = QHBoxLayout(self)
        self.root_layout.setContentsMargins(24, 24, 24, 24)
        self.root_layout.setSpacing(20)

        self.left_panel = QWidget()
        self.left_panel.setProperty("panel", True)
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(22, 22, 22, 22)
        self.left_layout.setSpacing(10)

        self.profile_label = QLabel()
        self.profile_label.setProperty("section", True)
        self.nick_caption = QLabel()
        self.nick_caption.setProperty("caption", True)
        self.nick_label = GradientNickLabel("—")
        self.nick_label.setStyleSheet(
            "color:#FFFFFF; font-size:24px; font-weight:600;"
            "background-color: rgba(255,255,255,0.04); border-radius:12px; padding:12px 16px;"
        )
        self.rank_caption = QLabel()
        self.rank_caption.setProperty("caption", True)
        self.rank_label = RankBadgeLabel("—")
        self.rank_label.setStyleSheet(
            "color:#E5E7EB; font-size:16px; font-style:italic;"
            "background-color: rgba(255,255,255,0.03); border-radius:12px; padding:10px 16px;"
        )
        self.updates_caption = QLabel()
        self.updates_caption.setProperty("caption", True)
        self.updates_badge = QLabel("—")
        self.updates_badge.setAlignment(Qt.AlignCenter)

        self.left_layout.addWidget(self.profile_label)
        self.left_layout.addSpacing(8)
        self.left_layout.addWidget(self.nick_caption)
        self.left_layout.addWidget(self.nick_label)
        self.left_layout.addSpacing(6)
        self.left_layout.addWidget(self.rank_caption)
        self.left_layout.addWidget(self.rank_label)
        self.left_layout.addSpacing(10)
        self.left_layout.addWidget(self.updates_caption)
        self.left_layout.addWidget(self.updates_badge)
        self.left_layout.addStretch()

        self.center_panel = QWidget()
        self.center_panel.setProperty("panel", True)
        self.center_layout = QVBoxLayout(self.center_panel)
        self.center_layout.setContentsMargins(40, 24, 40, 24)
        self.label_skin = QLabel()
        self.label_skin.setProperty("section", True)
        self.center_layout.addWidget(self.label_skin)
        self.center_layout.addStretch()
        self.skin_viewer = SkinViewer(self.skin_path, self)
        self.center_layout.addWidget(self.skin_viewer, alignment=Qt.AlignHCenter)
        self.center_layout.addStretch()

        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(240)
        self.sidebar.setProperty("panel2", True)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(18, 20, 18, 20)
        self.sidebar_layout.setSpacing(14)

        self.section_label = QLabel()
        self.section_label.setProperty("section", True)
        self.sidebar_layout.addWidget(self.section_label)

        self.btn_change_skin = QPushButton()
        self.btn_link_discord = QPushButton()
        self.btn_link_discord.setFixedHeight(56)
        self.btn_back = QPushButton()
        self.btn_back.setFixedHeight(38)

        self.sidebar_layout.addWidget(self.btn_change_skin)
        self.sidebar_layout.addWidget(self.btn_link_discord)
        self.sidebar_layout.addStretch()
        self.sidebar_layout.addWidget(self.btn_back)

        self.root_layout.addWidget(self.left_panel, stretch=1)
        self.root_layout.addWidget(self.center_panel, stretch=1)
        self.root_layout.addWidget(self.sidebar, stretch=0)
        apply_layout_overrides(self, "account")

    def set_profile(self, username: str, sub_level: int, rank_name: str, is_active: bool) -> None:
        self.nick_label.setText(username)
        self.nick_label.set_rank_level(sub_level)
        self.rank_label.setText(rank_name)
        self.rank_label.set_rank_level(sub_level)
        self.updates_badge.setText(t("account_active") if is_active else t("account_expired"))
        self.updates_badge.setStyleSheet(
            f"color:{'#052e12' if is_active else '#3b0a0a'};"
            f"font-size:14px; font-weight:700; letter-spacing:0.5px;"
            f"background-color:{'#22C55E' if is_active else '#EF4444'};"
            "border-radius:10px; padding:10px 14px;"
        )

    def set_skin_path(self, skin_path: str) -> None:
        self.skin_viewer.set_skin_path(skin_path)

    def apply_language(self):
        self.profile_label.setText(t("account_profile"))
        self.nick_caption.setText(t("account_nick"))
        self.rank_caption.setText(t("account_level"))
        self.updates_caption.setText(t("account_updates"))
        self.label_skin.setText(t("account_skin"))
        self.section_label.setText(t("account_section"))
        self.btn_change_skin.setText(t("btn_change_skin"))
        self.btn_link_discord.setText(t("btn_link_discord").replace(" ", "\n", 1))
        self.btn_back.setText(t("btn_back"))
        apply_layout_overrides(self, "account")
