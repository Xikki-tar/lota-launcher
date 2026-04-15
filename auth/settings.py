import os

DEFAULT_API_BASES = "https://ru.lota.work,https://eu.lota.work"

API_BASE = (
    os.getenv("LOTA_API_BASES", "").strip()
    or os.getenv("LOTA_API_BASE", "").strip()
    or DEFAULT_API_BASES
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_STEVE = os.path.join(PROJECT_ROOT, "assets/steve.png")
