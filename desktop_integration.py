import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from auth.auth_storage import get_data_dir


APP_ID = "lota-launcher"
APP_NAME = "LOTA Launcher"
WINDOWS_SEARCH_ALIAS = "LotaLauncher"
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


def windows_hidden_subprocess_kwargs() -> dict:
    if not sys.platform.startswith("win"):
        return {}

    startupinfo = None
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    except Exception:
        startupinfo = None

    creationflags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
        creationflags |= int(getattr(subprocess, flag_name, 0) or 0)

    kwargs = {"creationflags": creationflags}
    if startupinfo is not None:
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _data_home() -> Path:
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _linux_desktop_dir() -> Path | None:
    raw = os.getenv("XDG_DESKTOP_DIR", "").strip()
    if raw:
        return Path(raw.replace("$HOME", str(Path.home()))).expanduser()
    candidate = Path.home() / "Desktop"
    return candidate if candidate.exists() else None


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
    known = _windows_known_folder("{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}")  # FOLDERID_Programs
    if known is not None:
        return known
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _windows_desktop_dir() -> Path:
    known = _windows_known_folder("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
    if known is not None:
        return known
    userprofile = os.getenv("USERPROFILE")
    if userprofile:
        return Path(userprofile) / "Desktop"
    return Path.home() / "Desktop"


def _windows_known_folder(folder_id: str) -> Path | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_uint32),
                ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        guid_obj = uuid.UUID(folder_id)
        data4 = (ctypes.c_ubyte * 8)(*guid_obj.bytes[8:])
        guid = GUID(
            guid_obj.time_low,
            guid_obj.time_mid,
            guid_obj.time_hi_version,
            data4,
        )

        path_ptr = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid),
            0,
            None,
            ctypes.byref(path_ptr),
        )
        if result != 0 or not path_ptr.value:
            return None
        path_value = path_ptr.value
        ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(path_ptr, ctypes.c_void_p))
        path = Path(path_value)
        return path
    except Exception:
        return None


def _run_powershell_script(script: str) -> None:
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace").strip()
        stdout_text = result.stdout.decode("utf-8", errors="replace").strip()
        details = stderr_text or stdout_text or "(no output)"
        raise RuntimeError(f"PowerShell shortcut script failed (exit {result.returncode}): {details}")


def _register_windows_app_paths(executable: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import winreg
        key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{executable.name}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(executable))
            winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, str(executable.parent))
    except Exception:
        pass


def _notify_shell_path(path: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        SHCNE_UPDATEDIR = 0x00001000
        SHCNF_PATHW = 0x0005
        ctypes.windll.shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, str(path), None)
    except Exception:
        pass


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

    arguments = " ".join(f'"{arg}"' for arg in (args or []))
    start_menu_dir = _windows_start_menu_dir()
    desktop_dir = _windows_desktop_dir()
    alias_names = [
        APP_NAME,
        WINDOWS_SEARCH_ALIAS,
        executable.stem,
        "Lota Launcher",
        "lota-launcher",
    ]
    shortcuts = [
        desktop_dir / f"{APP_NAME}.lnk",
    ]
    shortcuts.extend(start_menu_dir / f"{name}.lnk" for name in alias_names)
    unique_shortcuts: list[Path] = []
    seen: set[str] = set()
    for shortcut in shortcuts:
        key = str(shortcut).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_shortcuts.append(shortcut)
    shortcuts = unique_shortcuts
    for shortcut_path in shortcuts:
        shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    script_lines = [
        "$ErrorActionPreference = 'Stop'",
        "$shell = New-Object -ComObject WScript.Shell",
    ]
    for shortcut_path in shortcuts:
        script_lines.extend(
            [
                f"$shortcut = $shell.CreateShortcut({_powershell_quote(str(shortcut_path))})",
                f"$shortcut.TargetPath = {_powershell_quote(str(executable))}",
                f"$shortcut.Arguments = {_powershell_quote(arguments)}",
                f"$shortcut.WorkingDirectory = {_powershell_quote(str(executable.parent))}",
                f"$shortcut.IconLocation = {_powershell_quote(str(icon_target))}",
                "$shortcut.Save()",
            ]
        )
    script = "\n".join(script_lines)
    _run_powershell_script(script)
    _register_windows_app_paths(executable)
    _notify_shell_path(desktop_dir)
    _notify_shell_path(start_menu_dir)
    return desktop_dir / f"{APP_NAME}.lnk"


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
    scalable_icon_dir = data_home / "icons" / "hicolor" / "scalable" / "apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    scalable_icon_dir.mkdir(parents=True, exist_ok=True)
    if icon_source.exists():
        icon_target = icon_dir / f"{ICON_NAME}.png"
        scalable_icon_target = scalable_icon_dir / f"{ICON_NAME}.png"
        shutil.copyfile(icon_source, icon_target)
        shutil.copyfile(icon_source, scalable_icon_target)
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
    try:
        _write_linux_desktop_file(local_desktop_path, executable, str(local_icon), args)
    except OSError:
        pass
    user_desktop_dir = _linux_desktop_dir()
    if user_desktop_dir is not None:
        user_desktop_dir.mkdir(parents=True, exist_ok=True)
        _write_linux_desktop_file(user_desktop_dir / f"{APP_NAME}.desktop", executable, str(local_icon), args)
    _refresh_linux_desktop_cache(data_home)
    return desktop_path
