from __future__ import annotations

import hashlib
import json
import os
import shutil
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Callable

import requests

UNITS_STATE_FILE = ".lota_units.json"
CLOSED_DIR = ".lota_closed"
TMP_DIR = ".lota_tmp"
LEGACY_META_FILE = ".lota_build_meta.json"
LEGACY_ARCHIVE = "build.zip"
DOWNLOAD_WORKERS = 6
UNIT_ATTEMPTS = 4
MANIFEST_REFRESHES = 3
STATE_SAVE_EVERY = 25
PENDING_LOG_LIMIT = 50
CHUNK_SIZE = 256 * 1024
PACK_HEADER = b"PACK\x01"
PACK_TAG_SIZE = 16
MIRROR_TIMEOUT = (5, 20)
MIRROR_MAX_FAILURES = 3
USER_AGENT = "LotaLauncher"
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
PLAYER_FILES = {
    "options.txt",
    "optionsof.txt",
    "servers.dat",
    "servers.dat_old",
    "usercache.json",
    "usernamecache.json",
    "launcher_profiles.json",
    "launcher_accounts.json",
}

ProgressCallback = Callable[[str, int, int, int], None] | None


class BuildSyncError(RuntimeError):
    pass


class _RefreshManifest(Exception):
    pass


class _Aborted(Exception):
    pass


class _Transient(Exception):
    pass


class _MirrorFailed(Exception):
    pass


def unit_rel_path(path: object) -> PurePosixPath | None:
    raw = str(path or "").replace("\\", "/").strip().lstrip("/")
    if not raw:
        return None
    rel = PurePosixPath(raw)
    if not rel.parts or any(part in (".", "..") or ":" in part for part in rel.parts):
        return None
    return rel


def is_player_file(path: str) -> bool:
    return "/" not in path and path.lower() in PLAYER_FILES


def closed_payload_name(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:32] + ".pack"


def load_state(install_dir: Path) -> dict:
    try:
        data = json.loads((install_dir / UNITS_STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    units = data.get("units")
    data["units"] = units if isinstance(units, dict) else {}
    return data


def save_state(install_dir: Path, state: dict) -> None:
    path = install_dir / UNITS_STATE_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def closed_units(install_dir: Path) -> list[tuple[str, dict]]:
    state = load_state(install_dir)
    result = []
    for path, entry in state["units"].items():
        if isinstance(entry, dict) and entry.get("closed") and entry.get("payload"):
            result.append((path, entry))
    return result


HIDDEN_SUFFIX = ".lota-hidden"


def is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def remove_link(path: Path) -> None:
    if not is_link(path):
        return
    if os.name == "nt":
        os.rmdir(path)
    else:
        os.unlink(path)


def link_dir(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_closed_links(install_dir: Path) -> None:
    for path, _entry in closed_units(install_dir):
        link = install_dir.joinpath(*PurePosixPath(path).parts)
        try:
            if is_link(link):
                remove_link(link)
                print(f"[bundle] removed leftover link {path}", flush=True)
            hidden = link.with_name(link.name + HIDDEN_SUFFIX)
            if hidden.exists() and not link.exists():
                hidden.replace(link)
                print(f"[bundle] restored hidden {path}", flush=True)
        except OSError as exc:
            print(f"[bundle] failed to clean leftover link {path}: {exc}", flush=True)
            continue


def extract_zip(source, dest: Path) -> list[str]:
    files: list[str] = []
    with zipfile.ZipFile(source, "r") as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel = unit_rel_path(info.filename)
            if rel is None:
                continue
            target = dest.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK_SIZE)
            files.append(rel.as_posix())
    return files


def decrypt_pack_file(source: Path, key: bytes, dest: Path) -> None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    size = source.stat().st_size
    if size < len(PACK_HEADER) + 12 + PACK_TAG_SIZE:
        raise ValueError("encrypted data too short")
    with source.open("rb") as src:
        header = src.read(len(PACK_HEADER))
        if header != PACK_HEADER:
            raise ValueError("bad magic/version")
        iv = src.read(12)
        src.seek(size - PACK_TAG_SIZE)
        tag = src.read(PACK_TAG_SIZE)
        src.seek(len(PACK_HEADER) + 12)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
        decryptor.authenticate_additional_data(PACK_HEADER)
        remaining = size - len(PACK_HEADER) - 12 - PACK_TAG_SIZE
        try:
            with dest.open("wb") as out:
                while remaining > 0:
                    chunk = src.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("encrypted data truncated")
                    remaining -= len(chunk)
                    out.write(decryptor.update(chunk))
                out.write(decryptor.finalize())
        except Exception:
            dest.unlink(missing_ok=True)
            raise


def _to_int(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _to_bool(value) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1"}


def _parse_units(raw) -> dict[str, dict]:
    units: dict[str, dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        rel = unit_rel_path(item.get("path"))
        if rel is None:
            continue
        unit = {
            "type": "dir" if str(item.get("type") or "").lower() == "dir" else "file",
            "hash": str(item.get("hash") or ""),
            "closed": _to_bool(item.get("closed")),
            "size": _to_int(item.get("size")),
            "sha1": "",
            "mirror_url": "",
        }
        if unit["type"] == "file" and not unit["closed"]:
            sha1 = str(item.get("sha1") or "").strip().lower()
            if SHA1_RE.match(sha1):
                unit["sha1"] = sha1
                mirror_url = str(item.get("mirror_url") or "").strip()
                if mirror_url.lower().startswith("https://"):
                    unit["mirror_url"] = mirror_url
        units[rel.as_posix()] = unit
    return units


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _error_code(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    return str(data.get("error") or "") if isinstance(data, dict) else ""


def _cleanup_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.resolve()
    current = path
    while True:
        try:
            if current.resolve() == stop:
                return
            current.rmdir()
        except OSError:
            return
        current = current.parent


class BuildSync:
    def __init__(
        self,
        *,
        api_base_resolver,
        token: str,
        build_id: int,
        install_dir: Path,
        progress: ProgressCallback = None,
    ):
        self.api_base_resolver = api_base_resolver
        self.token = token
        self.build_id = build_id
        self.install_dir = Path(install_dir)
        self.progress = progress
        self.lock = threading.Lock()
        self.abort = threading.Event()
        self.local = threading.local()
        self.state: dict = {"units": {}}
        self.download_token = ""
        self.base_url = ""
        self.done_bytes = 0
        self.total_bytes = 0
        self.completed = 0
        self.mirror_failures = 0
        self.mirror_disabled = False
        self.stats = {"mirror": 0, "server": 0, "fallback": 0, "local": 0}

    def run(self) -> None:
        if not self.token:
            raise BuildSyncError("no_token")
        self.install_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.install_dir / TMP_DIR
        shutil.rmtree(tmp_dir, ignore_errors=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        self.state = load_state(self.install_dir)
        previous_build = self.state.get("build_id")
        self.state["build_id"] = self.build_id
        legacy_files = self._legacy_managed_files() if not self.state["units"] else None
        print(
            f"[sync] build {self.build_id}: start into {self.install_dir}, {len(self.state['units'])} units installed"
            + (f" (previously build {previous_build})" if previous_build not in (None, self.build_id) else "")
            + (f", legacy install with {len(legacy_files)} files" if legacy_files is not None else ""),
            flush=True,
        )
        started = time.monotonic()
        try:
            units = self._sync_with_refresh()
            if legacy_files is not None:
                self._remove_legacy_files(legacy_files, units)
            print(
                f"[sync] build {self.build_id}: done in {time.monotonic() - started:.1f}s, {self.done_bytes} bytes, "
                f"modrinth {self.stats['mirror']}, server {self.stats['server']}, "
                f"fallback {self.stats['fallback']}, reused {self.stats['local']}",
                flush=True,
            )
        except BaseException as exc:
            print(f"[sync] build {self.build_id}: failed after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}", flush=True)
            raise
        finally:
            save_state(self.install_dir, self.state)
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _sync_with_refresh(self) -> dict[str, dict]:
        for attempt in range(MANIFEST_REFRESHES + 1):
            manifest = self._fetch_manifest()
            units = _parse_units(manifest.get("units"))
            self.download_token = str(manifest.get("download_token") or "")
            closed = sum(1 for u in units.values() if u["closed"])
            dirs = sum(1 for u in units.values() if u["type"] == "dir")
            mirrored = sum(1 for u in units.values() if u["mirror_url"])
            raw_count = len(manifest.get("units") or [])
            print(
                f"[sync] build {self.build_id}: manifest has {len(units)} units ({closed} closed, {dirs} dirs, {mirrored} on modrinth), "
                f"{sum(u['size'] for u in units.values())} bytes"
                + (f", {raw_count - len(units)} invalid entries skipped" if raw_count != len(units) else ""),
                flush=True,
            )
            self._remove_missing(units)
            pending = self._pending(units)
            self._log_pending(pending, units)
            try:
                self._download_all(pending, units)
                return units
            except _RefreshManifest:
                if attempt == MANIFEST_REFRESHES:
                    raise BuildSyncError("download token keeps expiring")
                print(f"[sync] build {self.build_id}: download token expired, refreshing manifest ({attempt + 1}/{MANIFEST_REFRESHES})", flush=True)
        raise BuildSyncError("unreachable")

    def _fetch_manifest(self) -> dict:
        self.base_url = self.api_base_resolver()
        try:
            response = requests.post(
                f"{self.base_url}/api/build/manifest",
                json={"token": self.token, "build_id": self.build_id},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise BuildSyncError(f"manifest: {exc}") from exc
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            code = data.get("error") if isinstance(data, dict) else ""
            raise BuildSyncError(f"manifest: HTTP {response.status_code} {code or ''}".strip())
        if not data.get("download_token") or not isinstance(data.get("units"), list):
            raise BuildSyncError("manifest: bad response")
        return data

    def _log_pending(self, pending: list[str], units: dict[str, dict]) -> None:
        size = sum(units[p]["size"] for p in pending)
        print(f"[sync] build {self.build_id}: {len(pending)} units to download, {size} bytes, {len(units) - len(pending)} up to date", flush=True)
        for path in pending[:PENDING_LOG_LIMIT]:
            unit = units[path]
            entry = self.state["units"].get(path)
            reason = "new" if not isinstance(entry, dict) else "changed"
            flags = ", closed" if unit["closed"] else (", modrinth" if unit["mirror_url"] else "")
            print(f"[sync]   {reason}: {path} ({unit['type']}, {unit['size']} bytes{flags})", flush=True)
        if len(pending) > PENDING_LOG_LIMIT:
            print(f"[sync]   ... and {len(pending) - PENDING_LOG_LIMIT} more", flush=True)

    def _target(self, path: str) -> Path:
        return self.install_dir.joinpath(*PurePosixPath(path).parts)

    def _present(self, path: str, entry: dict) -> bool:
        if entry.get("closed"):
            return (self.install_dir / CLOSED_DIR / str(entry.get("payload") or "")).is_file()
        target = self._target(path)
        if entry.get("type") == "dir":
            return target.is_dir() and all(self._target(f).is_file() for f in entry.get("files") or [])
        return target.is_file()

    def _pending(self, units: dict[str, dict]) -> list[str]:
        pending = []
        for path, unit in units.items():
            entry = self.state["units"].get(path)
            if is_player_file(path) and self._target(path).exists():
                if not entry:
                    self.state["units"][path] = {"type": unit["type"], "hash": unit["hash"], "closed": False}
                continue
            if (
                isinstance(entry, dict)
                and entry.get("type") == unit["type"]
                and bool(entry.get("closed")) == unit["closed"]
                and self._present(path, entry)
            ):
                if entry.get("hash") == unit["hash"]:
                    continue
                if unit["sha1"] and entry.get("sha1") == unit["sha1"]:
                    entry["hash"] = unit["hash"]
                    continue
            pending.append(path)
        return pending

    def _remove_entry_files(self, path: str, entry: dict) -> None:
        if entry.get("closed"):
            (self.install_dir / CLOSED_DIR / str(entry.get("payload") or "")).unlink(missing_ok=True)
            return
        if is_player_file(path):
            return
        files = entry.get("files") if entry.get("type") == "dir" else [path]
        for rel in files or []:
            target = self._target(rel)
            try:
                if target.is_file() or target.is_symlink():
                    target.unlink()
                _cleanup_empty_parents(target.parent, self.install_dir)
            except OSError:
                continue

    def _remove_missing(self, units: dict[str, dict]) -> None:
        for path in [p for p in self.state["units"] if p not in units]:
            entry = self.state["units"].pop(path)
            print(f"[sync] build {self.build_id}: removing {path}, no longer in manifest", flush=True)
            if isinstance(entry, dict):
                self._remove_entry_files(path, entry)

    def _legacy_managed_files(self) -> list[str] | None:
        try:
            meta = json.loads((self.install_dir / LEGACY_META_FILE).read_text(encoding="utf-8"))
        except Exception:
            return None
        files = meta.get("managed_files") if isinstance(meta, dict) else None
        return [str(f) for f in files] if isinstance(files, list) else None

    def _remove_legacy_files(self, legacy_files: list[str], units: dict[str, dict]) -> None:
        covered = set(units)
        for entry in self.state["units"].values():
            if isinstance(entry, dict):
                covered.update(entry.get("files") or [])
        print(f"[sync] build {self.build_id}: cleaning up legacy install ({len(legacy_files)} files listed)", flush=True)
        for raw in legacy_files:
            rel = unit_rel_path(raw)
            if rel is None:
                continue
            path = rel.as_posix()
            if path in covered or is_player_file(path):
                continue
            target = self._target(path)
            try:
                if target.is_file():
                    target.unlink()
                _cleanup_empty_parents(target.parent, self.install_dir)
            except OSError:
                continue
        (self.install_dir / LEGACY_ARCHIVE).unlink(missing_ok=True)

    def _session(self) -> requests.Session:
        session = getattr(self.local, "session", None)
        if session is None:
            session = requests.Session()
            self.local.session = session
        return session

    def _report(self, name: str, delta: int) -> None:
        with self.lock:
            self.done_bytes = max(0, self.done_bytes + delta)
            done, total = self.done_bytes, self.total_bytes
        if self.progress:
            self.progress(name, delta, done, total)

    def _download_all(self, pending: list[str], units: dict[str, dict]) -> None:
        self.abort.clear()
        with self.lock:
            self.done_bytes = 0
            self.total_bytes = sum(units[p]["size"] for p in pending)
        if self.progress:
            self.progress("", 0, 0, self.total_bytes)
        if not pending:
            return
        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            futures = [pool.submit(self._download_unit, path, units[path]) for path in pending]
            for future in as_completed(futures):
                try:
                    future.result()
                except _Aborted:
                    continue
                except BaseException as exc:
                    errors.append(exc)
                    self.abort.set()
        for exc in errors:
            if isinstance(exc, _RefreshManifest):
                raise exc
        if errors:
            raise errors[0]

    def _reuse_local(self, path: str, unit: dict) -> bool:
        if not unit["sha1"]:
            return False
        target = self._target(path)
        try:
            if not target.is_file() or target.stat().st_size != unit["size"]:
                return False
            return _file_sha1(target) == unit["sha1"]
        except OSError:
            return False

    def _download_unit(self, path: str, unit: dict) -> None:
        if self.abort.is_set():
            raise _Aborted()
        if self._reuse_local(path, unit):
            self._report(PurePosixPath(path).name, unit["size"])
            self._commit(path, {"type": "file", "hash": unit["hash"], "closed": False, "sha1": unit["sha1"]}, "local")
            return
        tmp_file = self._fetch_mirror(path, unit)
        source = "mirror"
        if tmp_file is None:
            tmp_file = self._fetch_server(path, unit)
            source = "fallback" if unit["mirror_url"] else "server"
        try:
            entry = self._install(path, unit, tmp_file)
        finally:
            tmp_file.unlink(missing_ok=True)
        self._commit(path, entry, source)

    def _commit(self, path: str, entry: dict, source: str) -> None:
        with self.lock:
            self.state["units"][path] = entry
            self.stats[source] += 1
            self.completed += 1
            if self.completed % STATE_SAVE_EVERY == 0:
                save_state(self.install_dir, self.state)

    def _fetch_mirror(self, path: str, unit: dict) -> Path | None:
        if not unit["mirror_url"] or self.mirror_disabled:
            return None
        try:
            tmp_file = self._stream(path, unit, unit["mirror_url"], None, MIRROR_TIMEOUT, mirror=True)
        except _Aborted:
            raise
        except Exception as exc:
            with self.lock:
                self.mirror_failures += 1
                disable = self.mirror_failures >= MIRROR_MAX_FAILURES and not self.mirror_disabled
                if disable:
                    self.mirror_disabled = True
            print(f"[sync] modrinth failed for {path}: {exc}", flush=True)
            if disable:
                print("[sync] modrinth disabled for this sync, using server only", flush=True)
            return None
        with self.lock:
            self.mirror_failures = 0
        return tmp_file

    def _fetch_server(self, path: str, unit: dict) -> Path:
        last_error: Exception | None = None
        for attempt in range(UNIT_ATTEMPTS):
            if self.abort.is_set():
                raise _Aborted()
            try:
                return self._stream(
                    path,
                    unit,
                    f"{self.base_url}/api/build/unit",
                    {"token": self.download_token, "path": path},
                    (10, 60),
                    mirror=False,
                )
            except (_RefreshManifest, _Aborted, BuildSyncError):
                raise
            except Exception as exc:
                last_error = exc
                print(f"[sync] {path}: server attempt {attempt + 1}/{UNIT_ATTEMPTS} failed: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(1.5 * (attempt + 1))
        raise BuildSyncError(f"{path}: {last_error}")

    def _stream(self, path: str, unit: dict, url: str, params: dict | None, timeout, *, mirror: bool) -> Path:
        tmp_file = self.install_dir / TMP_DIR / closed_payload_name(f"{path}:{time.monotonic_ns()}")
        received = 0
        name = PurePosixPath(path).name
        digest = hashlib.sha1()
        try:
            with self._session().get(
                url,
                params=params,
                stream=True,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            ) as response:
                if mirror and response.status_code != 200:
                    raise _MirrorFailed(f"HTTP {response.status_code}")
                if response.status_code != 200:
                    code = _error_code(response)
                    if (response.status_code, code) in ((401, "invalid_or_expired_token"), (404, "not_found")):
                        raise _RefreshManifest()
                    if response.status_code >= 500 or response.status_code == 429:
                        raise _Transient(f"HTTP {response.status_code} {code}".strip())
                    raise BuildSyncError(f"{path}: HTTP {response.status_code} {code}".strip())
                with tmp_file.open("wb") as out:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if self.abort.is_set():
                            raise _Aborted()
                        if not chunk:
                            continue
                        out.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        self._report(name, len(chunk))
                expected_length = _to_int(response.headers.get("Content-Length"))
            if expected_length and received != expected_length and "Content-Encoding" not in response.headers:
                raise _Transient(f"truncated: expected {expected_length}, got {received}")
            self._verify(path, unit, tmp_file, received, digest.hexdigest())
            return tmp_file
        except BaseException:
            tmp_file.unlink(missing_ok=True)
            self._report(name, -received)
            raise

    def _verify(self, path: str, unit: dict, tmp_file: Path, received: int, sha1: str) -> None:
        if unit["sha1"]:
            if received != unit["size"]:
                raise _Transient(f"size mismatch: expected {unit['size']}, got {received}")
            if sha1 != unit["sha1"]:
                raise _Transient(f"sha1 mismatch: expected {unit['sha1']}, got {sha1}")
            return
        if unit["closed"]:
            return
        if unit["type"] == "dir" or path.lower().endswith(".jar"):
            if not zipfile.is_zipfile(tmp_file):
                raise _Transient("broken archive")

    def _install(self, path: str, unit: dict, tmp_file: Path) -> dict:
        entry = {"type": unit["type"], "hash": unit["hash"], "closed": unit["closed"]}
        if unit["sha1"]:
            entry["sha1"] = unit["sha1"]
        previous = self.state["units"].get(path)
        if isinstance(previous, dict) and (previous.get("type") != unit["type"] or bool(previous.get("closed")) != unit["closed"]):
            self._remove_entry_files(path, previous)
            previous = None

        if unit["closed"]:
            payload = closed_payload_name(path)
            closed_dir = self.install_dir / CLOSED_DIR
            closed_dir.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_file, closed_dir / payload)
            entry["payload"] = payload
            return entry

        if unit["type"] == "file":
            target = self._target(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_file, target)
            return entry

        files = extract_zip(tmp_file, self.install_dir)
        stale = set((previous or {}).get("files") or []) - set(files)
        for rel in stale:
            target = self._target(rel)
            try:
                if target.is_file():
                    target.unlink()
                _cleanup_empty_parents(target.parent, self.install_dir)
            except OSError:
                continue
        self._target(path).mkdir(parents=True, exist_ok=True)
        entry["files"] = files
        return entry
