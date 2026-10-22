import sys
import io
import json
import hashlib
import hmac
import secrets
import os
import platform
import socket
import subprocess
import tempfile
import itertools
import threading
import re
import time
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# мокаем qt нах иначе сервисы не импортятся
_qt_mock = MagicMock()
for _mod in [
    "PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "PySide6.QtNetwork", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtMultimedia",
]:
    sys.modules[_mod] = _qt_mock

class _FakeQThread:
    def __init__(self, parent=None): pass
    def start(self): pass
    def wait(self, ms=0): return True
    def isRunning(self): return False
    
class _FakeSignal:
    def __init__(self, *args): pass
    def connect(self, *args): pass
    def emit(self, *args): pass
    def disconnect(self, *args): pass

_qt_mock.QThread = _FakeQThread
_qt_mock.Signal = _FakeSignal

from flask import Flask, g, request, jsonify, Response, send_file
from werkzeug.exceptions import HTTPException
import requests as http

from auth.auth_storage import (
    get_data_dir,
    load_auth_data,
    save_auth_data,
    clear_auth_data,
    load_settings,
    save_settings,
    load_register_data,
    save_register_data,
    clear_register_data,
    load_skin_model,
    save_skin_model,
)
from auth.api_base import drop_saved_default_api_bases, get_api_base
from services.library_service import LibraryService
from services.play_errors import (
    GameOutput,
    JavaError,
    PlayError,
    PlayFailure,
    classify_exception,
    classify_exit,
    format_details,
    has_java_failure,
    is_java_start_failure,
    redact,
)
from window.i18n import set_language, t

set_language()

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


_BACKEND_KEY = os.getenv("LOTA_BACKEND_KEY", "").strip() or secrets.token_hex(32)
_ALLOWED_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
}
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


def _safe_child(base: Path, rel: str) -> Path | None:
    try:
        root = base.resolve()
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if target != root and root in target.parents:
        return target
    return None


@app.after_request
def _cors(response):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Lota-Key"
        response.headers["Vary"] = "Origin"
    return response


@app.before_request
def _guard():
    if request.host.rsplit(":", 1)[0].strip("[]").lower() not in _ALLOWED_HOSTS:
        return Response(status=403)
    if request.method == "OPTIONS":
        return Response(status=200)
    supplied = request.headers.get("X-Lota-Key") or request.args.get("key") or ""
    if not hmac.compare_digest(supplied.encode(), _BACKEND_KEY.encode()):
        return jsonify({"ok": False, "error": "unauthorized"}), 403


_FRONT_QUIET_PATHS = ("/play/state", "/debug/logs", "/tasks/active_downloads", "/task/")
_FRONT_NO_BODY_PATHS = ("/i18n", "/library/catalog", "/news")
_FRONT_IGNORED_ARGS = {"key", "_t"}


def _front_request_summary() -> str:
    parts = []
    args = {k: v for k, v in request.args.items() if k not in _FRONT_IGNORED_ARGS}
    if args:
        parts.append(f"args={_short(_redact(args))}")
    if request.is_json:
        parts.append(f"json={_short(_redact(request.get_json(silent=True)))}")
    elif request.form:
        parts.append(f"form={_short(_redact(request.form.to_dict()))}")
    if request.files:
        parts.append("files=" + ", ".join(f"{name}:{f.filename} ({f.mimetype})" for name, f in request.files.items()))
    return " ".join(parts)


def _front_response_summary(response) -> str:
    if response.direct_passthrough or not response.is_json or request.path.startswith(_FRONT_NO_BODY_PATHS):
        size = response.content_length
        return f"<{response.mimetype or 'empty'} {size if size is not None else '?'} bytes>"
    return _short(_redact(response.get_json(silent=True)))


@app.before_request
def _log_front_request():
    if request.method == "OPTIONS":
        return
    g.front_started = time.monotonic()
    if request.path.startswith(_FRONT_QUIET_PATHS):
        return
    print(f"[front] -> {request.method} {request.path} {_front_request_summary()}".rstrip(), flush=True)


@app.after_request
def _log_front_response(response):
    if request.method == "OPTIONS":
        return response
    if request.path.startswith(_FRONT_QUIET_PATHS) and response.status_code < 400:
        return response
    started = g.get("front_started")
    took = f" in {time.monotonic() - started:.2f}s" if started is not None else " (rejected before handling)"
    print(f"[front] <- {response.status_code} {request.method} {request.path}{took}: {_front_response_summary(response)}", flush=True)
    return response


@app.errorhandler(Exception)
def _handle_error(exc):
    if isinstance(exc, HTTPException):
        return jsonify({"ok": False, "error": exc.name, "status": exc.code}), exc.code
    secrets = _auth_secrets()
    print(f"[backend] unhandled error in {request.method} {request.path}", flush=True)
    print(redact("".join(traceback.format_exception(exc)).rstrip(), secrets), file=sys.stderr, flush=True)
    return jsonify({"ok": False, "error": "internal", "detail": redact(f"{type(exc).__name__}: {exc}", secrets)}), 500

_LOG_MAX = 2000
_log_lines: deque[str] = deque(maxlen=_LOG_MAX)
_log_total = 0
_log_lock = threading.Lock()


_LOGS_KEEP = 5


def _prune_files(directory: Path, pattern: str, keep: int = _LOGS_KEEP) -> None:
    try:
        files = sorted((p for p in directory.glob(pattern) if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _prune_launcher_logs() -> None:
    logs_dir = get_data_dir() / "logs"
    for pattern in ("minecraft_*.log", "launch_failed_*.log", "launcher_*.log"):
        _prune_files(logs_dir, pattern)


def _prune_game_logs(game_dir: Path) -> None:
    _prune_files(game_dir / "logs", "*.log.gz")
    _prune_files(game_dir / "crash-reports", "crash-*.txt")


def _open_launcher_log():
    path = get_data_dir() / "launcher.log"
    try:
        if path.exists():
            path.replace(path.with_name("launcher.log.1"))
    except OSError:
        pass
    try:
        return path.open("a", encoding="utf-8")
    except Exception:
        return None


_log_file = _open_launcher_log()
_prune_launcher_logs()

_HTTP_SECRET_KEYS = {"token", "code", "key", "download_token", "link_token", "access_token", "password", "telegram_url"}
_HTTP_QUIET_PATHS = ("/api/build/unit",)
_HTTP_BODY_LIMIT = 1000
_http_ids = itertools.count(1)


def _redact(value):
    if isinstance(value, dict):
        return {k: ("***" if str(k).lower() in _HTTP_SECRET_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _short(value) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return text if len(text) <= _HTTP_BODY_LIMIT else text[:_HTTP_BODY_LIMIT] + "..."


def _install_http_logging() -> None:
    from urllib.parse import urlsplit
    import requests.sessions

    original = requests.sessions.Session.request
    if getattr(original, "_lota_logged", False):
        return

    def logged_request(self, method, url, *args, **kwargs):
        parts = urlsplit(str(url))
        if not parts.path.startswith("/api/"):
            return original(self, method, url, *args, **kwargs)
        quiet = parts.path.startswith(_HTTP_QUIET_PATHS)
        request_id = next(_http_ids)
        sent = []
        if kwargs.get("params"):
            sent.append(f"params={_short(_redact(dict(kwargs['params'])))}")
        if kwargs.get("json") is not None:
            sent.append(f"json={_short(_redact(kwargs['json']))}")
        elif isinstance(kwargs.get("data"), dict):
            sent.append(f"data={_short(_redact(kwargs['data']))}")
        if kwargs.get("files"):
            sent.append(f"files={list(kwargs['files'])}")
        sent_text = " ".join(sent)
        target = f"{method.upper()} {parts.path}"
        if not quiet:
            print(f"[http] #{request_id} -> {method.upper()} {parts.scheme}://{parts.netloc}{parts.path} {sent_text}".rstrip(), flush=True)
        started = time.monotonic()
        try:
            response = original(self, method, url, *args, **kwargs)
        except Exception as exc:
            print(f"[http] #{request_id} <- FAILED {target} after {time.monotonic() - started:.2f}s: {type(exc).__name__}: {exc}" + (f" | sent {sent_text}" if quiet else ""), flush=True)
            raise
        elapsed = time.monotonic() - started
        if quiet and response.status_code == 200:
            return response
        body = ""
        content_type = response.headers.get("Content-Type", "")
        if kwargs.get("stream") and response.status_code == 200:
            body = f"<stream {response.headers.get('Content-Length', '?')} bytes>"
        elif content_type.startswith("application/json"):
            try:
                body = _short(_redact(response.json()))
            except ValueError:
                body = _short(response.text)
        elif response.status_code != 200:
            body = _short(response.text or "")
        else:
            body = f"<{content_type or 'binary'} {len(response.content)} bytes>"
        print(f"[http] #{request_id} <- {response.status_code} {target} in {elapsed:.2f}s: {body}" + (f" | sent {sent_text}" if quiet else ""), flush=True)
        return response

    logged_request._lota_logged = True
    requests.sessions.Session.request = logged_request


_install_http_logging()


_hidden_paths: tuple[str, ...] = ()
_hidden_lock = threading.Lock()


def _hide_path(path) -> None:
    global _hidden_paths
    raw = str(path)
    values = {raw, os.path.realpath(raw), Path(raw).as_posix(), Path(os.path.realpath(raw)).as_posix()}
    with _hidden_lock:
        merged = set(_hidden_paths) | {v for v in values if v}
        _hidden_paths = tuple(sorted(merged, key=len, reverse=True))


def _scrub(text: str) -> str:
    for value in _hidden_paths:
        if value in text:
            text = text.replace(value, "<hidden>")
    return text


def _log_append(line: str, persist: bool = True) -> None:
    global _log_total
    line = _scrub(line)
    with _log_lock:
        _log_lines.append(line)
        _log_total += 1
        if persist and _log_file is not None:
            try:
                _log_file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
                _log_file.flush()
            except Exception:
                pass


class _LogWriter(io.TextIOBase):
    def __init__(self, original, prefix: str = ""):
        self._orig = original
        self._prefix = prefix
        self._buf = ""

    def write(self, s: str) -> int:
        if self._orig:
            try:
                self._orig.write(_scrub(s))
                self._orig.flush()
            except Exception:
                pass
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                _log_append(f"{self._prefix}{line}")
        return len(s)

    def flush(self):
        if self._orig:
            try:
                self._orig.flush()
            except Exception:
                pass


sys.stdout = _LogWriter(sys.__stdout__, "")
sys.stderr = _LogWriter(sys.__stderr__, "[ERR] ")
import logging as _logging

_ACCESS_LOG_RE = re.compile(r'"[A-Z]+ \S+ HTTP/[\d.]+" \d{3}')


class _WerkzeugFilter(_logging.Filter):
    def filter(self, record: _logging.LogRecord) -> bool:
        return record.levelno > _logging.INFO or not _ACCESS_LOG_RE.search(_ANSI_RE.sub("", record.getMessage()))

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_QUERY_SECRET_RE = re.compile(r"\b(token|link_token|download_token|access_token|code|key)=[^&\s\"]+")


class _ConsoleLogHandler(_logging.Handler):
    def emit(self, record: _logging.LogRecord) -> None:
        try:
            text = _scrub(_QUERY_SECRET_RE.sub(r"\1=***", _ANSI_RE.sub("", self.format(record))))
        except Exception:
            return
        if record.levelno >= _logging.ERROR:
            prefix, stream = "[ERR] ", sys.__stderr__
        elif record.levelno >= _logging.WARNING:
            prefix, stream = "[WARN] ", sys.__stderr__
        else:
            prefix, stream = "", sys.__stdout__
        if stream:
            try:
                stream.write(text + "\n")
                stream.flush()
            except Exception:
                pass
        for line in text.splitlines():
            if line.strip():
                _log_append(f"{prefix}{line}")


_root_logger = _logging.getLogger()
_root_logger.handlers[:] = [_ConsoleLogHandler()]
_root_logger.setLevel(_logging.INFO)
_logging.captureWarnings(True)
_logging.getLogger("werkzeug").addFilter(_WerkzeugFilter())


_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _new_task(kind: str = "generic") -> str:
    import uuid
    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {"state": "running", "progress": 0, "error": None, "result": None, "kind": kind, "started": time.monotonic()}
    print(f"[task] {task_id} ({kind}) started", flush=True)
    return task_id


def _task_done(task_id: str, error: str | None = None, result: dict | None = None):
    with _tasks_lock:
        task = _tasks.get(task_id)
        if task is not None:
            task["state"] = "error" if error else "done"
            task["error"] = error
            task["result"] = result
    if task is None:
        return
    took = time.monotonic() - task.get("started", time.monotonic())
    if error:
        print(f"[task] {task_id} ({task.get('kind')}) failed after {took:.1f}s: {error}", flush=True)
    else:
        print(f"[task] {task_id} ({task.get('kind')}) done in {took:.1f}s" + (f": {_short(_redact(result))}" if result else ""), flush=True)


def _task_progress(task_id: str, progress: int | None = None, file: str | None = None, speed: float | None = None):
    with _tasks_lock:
        if task_id in _tasks:
            if progress is not None:
                _tasks[task_id]["progress"] = progress
            if file is not None:
                _tasks[task_id]["file"] = file
            if speed is not None:
                _tasks[task_id]["speed"] = speed


class _SpeedMeter:
    def __init__(self, window: float = 2.0):
        self._lock = threading.Lock()
        self._samples: deque[tuple[float, int]] = deque()
        self._window = window

    def _trim(self, now: float) -> None:
        while self._samples and now - self._samples[0][0] > self._window:
            self._samples.popleft()

    def add(self, size: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._samples.append((now, size))
            self._trim(now)

    def speed(self) -> float:
        now = time.monotonic()
        with self._lock:
            self._trim(now)
            return sum(size for _, size in self._samples) / self._window


def _progress_logger(prefix: str, step: int = 10):
    last = {"bucket": -1}

    def log(done: int, total: int, speed: float = 0) -> None:
        if total <= 0:
            return
        bucket = min(100, int(done * 100 / total)) // step * step
        if bucket <= last["bucket"]:
            return
        last["bucket"] = bucket
        print(f"{prefix} {bucket}% ({done / 1048576:.1f}/{total / 1048576:.1f} MB, {speed / 1048576:.1f} MB/s)", flush=True)

    return log


def _lib() -> LibraryService:
    return LibraryService(get_data_dir(), get_api_base)


UPDATE_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
GITHUB_REPO = "Xikki-tar/lota-launcher"
_MACHINE_ALIASES = {"amd64": "x86_64", "x64": "x86_64", "x86-64": "x86_64", "aarch64": "arm64"}


def _detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    machine = _MACHINE_ALIASES.get(machine, machine)
    return f"{system}-{machine}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 256)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _appimage_path() -> Path | None:
    raw = os.environ.get("APPIMAGE", "").strip()
    return Path(raw) if raw else None


def _macos_app_bundle_path() -> Path | None:
    if platform.system() != "Darwin" or not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def _update_mode() -> str | None:
    system = platform.system()
    if system == "Windows":
        return "external" if getattr(sys, "frozen", False) else None
    if system == "Darwin":
        return "macos-app" if _macos_app_bundle_path() is not None else None
    return "appimage" if _appimage_path() is not None else None


def _check_launcher_update(local_version: str) -> dict | None:
    payload = {"platform": _detect_platform(), "version": local_version, "channel": UPDATE_CHANNEL}
    try:
        resp = http.post(f"{get_api_base()}/api/launcher/check", json=payload, timeout=15)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code != 200:
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not isinstance(data, dict) or data.get("ok") is not True:
        return {"ok": False, "error": str(data.get("error")) if isinstance(data, dict) else "bad_response"}
    return data


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(v or "0").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _check_launcher_update_github(local_version: str) -> dict | None:
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    print(f"[update] github check: GET {url}, local version {local_version}", flush=True)
    try:
        resp = http.get(
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=15,
        )
    except Exception as exc:
        print(f"[update] github check failed: {type(exc).__name__}: {exc}", flush=True)
        return {"ok": False, "error": str(exc)}
    if resp.status_code != 200:
        print(f"[update] github check failed: HTTP {resp.status_code}: {_short(resp.text or '')}", flush=True)
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError as exc:
        print(f"[update] github check: bad json: {exc}", flush=True)
        return {"ok": False, "error": str(exc)}

    assets = data.get("assets") or []
    print(f"[update] github release {data.get('tag_name')}: assets {[a.get('name') for a in assets]}", flush=True)
    asset = next((a for a in assets if str(a.get("name") or "").endswith(".AppImage")), None)
    if not asset:
        return {"ok": False, "error": "no_appimage_asset"}

    sha256 = ""
    sha_asset = next((a for a in assets if str(a.get("name") or "").endswith(".sha256")), None)
    if sha_asset:
        try:
            sha_resp = http.get(sha_asset["browser_download_url"], timeout=15)
            sha256 = sha_resp.text.strip().split()[0]
        except Exception as exc:
            print(f"[update] github sha256 fetch failed: {type(exc).__name__}: {exc}", flush=True)
            sha256 = ""
    else:
        print("[update] github release has no .sha256 asset, update will not be verified by hash", flush=True)

    remote_version = str(data.get("tag_name") or "").strip().lstrip("vV")
    return {
        "ok": True,
        "update_available": _version_tuple(remote_version) > _version_tuple(local_version),
        "version": remote_version,
        "url": asset.get("browser_download_url") or "",
        "sha256": sha256,
        "size": int(asset.get("size") or 0),
    }


@app.get("/update/check")
def update_check():
    from auth.settings import UPDATES_DISABLED
    mode = None if UPDATES_DISABLED else _update_mode()
    if mode not in ("appimage", "macos-app"):
        return jsonify({"ok": True, "mode": mode, "update_available": False})
    local_version = str(request.args.get("version") or "0.0.0")
    data = (
        _check_launcher_update_github(local_version)
        if mode == "appimage"
        else _check_launcher_update(local_version)
    )
    if not data or data.get("ok") is not True:
        return jsonify({"ok": False, "mode": mode, "error": data.get("error") if data else "check_failed"})
    data["mode"] = mode
    return jsonify(data)


def _macos_app_update_blocker(target_app: Path) -> str | None:
    if "/AppTranslocation/" in str(target_app) or not os.access(target_app.parent, os.W_OK):
        return t("update_error_move_to_applications")
    return None


def _install_macos_app_update(zip_path: Path, target_app: Path) -> str:
    import shutil
    import subprocess

    extract_dir = target_app.parent / f".lota-update-extract-{os.getpid()}"
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    print(f"[update] macos: extracting {zip_path.name} into {extract_dir}", flush=True)
    try:
        proc = subprocess.run(
            ["/usr/bin/ditto", "-x", "-k", str(zip_path), str(extract_dir)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ditto failed: {(proc.stderr or proc.stdout).strip()}")
        new_app = next((p for p in extract_dir.iterdir() if p.suffix == ".app"), None)
        if new_app is None:
            raise RuntimeError("update archive has no .app bundle")
        if not os.access(new_app / "Contents" / "MacOS" / "lota-launcher", os.X_OK):
            raise RuntimeError("update archive has no executable launcher binary")

        backup = target_app.with_name(target_app.name + ".old")
        shutil.rmtree(backup, ignore_errors=True)
        print(f"[update] macos: replacing {target_app} with {new_app.name} (backup {backup.name})", flush=True)
        os.replace(target_app, backup)
        try:
            os.replace(new_app, target_app)
        except Exception as exc:
            print(f"[update] macos: replace failed, restoring backup: {type(exc).__name__}: {exc}", flush=True)
            os.replace(backup, target_app)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return str(target_app / "Contents" / "MacOS" / "lota-launcher")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


_UPDATE_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}


def _trusted_update_url(url: str) -> bool:
    from urllib.parse import urlsplit
    from auth.api_base import get_api_candidates
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    hosts = set(_UPDATE_HOSTS)
    for base in get_api_candidates():
        host = urlsplit(base).hostname
        if host:
            hosts.add(host.lower())
    return parts.hostname.lower() in hosts


@app.post("/update/install")
def update_install():
    mode = _update_mode()
    if mode not in ("appimage", "macos-app"):
        return jsonify({"ok": False, "error": "unsupported"}), 400

    body = request.json or {}
    url = str(body.get("url") or "").strip()
    sha256 = str(body.get("sha256") or "").strip().lower()
    size = int(body.get("size") or 0)
    version = str(body.get("version") or "").strip()

    if not url:
        return jsonify({"ok": False, "error": "missing_url"}), 400
    if url.startswith("/"):
        url = f"{get_api_base()}{url}"
    if not _trusted_update_url(url):
        print(f"[update] install rejected: untrusted url {url.split('?', 1)[0]}", flush=True)
        return jsonify({"ok": False, "error": "untrusted_url"}), 400

    target_path = _appimage_path() if mode == "appimage" else _macos_app_bundle_path()
    task_id = _new_task(kind="update")
    print(f"[update] install start: version={version} mode={mode} url={url.split('?', 1)[0]} size={size or '?'} sha256={sha256 or '-'} target={target_path}", flush=True)

    def run():
        tmp_path: Path | None = None
        try:
            blocker = _macos_app_update_blocker(target_path) if mode == "macos-app" else None
            if blocker:
                raise RuntimeError(blocker)
            fd, tmp_name = tempfile.mkstemp(prefix="lota-update-", dir=str(target_path.parent))
            os.close(fd)
            tmp_path = Path(tmp_name)

            digest = hashlib.sha256()
            downloaded = 0
            meter = _SpeedMeter()
            log_progress = _progress_logger("[update] download")
            file_name = Path(url.split("?", 1)[0]).name or "update"
            with http.get(url, stream=True, timeout=120) as resp:
                print(f"[update] download response: HTTP {resp.status_code}, Content-Length {resp.headers.get('Content-Length') or '?'}, final url {resp.url.split('?', 1)[0]}", flush=True)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                total = int(resp.headers.get("Content-Length") or 0) or size
                with tmp_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        meter.add(len(chunk))
                        _task_progress(
                            task_id,
                            min(95, int(downloaded * 95 / total)) if total > 0 else None,
                            file=file_name,
                            speed=meter.speed(),
                        )
                        log_progress(downloaded, total, meter.speed())
            _task_progress(task_id, speed=0)

            actual_sha256 = digest.hexdigest().lower()
            print(f"[update] downloaded {downloaded} bytes, sha256 {actual_sha256}", flush=True)
            if size and downloaded != size:
                raise RuntimeError(f"size mismatch: expected {size}, got {downloaded}")
            if sha256 and actual_sha256 != sha256:
                raise RuntimeError("sha256 mismatch")

            if mode == "appimage":
                mode_bits = tmp_path.stat().st_mode
                os.chmod(tmp_path, mode_bits | 0o111)
                os.replace(tmp_path, target_path)
                print(f"[update] appimage replaced: {target_path}", flush=True)
                relaunch_path = str(target_path)
                tmp_path = None
            else:
                relaunch_path = _install_macos_app_update(tmp_path, target_path)
                tmp_path.unlink(missing_ok=True)
                tmp_path = None

            _task_progress(task_id, 100)
            _task_done(task_id, result={"relaunch_path": relaunch_path, "version": version})
            print(f"[update] install done: version={version}", flush=True)
        except Exception as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            _task_done(task_id, error=str(exc))
            print(f"[update] install failed: version={version}: {exc}", flush=True)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "task_id": task_id})


@app.get("/auth/load")
def auth_load():
    data = load_auth_data()
    return jsonify(data)


@app.post("/auth/save")
def auth_save():
    global _skin_sync_attempted
    body = request.json or {}
    save_auth_data(
        str(body.get("token") or ""),
        str(body.get("username") or ""),
        str(body.get("status") or "active"),
        int(body.get("sub_level") or 0),
        str(body.get("player_uuid") or ""),
    )
    _skin_sync_attempted = False
    return jsonify({"ok": True})


@app.post("/auth/clear")
def auth_clear_route():
    clear_auth_data()
    return jsonify({"ok": True})


@app.get("/settings")
def settings_load():
    return jsonify(load_settings())


_EDITABLE_SETTINGS = {
    "language", "java_path", "mem_min_mb", "mem_max_mb", "jvm_args",
    "auto_java_version", "disable_openal", "debug_mode",
}


@app.post("/settings")
def settings_save():
    body = request.json or {}
    settings = load_settings()
    updates = {k: v for k, v in body.items() if k in _EDITABLE_SETTINGS}
    changes = [f"{k}: {settings.get(k)!r} -> {v!r}" for k, v in updates.items() if str(settings.get(k)) != str(v)]
    ignored = sorted(k for k in body if k not in _EDITABLE_SETTINGS)
    print(f"[settings] changed: {'; '.join(changes) or 'nothing'}" + (f" (ignored non-editable keys: {ignored})" if ignored else ""), flush=True)
    settings.update(updates)
    save_settings(settings)
    set_language(str(settings.get("language") or ""))
    return jsonify({"ok": True})


@app.get("/i18n")
def i18n():
    from window.translations import TRANSLATIONS
    settings = load_settings()
    lang = str(settings.get("language") or "Русский")
    trans = TRANSLATIONS.get(lang) or TRANSLATIONS.get("Русский") or {}
    return jsonify({"language": lang, "strings": trans})


@app.get("/java/version")
def java_version():
    import shutil
    from auth.java_finder import JAVA_EXECUTABLE_NAMES, get_java_major_version, is_safe_java_path
    path = str(request.args.get("path") or "").strip()
    if path.lower() in JAVA_EXECUTABLE_NAMES:
        resolved = shutil.which(path)
    else:
        resolved = path if is_safe_java_path(path) else None
    if not resolved:
        print(f"[java] version check: {path!r} rejected (not on PATH, not a java executable or not executable)", flush=True)
        return jsonify({"path": path, "major": None, "found": False})
    major = get_java_major_version(resolved)
    print(f"[java] version check: {path!r} -> {resolved}, major {major}", flush=True)
    return jsonify({"path": path, "major": major, "found": True})


@app.get("/java/scan")
def java_scan():
    from auth.java_finder import find_java_candidates, get_java_version, get_java_major_version
    candidates = find_java_candidates()
    result = []
    for path in candidates:
        major = get_java_major_version(path)
        result.append({"path": path, "major": major})
    print(f"[java] scan found {len(result)}: " + (", ".join(f"{c['path']} (Java {c['major']})" for c in result) or "nothing"), flush=True)
    return jsonify({"candidates": result})


def _proxy_post(path: str, body: dict) -> tuple[dict, int]:
    try:
        base = get_api_base()
    except Exception as e:
        print(f"[backend] proxy POST {path} failed: no api base resolved: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0
    try:
        r = http.post(f"{base}{path}", json=body, timeout=15)
        return r.json() if r.content else {}, r.status_code
    except Exception as e:
        print(f"[backend] proxy POST {base}{path} failed: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0


def _proxy_get(path: str, params: dict) -> tuple[dict, int]:
    try:
        base = get_api_base()
    except Exception as e:
        print(f"[backend] proxy GET {path} failed: no api base resolved: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0
    try:
        r = http.get(f"{base}{path}", params=params, timeout=10)
        return r.json() if r.content else {}, r.status_code
    except Exception as e:
        print(f"[backend] proxy GET {base}{path} failed: {type(e).__name__}: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0


@app.get("/debug/logs")
def debug_logs():
    since = int(request.args.get("since", 0))
    with _log_lock:
        total = _log_total
        first = total - len(_log_lines)
        if since > total:
            since = 0
        start = max(since, first)
        lines = list(itertools.islice(_log_lines, start - first, None)) if start < total else []
    return jsonify({"lines": lines, "total": total})


@app.get("/debug/connection")
def debug_connection():
    from auth.api_base import get_api_candidates
    results: dict = {"candidates": get_api_candidates()}
    try:
        base = get_api_base()
        results["api_base"] = base
        results["ok"] = True
    except Exception as e:
        results["api_base"] = None
        results["ok"] = False
        results["error"] = str(e)
    return jsonify(results)


@app.post("/login")
def login():
    body = request.json or {}
    data, status = _proxy_post("/api/login", body)
    return jsonify({"ok": status == 200 and data.get("ok"), "status": status, "data": data})


@app.post("/register/telegram-link")
def register_telegram_link():
    data, status = _proxy_post("/api/register/telegram-link", {})
    return jsonify({"ok": status == 200 and data.get("ok"), "status": status, "data": data})


@app.get("/register/poll")
def register_poll():
    link_token = request.args.get("link_token", "")
    data, status = _proxy_get("/api/register/telegram-status", {"link_token": link_token})
    return jsonify({"ok": status == 200 and data.get("ok"), "status": status, "data": data})


@app.post("/register/complete")
def register_complete():
    body = request.json or {}
    data, status = _proxy_post("/api/register/complete", body)
    return jsonify({"ok": status == 200 and data.get("ok"), "status": status, "data": data})


@app.get("/register/link")
def register_link_load():
    return jsonify(load_register_data())


@app.post("/register/link")
def register_link_save():
    body = request.json or {}
    save_register_data(str(body.get("link_token") or ""), str(body.get("telegram_url") or ""))
    return jsonify({"ok": True})


@app.delete("/register/link")
def register_link_clear():
    clear_register_data()
    return jsonify({"ok": True})


# ── Library ───────────────────────────────────────────────────────────────────

@app.get("/library/catalog")
def library_catalog():
    fresh = request.args.get("fresh") == "1"
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    lib = _lib()
    catalog = lib.load_catalog(token, prefer_remote=fresh)
    # инстансы первыми потом сборки по id (новые выше)
    def _sort_key(item):
        is_inst = bool(item.get("is_instance"))
        try:
            bid = -int(item.get("id") or 0)
        except (TypeError, ValueError):
            bid = 0
        return (0 if is_inst else 1, bid)
    sorted_builds = sorted(catalog.builds, key=_sort_key)
    builds = []
    for item in sorted_builds:
        b = dict(item)
        b["_installed"] = lib.is_build_installed(item)
        b["_up_to_date"] = lib.is_build_up_to_date(item) if b["_installed"] else False
        b["_build_key"] = lib.build_key(item)
        builds.append(b)
    settings = load_settings()
    selected = str(settings.get("selected_build") or "")
    print(f"[library] catalog ({'fresh' if fresh else 'cached'}): {len(builds)} builds, selected={selected or '-'}", flush=True)
    for b in builds:
        print(
            f"[library]   {b['_build_key']}: id={b.get('id')} version={b.get('version') or '-'} "
            f"updated_at={lib.expected_build_updated_at(b) or '-'} instance={bool(b.get('is_instance'))} "
            f"installed={b['_installed']} up_to_date={b['_up_to_date']}",
            flush=True,
        )
    return jsonify({
        "builds": builds,
        "selected_build": selected,
    })


@app.post("/library/select")
def library_select():
    body = request.json or {}
    build_key = str(body.get("build_key") or "")
    settings = load_settings()
    print(f"[library] selected build: {settings.get('selected_build') or '-'} -> {build_key or '-'}", flush=True)
    settings["selected_build"] = build_key
    save_settings(settings)
    return jsonify({"ok": True})


_active_downloads: dict[str, str] = {}


@app.post("/library/download")
def library_download():
    body = request.json or {}
    build_key = str(body.get("build_key") or "")

    with _tasks_lock:
        existing_task_id = _active_downloads.get(build_key)
        if existing_task_id and _tasks.get(existing_task_id, {}).get("state") == "running":
            print(f"[library] download already running: build_key={build_key} task={existing_task_id}", flush=True)
            return jsonify({"ok": True, "task_id": existing_task_id})

    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")

    lib = _lib()
    catalog = lib.load_catalog(token)
    item = next((b for b in catalog.builds if lib.build_key(b) == build_key), None)
    if not item:
        print(f"[library] download rejected: build_key={build_key} not in catalog ({len(catalog.builds)} builds)", flush=True)
        return jsonify({"ok": False, "error": "build_not_found"}), 404

    source_item = None
    if item.get("is_instance"):
        source_id = item.get("_source_build_id")
        source_item = next((b for b in catalog.builds if not b.get("is_instance") and b.get("id") == source_id), None)
        print(f"[library] instance {build_key} uses source build id={source_id}: {'found' if source_item else 'NOT FOUND in catalog'}", flush=True)

    task_id = _new_task(kind="download")
    with _tasks_lock:
        _active_downloads[build_key] = task_id
    print(f"[library] download start: build_key={build_key} build_id={(source_item or item).get('id')} task={task_id} dir={lib.build_install_dir(item)}", flush=True)

    def run():
        try:
            meter = _SpeedMeter()
            log_progress = _progress_logger(f"[library] download {build_key}:")

            def on_progress(name: str, delta: int, done: int, total: int):
                if delta > 0:
                    meter.add(delta)
                _task_progress(
                    task_id,
                    min(99, int(done * 99 / total)) if total > 0 else None,
                    file=name or None,
                    speed=meter.speed(),
                )
                log_progress(done, total, meter.speed())

            lib.sync_build(item, token=token, source_item=source_item, progress=on_progress)
            _task_progress(task_id, 100, speed=0)
            _task_done(task_id)
            print(f"[library] download done: build_key={build_key}", flush=True)
        except Exception as exc:
            print(f"[library] download failed: build_key={build_key}: {type(exc).__name__}: {exc}", flush=True)
            _task_done(task_id, str(exc))
        finally:
            with _tasks_lock:
                if _active_downloads.get(build_key) == task_id:
                    del _active_downloads[build_key]

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "task_id": task_id})


@app.delete("/library/build")
def library_delete():
    body = request.json or {}
    build_key = str(body.get("build_key") or "")
    lib = _lib()
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    catalog = lib.load_catalog(token)
    item = next((b for b in catalog.builds if lib.build_key(b) == build_key), None)
    if not item:
        print(f"[library] delete rejected: build_key={build_key} not in catalog", flush=True)
        return jsonify({"ok": False, "error": "build_not_found"}), 404
    build_dir = lib.build_install_dir(item)
    removed = lib.delete_build_files(item)
    print(f"[library] build deleted: build_key={build_key} dir={build_dir} existed={removed}", flush=True)
    settings = load_settings()
    if settings.get("selected_build") == build_key:
        settings["selected_build"] = ""
        save_settings(settings)
        print(f"[library] selected build cleared because {build_key} was deleted", flush=True)
    return jsonify({"ok": True})


@app.post("/library/instance/create")
def library_instance_create():
    body = request.json or {}
    lib = _lib()
    instance = lib.create_instance(body)
    return jsonify({"ok": True, "instance": instance})


@app.post("/library/instance/update")
def library_instance_update():
    body = request.json or {}
    target_id = str(body.get("id") or "")
    if not target_id:
        return jsonify({"ok": False, "error": "missing id"}), 400
    lib = _lib()
    lib.update_instance(target_id, body)
    return jsonify({"ok": True})


@app.delete("/library/instance")
def library_instance_delete():
    body = request.json or {}
    target_id = str(body.get("id") or "")
    if not target_id:
        return jsonify({"ok": False, "error": "missing id"}), 400
    lib = _lib()
    lib.delete_instance(target_id)
    settings = load_settings()
    build_key = f"instance-{target_id}"
    if settings.get("selected_build", "").startswith("instance-"):
        print(f"[library] selected build {settings.get('selected_build')} cleared after deleting instance {target_id}", flush=True)
        settings["selected_build"] = ""
        save_settings(settings)
    return jsonify({"ok": True})


@app.get("/library/build/folder")
def library_build_folder():
    build_key = request.args.get("build_key", "")
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    lib = _lib()
    catalog = lib.load_catalog(token)
    item = next((b for b in catalog.builds if lib.build_key(b) == build_key), None)
    if not item:
        return jsonify({"ok": False, "error": "not_found"}), 404
    folder = str(lib.build_install_dir(item))
    return jsonify({"ok": True, "path": folder})


@app.get("/library/image")
def library_image():
    path = request.args.get("path", "").strip()
    if not path:
        return Response(status=400)
    lib = _lib()
    for base in (lib.paths.cache_dir, lib.local_asset_dir()):
        resolved = _safe_child(base, path)
        if resolved is not None and resolved.is_file():
            return send_file(str(resolved))
    return Response(status=404)


@app.get("/task/<task_id>")
def task_status(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "not_found"}), 404
    return jsonify(task)


@app.get("/tasks/active_downloads")
def tasks_active_downloads():
    with _tasks_lock:
        count = sum(1 for t in _tasks.values() if t.get("kind") == "download" and t.get("state") == "running")
    return jsonify({"active": count > 0, "count": count})


class _LaunchReport:
    def __init__(self):
        self.lines: list[str] = []
        self.started = time.monotonic()
        self.last = self.started

    def add(self, text: str, console: bool = True) -> None:
        line = _scrub(f"[launch] {text}")
        self.lines.append(line)
        if console:
            print(line, flush=True)

    def section(self, title: str) -> None:
        self.add(f"=== {title} ===")

    def step(self, name: str) -> None:
        now = time.monotonic()
        self.add(f"{name}: {now - self.last:.2f}s (total {now - self.started:.2f}s)")
        self.last = now

    def write_to(self, path: Path) -> None:
        try:
            with path.open("w", encoding="utf-8") as out:
                out.write("\n".join(self.lines) + "\n\n")
        except OSError:
            pass


_SECRET_ARGS = ("--accessToken", "--clientId", "--xuid")


def _report_environment(report: _LaunchReport, settings: dict) -> None:
    import platform as _platform
    report.section("environment")
    report.add(f"time: {datetime.now().isoformat(timespec='seconds')}")
    report.add(f"os: {_platform.platform()} ({_platform.machine()})")
    report.add(f"python: {sys.version.split()[0]}, frozen: {bool(getattr(sys, 'frozen', False))}")
    report.add(f"data dir: {get_data_dir()}")
    try:
        report.add(f"api base: {get_api_base()}")
    except Exception as exc:
        report.add(f"api base: unresolved ({type(exc).__name__}: {exc})")
    report.section("settings")
    for key in ("auto_java_version", "java_path", "mem_min_mb", "mem_max_mb", "jvm_args", "disable_openal", "language", "selected_build"):
        report.add(f"{key}: {settings.get(key)!r}")


def _report_java(report: _LaunchReport, java_path: str, mode: str) -> str:
    from auth.java_finder import get_java_major_version, get_java_version
    import shutil as _shutil
    resolved = java_path if os.path.isfile(java_path) else (_shutil.which(java_path) or java_path)
    report.section("java")
    report.add(f"mode: {mode}")
    report.add(f"path: {java_path}")
    if resolved != java_path:
        report.add(f"resolved: {resolved}")
    version = get_java_version(resolved)
    report.add(f"version: {version}")
    report.add(f"major: {get_java_major_version(resolved)}")
    return version


def _report_build(report: _LaunchReport, build_key: str, game_dir: Path) -> None:
    from services.build_sync import CLOSED_DIR, load_state
    report.section("build")
    report.add(f"build key: {build_key}")
    report.add(f"game dir: {game_dir}")
    state = load_state(game_dir)
    units = state.get("units") or {}
    closed = [p for p, e in units.items() if isinstance(e, dict) and e.get("closed")]
    report.add(f"build id: {state.get('build_id')}, units: {len(units)}, closed: {len(closed)}")
    for path in closed:
        payload = game_dir / CLOSED_DIR / str(units[path].get("payload") or "")
        size = payload.stat().st_size if payload.is_file() else None
        report.add(f"closed unit: {path} -> {payload.name} ({size if size is not None else 'MISSING'} bytes)")
    mods_dir = game_dir / "mods"
    mods = sorted(p.name for p in mods_dir.glob("*.jar")) if mods_dir.is_dir() else []
    disabled = sorted(p.name for p in mods_dir.glob("*.disabled")) if mods_dir.is_dir() else []
    report.add(f"mods: {len(mods)} enabled, {len(disabled)} disabled")
    for name in mods:
        report.add(f"  mod: {name}", console=False)
    for name in disabled:
        report.add(f"  disabled: {name}", console=False)


def _report_bundle(report: _LaunchReport, bundle_state) -> None:
    report.section("protected content")
    if bundle_state is None:
        report.add("none")
        return
    _hide_path(bundle_state.temp_dir)
    for link in bundle_state.links:
        report.add(f"linked: {link}")
    for original, hidden in bundle_state.hidden:
        report.add(f"hidden during game: {original} -> {hidden.name}")
    report.add(f"overlay files: {len(bundle_state.written)}, backups: {len(bundle_state.backups)}, disabled mods: {len(bundle_state.disabled)}")
    for original, renamed in bundle_state.disabled:
        report.add(f"  disabled duplicate: {original.name}", console=False)
    for arg in bundle_state.game_args:
        report.add(f"game arg: {arg}")


def _report_version(report: _LaunchReport, prepared) -> None:
    data = prepared.version_json
    report.section("minecraft")
    report.add(f"version: {prepared.version_id} (inherits {data.get('inheritsFrom') or '-'})")
    report.add(f"main class: {data.get('mainClass')}")
    report.add(f"asset index: {(data.get('assetIndex') or {}).get('id')}")
    report.add(f"libraries: {len(data.get('libraries') or [])}")
    report.add(f"versions dir: {prepared.versions_dir}")
    report.add(f"libraries dir: {prepared.libraries_dir}")
    report.add(f"assets dir: {prepared.assets_dir}")
    report.add(f"natives dir: {prepared.natives_dir}")


def _report_command(report: _LaunchReport, argv: list[str], cwd) -> None:
    report.section("command")
    report.add(f"cwd: {cwd}")
    report.add(f"executable: {argv[0] if argv else '-'}")
    hide_next = False
    cp_next = False
    for index, arg in enumerate(argv[1:], start=1):
        if hide_next:
            report.add(f"arg[{index}]: ***")
            hide_next = False
            continue
        if cp_next:
            entries = [e for e in arg.split(os.pathsep) if e]
            missing = [e for e in entries if not os.path.exists(e)]
            report.add(f"arg[{index}]: <classpath: {len(entries)} entries, {len(missing)} missing>")
            for entry in entries:
                report.add(f"  cp: {entry}", console=False)
            for entry in missing:
                report.add(f"  cp MISSING: {entry}")
            cp_next = False
            continue
        report.add(f"arg[{index}]: {arg}")
        if arg in _SECRET_ARGS:
            hide_next = True
        elif arg in ("-cp", "-classpath", "--class-path"):
            cp_next = True


_play_state: dict = {"state": "idle", "status": "", "error": None}
_play_lock = threading.Lock()
_play_meter: _SpeedMeter | None = None

def _auth_secrets() -> list[str]:
    try:
        return [str((load_auth_data() or {}).get("token") or "")]
    except Exception:
        return []


def _new_log_path(prefix: str) -> Path:
    path = get_data_dir() / "logs" / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_failed_report(report: _LaunchReport) -> Path | None:
    try:
        path = _new_log_path("launch_failed")
    except OSError as exc:
        print(f"[launch] report not saved: {exc}", flush=True)
        return None
    report.write_to(path)
    _prune_launcher_logs()
    print(f"[launch] report saved: {path}", flush=True)
    return path if path.is_file() else None


def _publish_failure(failure: PlayFailure, context: dict[str, str], log_path: Path | None) -> None:
    header = [f"{t('play_details_log')}: {log_path}"] if log_path else []
    header.append(f"OS: {platform.platform()} ({platform.machine()})")
    if context.get("java"):
        header.append(f"Java: {context['java']}")
    if context.get("build"):
        header.append(f"{t('play_details_build')}: {context['build']}")
    secrets = _auth_secrets()
    with _play_lock:
        _play_state.update({
            "state": "error", "status": "", "pid": None, "_proc": None,
            "error": _scrub(redact(failure.message, secrets)),
            "error_kind": failure.kind,
            "error_details": _scrub(format_details(failure, header, secrets)),
            "log_path": str(log_path) if log_path else None,
        })


def _ensure_forge(versions_dir: Path, java_path: str, game_dir: Path, status) -> str:
    from minecraft.mc_client import ensure_forge_version
    try:
        return ensure_forge_version(versions_dir, java_path, game_dir, status=status)
    except OSError as exc:
        if not is_java_start_failure(exc, java_path):
            raise
        raise JavaError(t("play_error_java_start"), str(exc)) from exc
    except RuntimeError as exc:
        if isinstance(exc, PlayError):
            raise
        if has_java_failure(str(exc)):
            raise JavaError(t("play_error_java_crash"), str(exc)) from exc
        raise PlayError(t("play_error_forge"), str(exc), kind="forge") from exc


def _spawn_game(argv: list[str], cwd) -> subprocess.Popen:
    try:
        return subprocess.Popen(
            argv, cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        if not is_java_start_failure(exc, argv[0]):
            raise
        raise JavaError(t("play_error_java_start"), str(exc)) from exc


def _close_quietly(handle) -> None:
    try:
        handle.close()
    except OSError:
        pass


def _pipe_game_output(proc: subprocess.Popen, log_path: Path, output: GameOutput) -> None:
    secrets = _auth_secrets()
    try:
        log_file = log_path.open("a", encoding="utf-8")
    except OSError as exc:
        print(f"[play] game log unavailable: {exc}", flush=True)
        log_file = None
    try:
        for line in proc.stdout:
            clean = _scrub(redact(line.rstrip(), secrets))
            _log_append("[MC] " + clean, persist=False)
            output.feed(clean)
            if log_file is None:
                continue
            try:
                log_file.write(clean + "\n")
            except OSError as exc:
                print(f"[play] game log write failed: {exc}", flush=True)
                _close_quietly(log_file)
                log_file = None
    finally:
        if log_file is not None:
            _close_quietly(log_file)


@app.get("/play/state")
def play_state():
    meter = _play_meter
    with _play_lock:
        data = {k: v for k, v in _play_state.items() if not k.startswith("_")}
    data["speed"] = meter.speed() if meter else 0
    return jsonify(data)


@app.post("/play/start")
def play_start():
    with _play_lock:
        if _play_state["state"] in ("running", "launched"):
            print(f"[play] start rejected: already {_play_state['state']}", flush=True)
            return jsonify({"ok": False, "error": "already_running"})
        _play_state.update({
            "state": "running", "status": t("play_status_preparing"), "progress": 0, "file": None, "pid": None,
            "error": None, "error_kind": None, "error_details": None, "log_path": None, "_stop_requested": False,
        })

    def run():
        global _play_meter
        from services.play_service import PlayService
        from minecraft.mc_client import set_download_listener
        service = PlayService()
        meter = _SpeedMeter()

        def on_download_bytes(name: str, size: int):
            meter.add(size)
            with _play_lock:
                _play_state["file"] = name

        def set_status(msg):
            with _play_lock:
                changed = _play_state.get("status") != msg
                _play_state["status"] = msg
            if changed:
                print(f"[play] status: {msg}", flush=True)

        def set_progress(done, total=None):
            if total is not None and total > 0:
                p = int(done * 100 / total)
            else:
                p = int(done)
            with _play_lock:
                _play_state["progress"] = max(0, min(100, p))

        _play_meter = meter
        set_download_listener(on_download_bytes)

        report = _LaunchReport()
        context: dict[str, str] = {}
        try:
            settings = load_settings()
            _report_environment(report, settings)
            allow_update = True
            build_key = service.ensure_latest_build_selected(
                status=set_status, progress=set_progress, allow_build_update=allow_update
            )
            if not build_key:
                raise PlayError(t("play_error_build_unavailable"), kind="build")
            context["build"] = build_key
            print(f"[play] build selected: {build_key}", flush=True)
            report.step("build check")

            from services.play_service import prefer_high_performance_gpu, resolve_custom_java, system_openal_jvm_args
            custom_java = str(settings.get("java_path") or "").strip()
            if settings.get("auto_java_version", True) or not custom_java:
                java_mode = "auto (launcher GraalVM 21)" if settings.get("auto_java_version", True) else "auto (no custom path set)"
                java_path = service.ensure_graalvm_21(status=set_status, progress=set_progress)
            else:
                java_mode = "custom"
                java_path = resolve_custom_java(custom_java)
            print(f"[play] java_path: {java_path}", flush=True)
            context["java"] = f"{java_path} ({_report_java(report, java_path, java_mode)})"
            report.step("java ready")

            set_status("Запуск...")

            from minecraft.mc_client import prepare_version
            from minecraft.mc_launch import build_launch_spec

            game_dir = (get_data_dir() / "library" / build_key)
            if not game_dir.is_dir():
                game_dir = get_data_dir() / "minecraft"

            _report_build(report, build_key, game_dir)
            bundle_state = service.prepare_bundle_files(game_dir, hide=_hide_path)
            _report_bundle(report, bundle_state)
            report.step("protected content ready")
            try:
                shared_game_dir = get_data_dir() / "minecraft"
                versions_dir = shared_game_dir / "versions"
                version_id = _ensure_forge(versions_dir, java_path, shared_game_dir, set_status)
                report.step("forge ready")
                prepared = prepare_version(version_id, progress=set_progress, status=set_status)
                _report_version(report, prepared)
                report.step("libraries and assets ready")

                auth = load_auth_data() or {}
                username = str(settings.get("offline_username") or auth.get("username") or "Player")

                mem_max = int(settings.get("mem_max_mb") or 4096)
                mem_min = min(int(settings.get("mem_min_mb") or 1024), mem_max)
                jvm_args = str(settings.get("jvm_args") or "")
                if settings.get("disable_openal"):
                    jvm_args = system_openal_jvm_args(jvm_args)

                spec = build_launch_spec(
                    prepared=prepared,
                    username=username,
                    java_path=java_path,
                    mem_min_mb=mem_min,
                    mem_max_mb=mem_max,
                    jvm_args=jvm_args,
                    game_dir_override=game_dir,
                )

                argv = spec.argv + (bundle_state.game_args if bundle_state else [])
                report.section("launch")
                for line in prefer_high_performance_gpu(java_path):
                    report.add(f"gpu preference: {line}")
                report.add(f"player: {username}")
                report.add(f"memory: -Xms{mem_min}M -Xmx{mem_max}M")
                report.add(f"user jvm args: {settings.get('jvm_args') or '-'}")
                report.add(f"effective jvm args: {jvm_args or '-'}")
                _report_command(report, argv, spec.cwd)

                log_path = _new_log_path("minecraft")
                report.add(f"minecraft log: {log_path}")
                report.write_to(log_path)
                _prune_launcher_logs()
                _prune_game_logs(game_dir)

                started_at = time.time()
                proc = _spawn_game(argv, spec.cwd)
                output = GameOutput()
                log_thread = threading.Thread(target=_pipe_game_output, args=(proc, log_path, output), daemon=True)
                log_thread.start()
                print(f"[play] process launched, pid={proc.pid}", flush=True)
                report.add(f"pid: {proc.pid}")
                report.step("process started")
                with _play_lock:
                    _play_state.update({"state": "launched", "status": "Игра запущена", "pid": proc.pid, "_proc": proc})

                proc.wait()
                log_thread.join(timeout=5)
                print(f"[launch] game ran for {time.monotonic() - report.last:.0f}s, exit code {proc.returncode}", flush=True)
            finally:
                service.cleanup_bundle_files(bundle_state)

            with _play_lock:
                stop_requested = bool(_play_state.get("_stop_requested"))
            if proc.returncode == 0 or stop_requested:
                print("[play] process exited normally" if proc.returncode == 0 else "[play] process stopped by user", flush=True)
                with _play_lock:
                    _play_state.update({"state": "idle", "status": "", "pid": None, "_proc": None, "log_path": str(log_path)})
            else:
                _log_append(f"[MC] process exited with code {proc.returncode}")
                failure = classify_exit(
                    proc.returncode,
                    output,
                    game_dir=game_dir,
                    pid=proc.pid,
                    started_at=started_at,
                    user_jvm_args=str(settings.get("jvm_args") or ""),
                )
                print(f"[play] process exited with code {proc.returncode}: {failure.kind}: {failure.message}", flush=True)
                _publish_failure(failure, context, log_path)

        except Exception as exc:
            secrets = _auth_secrets()
            reason = redact(f"{type(exc).__name__}: {exc}", secrets)
            print(f"[play] launch failed: {reason}", flush=True)
            report.add(f"FAILED after {time.monotonic() - report.started:.2f}s: {reason}")
            for line in traceback.format_exc().splitlines():
                report.add(redact(line, secrets))
            failure = classify_exception(exc)
            report.add(f"error kind: {failure.kind}")
            _publish_failure(failure, context, _save_failed_report(report))
        finally:
            set_download_listener(None)
            _play_meter = None
            with _play_lock:
                _play_state["file"] = None

    def run_guarded():
        try:
            run()
        except Exception as exc:
            print(f"[play] launch thread crashed: {type(exc).__name__}: {exc}", flush=True)
            _publish_failure(classify_exception(exc), {}, None)
        with _play_lock:
            stuck = _play_state["state"] == "running"
        if stuck:
            _publish_failure(PlayFailure("internal", t("play_error_unexpected").format(reason="launch thread stopped")), {}, None)

    try:
        threading.Thread(target=run_guarded, daemon=True).start()
    except RuntimeError as exc:
        _publish_failure(classify_exception(exc), {}, None)
        raise
    return jsonify({"ok": True})


@app.post("/play/stop")
def play_stop():
    with _play_lock:
        proc = _play_state.get("_proc")
        launched = proc is not None and _play_state.get("state") == "launched"
        if launched:
            _play_state["_stop_requested"] = True
    if launched:
        try:
            proc.terminate()
            print(f"[play] process terminated, pid={proc.pid}", flush=True)
        except Exception as exc:
            print(f"[play] terminate failed: {exc}", flush=True)
    return jsonify({"ok": True})


def _parse_news_date(value) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.min
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return datetime.min


def _news_cache_path() -> Path:
    return get_data_dir() / "news_cache" / "news.json"


def _load_cached_news() -> list:
    path = _news_cache_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _save_cached_news(items: list) -> None:
    path = _news_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/news")
def news():
    if request.args.get("fresh") != "1":
        items = _load_cached_news()
        print(f"[news] served {len(items)} cached items", flush=True)
        return jsonify({"ok": True, "items": items})

    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    try:
        base = get_api_base()
        r = http.post(f"{base}/api/news/check", json={"token": token, "hash": ""}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else {}
            items = list(manifest.get("items") or []) if isinstance(manifest, dict) else []
            items.sort(key=lambda x: _parse_news_date(x.get("date")), reverse=True)
            _save_cached_news(items)
            print(f"[news] fetched {len(items)} items: " + ", ".join(f"{x.get('date')} {x.get('title')!r}" for x in items[:10] if isinstance(x, dict)), flush=True)
            return jsonify({"ok": True, "items": items})
        print(f"[news] fetch failed: HTTP {r.status_code}", flush=True)
        return jsonify({"ok": False, "items": [], "status": r.status_code})
    except Exception as exc:
        print(f"[news] fetch failed: {type(exc).__name__}: {exc}", flush=True)
        return jsonify({"ok": False, "items": [], "error": "conn_refused"})


@app.get("/news/image")
def news_image():
    rel_path = request.args.get("path", "").replace("\\", "/").strip().lstrip("/")
    if not rel_path:
        return Response(status=400)
    trimmed = rel_path[len("images/"):] if rel_path.startswith("images/") else rel_path
    cache_path = _safe_child(get_data_dir() / "news_cache" / "images", trimmed)
    if cache_path is None:
        return Response(status=400)
    if cache_path.is_file():
        return send_file(str(cache_path))
    try:
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "")
        base = get_api_base()
        r = http.get(f"{base}/api/news/image", params={"token": token, "path": rel_path}, timeout=10)
        if r.status_code == 200:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(r.content)
            print(f"[news] image cached: {rel_path} ({len(r.content)} bytes)", flush=True)
            return Response(r.content, content_type=r.headers.get("Content-Type", "image/png"))
        print(f"[news] image {rel_path} not available: HTTP {r.status_code}", flush=True)
    except Exception as exc:
        print(f"[news] image {rel_path} failed: {type(exc).__name__}: {exc}", flush=True)
    return Response(status=404)


_skin_sync_attempted = False
_skin_sync_lock = threading.Lock()


def _extract_skin_profile(data):
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                profile = _extract_skin_profile(item)
                if profile:
                    return profile
        return None
    if not isinstance(data, dict):
        return None

    direct_hash = str(data.get("skin_hash") or data.get("hash") or "").strip()
    if direct_hash:
        return data

    for key in ("profile", "result", "data", "player", "entry"):
        candidate = data.get(key)
        if isinstance(candidate, dict):
            profile = _extract_skin_profile(candidate)
            if profile:
                return profile

    for key in ("profiles", "results", "players", "entries", "items"):
        candidate = data.get(key)
        if isinstance(candidate, dict):
            for item in candidate.values():
                if isinstance(item, dict):
                    profile = _extract_skin_profile(item)
                    if profile:
                        return profile
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, dict):
                    profile = _extract_skin_profile(item)
                    if profile:
                        return profile
    return None


def _sync_skin_from_server() -> dict:
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "").strip()
    player_uuid = str(auth.get("player_uuid") or "").strip()
    username = str(auth.get("username") or "").strip()
    if not token or (not player_uuid and not username):
        return {"ok": False, "error": "no_profile_identity"}

    identity_payload = {}
    if player_uuid:
        identity_payload["player_uuid"] = player_uuid
    if username:
        identity_payload["username"] = username

    try:
        resp = http.post(
            f"{get_api_base()}/api/skins/profiles/check",
            json={"token": token, "players": [identity_payload]},
            timeout=10,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if resp.status_code != 200:
        return {"ok": False, "error": f"http_{resp.status_code}"}
    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "bad_response"}

    profile_data = _extract_skin_profile(data)
    if not profile_data:
        return {"ok": False, "error": "profile_not_found"}

    skin_hash = str(profile_data.get("skin_hash") or profile_data.get("hash") or "").strip()
    if not skin_hash:
        return {"ok": False, "error": "skin_hash_missing"}

    model = str(profile_data.get("model") or profile_data.get("skin_model") or "classic").strip().lower()
    if model not in ("classic", "slim"):
        model = "classic"

    try:
        file_resp = http.get(
            f"{get_api_base()}/api/skins/file/{skin_hash}",
            params={"token": token},
            timeout=15,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if file_resp.status_code != 200:
        return {"ok": False, "error": f"skin_file_http_{file_resp.status_code}"}

    target_path = get_data_dir() / "skin.png"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(file_resp.content)
    save_skin_model(model)
    return {"ok": True, "path": str(target_path), "model": model, "skin_hash": skin_hash}


def _ensure_skin_cached() -> None:
    global _skin_sync_attempted
    if (get_data_dir() / "skin.png").exists():
        return
    with _skin_sync_lock:
        if _skin_sync_attempted:
            return
        _skin_sync_attempted = True
    print("[skin] no local skin.png, syncing from server", flush=True)
    try:
        result = _sync_skin_from_server()
    except Exception as exc:
        print(f"[skin] sync crashed: {type(exc).__name__}: {exc}", flush=True)
        return
    print(f"[skin] sync result: {_short(result)}", flush=True)


@app.get("/skin/head")
def skin_head():
    from PIL import Image as PilImage
    size = min(max(int(request.args.get("size", 40)), 8), 256)
    _ensure_skin_cached()
    skin_path = get_data_dir() / "skin.png"
    try:
        if not skin_path.exists():
            raise FileNotFoundError
        skin = PilImage.open(skin_path).convert("RGBA")
        if skin.width < 16 or skin.height < 16:
            raise ValueError("skin too small")
        head = skin.crop((8, 8, 16, 16)).resize((size, size), PilImage.NEAREST)
        if skin.height >= 64:
            hat = skin.crop((40, 8, 48, 16)).resize((size, size), PilImage.NEAREST)
            if hat.getbbox():
                head.paste(hat, (0, 0), hat)
    except Exception as exc:
        if not isinstance(exc, FileNotFoundError):
            print(f"[skin] head render failed, using placeholder: {type(exc).__name__}: {exc}", flush=True)
        from PIL import Image as PilImage
        head = PilImage.new("RGBA", (size, size), (106, 127, 153, 255))
    buf = io.BytesIO()
    head.save(buf, "PNG")
    buf.seek(0)
    return Response(buf.getvalue(), content_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/friends")
def friends_list():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    data, status = _proxy_post("/api/friends/list", {"token": token})
    return jsonify({"ok": status == 200, "status": status, "data": data})


@app.post("/friends/request")
def friends_request():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    body = request.json or {}
    username = str(body.get("username") or "").strip()
    data, status = _proxy_post("/api/friends/request", {"token": token, "username": username})
    return jsonify({"ok": status == 200, "status": status, "data": data})


@app.post("/friends/respond")
def friends_respond():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    body = request.json or {}
    data, status = _proxy_post("/api/friends/respond", {
        "token": token,
        "friend_user_id": int(body.get("friend_user_id") or 0),
        "action": str(body.get("action") or "").strip().lower(),
    })
    return jsonify({"ok": status == 200, "status": status, "data": data})


@app.post("/friends/remove")
def friends_remove():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    body = request.json or {}
    data, status = _proxy_post("/api/friends/remove", {
        "token": token,
        "friend_user_id": int(body.get("friend_user_id") or 0),
    })
    return jsonify({"ok": status == 200, "status": status, "data": data})


@app.get("/account")
def account_info():
    return jsonify(load_auth_data())


@app.get("/skin/model")
def skin_model():
    from PIL import Image as PilImage
    width  = min(max(int(request.args.get("w", 200)), 32), 512)
    height = min(max(int(request.args.get("h", 400)), 32), 1024)
    _ensure_skin_cached()
    skin_path = get_data_dir() / "skin.png"

    try:
        if not skin_path.exists():
            raise FileNotFoundError
        skin = PilImage.open(skin_path).convert("RGBA")
        if skin.width < 64 or skin.height < 32:
            raise ValueError

        has_overlay = skin.height >= 64
        model = load_skin_model() if has_overlay else "classic"
        arm_w = 3 if model == "slim" else 4

        def crop(x, y, w, h):
            if skin.width < x + w or skin.height < y + h:
                return None
            return skin.crop((x, y, x + w, y + h))

        def mirror(img):
            return img.transpose(PilImage.FLIP_LEFT_RIGHT) if img else None

        head   = crop(8,  8,  8,     8)
        body   = crop(20, 20, 8,     12)
        r_arm  = crop(44, 20, arm_w, 12)
        r_leg  = crop(4,  20, 4,     12)
        if not all([head, body, r_arm, r_leg]):
            raise ValueError("missing parts")

        l_arm = mirror(r_arm)
        l_leg = mirror(r_leg)
        head_ov  = crop(40, 8,  8,     8)  if has_overlay else None
        body_ov  = crop(20, 36, 8,     12) if has_overlay else None
        r_arm_ov = crop(44, 36, arm_w, 12) if has_overlay else None
        r_leg_ov = crop(4,  36, 4,     12) if has_overlay else None
        l_arm_ov = mirror(r_arm_ov) if r_arm_ov else None
        l_leg_ov = mirror(r_leg_ov) if r_leg_ov else None

        margin = 16
        avail_h = max(1, height - 2 * margin)
        avail_w = max(1, width  - 2 * margin)
        pix_h = 8 + 12 + 12
        pix_w = arm_w + 8 + arm_w
        scale = min(avail_h // pix_h, avail_w // pix_w, 16)
        scale = max(scale, 1)

        hs  = 8     * scale
        bws = 8     * scale
        bhs = 12    * scale
        aws = arm_w * scale
        ls  = 4     * scale
        lhs = 12    * scale

        total_w = aws + bws + aws
        total_h = hs  + bhs + lhs

        canvas = PilImage.new("RGBA", (total_w, total_h), (0, 0, 0, 0))

        def paste(img, x, y, w, h):
            if img is None:
                return
            canvas.paste(img.resize((w, h), PilImage.NEAREST), (x, y), img.resize((w, h), PilImage.NEAREST))

        head_x = aws + (bws - hs) // 2
        paste(head,  head_x, 0,         hs,  hs)
        paste(body,  aws,    hs,         bws, bhs)
        paste(r_arm, 0,      hs,         aws, bhs)
        paste(l_arm, aws+bws, hs,        aws, bhs)
        paste(r_leg, aws,    hs + bhs,   ls,  lhs)
        paste(l_leg, aws+ls, hs + bhs,   ls,  lhs)

        if head_ov:
            pad = max(0, scale // 5)
            ov = head_ov.resize((hs + 2*pad, hs + 2*pad), PilImage.NEAREST)
            canvas.paste(ov, (head_x - pad, -pad), ov)
        if body_ov:  paste(body_ov,  aws,    hs,       bws, bhs)
        if r_arm_ov: paste(r_arm_ov, 0,      hs,       aws, bhs)
        if l_arm_ov: paste(l_arm_ov, aws+bws, hs,      aws, bhs)
        if r_leg_ov: paste(r_leg_ov, aws,    hs + bhs, ls,  lhs)
        if l_leg_ov: paste(l_leg_ov, aws+ls, hs + bhs, ls,  lhs)

        final = PilImage.new("RGBA", (width, height), (0, 0, 0, 0))
        final.paste(canvas, ((width - total_w) // 2, (height - total_h) // 2), canvas)

    except Exception as exc:
        if not isinstance(exc, FileNotFoundError):
            print(f"[skin] model render failed, using empty image: {type(exc).__name__}: {exc!r}", flush=True)
        final = PilImage.new("RGBA", (width, height), (0, 0, 0, 0))

    buf = io.BytesIO()
    final.save(buf, "PNG")
    buf.seek(0)
    return Response(buf.getvalue(), content_type="image/png", headers={"Cache-Control": "no-store"})


_SKIN_MAX_BYTES = 16 * 1024


@app.post("/account/skin/upload")
def account_skin_upload():
    file = request.files.get("file")
    model = (request.form.get("model") or "classic").strip().lower()
    if model not in ("classic", "slim"):
        model = "classic"
    if not file:
        print("[account] skin upload rejected: no file in request", flush=True)
        return jsonify({"ok": False, "error": "no_file"}), 400

    data = file.read()
    print(f"[account] skin upload: {file.filename!r}, {len(data)} bytes, model={model}", flush=True)
    if not data:
        print("[account] skin upload rejected: empty file", flush=True)
        return jsonify({"ok": False, "error": "no_file"}), 400
    if len(data) > _SKIN_MAX_BYTES:
        print(f"[account] skin upload rejected: {len(data)} bytes > {_SKIN_MAX_BYTES}", flush=True)
        return jsonify({"ok": False, "error": "skin_too_large"})
    if not data.startswith(b"\x89PNG"):
        print(f"[account] skin upload rejected: not a png (header {data[:8]!r})", flush=True)
        return jsonify({"ok": False, "error": "skin_bad_format"})

    try:
        from PIL import Image as PilImage
        img = PilImage.open(io.BytesIO(data))
        if img.width != 64 or img.height not in (32, 64):
            print(f"[account] skin upload rejected: dimensions {img.width}x{img.height}", flush=True)
            return jsonify({"ok": False, "error": "skin_bad_dimensions"})
    except Exception as exc:
        print(f"[account] skin upload rejected: png decode failed: {type(exc).__name__}: {exc}", flush=True)
        return jsonify({"ok": False, "error": "skin_bad_format"})

    skin_path = get_data_dir() / "skin.png"
    skin_path.parent.mkdir(parents=True, exist_ok=True)
    skin_path.write_bytes(data)
    save_skin_model(model)
    print(f"[account] skin saved locally: {skin_path} ({img.width}x{img.height}, {model})", flush=True)

    auth = load_auth_data() or {}
    token = str(auth.get("token") or "").strip()
    if not token:
        print("[account] skin not uploaded: not logged in", flush=True)
        return jsonify({"ok": True, "saved": True, "uploaded": False})

    try:
        base = get_api_base()
        r = http.post(
            f"{base}/api/skins/upload",
            data={"token": token, "model": model},
            files={"file": ("skin.png", io.BytesIO(data), "image/png")},
            timeout=15,
        )
        resp = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
    except Exception as exc:
        print(f"[account] skin upload failed: {type(exc).__name__}: {exc}", flush=True)
        return jsonify({"ok": False, "error": "conn_refused", "saved": True})
    if r.status_code != 200 or not isinstance(resp, dict) or resp.get("ok") is not True:
        error = (resp.get("error") if isinstance(resp, dict) else None) or f"http_{r.status_code}"
        print(f"[account] skin upload rejected: HTTP {r.status_code}: {str(resp)[:300]}", flush=True)
        return jsonify({"ok": False, "error": error, "status_code": r.status_code, "saved": True})
    return jsonify({"ok": True, "status_code": r.status_code, "data": resp, "saved": True})


@app.post("/account/discord/link")
def account_discord_link():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "no_token"})
    try:
        base = get_api_base()
        r = http.post(f"{base}/api/account/discord-link", json={"token": token}, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = {"error": "bad_response"}
        if r.status_code not in (200, 409):
            print(f"[account] discord link failed: HTTP {r.status_code}: {str(data)[:300]}", flush=True)
        return jsonify({"ok": r.status_code == 200, "status_code": r.status_code, "data": data})
    except Exception as exc:
        print(f"[account] discord link failed: {type(exc).__name__}: {exc}", flush=True)
        return jsonify({"ok": False, "error": "conn_refused"})


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _install_desktop_entry_if_appimage() -> None:
    appimage_path = os.environ.get("APPIMAGE")
    if not appimage_path:
        return
    try:
        from desktop_integration import install_desktop_entry

        base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
        install_desktop_entry(Path(appimage_path), base / "assets" / "logo.png")
        print(f"[backend] desktop entry installed for {appimage_path}", flush=True)
    except Exception as exc:
        print(f"[backend] desktop entry install failed: {type(exc).__name__}: {exc}", flush=True)


def _launcher_work_pending() -> bool:
    with _play_lock:
        playing = _play_state.get("state") in ("running", "launched")
    with _tasks_lock:
        downloading = any(t.get("kind") == "download" and t.get("state") == "running" for t in _tasks.values())
    return playing or downloading


def _exit_when_launcher_closes() -> None:
    try:
        while sys.stdin.buffer.read(4096):
            pass
    except (OSError, ValueError):
        pass
    print("[backend] launcher closed, exiting after the game and downloads finish", flush=True)
    while _launcher_work_pending():
        time.sleep(2)
    print("[backend] exiting", flush=True)
    os._exit(0)


def _log_startup(port: int) -> None:
    from auth.api_base import get_api_candidates
    print(f"[backend] started: pid={os.getpid()} port={port} log={get_data_dir() / 'launcher.log'}", flush=True)
    print(f"[backend] os: {platform.platform()} ({platform.machine()}), python {sys.version.split()[0]}, frozen={bool(getattr(sys, 'frozen', False))}", flush=True)
    print(f"[backend] data dir: {get_data_dir()}", flush=True)
    print(f"[backend] update channel: {UPDATE_CHANNEL}, update mode: {_update_mode() or '-'}", flush=True)
    print(f"[backend] api candidates: {', '.join(get_api_candidates())}", flush=True)
    print(f"[backend] settings: {_short(_redact(load_settings()))}", flush=True)
    auth = load_auth_data() or {}
    print(f"[backend] auth: username={auth.get('username') or '-'} status={auth.get('status') or '-'} sub_level={auth.get('sub_level', '-')} token={'set' if auth.get('token') else 'none'}", flush=True)


if __name__ == "__main__":
    import argparse, pathlib
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", type=str, default=None)
    args, _ = parser.parse_known_args()

    port = args.port if args.port else _find_free_port()

    port_file = pathlib.Path(args.port_file) if args.port_file else pathlib.Path(__file__).parent / ".dev-port"
    port_file.write_text(str(port))

    print(f"PORT:{port}", flush=True)
    drop_saved_default_api_bases()
    try:
        _log_startup(port)
    except Exception as exc:
        print(f"[backend] startup info failed: {type(exc).__name__}: {exc}", flush=True)
    threading.Thread(target=_install_desktop_entry_if_appimage, daemon=True).start()
    if os.environ.get("LOTA_EXIT_ON_STDIN_CLOSE") == "1" and sys.stdin is not None:
        threading.Thread(target=_exit_when_launcher_closes, daemon=True).start()
    try:
        app.run(host="127.0.0.1", port=port, threaded=True)
    finally:
        port_file.unlink(missing_ok=True)
