import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap

from auth.api_base import get_api_base
from auth.auth_storage import get_data_dir, load_auth_data
from window.i18n import get_language, t


@dataclass(frozen=True)
class NewsPaths:
    cache_dir: Path
    manifest_path: Path
    hash_path: Path
    images_dir: Path


class NewsRefreshWorker(QThread):
    loaded = Signal(object)

    def __init__(self, paths: NewsPaths, parent=None):
        super().__init__(parent)
        self.paths = paths

    def _cache_path_for(self, rel_path: str) -> Path:
        normalized = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if normalized.startswith("images/"):
            normalized = normalized[len("images/"):]
        return self.paths.images_dir / normalized

    def run(self):
        payload = {"manifest": None, "images": {}, "server_unreachable": False}
        auth = load_auth_data() or {}
        token = str(auth.get("token") or "").strip()
        if not token:
            self.loaded.emit(payload)
            return

        try:
            base_url = get_api_base()
        except Exception:
            payload["server_unreachable"] = True
            self.loaded.emit(payload)
            return
        cached_hash = ""
        if self.paths.hash_path.exists():
            try:
                cached_hash = self.paths.hash_path.read_text(encoding="utf-8").strip()
            except Exception:
                cached_hash = ""

        manifest = None
        try:
            response = requests.post(
                f"{base_url}/api/news/check",
                json={"token": token, "hash": cached_hash},
                timeout=10,
            )
            if response.status_code != 200:
                payload["server_unreachable"] = True
            if response.status_code == 200:
                data = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else None
                if isinstance(data, dict):
                    if data.get("ok") is True and self.paths.manifest_path.exists():
                        try:
                            manifest = json.loads(self.paths.manifest_path.read_text(encoding="utf-8"))
                        except Exception:
                            manifest = None
                    else:
                        manifest = data.get("manifest") if isinstance(data.get("manifest"), dict) else None
                        if manifest:
                            try:
                                self.paths.manifest_path.write_text(
                                    json.dumps(manifest, ensure_ascii=False, indent=2),
                                    encoding="utf-8",
                                )
                                self.paths.hash_path.write_text(str(data.get("hash") or ""), encoding="utf-8")
                            except Exception:
                                pass
        except Exception:
            payload["server_unreachable"] = True
            manifest = None

        if not isinstance(manifest, dict) and self.paths.manifest_path.exists():
            try:
                manifest = json.loads(self.paths.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = None

        payload["manifest"] = manifest
        items = manifest.get("items") if isinstance(manifest, dict) else None
        if not isinstance(items, list):
            self.loaded.emit(payload)
            return

        for entry in items:
            rel_path = str(entry.get("image") or "").strip()
            if not rel_path or rel_path in payload["images"]:
                continue
            cache_path = self._cache_path_for(rel_path)
            if cache_path.exists():
                continue
            try:
                response = requests.get(
                    f"{base_url}/api/news/image",
                    params={"token": token, "path": rel_path},
                    timeout=10,
                )
            except Exception:
                continue
            if response.status_code == 200:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(response.content)
                except Exception:
                    pass
                payload["images"][rel_path] = response.content

        self.loaded.emit(payload)


class NewsService:
    def __init__(self):
        cache_dir = get_data_dir() / "news_cache"
        images_dir = cache_dir / "images"
        self.paths = NewsPaths(
            cache_dir=cache_dir,
            manifest_path=cache_dir / "manifest.json",
            hash_path=cache_dir / "manifest.hash",
            images_dir=images_dir,
        )
        self.paths.cache_dir.mkdir(parents=True, exist_ok=True)
        self.paths.images_dir.mkdir(parents=True, exist_ok=True)

    def load_cached_manifest(self) -> dict | None:
        if not self.paths.manifest_path.exists():
            return None
        try:
            return json.loads(self.paths.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def build_refresh_worker(self, parent=None) -> NewsRefreshWorker:
        return NewsRefreshWorker(self.paths, parent=parent)

    def image_cache_candidates(self, rel_path: str) -> list[Path]:
        normalized = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not normalized:
            return []
        trimmed = normalized[len("images/"):] if normalized.startswith("images/") else normalized
        candidates = [
            self.paths.images_dir / trimmed,
            self.paths.cache_dir / normalized,
            self.paths.images_dir / normalized,
        ]
        seen: set[str] = set()
        unique: list[Path] = []
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def pixmap_from_cache(self, rel_path: str, in_memory_images: dict[str, bytes]) -> QPixmap | None:
        pixmap = QPixmap()
        data = in_memory_images.get(rel_path)
        if data and pixmap.loadFromData(data):
            return pixmap
        for cache_path in self.image_cache_candidates(rel_path):
            if cache_path.exists() and pixmap.load(str(cache_path)):
                return pixmap
        return None

    def sorted_items(self, manifest: dict | None) -> list[dict]:
        items = manifest.get("items") if isinstance(manifest, dict) else None
        if not isinstance(items, list):
            return []

        def parse_date(value: str) -> datetime | None:
            if not value:
                return None
            text = str(value).strip()
            if not text:
                return None
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(text, fmt)
                except Exception:
                    continue
            try:
                return datetime.fromisoformat(text)
            except Exception:
                return None

        return sorted(
            items,
            key=lambda item: parse_date(str(item.get("date") or "")) or datetime.min,
            reverse=True,
        )

    def localize_text(self, value) -> str:
        if isinstance(value, dict):
            lang = get_language()
            lang_map = {"Русский": "ru", "English": "en", "Українська": "uk"}
            key = lang_map.get(lang, "ru")
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
            for candidate in value.values():
                if isinstance(candidate, str) and candidate.strip():
                    return candidate
            return ""
        if value is None:
            return ""
        return str(value)

    def localize_list(self, value) -> list[str]:
        if not isinstance(value, list):
            return []
        items: list[str] = []
        for entry in value:
            text = self.localize_text(entry)
            if text:
                items.append(text)
        return items

    def format_news_card_payload(self, entry: dict) -> dict:
        title = self.localize_text(entry.get("title")) or "—"
        body = self.localize_text(entry.get("body")) or ""
        return {
            "title": title,
            "date": str(entry.get("date") or ""),
            "body": body,
            "details": self.localize_text(entry.get("details")) or "",
            "changes": self.localize_list(entry.get("changes")),
            "type_key": str(entry.get("type") or "news").strip().lower(),
            "type_label": {
                "update": t("news_type_update"),
                "news": t("news_type_news"),
                "patch": t("news_type_patch"),
                "fix": t("news_type_patch"),
                "hotfix": t("news_type_patch"),
            }.get(str(entry.get("type") or "news").strip().lower(), t("news_type_news")),
        }
