from __future__ import annotations

import json
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from services.build_sync import BuildSync, ProgressCallback, remove_closed_links


@dataclass(frozen=True)
class LibraryCatalog:
    builds: list[dict]
    dlc: list[dict]
    base_dir: Path


@dataclass(frozen=True)
class LibraryPaths:
    data_dir: Path

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "library_cache"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def builds_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def instances_path(self) -> Path:
        return self.cache_dir / "instances.json"

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / "manifest.json"

    @property
    def manifest_hash_path(self) -> Path:
        return self.cache_dir / "manifest.hash"


class LibraryService:
    BUILD_META_FILE_NAME = ".lota_build_meta.json"

    def __init__(self, data_dir: Path, api_base_resolver):
        self.paths = LibraryPaths(Path(data_dir))
        self._api_base_resolver = api_base_resolver

    def local_asset_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent / "assets" / "library"

    def prepare_dirs(self) -> None:
        for path in (self.paths.cache_dir, self.paths.downloads_dir, self.paths.builds_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue

    def pick_random_cached_image(self) -> str:
        images_dir = self.paths.cache_dir / "images"
        if not images_dir.exists():
            return ""
        candidates = [
            path
            for path in images_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        ]
        if not candidates:
            return ""
        return str(random.choice(candidates))

    def load_instances(self) -> list[dict]:
        path = self.paths.instances_path
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        normalized: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.setdefault("is_instance", True)
            normalized.append(row)
        return normalized

    def save_instances(self, items: list[dict]) -> None:
        self.prepare_dirs()
        payload = {"items": items}
        self.paths.instances_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_instance(self, payload: dict) -> dict:
        source_build = payload.get("build") or {}
        timestamp = int(time.time())
        instance = {
            "id": f"instance-{timestamp}-{int(time.time_ns() % 1_000_000)}",
            "created_at": timestamp,
            "name": str(payload.get("name") or "").strip(),
            "version": str(source_build.get("version") or "").strip(),
            "description": str(payload.get("description") or "").strip(),
            "image": str(payload.get("image") or "").strip(),
            "_source_build_id": source_build.get("id"),
            "is_instance": True,
        }
        items = self.load_instances()
        items.append(instance)
        self.save_instances(items)
        return instance

    def update_instance(self, target_id, payload: dict) -> list[dict]:
        items = self.load_instances()
        for item in items:
            if item.get("id") != target_id:
                continue
            item["name"] = str(payload.get("name") or item.get("name") or "")
            item["description"] = str(payload.get("description") or item.get("description") or "")
            item["image"] = str(payload.get("image") or item.get("image") or "")
            break
        self.save_instances(items)
        return items

    def delete_instance(self, target_id) -> list[dict]:
        items = [item for item in self.load_instances() if item.get("id") != target_id]
        self.save_instances(items)
        return items

    def load_catalog(self, token: str = "", *, prefer_remote: bool = True) -> LibraryCatalog:
        self.prepare_dirs()
        remote_catalog = self._fetch_remote_catalog(token) if prefer_remote else None
        instances = self.load_instances()
        if remote_catalog is not None:
            builds = instances + remote_catalog.builds
            print(f"[library] catalog from server: {len(remote_catalog.builds)} builds, {len(instances)} instances", flush=True)
            return LibraryCatalog(builds=builds, dlc=remote_catalog.dlc, base_dir=remote_catalog.base_dir)

        if self.paths.manifest_path.exists():
            builds, dlc = self._load_from_manifest(self.paths.manifest_path, self.paths.cache_dir)
            if builds or dlc:
                print(f"[library] catalog from local cache{' (server unavailable)' if prefer_remote else ''}: {len(builds)} builds, {len(instances)} instances", flush=True)
                builds = instances + builds
                return LibraryCatalog(builds=builds, dlc=dlc, base_dir=self.paths.cache_dir)

        local_dir = self.local_asset_dir()
        manifest_path = local_dir / "manifest.json"
        if manifest_path.exists():
            builds, dlc = self._load_from_manifest(manifest_path, local_dir)
        else:
            builds = self._load_json_items(local_dir / "builds.json")
            dlc = self._load_json_items(local_dir / "dlc.json")
        print(f"[library] catalog from bundled assets (no server, no cache): {len(builds)} builds, {len(instances)} instances", flush=True)
        builds = instances + builds
        return LibraryCatalog(builds=builds, dlc=dlc, base_dir=local_dir)

    def build_key(self, item: dict) -> str:
        if item.get("is_instance") and item.get("id"):
            instance_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(item.get("id")))
            return f"instance-{instance_id}"
        return self._legacy_build_key(item)

    def _legacy_build_key(self, item: dict) -> str:
        name = str(item.get("name") or "").strip()
        version = str(item.get("version") or "").strip()
        title = f"{name} {version}".strip()
        if not title:
            build_id = item.get("id")
            title = f"build_{build_id}" if build_id else "build"
        title = title.replace("/", " ").replace("\\", " ")
        title = re.sub(r"[^A-Za-z0-9._ -]+", "_", title)
        title = re.sub(r"\s+", " ", title).strip()
        return title or "build"

    def build_install_dir(self, item: dict) -> Path:
        self.prepare_dirs()
        stable_dir = self.paths.builds_dir / self.build_key(item)
        if item.get("is_instance"):
            legacy_dir = self.paths.builds_dir / self._legacy_build_key(item)
            if legacy_dir.exists() and not stable_dir.exists():
                return legacy_dir
        return stable_dir

    def build_meta_path(self, item: dict) -> Path:
        return self.build_install_dir(item) / self.BUILD_META_FILE_NAME

    def is_build_installed(self, item: dict) -> bool:
        build_dir = self.build_install_dir(item)
        if not build_dir.is_dir():
            return False
        for name in ("mods", "config", "resourcepacks", "shaderpacks", "saves"):
            if (build_dir / name).exists():
                return True
        try:
            return any(path.name != "build.zip" for path in build_dir.iterdir())
        except Exception:
            return False

    def expected_build_updated_at(self, item: dict) -> str:
        return str(item.get("updated_at") or item.get("created_at") or "").strip()

    def load_build_meta(self, item: dict) -> dict:
        meta_path = self.build_meta_path(item)
        if not meta_path.exists():
            return {}
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def is_build_up_to_date(self, item: dict, *, source_item: dict | None = None) -> bool:
        if not self.is_build_installed(item):
            return False
        expected = self.expected_build_updated_at(source_item or item)
        if not expected:
            return True
        meta = self.load_build_meta(item)
        actual = str(meta.get("updated_at") or "").strip()
        return bool(actual and actual == expected)

    def _write_build_meta(self, target_item: dict, *, source_item: dict | None = None, managed_files: list[str] | None = None) -> None:
        meta_path = self.build_meta_path(target_item)
        source = source_item or target_item
        payload = {
            "build_id": source.get("id"),
            "source_build_id": source.get("id"),
            "target_build_key": self.build_key(target_item),
            "updated_at": self.expected_build_updated_at(source),
            "version": str(source.get("version") or ""),
            "installed_at": int(time.time()),
            "managed_files": managed_files or [],
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync_build(
        self,
        target_item: dict,
        *,
        token: str,
        source_item: dict | None = None,
        progress: ProgressCallback = None,
    ) -> None:
        BuildSync(
            api_base_resolver=self._api_base_resolver,
            token=token,
            build_id=int((source_item or target_item).get("id")),
            install_dir=self.build_install_dir(target_item),
            progress=progress,
        ).run()
        self._write_build_meta(target_item, source_item=source_item, managed_files=[])

    def delete_build_files(self, item: dict) -> bool:
        build_dir = self.build_install_dir(item)
        if not build_dir.exists():
            return False
        remove_closed_links(build_dir)
        shutil.rmtree(build_dir)
        return True

    def resolve_image_path(self, base_dir: Path, item: dict) -> Path | None:
        image_path = str(item.get("image") or "").strip()
        if not image_path:
            return None
        candidate = Path(image_path)
        if candidate.is_absolute() and candidate.exists():
            return candidate
        resolved = (base_dir / candidate).resolve()
        return resolved if resolved.exists() else None

    def _read_cached_hash(self) -> str:
        if not self.paths.manifest_hash_path.exists():
            return ""
        try:
            return self.paths.manifest_hash_path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _write_cached_hash(self, value: str) -> None:
        self.prepare_dirs()
        self.paths.manifest_hash_path.write_text(value or "", encoding="utf-8")

    def _fetch_remote_catalog(self, token: str) -> LibraryCatalog | None:
        token = str(token or "").strip()
        if not token:
            print("[library] remote catalog skipped: not logged in", flush=True)
            return None
        try:
            base_url = self._api_base_resolver()
        except Exception as exc:
            print(f"[library] remote catalog skipped: no api base: {type(exc).__name__}: {exc}", flush=True)
            return None
        cached_hash = self._read_cached_hash() if self.paths.manifest_path.exists() else ""
        try:
            response = requests.post(
                f"{base_url}/api/library/check",
                json={"token": token, "hash": cached_hash},
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"[library] remote catalog failed: {type(exc).__name__}: {exc}", flush=True)
            return None
        if response.status_code != 200:
            print(f"[library] remote catalog failed: HTTP {response.status_code}", flush=True)
            return None
        try:
            data = response.json()
        except ValueError:
            print("[library] remote catalog failed: response is not json", flush=True)
            return None
        if not isinstance(data, dict):
            print(f"[library] remote catalog failed: unexpected response type {type(data).__name__}", flush=True)
            return None

        if data.get("ok") is True and self.paths.manifest_path.exists():
            print(f"[library] remote catalog unchanged (hash {cached_hash or '-'}), using cache", flush=True)
            builds, dlc = self._load_from_manifest(self.paths.manifest_path, self.paths.cache_dir)
            return LibraryCatalog(builds=builds, dlc=dlc, base_dir=self.paths.cache_dir)

        manifest = data.get("manifest")
        if not isinstance(manifest, dict):
            print(f"[library] remote catalog failed: no manifest in response (keys {sorted(data)})", flush=True)
            return None

        print(f"[library] remote catalog changed: hash {cached_hash or '-'} -> {data.get('hash') or '-'}, downloading files", flush=True)
        self.paths.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for group in ("builds", "dlc"):
            for entry in manifest.get(group, []) or []:
                if not isinstance(entry, dict):
                    continue
                for key in ("json", "image"):
                    rel_path = entry.get(key)
                    if rel_path:
                        self._download_library_file(base_url, token, str(rel_path))

        self._write_cached_hash(str(data.get("hash") or ""))
        builds, dlc = self._load_from_manifest(self.paths.manifest_path, self.paths.cache_dir)
        return LibraryCatalog(builds=builds, dlc=dlc, base_dir=self.paths.cache_dir)

    def _download_library_file(self, base_url: str, token: str, rel_path: str) -> None:
        destination = self.paths.cache_dir / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(
            f"{base_url}/api/library/file",
            params={"token": token, "path": rel_path},
            timeout=10,
        )
        if response.status_code != 200:
            return
        destination.write_bytes(response.content)

    def _load_from_manifest(self, manifest_path: Path, base_dir: Path) -> tuple[list[dict], list[dict]]:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return [], []
        builds = self._load_manifest_group(data, "builds", base_dir)
        dlc = self._load_manifest_group(data, "dlc", base_dir)
        return builds, dlc

    def _load_manifest_group(self, data: dict, key: str, base_dir: Path) -> list[dict]:
        group = data.get(key, [])
        if not isinstance(group, list):
            return []
        items: list[dict] = []
        for entry in group:
            if not isinstance(entry, dict):
                continue
            json_path = entry.get("json")
            row: dict | None = None
            if json_path:
                item_path = (base_dir / str(json_path)).resolve()
                try:
                    item = json.loads(item_path.read_text(encoding="utf-8"))
                except Exception:
                    item = None
                if isinstance(item, dict):
                    row = dict(item)
            if row is None:
                inline_keys = {"json", "image"}
                row = {k: v for k, v in entry.items() if k not in inline_keys}
                if not row:
                    continue
            if "image" not in row and entry.get("image"):
                row["image"] = entry.get("image")
            if entry.get("id") and "id" not in row:
                row["id"] = entry.get("id")
            items.append(row)
        return items

    def _load_json_items(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []
