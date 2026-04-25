from __future__ import annotations

import math

from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtCore import Qt, QRectF

from auth.auth_storage import get_skin_file, load_skin_model
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


def render_skin_model_pixmap(
    target_width: int,
    target_height: int,
    skin_path: str | None = None,
    *,
    margin: int = 20,
    model: str | None = None,
) -> QPixmap:
    width = max(1, int(target_width or 1))
    height = max(1, int(target_height or 1))
    margin = max(0, int(margin))

    img_path = _resolve_skin_path(skin_path)
    img = QImage(img_path)
    if img.isNull():
        pm = QPixmap(width, height)
        pm.fill(Qt.transparent)
        return pm

    if img.width() < 64 or img.height() < 32:
        return QPixmap.fromImage(img).scaled(width, height, Qt.KeepAspectRatio, Qt.FastTransformation)

    def crop(x: int, y: int, w: int, h: int) -> QImage | None:
        if img.width() < x + w or img.height() < y + h:
            return None
        return img.copy(x, y, w, h)

    def mirror_img(source: QImage | None) -> QImage | None:
        if source is None:
            return None
        return source.mirrored(True, False)

    head_img = crop(8, 8, 8, 8)
    body_img = crop(20, 20, 8, 12)
    has_overlay = img.height() >= 64

    def scale_img(source: QImage | None, w_px: int, h_px: int) -> QPixmap | None:
        if source is None:
            return None
        return QPixmap.fromImage(source).scaled(w_px, h_px, Qt.IgnoreAspectRatio, Qt.FastTransformation)

    resolved_model = str(model or load_skin_model() or "classic").strip().lower()
    if resolved_model not in {"classic", "slim"}:
        resolved_model = "classic"
    arm_tex_w = 3 if resolved_model == "slim" and has_overlay else 4

    right_arm_img = crop(44, 20, arm_tex_w, 12)
    right_leg_img = crop(4, 20, 4, 12)

    head_ov_img = crop(40, 8, 8, 8) if has_overlay else None
    body_ov_img = crop(20, 36, 8, 12) if has_overlay else None
    right_arm_ov_img = crop(44, 36, arm_tex_w, 12) if has_overlay else None
    right_leg_ov_img = crop(4, 36, 4, 12) if has_overlay else None

    if not all([head_img, body_img, right_arm_img, right_leg_img]):
        return QPixmap.fromImage(img).scaled(width, height, Qt.KeepAspectRatio, Qt.FastTransformation)

    avail_w = max(1, width - 2 * margin)
    avail_h = max(1, height - 2 * margin)
    pix_total_h = 8 + 12 + 12
    pix_total_w = max(4 + 8 + 4, arm_tex_w + 8 + arm_tex_w)
    scale = min(max(1, avail_h // pix_total_h), max(1, avail_w // pix_total_w), 16)

    head_h, body_h, limb_h = 8 * scale, 12 * scale, 12 * scale
    head_w, body_w = 8 * scale, 8 * scale
    arm_w, leg_w = arm_tex_w * scale, 4 * scale
    model_w = max(body_w + leg_w * 2, body_w + arm_w * 2)

    model_pm = QPixmap(model_w, head_h + body_h + limb_h)
    model_pm.fill(Qt.transparent)
    mp = QPainter(model_pm)
    mp.setRenderHint(QPainter.Antialiasing, False)
    mp.setRenderHint(QPainter.SmoothPixmapTransform, False)

    head = scale_img(head_img, head_w, head_h)
    body = scale_img(body_img, body_w, body_h)
    right_arm = scale_img(right_arm_img, arm_w, limb_h)
    right_leg = scale_img(right_leg_img, leg_w, limb_h)
    left_arm = scale_img(mirror_img(right_arm_img), arm_w, limb_h)
    left_leg = scale_img(mirror_img(right_leg_img), leg_w, limb_h)

    pad = max(0, int(scale * 0.2))
    head_ov = scale_img(head_ov_img, head_w + 2 * pad, head_h + 2 * pad)
    body_ov = scale_img(body_ov_img, body_w + 2 * pad, body_h + 2 * pad)
    right_arm_ov = scale_img(right_arm_ov_img, arm_w + 2 * pad, limb_h + 2 * pad)
    right_leg_ov = scale_img(right_leg_ov_img, leg_w + 2 * pad, limb_h + 2 * pad)
    left_arm_ov = scale_img(mirror_img(right_arm_ov_img), arm_w + 2 * pad, limb_h + 2 * pad)
    left_leg_ov = scale_img(mirror_img(right_leg_ov_img), leg_w + 2 * pad, limb_h + 2 * pad)

    def draw_part(x: int, y: int, base_pm: QPixmap | None, ov_pm: QPixmap | None):
        if base_pm is None:
            return
        mp.drawPixmap(x, y, base_pm)
        if ov_pm:
            mp.drawPixmap(x - pad, y - pad, ov_pm)

    x_body = (model_w - body_w) // 2
    y_body = head_h
    y_leg = head_h + body_h
    draw_part(x_body, 0, head, head_ov)
    draw_part(x_body, y_body, body, body_ov)
    draw_part(x_body - arm_w, y_body, right_arm, right_arm_ov)
    draw_part(x_body + body_w, y_body, left_arm, left_arm_ov)
    draw_part(x_body, y_leg, right_leg, right_leg_ov)
    draw_part(x_body + leg_w, y_leg, left_leg, left_leg_ov)
    mp.end()

    canvas = QPixmap(width, height)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
    x = (width - model_pm.width()) // 2
    y = (height - model_pm.height()) // 2
    painter.drawPixmap(x, y, model_pm)
    painter.end()
    return canvas
