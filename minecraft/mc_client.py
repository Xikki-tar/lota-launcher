from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
from requests.adapters import HTTPAdapter

from auth.auth_storage import get_data_dir

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSETS_BASE_URL = "https://resources.download.minecraft.net"

MC_VERSION = "1.20.1"
FORGE_VERSION = "47.4.0"
FORGE_MAVEN_BASE = (
    f"https://maven.minecraftforge.net/net/minecraftforge/forge/{MC_VERSION}-{FORGE_VERSION}"
)
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
REQUEST_TIMEOUT = (10, 60)

ProgressCallback = Callable[[int, int], None] | None
StatusCallback = Callable[[str], None] | None
_thread_local = threading.local()


def _download_worker_count() -> int:
    try:
        value = int(os.environ.get("LL_DOWNLOAD_WORKERS", "32"))
    except ValueError:
        value = 32
    return max(4, min(64, value))


DOWNLOAD_WORKERS = _download_worker_count()


@dataclass
class PreparedVersion:
    version_id: str
    version_json: dict
    game_dir: Path
    versions_dir: Path
    libraries_dir: Path
    assets_dir: Path
    natives_dir: Path


def _os_name() -> str:
    sysname = platform.system().lower()
    if "windows" in sysname:
        return "windows"
    if "darwin" in sysname or "mac" in sysname:
        return "osx"
    return "linux"


def _arch() -> str:
    arch = platform.architecture()[0]
    return "64" if "64" in arch else "32"


def _get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=DOWNLOAD_WORKERS, pool_maxsize=DOWNLOAD_WORKERS)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({"User-Agent": "LL-Launcher/1.0"})
        _thread_local.session = session
    return session


def _download_json(url: str, dest: Path | None = None) -> dict:
    url = _normalize_url(url)
    r = _get_session().get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if dest:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _valid_file(path: Path, size: int | None = None, sha1: str | None = None) -> bool:
    if not path.exists():
        return False
    if size is not None and path.stat().st_size != int(size):
        return False
    if sha1 and _sha1_file(path) != sha1:
        return False
    return True


def _download_file(url: str, dest: Path, size: int | None = None, sha1: str | None = None) -> None:
    url = _normalize_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _valid_file(dest, size, sha1):
        return
    dest.unlink(missing_ok=True)

    tmp = dest.with_name(f"{dest.name}.{threading.get_ident()}.tmp")
    tmp.unlink(missing_ok=True)
    last_error: Exception | None = None
    for _ in range(3):
        try:
            with _get_session().get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
            if not _valid_file(tmp, size, sha1):
                raise RuntimeError(f"Downloaded file validation failed: {dest.name}")
            tmp.replace(dest)
            return
        except Exception as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
    raise last_error or RuntimeError(f"Download failed: {url}")


def _download_many(
    items: list[tuple[str, dict, Path]],
    progress: ProgressCallback = None,
    initial_done: int = 0,
    total: int | None = None,
) -> int:
    if total is None:
        total = initial_done + len(items)
    done = initial_done
    if not items:
        if progress:
            progress(done, total)
        return done

    progress_step = max(1, total // 200)
    unique_items: list[tuple[str, dict, Path]] = []
    seen: set[Path] = set()
    duplicate_count = 0
    for item in items:
        dest = item[2]
        if dest in seen:
            duplicate_count += 1
            continue
        seen.add(dest)
        unique_items.append(item)

    workers = min(DOWNLOAD_WORKERS, max(1, len(unique_items)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _download_file,
                info.get("url"),
                dest,
                info.get("size"),
                info.get("sha1"),
            )
            for _, info, dest in unique_items
        ]
        for future in as_completed(futures):
            future.result()
            done += 1
            if progress and (done == total or done % progress_step == 0):
                progress(done, total)
    done += duplicate_count
    if duplicate_count and progress:
        progress(done, total)
    return done


def _ensure_readable_jar(path: Path, label: str) -> None:
    if not path.exists():
        raise RuntimeError(f"{label} not found: {path}")
    if path.stat().st_size <= 0:
        raise RuntimeError(f"{label} is empty: {path}")
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"{label} is not a valid jar: {path}")
    try:
        with open(path, "rb") as f:
            f.read(1)
    except OSError as exc:
        raise RuntimeError(f"{label} is not readable: {path}\n{exc}") from exc


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_url(url: str) -> str:
    if not url:
        return url
    return url.replace("maven.minecrafteforge.net", "maven.minecraftforge.net")


def _rule_allows(rule: dict) -> bool:
    if not isinstance(rule, dict):
        return True
    os_rule = rule.get("os")
    if isinstance(os_rule, dict):
        name = os_rule.get("name")
        if name and name != _os_name():
            return False
    return True


def _rules_allow(rules: list[dict] | None) -> bool:
    if not rules:
        return True
    allowed = False
    for rule in rules:
        action = rule.get("action", "allow")
        ok = _rule_allows(rule)
        if ok:
            allowed = action == "allow"
        elif action == "disallow":
            allowed = False
    return allowed


def _merge_version(parent: dict, child: dict) -> dict:
    result = dict(parent)
    for k, v in child.items():
        if k in ("libraries",):
            result[k] = (parent.get(k) or []) + (v or [])
        elif k in ("arguments",):
            merged = dict(parent.get(k) or {})
            for ak, av in (v or {}).items():
                merged[ak] = (merged.get(ak) or []) + (av or [])
            result[k] = merged
        else:
            result[k] = v
    return result


def _maven_path_from_name(name: str) -> tuple[str, str]:
    # group:artifact:version[:classifier][@ext]
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
        ext = ext or "jar"
    parts = name.split(":")
    if len(parts) < 3:
        raise ValueError(f"Invalid maven name: {name}")
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    group_path = group.replace(".", "/")
    base = f"{group_path}/{artifact}/{version}"
    filename = f"{artifact}-{version}"
    if classifier:
        filename += f"-{classifier}"
    filename += f".{ext}"
    return f"{base}/{filename}", filename


def _resolve_version_json(version_id: str, manifest: dict, versions_dir: Path) -> dict:
    version_path = versions_dir / version_id / f"{version_id}.json"
    version_entry = next((v for v in manifest.get("versions", []) if v.get("id") == version_id), None)
    if version_entry and version_entry.get("url"):
        version_json = _download_json(version_entry["url"], version_path)
    elif version_path.exists():
        version_json = json.loads(version_path.read_text(encoding="utf-8"))
    else:
        raise RuntimeError(f"Unknown version: {version_id}")

    parent_id = version_json.get("inheritsFrom")
    if parent_id:
        parent_json = _resolve_version_json(parent_id, manifest, versions_dir)
        version_json = _merge_version(parent_json, version_json)

    return version_json


def get_latest_release_id() -> str:
    manifest = _download_json(MANIFEST_URL, None)
    latest = manifest.get("latest", {}).get("release")
    if not latest:
        raise RuntimeError("No latest release found")
    return str(latest)


def get_forge_version_id() -> str:
    return f"{MC_VERSION}-forge-{FORGE_VERSION}"


def ensure_forge_version(versions_dir: Path, java_path: str, game_dir: Path, status: StatusCallback = None) -> str:
    version_id = get_forge_version_id()
    ver_dir = versions_dir / version_id
    json_path = ver_dir / f"{version_id}.json"
    jar_path = ver_dir / f"{version_id}.jar"

    if json_path.exists() and jar_path.exists():
        return version_id

    ver_dir.mkdir(parents=True, exist_ok=True)
    json_url = f"{FORGE_MAVEN_BASE}/forge-{MC_VERSION}-{FORGE_VERSION}.json"
    jar_url = f"{FORGE_MAVEN_BASE}/forge-{MC_VERSION}-{FORGE_VERSION}.jar"

    try:
        data = _download_json(json_url, json_path)
        real_id = str(data.get("id") or version_id)
        if real_id != version_id:
            ver_dir = versions_dir / real_id
            ver_dir.mkdir(parents=True, exist_ok=True)
            json_path = ver_dir / f"{real_id}.json"
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            jar_path = ver_dir / f"{real_id}.jar"
            version_id = real_id

        _download_file(jar_url, jar_path, None, None)
        return version_id
    except Exception:
        pass

    if status:
        status("download_forge_installer")

    installer_name = f"forge-{MC_VERSION}-{FORGE_VERSION}-installer.jar"
    installer_url = f"{FORGE_MAVEN_BASE}/{installer_name}"
    installer_path = versions_dir / installer_name
    _download_file(installer_url, installer_path, None, None)
    if not zipfile.is_zipfile(installer_path):
        installer_path.unlink(missing_ok=True)
        _download_file(installer_url, installer_path, None, None)
    _ensure_readable_jar(installer_path, "Forge installer")

    installer_runtime_path = ver_dir / "installer.jar"
    installer_runtime_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_runtime_path = installer_runtime_path.with_suffix(".jar.tmp")
    shutil.copy2(installer_path, tmp_runtime_path)
    tmp_runtime_path.replace(installer_runtime_path)
    _ensure_readable_jar(installer_runtime_path, "Forge runtime installer")

    if status:
        status("install_forge")

    import subprocess

    _ensure_launcher_profile(game_dir)
    cmd = [java_path, "-jar", str(installer_path), "--installClient"]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if platform.system() == "Windows" else 0
    proc = subprocess.run(cmd, cwd=str(game_dir), capture_output=True, text=True, creationflags=creationflags)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(msg or "Forge installer failed")

    if json_path.exists() and jar_path.exists():
        return version_id

    # Fallback: installer may have created a different version id
    if ver_dir.exists():
        for p in ver_dir.iterdir():
            if p.name.endswith(".json"):
                return p.stem

    raise RuntimeError("Forge version files not found after install")


def _ensure_launcher_profile(game_dir: Path) -> None:
    try:
        profile_path = game_dir / "launcher_profiles.json"
        if profile_path.exists():
            return
        data = {
            "profiles": {},
            "clientToken": "00000000000000000000000000000000",
        }
        profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def prepare_version(
    version_id: str,
    progress: ProgressCallback = None,
    status: StatusCallback = None,
) -> PreparedVersion:
    if version_id == "latest_release":
        version_id = get_latest_release_id()

    game_dir = get_data_dir() / "minecraft"
    versions_dir = game_dir / "versions"
    libraries_dir = game_dir / "libraries"
    assets_dir = game_dir / "assets"
    natives_dir = game_dir / "natives" / version_id

    manifest = _download_json(MANIFEST_URL, None)
    version_json = _resolve_version_json(version_id, manifest, versions_dir)

    if status:
        status("download_client")

    # client jar
    client = (version_json.get("downloads") or {}).get("client") or {}
    jar_url = client.get("url")
    if not jar_url:
        raise RuntimeError("Client URL missing")
    jar_path = versions_dir / version_id / f"{version_id}.jar"
    _download_file(jar_url, jar_path, client.get("size"), client.get("sha1"))

    downloads = []

    # libraries + natives
    for lib in version_json.get("libraries", []) or []:
        if not _rules_allow(lib.get("rules")):
            continue
        downloads_info = lib.get("downloads") or {}
        artifact = downloads_info.get("artifact")
        if artifact:
            downloads.append(("lib", artifact, libraries_dir / artifact.get("path", "")))
        else:
            name = lib.get("name")
            if name:
                try:
                    rel_path, _ = _maven_path_from_name(str(name))
                    base_url = (lib.get("url") or "https://libraries.minecraft.net").rstrip("/")
                    url = f"{base_url}/{rel_path}"
                    downloads.append(("lib", {"url": url}, libraries_dir / rel_path))
                except Exception:
                    pass
        natives = lib.get("natives") or {}
        native_key = natives.get(_os_name())
        if native_key:
            native_key = native_key.replace("${arch}", _arch())
            classifier = (downloads_info.get("classifiers") or {}).get(native_key)
            if classifier:
                downloads.append(("native", classifier, libraries_dir / classifier.get("path", "")))
            elif lib.get("name"):
                # fallback for natives without downloads in json
                try:
                    rel_path, _ = _maven_path_from_name(f"{lib.get('name')}:{native_key}")
                    base_url = (lib.get("url") or "https://libraries.minecraft.net").rstrip("/")
                    url = f"{base_url}/{rel_path}"
                    downloads.append(("native", {"url": url}, libraries_dir / rel_path))
                except Exception:
                    pass

    # assets index + objects
    asset_index = version_json.get("assetIndex") or {}
    index_id = asset_index.get("id") or "legacy"
    index_url = asset_index.get("url")
    index_path = assets_dir / "indexes" / f"{index_id}.json"
    if index_url:
        downloads.append(("asset_index", {"url": index_url}, index_path))

    total = len(downloads)
    if status and any(kind == "lib" for kind, _, _ in downloads):
        status("download_libs")
    if status and any(kind == "native" for kind, _, _ in downloads):
        status("download_natives")
    if status and any(kind == "asset_index" for kind, _, _ in downloads):
        status("download_asset_index")

    _download_many(downloads, progress=progress, total=total)

    for kind, _, dest in downloads:
        if kind == "native":
            _extract_native(dest, natives_dir)

    if index_path.exists():
        if status:
            status("download_assets")
        asset_index_json = json.loads(index_path.read_text(encoding="utf-8"))
        objects = (asset_index_json.get("objects") or {})
        total_assets = len(objects)
        downloaded = 0
        asset_downloads = []
        progress_step = max(1, total_assets // 200)
        for name, obj in objects.items():
            h = obj.get("hash")
            if not h:
                continue
            sub = h[:2]
            obj_path = assets_dir / "objects" / sub / h
            size = int(obj.get("size") or 0)
            if _valid_file(obj_path, size, None):
                downloaded += 1
                if progress and (downloaded == total_assets or downloaded % progress_step == 0):
                    progress(downloaded, total_assets)
                continue
            url = f"{ASSETS_BASE_URL}/{sub}/{h}"
            asset_downloads.append(("asset", {"url": url, "size": size, "sha1": h}, obj_path))
        _download_many(asset_downloads, progress=progress, initial_done=downloaded, total=total_assets)

    return PreparedVersion(
        version_id=version_id,
        version_json=version_json,
        game_dir=game_dir,
        versions_dir=versions_dir,
        libraries_dir=libraries_dir,
        assets_dir=assets_dir,
        natives_dir=natives_dir,
    )


def _extract_native(archive_path: Path, natives_dir: Path) -> None:
    if not archive_path.exists():
        return
    natives_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                if not member or member.endswith("/"):
                    continue
                if member.startswith("META-INF/"):
                    continue
                target = natives_dir / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile:
        return
