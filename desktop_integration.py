import os
import shutil
import subprocess
import sys
from pathlib import Path

from auth.auth_storage import get_data_dir


APP_ID = "lota-launcher"
APP_NAME = "LOTA Launcher"
ICON_NAME = "lota-launcher"
WINDOWS_APP_DIR = "LotaLauncher"
WINDOWS_APP_USER_MODEL_ID = "LOTA.Launcher"


def set_windows_app_user_model_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except Exception:
        pass


def _data_home() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _desktop_quote(value: str) -> str:
    escaped = (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _desktop_exec(executable: Path, args: list[str] | None = None) -> str:
    parts = [_desktop_quote(str(executable))]
    parts.extend(_desktop_quote(arg) for arg in (args or []))
    return " ".join(parts)


def _write_linux_desktop_file(path: Path, executable: Path, icon_name: str, args: list[str] | None = None) -> None:
    path.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Type=Application",
                f"Name={APP_NAME}",
                "Comment=Играть в LOTA",
                f"Exec={_desktop_exec(executable, args)}",
                f"Icon={icon_name}",
                "Terminal=false",
                "Categories=Game;",
                "StartupNotify=true",
                "StartupWMClass=LOTA Launcher",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_app_dir() -> Path:
    return get_data_dir() / "desktop"


def _windows_start_menu_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _sibling_icon(icon_source: Path, suffix: str) -> Path:
    candidate = icon_source.with_suffix(suffix)
    return candidate if candidate.exists() else icon_source


def _install_windows_shortcut(executable: Path, icon_source: Path, args: list[str] | None) -> Path:
    app_dir = _windows_app_dir()
    app_dir.mkdir(parents=True, exist_ok=True)

    icon_target = app_dir / f"{ICON_NAME}.ico"
    if icon_source.exists():
        shutil.copyfile(icon_source, icon_target)
    else:
        icon_target = executable

    shortcut_path = _windows_start_menu_dir() / f"{APP_NAME}.lnk"
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    arguments = " ".join(f'"{arg}"' for arg in (args or []))
    script = "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$shortcut = $shell.CreateShortcut({_powershell_quote(str(shortcut_path))})",
            f"$shortcut.TargetPath = {_powershell_quote(str(executable))}",
            f"$shortcut.Arguments = {_powershell_quote(arguments)}",
            f"$shortcut.WorkingDirectory = {_powershell_quote(str(executable.parent))}",
            f"$shortcut.IconLocation = {_powershell_quote(str(icon_target))}",
            "$shortcut.Save()",
        ]
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return shortcut_path


def _refresh_linux_desktop_cache(data_home: Path) -> None:
    commands = [
        ["update-desktop-database", str(data_home / "applications")],
        ["gtk-update-icon-cache", "-q", str(data_home / "icons" / "hicolor")],
    ]
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except Exception:
            pass


def install_desktop_entry(
    executable: Path,
    icon_source: Path,
    *,
    args: list[str] | None = None,
) -> Path | None:
    if sys.platform == "darwin":
        return None

    executable = Path(executable).expanduser().resolve()
    icon_source = Path(icon_source).expanduser().resolve()
    if sys.platform.startswith("win"):
        icon_source = _sibling_icon(icon_source, ".ico")
        return _install_windows_shortcut(executable, icon_source, args)

    icon_source = _sibling_icon(icon_source, ".png")
    data_home = _data_home()

    icon_dir = data_home / "icons" / "hicolor" / "32x32" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    if icon_source.exists():
        icon_target = icon_dir / f"{ICON_NAME}.png"
        shutil.copyfile(icon_source, icon_target)
        local_icon = executable.parent / f"{ICON_NAME}.png"
        try:
            shutil.copyfile(icon_source, local_icon)
        except OSError:
            local_icon = icon_target
    else:
        local_icon = Path(ICON_NAME)

    applications_dir = data_home / "applications"
    applications_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = applications_dir / f"{APP_ID}.desktop"
    _write_linux_desktop_file(desktop_path, executable, ICON_NAME, args)
    local_desktop_path = executable.parent / f"{APP_ID}.desktop"
    _write_linux_desktop_file(local_desktop_path, executable, str(local_icon), args)
    _refresh_linux_desktop_cache(data_home)
    return desktop_path
