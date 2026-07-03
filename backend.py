import sys
import io
import json
import hashlib
import os
import platform
import socket
import tempfile
import threading
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

from flask import Flask, request, jsonify, Response, send_file
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
from auth.api_base import get_api_base
from services.library_service import LibraryService

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.before_request
def _preflight():
    if request.method == "OPTIONS":
        return Response(status=200)

_log_lines: list[str] = []
_log_lock = threading.Lock()
_LOG_MAX = 2000


def _log_append(line: str) -> None:
    with _log_lock:
        _log_lines.append(line)
        if len(_log_lines) > _LOG_MAX:
            del _log_lines[:len(_log_lines) - _LOG_MAX]


class _LogWriter(io.TextIOBase):
    def __init__(self, original, prefix: str = ""):
        self._orig = original
        self._prefix = prefix
        self._buf = ""

    def write(self, s: str) -> int:
        if self._orig:
            try:
                self._orig.write(s)
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

# werkzeug не должен логировать частые поллинг-ендпоинты иначе дебаг консоль зациклится
import logging as _logging

class _WerkzeugFilter(_logging.Filter):
    _SKIP = ("/debug/logs", "/play/state", "/skin/head")
    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(s in msg for s in self._SKIP)

_logging.getLogger("werkzeug").addFilter(_WerkzeugFilter())


_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


def _new_task() -> str:
    import uuid
    task_id = str(uuid.uuid4())[:8]
    with _tasks_lock:
        _tasks[task_id] = {"state": "running", "progress": 0, "error": None, "result": None}
    return task_id


def _task_done(task_id: str, error: str | None = None, result: dict | None = None):
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id]["state"] = "error" if error else "done"
            _tasks[task_id]["error"] = error
            _tasks[task_id]["result"] = result


def _task_progress(task_id: str, progress: int):
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id]["progress"] = progress


def _lib() -> LibraryService:
    return LibraryService(get_data_dir(), get_api_base)


UPDATE_CHANNEL = os.getenv("LOTA_LAUNCHER_CHANNEL", "stable").strip() or "stable"
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
    # frozen backend сидит в LotaLauncher.app/Contents/MacOS/backend —
    # поднимаемся до самого .app, без привязки к точной глубине вложенности.
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def _update_mode() -> str | None:
    # Windows обновляется отдельным updater.exe (см. updater/src-tauri) —
    # питон в этом вообще не участвует, апдейтер сам стучится на сервер.
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


@app.get("/update/check")
def update_check():
    mode = _update_mode()
    if mode not in ("appimage", "macos-app"):
        return jsonify({"ok": True, "mode": mode, "update_available": False})
    local_version = str(request.args.get("version") or "0.0.0")
    data = _check_launcher_update(local_version)
    if not data or data.get("ok") is not True:
        return jsonify({"ok": False, "mode": mode, "error": data.get("error") if data else "check_failed"})
    data["mode"] = mode
    return jsonify(data)


def _install_macos_app_update(zip_path: Path, target_app: Path) -> str:
    import shutil
    import zipfile

    extract_dir = target_app.parent / f".lota-update-extract-{os.getpid()}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        new_app = next((p for p in extract_dir.iterdir() if p.suffix == ".app"), None)
        if new_app is None:
            raise RuntimeError("update archive has no .app bundle")

        # Замена директории бандла целиком, пока текущий процесс из неё же
        # исполняется — на POSIX это безопасно (открытый файл живёт по inode,
        # не по пути), тот же принцип, что и с AppImage.
        backup = target_app.with_name(target_app.name + ".old")
        shutil.rmtree(backup, ignore_errors=True)
        os.replace(target_app, backup)
        try:
            os.replace(new_app, target_app)
        except Exception:
            os.replace(backup, target_app)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        # apply_update() запускает конкретный бинарник, не .app-директорию
        return str(target_app / "Contents" / "MacOS" / "lota-launcher")
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


@app.post("/update/install")
def update_install():
    # На Windows апдейт полностью в updater.exe, сюда не заходит.
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

    target_path = _appimage_path() if mode == "appimage" else _macos_app_bundle_path()
    task_id = _new_task()

    def run():
        tmp_path: Path | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix="lota-update-", dir=str(target_path.parent))
            os.close(fd)
            tmp_path = Path(tmp_name)

            digest = hashlib.sha256()
            downloaded = 0
            with http.get(url, stream=True, timeout=120) as resp:
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
                        if total > 0:
                            _task_progress(task_id, min(95, int(downloaded * 95 / total)))

            if size and downloaded != size:
                raise RuntimeError(f"size mismatch: expected {size}, got {downloaded}")
            if sha256 and digest.hexdigest().lower() != sha256:
                raise RuntimeError("sha256 mismatch")

            if mode == "appimage":
                mode_bits = tmp_path.stat().st_mode
                os.chmod(tmp_path, mode_bits | 0o111)
                os.replace(tmp_path, target_path)
                relaunch_path = str(target_path)
                tmp_path = None
            else:
                relaunch_path = _install_macos_app_update(tmp_path, target_path)
                tmp_path.unlink(missing_ok=True)
                tmp_path = None

            _task_progress(task_id, 100)
            _task_done(task_id, result={"relaunch_path": relaunch_path, "version": version})
        except Exception as exc:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            _task_done(task_id, error=str(exc))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "task_id": task_id})


@app.get("/auth/load")
def auth_load():
    data = load_auth_data()
    return jsonify(data)


@app.post("/auth/save")
def auth_save():
    body = request.json or {}
    save_auth_data(
        str(body.get("token") or ""),
        str(body.get("username") or ""),
        str(body.get("status") or "active"),
        int(body.get("sub_level") or 0),
        str(body.get("player_uuid") or ""),
    )
    return jsonify({"ok": True})


@app.post("/auth/clear")
def auth_clear_route():
    clear_auth_data()
    return jsonify({"ok": True})


@app.get("/settings")
def settings_load():
    return jsonify(load_settings())


@app.post("/settings")
def settings_save():
    body = request.json or {}
    settings = load_settings()
    settings.update(body)
    save_settings(settings)
    return jsonify({"ok": True})


@app.get("/i18n")
def i18n():
    from window.translations import TRANSLATIONS
    settings = load_settings()
    lang = str(settings.get("language") or "Русский")
    trans = TRANSLATIONS.get(lang) or TRANSLATIONS.get("Русский") or {}
    return jsonify({"language": lang, "strings": trans})


@app.get("/java/scan")
def java_scan():
    from auth.java_finder import find_java_candidates, get_java_version, get_java_major_version
    candidates = find_java_candidates()
    result = []
    for path in candidates:
        major = get_java_major_version(path)
        result.append({"path": path, "major": major})
    return jsonify({"candidates": result})


def _proxy_post(path: str, body: dict) -> tuple[dict, int]:
    try:
        base = get_api_base()
        r = http.post(f"{base}{path}", json=body, timeout=15)
        return r.json() if r.content else {}, r.status_code
    except Exception as e:
        print(f"[backend] proxy POST {path} failed: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0


def _proxy_get(path: str, params: dict) -> tuple[dict, int]:
    try:
        base = get_api_base()
        r = http.get(f"{base}{path}", params=params, timeout=10)
        return r.json() if r.content else {}, r.status_code
    except Exception as e:
        print(f"[backend] proxy GET {path} failed: {e}", flush=True)
        return {"ok": False, "error": "conn_refused", "detail": str(e)}, 0


@app.get("/debug/logs")
def debug_logs():
    since = int(request.args.get("since", 0))
    with _log_lock:
        total = len(_log_lines)
        lines = _log_lines[since:] if since < total else []
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
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")
    lib = _lib()
    catalog = lib.load_catalog(token)
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
    return jsonify({
        "builds": builds,
        "selected_build": str(settings.get("selected_build") or ""),
    })


@app.post("/library/select")
def library_select():
    body = request.json or {}
    build_key = str(body.get("build_key") or "")
    settings = load_settings()
    settings["selected_build"] = build_key
    save_settings(settings)
    return jsonify({"ok": True})


@app.post("/library/download")
def library_download():
    body = request.json or {}
    build_key = str(body.get("build_key") or "")
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "")

    lib = _lib()
    catalog = lib.load_catalog(token)
    item = next((b for b in catalog.builds if lib.build_key(b) == build_key), None)
    if not item:
        return jsonify({"ok": False, "error": "build_not_found"}), 404

    source_item = None
    if item.get("is_instance"):
        source_id = item.get("_source_build_id")
        source_item = next((b for b in catalog.builds if not b.get("is_instance") and b.get("id") == source_id), None)

    task_id = _new_task()

    def run():
        try:
            base_url = get_api_base()
            build_id = int((source_item or item).get("id"))
            archive_path = lib.build_archive_path(item)
            archive_path.parent.mkdir(parents=True, exist_ok=True)

            with http.post(
                f"{base_url}/api/build/download",
                json={"token": token, "build_id": build_id},
                stream=True, timeout=120,
            ) as resp:
                if resp.status_code != 200:
                    _task_done(task_id, f"HTTP {resp.status_code}")
                    return
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with archive_path.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            _task_progress(task_id, min(90, int(downloaded * 90 / total)))

            lib.install_or_update_build(item, archive_path, source_item=source_item)
            _task_progress(task_id, 100)
            _task_done(task_id)
        except Exception as exc:
            _task_done(task_id, str(exc))

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
        return jsonify({"ok": False, "error": "build_not_found"}), 404
    lib.delete_build_files(item)
    settings = load_settings()
    if settings.get("selected_build") == build_key:
        settings["selected_build"] = ""
        save_settings(settings)
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
    p = Path(path)
    if p.is_absolute() and p.is_file():
        return send_file(str(p))
    lib = _lib()
    resolved = (lib.paths.cache_dir / path).resolve()
    if resolved.is_file():
        return send_file(str(resolved))
    return Response(status=404)


@app.get("/task/<task_id>")
def task_status(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "not_found"}), 404
    return jsonify(task)


_play_state: dict = {"state": "idle", "status": "", "error": None}
_play_lock = threading.Lock()


@app.get("/play/state")
def play_state():
    with _play_lock:
        return jsonify({k: v for k, v in _play_state.items() if k != "_proc"})


@app.post("/play/start")
def play_start():
    with _play_lock:
        if _play_state["state"] in ("running", "launched"):
            return jsonify({"ok": False, "error": "already_running"})

    def run():
        from services.play_service import PlayService
        service = PlayService()

        def set_status(msg):
            with _play_lock:
                _play_state["status"] = msg

        def set_progress(done, total=None):
            if total is not None and total > 0:
                p = int(done * 100 / total)
            else:
                p = int(done)
            with _play_lock:
                _play_state["progress"] = max(0, min(100, p))

        with _play_lock:
            _play_state.update({"state": "running", "status": "Подготовка...", "error": None, "progress": 0})

        try:
            settings = load_settings()
            allow_update = True
            build_key = service.ensure_latest_build_selected(
                status=set_status, progress=set_progress, allow_build_update=allow_update
            )
            if not build_key:
                with _play_lock:
                    _play_state.update({"state": "error", "error": "Нет доступных сборок"})
                return

            java_path = service.ensure_oracle_java_21(status=set_status, progress=set_progress)
            if not java_path:
                java_path = str(settings.get("java_path") or "")

            set_status("Запуск...")

            from minecraft.mc_client import ensure_forge_version, prepare_version
            from minecraft.mc_launch import build_launch_spec
            from auth.auth_storage import get_data_dir
            import platform

            game_dir = (get_data_dir() / "library" / build_key)
            if not game_dir.is_dir():
                game_dir = get_data_dir() / "minecraft"

            shared_game_dir = get_data_dir() / "minecraft"
            versions_dir = shared_game_dir / "versions"
            version_id = ensure_forge_version(versions_dir, java_path, shared_game_dir, status=set_status)
            prepared = prepare_version(version_id, progress=set_progress, status=set_status)

            auth = load_auth_data() or {}
            username = str(settings.get("offline_username") or auth.get("username") or "Player")

            mem_min = int(settings.get("mem_min_mb") or 1024)
            mem_max = int(settings.get("mem_max_mb") or 4096)
            jvm_args = str(settings.get("jvm_args") or "")

            spec = build_launch_spec(
                prepared=prepared,
                username=username,
                java_path=java_path,
                mem_min_mb=mem_min,
                mem_max_mb=mem_max,
                jvm_args=jvm_args,
                game_dir_override=game_dir,
            )

            import subprocess
            proc = subprocess.Popen(
                spec.argv, cwd=spec.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
            )
            with _play_lock:
                _play_state.update({"state": "launched", "status": "Игра запущена", "pid": proc.pid, "_proc": proc})

            def _pipe_mc_logs():
                for line in proc.stdout:
                    _log_append("[MC] " + line.rstrip())
            threading.Thread(target=_pipe_mc_logs, daemon=True).start()

            proc.wait()
            with _play_lock:
                _play_state.update({"state": "idle", "status": "", "pid": None, "_proc": None})

        except Exception as exc:
            with _play_lock:
                _play_state.update({"state": "error", "error": str(exc)})

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True})


@app.post("/play/stop")
def play_stop():
    with _play_lock:
        proc = _play_state.get("_proc")
        state = _play_state.get("state")
    if proc is not None and state == "launched":
        try:
            proc.terminate()
        except Exception:
            pass
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


@app.get("/news")
def news():
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
            return jsonify({"ok": True, "items": items})
        return jsonify({"ok": False, "items": [], "status": r.status_code})
    except Exception:
        return jsonify({"ok": False, "items": [], "error": "conn_refused"})


@app.get("/news/image")
def news_image():
    rel_path = request.args.get("path", "").replace("\\", "/").strip().lstrip("/")
    if not rel_path:
        return Response(status=400)
    trimmed = rel_path[len("images/"):] if rel_path.startswith("images/") else rel_path
    cache_path = get_data_dir() / "news_cache" / "images" / trimmed
    if cache_path.exists():
        return send_file(str(cache_path))
    try:
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "")
        base = get_api_base()
        r = http.get(f"{base}/api/news/image", params={"token": token, "path": rel_path}, timeout=10)
        if r.status_code == 200:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(r.content)
            return Response(r.content, content_type=r.headers.get("Content-Type", "image/png"))
    except Exception:
        pass
    return Response(status=404)


@app.get("/skin/head")
def skin_head():
    from PIL import Image as PilImage
    size = min(max(int(request.args.get("size", 40)), 8), 256)
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
    except Exception:
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

    except Exception:
        final = PilImage.new("RGBA", (width, height), (0, 0, 0, 0))

    buf = io.BytesIO()
    final.save(buf, "PNG")
    buf.seek(0)
    return Response(buf.getvalue(), content_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/account/skin/upload")
def account_skin_upload():
    file = request.files.get("file")
    model = (request.form.get("model") or "classic").strip().lower()
    if model not in ("classic", "slim"):
        model = "classic"
    if not file:
        return jsonify({"ok": False, "error": "no_file"}), 400

    data = file.read()
    if not data:
        return jsonify({"ok": False, "error": "no_file"}), 400
    if not data.startswith(b"\x89PNG"):
        return jsonify({"ok": False, "error": "skin_bad_format"})

    try:
        from PIL import Image as PilImage
        img = PilImage.open(io.BytesIO(data))
        if img.width != 64 or img.height not in (32, 64):
            return jsonify({"ok": False, "error": "skin_bad_dimensions"})
    except Exception:
        return jsonify({"ok": False, "error": "skin_bad_format"})

    skin_path = get_data_dir() / "skin.png"
    skin_path.parent.mkdir(parents=True, exist_ok=True)
    skin_path.write_bytes(data)
    save_skin_model(model)

    auth = load_auth_data() or {}
    token = str(auth.get("token") or "").strip()
    if not token:
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
        return jsonify({"ok": r.status_code == 200, "status_code": r.status_code, "data": resp, "saved": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "saved": True})


@app.post("/account/discord/link")
def account_discord_link():
    auth = load_auth_data() or {}
    token = str(auth.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "no_token"})
    try:
        base = get_api_base()
        r = http.post(f"{base}/api/account/discord-link", json={"token": token}, timeout=5)
        return jsonify({"ok": r.status_code == 200, "status_code": r.status_code, "data": r.json()})
    except Exception:
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
    except Exception:
        pass


if __name__ == "__main__":
    import argparse, pathlib
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--port-file", type=str, default=None)
    args, _ = parser.parse_known_args()

    port = args.port if args.port else _find_free_port()

    port_file = pathlib.Path(args.port_file) if args.port_file else pathlib.Path(__file__).parent / ".dev-port"
    port_file.write_text(str(port))

    # tauri читает PORT:xxxx из stdout
    print(f"PORT:{port}", flush=True)
    _install_desktop_entry_if_appimage()
    try:
        app.run(host="127.0.0.1", port=port, threaded=True)
    finally:
        port_file.unlink(missing_ok=True)
