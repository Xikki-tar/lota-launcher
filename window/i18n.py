from __future__ import annotations

from auth.auth_storage import load_settings
from window.translations import TRANSLATIONS

_CURRENT_LANGUAGE = "Русский"


def set_language(lang: str | None = None) -> str:
    global _CURRENT_LANGUAGE
    if not lang:
        cfg = load_settings()
        lang = cfg.get("language") or "Русский"
    if lang not in TRANSLATIONS:
        lang = "Русский"
    _CURRENT_LANGUAGE = lang
    return _CURRENT_LANGUAGE


def get_language() -> str:
    return _CURRENT_LANGUAGE


def t(key: str) -> str:
    table = TRANSLATIONS.get(_CURRENT_LANGUAGE) or TRANSLATIONS["Русский"]
    return table.get(key, TRANSLATIONS["Русский"].get(key, key))
