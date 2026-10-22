import errno
import itertools
import os
import re
import signal
import socket
import ssl
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import requests

from services.build_sync import BuildSyncError
from window.i18n import t


class PlayError(RuntimeError):
    kind = "internal"

    def __init__(self, message: str, details: str = "", kind: str | None = None):
        super().__init__(message)
        self.details = details
        if kind:
            self.kind = kind


class JavaError(PlayError):
    kind = "java"


@dataclass
class PlayFailure:
    kind: str
    message: str
    details: str = ""


_LINE_LIMIT = 400
_OUTPUT_TAIL = 60
_MATCH_CONTEXT = 30
_CRASH_REPORT_LINES = 60
_HS_ERR_LINES = 40
_BLOCK_LIMIT = 6000
_DETAILS_LIMIT = 40000

_NETWORK_ERRORS = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
    ssl.SSLError,
    socket.gaierror,
    ConnectionError,
    TimeoutError,
)
_DISK_FULL = {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}
_DISK_DENIED = {errno.EACCES, errno.EPERM, errno.EROFS}
_EXEC_WINERRORS = {2, 3, 5, 193, 216}

_OUTPUT_MARKERS = tuple(
    (kind, tuple(marker.lower() for marker in markers))
    for kind, markers in (
        ("memory_heap", ("java.lang.OutOfMemoryError",)),
        ("memory_alloc", (
            "Could not reserve enough space for",
            "Initial heap size set to a larger value than the maximum heap size",
            "Invalid maximum heap size",
            "Invalid initial heap size",
            "There is insufficient memory for the Java Runtime Environment",
        )),
        ("java_version", (
            "UnsupportedClassVersionError",
            "has been compiled by a more recent version of the Java Runtime",
        )),
        ("jvm_option", (
            "Unrecognized VM option",
            "Unrecognized option:",
            "Could not find or load main class",
        )),
        ("jvm_start", (
            "Could not create the Java Virtual Machine",
            "Error occurred during initialization of VM",
        )),
        ("jvm_fatal", ("A fatal error has been detected by the Java Runtime Environment",)),
        ("graphics", (
            "GLFW error 65542",
            "GLFW error 65543",
            "WGL: The driver does not appear to support OpenGL",
            "Pixel format not accelerated",
            "No OpenGL context found in the current thread",
        )),
        ("crash_report", ("---- Minecraft Crash Report ----",)),
        ("mods", (
            "ModLoadingException",
            "Mod Loading Errors have occurred",
            "Mod Loading has failed",
            "Missing or unsupported mandatory dependencies",
            "DuplicateModsFoundException",
            "net.fabricmc.loader.impl.FormattedException",
        )),
    )
)
_JAVA_MARKERS = tuple(
    marker
    for kind, markers in _OUTPUT_MARKERS
    if kind in ("memory_alloc", "java_version", "jvm_option", "jvm_start", "jvm_fatal")
    for marker in markers
)
_GPU_DRIVER_LIBS = (
    "atio6axx", "atioglxx", "nvoglv", "ig7icd", "ig75icd", "ig8icd", "ig9icd", "igxelpicd",
    "libnvidia-glcore", "radeonsi_dri", "iris_dri", "i965_dri", "libglx",
)
_JVM_ARG_PATTERNS = (
    re.compile(r"Unrecognized VM option '([^']+)'"),
    re.compile(r"Unrecognized option: (\S+)"),
    re.compile(r"Could not find or load main class (\S+)"),
)
_CRASH_DESCRIPTION = re.compile(r"Description:\s*(.+)")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(\b(?:access_?token|download_token|token|key|password)=)[^&\s\"']+"),
    re.compile(r"(?i)(\"(?:access_?token|download_token|token|key|password)\"\s*:\s*\")[^\"]*"),
    re.compile(r"(--accessToken\s+)\S+"),
)
_NTSTATUS = {
    0xC0000005: "ACCESS_VIOLATION",
    0xC0000017: "NO_MEMORY",
    0xC00000FD: "STACK_OVERFLOW",
    0xC0000135: "DLL_NOT_FOUND",
    0xC000013A: "CONTROL_C_EXIT",
    0xC0000374: "HEAP_CORRUPTION",
    0xC0000409: "STACK_BUFFER_OVERRUN",
}
_OOM_EXITS = {"SIGKILL", "0xC0000017 NO_MEMORY"}


class GameOutput:
    def __init__(self):
        self._lock = threading.Lock()
        self._tail: deque[str] = deque(maxlen=_OUTPUT_TAIL)
        self._matches: dict[str, list[str]] = {}

    def feed(self, line: str) -> None:
        line = line[:_LINE_LIMIT]
        lowered = line.lower()
        with self._lock:
            self._tail.append(line)
            for lines in self._matches.values():
                if len(lines) < _MATCH_CONTEXT:
                    lines.append(line)
            for kind, markers in _OUTPUT_MARKERS:
                if kind not in self._matches and any(marker in lowered for marker in markers):
                    self._matches[kind] = [line]

    def snapshot(self) -> tuple[list[str], dict[str, list[str]]]:
        with self._lock:
            return list(self._tail), {kind: list(lines) for kind, lines in self._matches.items()}


def has_java_failure(text: str) -> bool:
    return any(marker in line.lower() for line in str(text or "").splitlines() for marker in _JAVA_MARKERS)


def is_java_start_failure(exc: OSError, java_path: str) -> bool:
    if isinstance(exc, requests.RequestException):
        return False
    if exc.filename is not None:
        return str(exc.filename) == java_path
    return getattr(exc, "winerror", None) in _EXEC_WINERRORS


def redact(text: str, secrets=()) -> str:
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text


def format_details(failure: PlayFailure, header: list[str], secrets=()) -> str:
    text = redact("\n\n".join(part for part in ("\n".join(header), failure.details) if part), secrets)
    return text if len(text) <= _DETAILS_LIMIT else text[:_DETAILS_LIMIT] + "\n..."


def classify_exception(exc: BaseException) -> PlayFailure:
    chain = _exception_chain(exc)
    for item in chain:
        found = _classify_error(item)
        if found:
            kind, message = found
            return PlayFailure(kind, message, _exception_details(chain, with_traceback=False))
    if any(isinstance(item, BuildSyncError) for item in chain):
        return PlayFailure("server", t("play_error_build_sync"), _exception_details(chain, with_traceback=True))
    reason = _first_line(str(exc)) or type(exc).__name__
    return PlayFailure(
        "internal",
        t("play_error_unexpected").format(reason=reason),
        _exception_details(chain, with_traceback=True),
    )


def classify_exit(
    returncode: int,
    output: GameOutput,
    *,
    game_dir: Path,
    pid: int,
    started_at: float,
    user_jvm_args: str = "",
) -> PlayFailure:
    game_dir = Path(game_dir)
    tail, matches = output.snapshot()
    crash_path = _find_crash_report(game_dir, started_at)
    crash_lines = _read_lines(crash_path, _CRASH_REPORT_LINES) if crash_path else matches.get("crash_report", [])
    hs_err_path = game_dir / f"hs_err_pid{pid}.log"
    hs_err_lines = _read_lines(hs_err_path, _HS_ERR_LINES)
    kind, message, evidence = _exit_reason(returncode, matches, crash_lines, hs_err_lines, user_jvm_args)

    blocks = [f"{t('play_details_exit_code')}: {_exit_code_label(returncode)}"]
    if evidence:
        blocks.append(_block(t("play_details_reason"), evidence))
    if crash_lines:
        blocks.append(_block(t("play_details_crash_report") + (f": {crash_path}" if crash_path else ""), crash_lines))
    if hs_err_lines:
        blocks.append(_block(f"JVM crash log: {hs_err_path}", hs_err_lines))
    if tail and tail != evidence[-len(tail):]:
        blocks.append(_block(t("play_details_output"), tail))
    return PlayFailure(kind, message, "\n\n".join(blocks))


def _exit_reason(
    returncode: int,
    matches: dict[str, list[str]],
    crash_lines: list[str],
    hs_err_lines: list[str],
    user_jvm_args: str,
) -> tuple[str, str, list[str]]:
    for key, kind, message_key in (
        ("memory_heap", "memory", "play_error_memory_low"),
        ("memory_alloc", "memory", "play_error_memory_alloc"),
        ("java_version", "java", "play_error_java_too_old"),
    ):
        if key in matches:
            return kind, t(message_key), matches[key]
    if "jvm_option" in matches:
        arg = _user_jvm_arg(matches["jvm_option"][0], user_jvm_args)
        if arg:
            return "jvm_args", t("play_error_jvm_args").format(arg=arg), matches["jvm_option"]
    if "graphics" in matches:
        return "graphics", t("play_error_graphics"), matches["graphics"]
    for key in ("jvm_option", "jvm_start"):
        if key in matches:
            return "java", t("play_error_java_crash"), matches[key]

    description = _crash_description(crash_lines)
    if description and "mod loading" not in description.lower():
        return "crash", t("play_error_game_crash").format(reason=_first_line(description, 120)), []
    if description or "mods" in matches:
        return "mods", t("play_error_mods"), matches.get("mods", [])

    native = _native_exit(returncode)
    fatal_lines = matches.get("jvm_fatal", [])
    fatal = "\n".join([*hs_err_lines, *fatal_lines]).lower()
    if fatal:
        if any(lib in fatal for lib in _GPU_DRIVER_LIBS):
            return "graphics", t("play_error_graphics_crash"), fatal_lines
        if "insufficient memory" in fatal or "out of memory" in fatal:
            return "memory", t("play_error_memory_alloc"), fatal_lines
        return "crash", t("play_error_native_crash").format(code=native or returncode), fatal_lines
    if native in _OOM_EXITS:
        return "memory", t("play_error_memory_killed"), []
    if native:
        return "crash", t("play_error_native_crash").format(code=native), []
    return "crash", t("play_error_exit_code").format(code=returncode), []


def _classify_error(exc: BaseException) -> tuple[str, str] | None:
    if isinstance(exc, PlayError):
        return exc.kind, str(exc)
    if isinstance(exc, BuildSyncError):
        return _classify_build_sync(exc)
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return "server", t("play_error_download_failed").format(status=exc.response.status_code)
    if isinstance(exc, _NETWORK_ERRORS):
        return "network", t("play_error_network")
    if isinstance(exc, OSError) and exc.errno in _DISK_FULL:
        return "disk", t("play_error_disk_full")
    if isinstance(exc, OSError) and exc.errno in _DISK_DENIED:
        return "disk", t("play_error_disk_access")
    return None


def _classify_build_sync(exc: BuildSyncError) -> tuple[str, str] | None:
    status = getattr(exc, "status", None)
    if str(exc) == "no_token":
        return "auth", t("play_error_build_auth")
    if status == 401:
        return "auth", t("play_error_session")
    if status == 403:
        return "build", t("play_error_build_forbidden")
    if status == 404:
        return "build", t("play_error_build_unavailable")
    if status is not None and (status >= 500 or status == 429):
        return "server", t("play_error_server")
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and all(current is not item for item in chain):
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return chain


def _exception_details(chain: list[BaseException], *, with_traceback: bool) -> str:
    lines = [f"{t('play_details_error')}:"]
    for item in chain:
        lines.append(f"{type(item).__name__}: {item}")
        details = str(getattr(item, "details", "") or "")
        if details:
            lines.append(_clip_tail(details))
    if with_traceback:
        lines += ["", "".join(traceback.format_exception(chain[0])).rstrip()]
    return "\n".join(lines)


def _native_exit(returncode: int) -> str | None:
    if os.name != "nt":
        if returncode >= 0:
            return None
        try:
            return signal.Signals(-returncode).name
        except ValueError:
            return f"signal {-returncode}"
    status = returncode & 0xFFFFFFFF
    if status & 0xF0000000 != 0xC0000000:
        return None
    return f"0x{status:08X} {_NTSTATUS.get(status, '')}".strip()


def _exit_code_label(returncode: int) -> str:
    native = _native_exit(returncode)
    return f"{returncode} ({native})" if native else str(returncode)


def _user_jvm_arg(line: str, user_jvm_args: str) -> str | None:
    for pattern in _JVM_ARG_PATTERNS:
        match = pattern.search(line)
        if match:
            value = match.group(1)
            return next((token for token in user_jvm_args.split() if value in token), None)
    return None


def _crash_description(lines: list[str]) -> str:
    for line in lines:
        match = _CRASH_DESCRIPTION.search(line)
        if match:
            return match.group(1).strip()
    return ""


def _find_crash_report(game_dir: Path, started_at: float) -> Path | None:
    try:
        reports = [(path.stat().st_mtime, path) for path in (game_dir / "crash-reports").glob("crash-*.txt")]
    except OSError:
        return None
    recent = [item for item in reports if item[0] >= started_at - 2]
    return max(recent)[1] if recent else None


def _read_lines(path: Path, limit: int) -> list[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as source:
            return [line.rstrip()[:_LINE_LIMIT] for line in itertools.islice(source, limit)]
    except OSError:
        return []


def _block(title: str, lines: list[str]) -> str:
    return "\n".join([f"{title}:", *lines])


def _first_line(text: str, limit: int = 200) -> str:
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[: limit - 3] + "..."


def _clip_tail(text: str) -> str:
    return text if len(text) <= _BLOCK_LIMIT else "...\n" + text[-_BLOCK_LIMIT:]
