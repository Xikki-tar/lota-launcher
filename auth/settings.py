import os

try:
    from auth.build_api import UPDATES_DISABLED
except ImportError:
    UPDATES_DISABLED = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
DEFAULT_STEVE = os.path.join(PROJECT_ROOT, "assets/steve.png")
