import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from auth.auth_storage import load_settings
from auth.settings import API_BASE


DEFAULT_PROBE_TIMEOUT = 2.5
DEFAULT_CACHE_TTL_SECONDS = 300.0

_api_base_cache_lock = threading.Lock()
_api_base_cache_value = ""
_api_base_cache_until = 0.0


def _split_candidates(raw: str) -> list[str]:
    items: list[str] = []
    for part in raw.replace(";", ",").split(","):
        candidate = part.strip().rstrip("/")
        if not candidate:
            continue
        items.append(candidate)
    return items


def get_api_candidates() -> list[str]:
    settings = load_settings()
    candidates: list[str] = []

    if isinstance(settings, dict):
        multi = str(settings.get("api_base_urls") or "").strip()
        single = str(settings.get("api_base_url") or "").strip()
        if multi:
            candidates.extend(_split_candidates(multi))
        if single:
            candidates.extend(_split_candidates(single))

    env_multi = os.getenv("LOTA_API_BASES", "").strip()
    env_single = os.getenv("LOTA_API_BASE", "").strip()
    if env_multi:
        candidates.extend(_split_candidates(env_multi))
    if env_single:
        candidates.extend(_split_candidates(env_single))

    if API_BASE:
        candidates.extend(_split_candidates(API_BASE))

    seen: set[str] = set()
    normalized: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def _probe_candidate(base_url: str, timeout: float) -> tuple[str, float]:
    started = time.perf_counter()
    response = requests.get(f"{base_url}/ping", timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    return base_url, time.perf_counter() - started


def resolve_fastest_api_base(*, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    global _api_base_cache_value, _api_base_cache_until

    now = time.monotonic()
    with _api_base_cache_lock:
        if not force_refresh and _api_base_cache_value and now < _api_base_cache_until:
            return _api_base_cache_value

    candidates = get_api_candidates()
    if not candidates:
        raise RuntimeError("No API base candidates configured")
    if len(candidates) == 1:
        winner = candidates[0]
        with _api_base_cache_lock:
            _api_base_cache_value = winner
            _api_base_cache_until = time.monotonic() + DEFAULT_CACHE_TTL_SECONDS
        return winner

    best_url = ""
    best_latency = None
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(len(candidates), 4)) as executor:
        future_map = {
            executor.submit(_probe_candidate, base_url, timeout): base_url
            for base_url in candidates
        }
        for future in as_completed(future_map):
            base_url = future_map[future]
            try:
                url, latency = future.result()
            except Exception as exc:
                errors.append(f"{base_url}: {exc}")
                continue
            if best_latency is None or latency < best_latency:
                best_url = url
                best_latency = latency

    if not best_url:
        raise RuntimeError("All API candidates failed: " + "; ".join(errors))

    with _api_base_cache_lock:
        _api_base_cache_value = best_url
        _api_base_cache_until = time.monotonic() + DEFAULT_CACHE_TTL_SECONDS
    return best_url


def get_api_base(*, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    return resolve_fastest_api_base(force_refresh=force_refresh, timeout=timeout).rstrip("/")


def build_api_url(path: str, *, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    return f"{get_api_base(force_refresh=force_refresh, timeout=timeout)}/{path.lstrip('/')}"
