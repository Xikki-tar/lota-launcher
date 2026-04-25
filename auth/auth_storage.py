import configparser
import ctypes
import os
import platform
import shutil
from pathlib import Path


APP_DIR_NAME = "lota-launcher"
LINUX_APP_DIR_NAME = ".lota-launcher"
SETTINGS_FILE_NAME = "config.cfg"


def _to_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def _total_memory_bytes() -> int | None:
    system = platform.system()

    if system == "Windows":
        try:
            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except Exception:
            return None

    if hasattr(os, "sysconf"):
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            page_count = os.sysconf("SC_PHYS_PAGES")
            if isinstance(page_size, int) and isinstance(page_count, int) and page_size > 0 and page_count > 0:
                return page_size * page_count
        except Exception:
            return None

    return None


def _default_mem_max_mb() -> int:
    total_bytes = _total_memory_bytes()
    if not total_bytes or total_bytes <= 0:
        return 4096

    total_gib = total_bytes / (1024 ** 3)
    if total_gib >= 8 and total_gib < 9:
        return 6144
    if total_gib > 8:
        return 8192
    return 4096


def _apply_default_client_settings(data: dict) -> dict:
    normalized = dict(data or {})
    normalized.setdefault("mem_min_mb", 1024)
    normalized.setdefault("mem_max_mb", _default_mem_max_mb())
    normalized.setdefault("auto_java_version", True)
    normalized.setdefault("disable_openal", False)
    return normalized


def _platform_app_dir(home: Path, system: str) -> Path:
    override = os.getenv("LOTA_LAUNCHER_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    if system == "Windows":
        return Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local")) / APP_DIR_NAME
    if system == "Darwin":
        return home / "Library" / "Application Support" / APP_DIR_NAME
    return home / LINUX_APP_DIR_NAME


def _legacy_app_candidates(home: Path, system: str) -> list[Path]:
    candidates = [
        home / ".lotalauncher",
    ]
    if system == "Windows":
        appdata = Path(os.getenv("APPDATA", home / "AppData" / "Roaming"))
        localappdata = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        candidates.extend(
            [
                localappdata / "LotaLauncher",
                localappdata / "lota_launcher",
                localappdata / "lota-launcher",
                appdata / "lota_launcher",
                appdata / "lota-launcher",
                appdata / "LotaLauncher",
            ]
        )
    elif system == "Darwin":
        candidates.extend(
            [
                home / "Library" / "Application Support" / "lota_launcher",
                home / "Library" / "Application Support" / "LotaLauncher",
            ]
        )
    else:
        xdg_config_home = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
        xdg_data_home = Path(os.getenv("XDG_DATA_HOME", home / ".local" / "share"))
        candidates.extend(
            [
                xdg_data_home / "lota-launcher",
                xdg_data_home / "lota_launcher",
                xdg_data_home / "LotaLauncher",
                xdg_config_home / "lota_launcher",
                xdg_config_home / "lota-launcher",
                xdg_config_home / "LotaLauncher",
            ]
        )
    return candidates


def _copy_missing_tree(source_dir: Path, target_dir: Path) -> None:
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(source_dir)
        target_root = target_dir / rel_root
        target_root.mkdir(parents=True, exist_ok=True)
        for dirname in dirs:
            (target_root / dirname).mkdir(parents=True, exist_ok=True)
        for filename in files:
            src = root_path / filename
            dst = target_root / filename
            if dst.exists():
                continue
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue


def _migrate_dir(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.exists() or source_dir == target_dir:
        return
    if target_dir.exists():
        try:
            _copy_missing_tree(source_dir, target_dir)
            shutil.rmtree(source_dir, ignore_errors=True)
        except OSError:
            return
        return
    try:
        source_dir.rename(target_dir)
    except OSError:
        try:
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
        except OSError:
            return


def _ensure_dir(path: Path, fallback_candidates: list[Path]) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        for candidate in fallback_candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue
    return path


def get_config_dir() -> Path:
    home = Path.home()
    system = platform.system()
    app_dir = _platform_app_dir(home, system)
    legacy_dirs = _legacy_app_candidates(home, system)
    for legacy_dir in legacy_dirs:
        if legacy_dir.resolve() != app_dir.resolve():
            _migrate_dir(legacy_dir, app_dir)
    return _ensure_dir(app_dir, [])


def get_data_dir() -> Path:
    return get_config_dir()


def get_settings_cfg() -> Path:
    return get_config_dir() / SETTINGS_FILE_NAME


def get_skin_file() -> Path:
    return get_data_dir() / "skin.png"


def save_skin_model(model: str) -> None:
    cfg = get_settings_cfg()
    parser = configparser.ConfigParser()
    if cfg.exists():
        parser.read(cfg, encoding="utf-8")
    if not parser.has_section("auth"):
        parser.add_section("auth")
    normalized = str(model or "classic").strip().lower()
    if normalized not in {"classic", "slim"}:
        normalized = "classic"
    parser.set("auth", "skin_model", normalized)
    with cfg.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_skin_model() -> str:
    auth = load_auth_data() or {}
    model = str(auth.get("skin_model") or "classic").strip().lower()
    return model if model in {"classic", "slim"} else "classic"


def save_auth_data(token: str, username: str, status: str, sub_level: int, player_uuid: str | None = None):
    cfg = get_settings_cfg()
    parser = configparser.ConfigParser()
    if cfg.exists():
        parser.read(cfg, encoding="utf-8")
    if not parser.has_section("auth"):
        parser.add_section("auth")
    parser.set("auth", "token", token)
    parser.set("auth", "username", username)
    parser.set("auth", "status", status)
    parser.set("auth", "sub_level", str(sub_level))
    if player_uuid is not None:
        parser.set("auth", "player_uuid", str(player_uuid or ""))
    with cfg.open("w", encoding="utf-8") as f:
        parser.write(f)


def save_register_data(link_token: str, telegram_url: str):
    cfg = get_settings_cfg()
    parser = configparser.ConfigParser()
    if cfg.exists():
        parser.read(cfg, encoding="utf-8")
    if not parser.has_section("register"):
        parser.add_section("register")
    parser.set("register", "link_token", link_token)
    parser.set("register", "telegram_url", telegram_url)
    with cfg.open("w", encoding="utf-8") as f:
        parser.write(f)


def load_register_data():
    cfg = get_settings_cfg()
    if not cfg.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(cfg, encoding="utf-8")
    if not parser.has_section("register"):
        return None
    link_token = parser.get("register", "link_token", fallback="").strip()
    telegram_url = parser.get("register", "telegram_url", fallback="").strip()
    if not link_token or not telegram_url:
        return None
    return {
        "link_token": link_token,
        "telegram_url": telegram_url,
    }


def clear_register_data():
    cfg = get_settings_cfg()
    if not cfg.exists():
        return
    parser = configparser.ConfigParser()
    parser.read(cfg, encoding="utf-8")
    if parser.has_section("register"):
        parser.remove_section("register")
        with cfg.open("w", encoding="utf-8") as f:
            parser.write(f)


def load_auth_data():
    cfg = get_settings_cfg()
    if not cfg.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(cfg, encoding="utf-8")
    if not parser.has_section("auth"):
        return None
    data = {k: v for k, v in parser.items("auth")}
    if "sub_level" in data:
        try:
            data["sub_level"] = int(data["sub_level"])
        except Exception:
            pass
    return data


def load_settings():
    cfg_path = get_settings_cfg()
    if not cfg_path.exists():
        return _apply_default_client_settings({})
    parser = configparser.ConfigParser()
    parser.read(cfg_path, encoding="utf-8")
    if not parser.has_section("client"):
        return _apply_default_client_settings({})
    data = {k: v for k, v in parser.items("client")}
    for key in ("auto_java_version", "disable_openal"):
        if key in data:
            data[key] = _to_bool(data[key], default=False)
    for key in ("mem_min_mb", "mem_max_mb"):
        if key in data:
            try:
                data[key] = int(data[key])
            except Exception:
                data.pop(key, None)
    return _apply_default_client_settings(data)


def save_settings(data: dict):
    cfg = get_settings_cfg()
    parser = configparser.ConfigParser()
    if cfg.exists():
        parser.read(cfg, encoding="utf-8")
    if not parser.has_section("client"):
        parser.add_section("client")
    for key, value in data.items():
        parser.set("client", key, str(value))
    with cfg.open("w", encoding="utf-8") as f:
        parser.write(f)
