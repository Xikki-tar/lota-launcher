import hashlib
import os
import platform
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests

from auth.api_base import get_api_base as resolve_api_base


DEFAULT_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
REQUEST_TIMEOUT = 15


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _log_path() -> Path:
    return _runtime_dir() / "updater.log"


def _launcher_binary_name() -> str:
    return "launcher.exe" if platform.system() == "Windows" else "launcher"


def _launcher_path() -> Path:
    raw = os.getenv("LOTA_LAUNCHER_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_runtime_dir() / _launcher_binary_name()).resolve()


def _launcher_source_path() -> Path:
    return (_runtime_dir() / "launcher.py").resolve()


def _launcher_version_path() -> Path:
    raw = os.getenv("LOTA_LAUNCHER_VERSION_PATH", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_runtime_dir() / "launcher.version").resolve()


def _launcher_backup_path() -> Path:
    launcher = _launcher_path()
    return launcher.with_name(f"{launcher.name}.old")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    line = f"[{_now_text()}] {message}\n"
    try:
        _log_path().parent.mkdir(parents=True, exist_ok=True)
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    try:
        if sys.stderr:
            sys.stderr.write(line)
    except Exception:
        pass


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    machine_aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }
    machine = machine_aliases.get(machine, machine)
    return f"{system}-{machine}"


def launcher_exists() -> bool:
    return _launcher_path().exists() or (not getattr(sys, "frozen", False) and _launcher_source_path().exists())


def read_local_version() -> str:
    path = _launcher_version_path()
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip() or "0.0.0"
        except Exception as exc:
            log(f"Failed to read version file {path}: {exc}")
    return os.getenv("LOTA_LAUNCHER_VERSION", "0.0.0").strip() or "0.0.0"


def write_local_version(version: str) -> None:
    path = _launcher_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((version or "").strip() + "\n", encoding="utf-8")


def get_api_base() -> str:
    return resolve_api_base()


def check_for_update() -> dict | None:
    payload = {
        "platform": detect_platform(),
        "version": read_local_version(),
        "channel": DEFAULT_CHANNEL,
    }
    try:
        response = requests.post(
            f"{get_api_base()}/api/launcher/check",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log(f"Update check failed: {exc}")
        return None

    if response.status_code != 200:
        log(f"Update check returned HTTP {response.status_code}")
        return None

    try:
        data = response.json()
    except ValueError as exc:
        log(f"Update check returned invalid JSON: {exc}")
        return None

    if not isinstance(data, dict):
        log("Update check returned non-dict payload")
        return None
    if data.get("ok") is not True:
        log(f"Update check error: {data.get('error')}")
        return None
    return data


def _apply_executable_bits(path: Path) -> None:
    if platform.system() == "Windows":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_to_temp(url: str, expected_sha256: str, expected_size: int) -> Path:
    fd, tmp_name = tempfile.mkstemp(prefix="launcher_update_", dir=str(_runtime_dir()))
    os.close(fd)
    tmp_path = Path(tmp_name)

    sha256 = hashlib.sha256()
    total = 0

    try:
        with requests.get(url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            with tmp_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    sha256.update(chunk)
                    total += len(chunk)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if expected_size > 0 and total != expected_size:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded size mismatch: expected {expected_size}, got {total}")

    actual_sha256 = sha256.hexdigest()
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("Downloaded sha256 mismatch")

    _apply_executable_bits(tmp_path)
    return tmp_path


def replace_binary(current_path: Path, new_path: Path) -> None:
    backup_path = _launcher_backup_path()
    backup_path.unlink(missing_ok=True)
    current_path.parent.mkdir(parents=True, exist_ok=True)

    restored = False
    try:
        if current_path.exists():
            os.replace(current_path, backup_path)
        os.replace(new_path, current_path)
        restored = True
    except Exception:
        if not current_path.exists() and backup_path.exists():
            os.replace(backup_path, current_path)
        raise
    finally:
        if restored and backup_path.exists():
            backup_path.unlink(missing_ok=True)


def install_update(update_info: dict) -> bool:
    launcher_path = _launcher_path()
    launcher_url = str(update_info.get("url") or "").strip()
    if not launcher_url:
        log("Update payload does not contain a file URL")
        return False

    if launcher_url.startswith("/"):
        launcher_url = f"{get_api_base()}{launcher_url}"

    version = str(update_info.get("version") or "").strip()
    sha256 = str(update_info.get("sha256") or "").strip()
    size = int(update_info.get("size") or 0)
    temp_path: Path | None = None

    try:
        log(f"Downloading launcher update {version or '<unknown>'} from {launcher_url}")
        temp_path = _download_to_temp(launcher_url, sha256, size)
        replace_binary(launcher_path, temp_path)
        write_local_version(version)
        log(f"Launcher updated to version {version}")
        return True
    except Exception as exc:
        log(f"Failed to install launcher update: {exc}")
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        return False


def launch_launcher(args: list[str]) -> int:
    launcher_path = _launcher_path()
    if launcher_path.exists():
        cmd = [str(launcher_path), *args]
    elif not getattr(sys, "frozen", False) and _launcher_source_path().exists():
        cmd = [sys.executable, str(_launcher_source_path()), *args]
    else:
        log(f"Launcher binary not found at {launcher_path}")
        return 1

    try:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0
        process = subprocess.Popen(cmd, cwd=str(_runtime_dir()), creationflags=creationflags)
    except Exception as exc:
        log(f"Failed to launch launcher: {exc}")
        return 1

    log(f"Launcher started with PID {process.pid}")
    return 0


def main(argv: list[str]) -> int:
    if not launcher_exists():
        log("Launcher is missing locally; updater will still try to fetch metadata")

    update_info = check_for_update()
    if update_info and update_info.get("update_available") is True:
        install_update(update_info)

    return launch_launcher(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
