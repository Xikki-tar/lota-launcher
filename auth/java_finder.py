import os
import platform
import re
import shutil
import subprocess
from pathlib import Path


def normalize_path(p: str) -> str:
    try:
        return str(Path(p).resolve())
    except Exception:
        return p


def is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def get_java_version(java_path: str) -> str:
    try:
        p = subprocess.run([java_path, "-version"], capture_output=True, text=True, timeout=3)
        out = (p.stderr or p.stdout or "").strip()
        if not out:
            return "unknown version"
        return out.splitlines()[0].strip() or "unknown version"
    except Exception:
        return "unknown version"


def _candidate_from_java_home(java_home: str) -> str | None:
    if not java_home:
        return None
    exe = "java.exe" if platform.system() == "Windows" else "java"
    p = os.path.join(java_home, "bin", exe)
    return p if is_executable(p) else None


def _find_linux() -> list[str]:
    cands = set()

    java = shutil.which("java")
    if java:
        cands.add(normalize_path(java))

    for cmd in (["update-alternatives", "--list", "java"], ["update-alternatives", "--display", "java"]):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            out = (p.stdout or "").strip()
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("/") and "java" in os.path.basename(line) and is_executable(line):
                    cands.add(normalize_path(line))
        except Exception:
            pass

    alt = "/etc/alternatives/java"
    if os.path.exists(alt):
        try:
            resolved = normalize_path(os.path.realpath(alt))
            if is_executable(resolved):
                cands.add(resolved)
        except Exception:
            pass

    jvm_root = "/usr/lib/jvm"
    if os.path.isdir(jvm_root):
        for name in os.listdir(jvm_root):
            p = os.path.join(jvm_root, name, "bin", "java")
            if is_executable(p):
                cands.add(normalize_path(p))

    sdkman = os.path.expanduser("~/.sdkman/candidates/java")
    if os.path.isdir(sdkman):
        for name in os.listdir(sdkman):
            p = os.path.join(sdkman, name, "bin", "java")
            if is_executable(p):
                cands.add(normalize_path(p))

    return sorted(cands)


def _find_macos() -> list[str]:
    cands = set()

    java = shutil.which("java")
    if java:
        cands.add(normalize_path(java))

    try:
        p = subprocess.run(["/usr/libexec/java_home", "-V"], capture_output=True, text=True, timeout=3)
        out = (p.stderr or p.stdout or "").strip()
        for line in out.splitlines():
            m = re.search(r"(/Library/Java/JavaVirtualMachines/.*?/Contents/Home)$", line.strip())
            if m:
                jp = _candidate_from_java_home(m.group(1))
                if jp:
                    cands.add(normalize_path(jp))
    except Exception:
        pass

    roots = [
        "/Library/Java/JavaVirtualMachines",
        os.path.expanduser("~/Library/Java/JavaVirtualMachines"),
    ]
    for r in roots:
        if os.path.isdir(r):
            for name in os.listdir(r):
                home = os.path.join(r, name, "Contents", "Home")
                jp = _candidate_from_java_home(home)
                if jp:
                    cands.add(normalize_path(jp))

    return sorted(cands)


def _find_windows() -> list[str]:
    cands = set()

    java = shutil.which("java")
    if java and is_executable(java):
        cands.add(normalize_path(java))

    java_home = os.environ.get("JAVA_HOME")
    jp = _candidate_from_java_home(java_home) if java_home else None
    if jp:
        cands.add(normalize_path(jp))

    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    roots = [
        os.path.join(pf, "Java"),
        os.path.join(pf86, "Java"),
        os.path.join(pf, "Eclipse Adoptium"),
        os.path.join(pf86, "Eclipse Adoptium"),
        os.path.join(pf, "Microsoft"),
        os.path.join(pf, "Zulu"),
        os.path.join(pf, "BellSoft"),
        os.path.join(pf, "Amazon Corretto"),
    ]

    def scan_root(root: str):
        if not os.path.isdir(root):
            return
        for dirpath, dirnames, _ in os.walk(root):
            if "bin" in dirnames:
                jp = os.path.join(dirpath, "bin", "java.exe")
                if is_executable(jp):
                    cands.add(normalize_path(jp))

    for r in roots:
        scan_root(r)

    try:
        import winreg

        def add_from_key(root, subkey):
            try:
                with winreg.OpenKey(root, subkey) as k:
                    versions = []
                    try:
                        cv, _ = winreg.QueryValueEx(k, "CurrentVersion")
                        if cv:
                            versions.append(cv)
                    except Exception:
                        pass

                    i = 0
                    while True:
                        try:
                            ver = winreg.EnumKey(k, i)
                            versions.append(ver)
                            i += 1
                        except OSError:
                            break

                    for ver in versions:
                        try:
                            with winreg.OpenKey(k, ver) as vk:
                                java_home, _ = winreg.QueryValueEx(vk, "JavaHome")
                                jp = _candidate_from_java_home(java_home)
                                if jp:
                                    cands.add(normalize_path(jp))
                        except Exception:
                            pass
            except Exception:
                pass

        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JDK")
        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\JavaSoft\JRE")
        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eclipse Adoptium\JDK")
        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Azul Systems\Zulu")
        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\JDK")
        add_from_key(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\JavaSoft\JRE")
    except Exception:
        pass

    return sorted(cands)


def find_java_candidates() -> list[str]:
    sysname = platform.system()
    if sysname == "Windows":
        return _find_windows()
    if sysname == "Darwin":
        return _find_macos()
    return _find_linux()
