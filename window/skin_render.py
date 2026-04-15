from __future__ import annotations

import math

from PySide6.QtGui import QImage, QPixmap, QPainter
from PySide6.QtCore import Qt, QRectF

from auth.auth_storage import get_skin_file
from auth.settings import DEFAULT_STEVE


def _resolve_skin_path(skin_path: str | None = None) -> str:
    if skin_path:
        img = QImage(skin_path)
        if not img.isNull():
            return skin_path
    fallback = str(get_skin_file())
    if fallback:
        img = QImage(fallback)
        if not img.isNull():
            return fallback
    return DEFAULT_STEVE


def render_head_pixmap(
    size: int,
    skin_path: str | None = None,
    reference_rect_height: int | None = None,
) -> QPixmap:
    img_path = _resolve_skin_path(skin_path)
    img = QImage(img_path)
    if img.isNull():
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        return pm

    if img.width() < 16 or img.height() < 16:
        return QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)

    def crop(x: int, y: int, w: int, h: int) -> QImage | None:
        if img.width() < x + w or img.height() < y + h:
            return None
        return img.copy(x, y, w, h)

    base = crop(8, 8, 8, 8)
    if base is None:
        return QPixmap.fromImage(img).scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation)

    pix_total_h = 32
    if reference_rect_height is None:
        target_rect_h = max(1, int(size * (pix_total_h / 8)))
        reference_rect_height = target_rect_h
    scale = max(1, reference_rect_height // pix_total_h)
    scale = min(scale, 16)

    head_w = 8 * scale
    pad = max(0, int(scale * 0.4))
    extra = max(0.0, scale * 0.4)

    head = QPixmap.fromImage(base).scaled(head_w, head_w, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    canvas_size = int(math.ceil(head_w + 2 * pad + 2 * extra))
    composed = QPixmap(canvas_size, canvas_size)
    composed.fill(Qt.transparent)

    p = QPainter(composed)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)
    p.drawPixmap(
        QRectF(pad + extra, pad + extra, head_w, head_w),
        head,
        QRectF(0, 0, head.width(), head.height()),
    )

    if img.height() >= 64:
        overlay = crop(40, 8, 8, 8)
        if overlay:
            ov = QPixmap.fromImage(overlay).scaled(
                int(math.ceil(head_w + 2 * pad + 2 * extra)),
                int(math.ceil(head_w + 2 * pad + 2 * extra)),
                Qt.IgnoreAspectRatio,
                Qt.FastTransformation,
            )
            p.drawPixmap(
                QRectF(0, 0, head_w + 2 * pad + 2 * extra, head_w + 2 * pad + 2 * extra),
                ov,
                QRectF(0, 0, ov.width(), ov.height()),
            )

    p.end()

    if composed.size() != (size, size):
        composed = composed.scaled(size, size, Qt.IgnoreAspectRatio, Qt.FastTransformation)

    return composed
