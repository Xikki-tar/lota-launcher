import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from auth.auth_storage import load_settings, remove_settings
from auth.settings import DEFAULT_API_BASES


DEFAULT_PROBE_TIMEOUT = 2.5
DEFAULT_CACHE_TTL_SECONDS = 300.0

_SAVED_DEFAULT_API_BASES = (
    {"https://ru.lota.work", "https://eu.lota.work"},
    {"https://test.lota.work"},
)

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


def _env_candidates() -> list[str]:
    candidates: list[str] = []
    for key in ("LOTA_API_BASES", "LOTA_API_BASE"):
        raw = os.getenv(key, "").strip()
        if raw:
            candidates.extend(_split_candidates(raw))
    return candidates


def get_api_candidates() -> list[str]:
    env_candidates = _env_candidates()
    if env_candidates:
        return list(dict.fromkeys(env_candidates))

    settings = load_settings()
    candidates: list[str] = []

    if isinstance(settings, dict):
        multi = str(settings.get("api_base_urls") or "").strip()
        single = str(settings.get("api_base_url") or "").strip()
        if multi:
            candidates.extend(_split_candidates(multi))
        if single:
            candidates.extend(_split_candidates(single))

    if not candidates:
        candidates = _split_candidates(DEFAULT_API_BASES)

    seen: set[str] = set()
    normalized: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def drop_saved_default_api_bases() -> None:
    settings = load_settings()
    stale = {}
    for key in ("api_base_urls", "api_base_url"):
        saved = {base.lower() for base in _split_candidates(str(settings.get(key) or ""))}
        if saved in _SAVED_DEFAULT_API_BASES:
            stale[key] = settings.get(key)
    if not stale:
        return
    try:
        remove_settings(stale)
        print(f"[api] dropped api bases saved by older versions: {stale}", flush=True)
    except Exception as exc:
        print(f"[api] failed to drop saved api bases: {type(exc).__name__}: {exc}", flush=True)


def _probe_candidate(base_url: str, timeout: float) -> tuple[str, float]:
    started = time.perf_counter()
    try:
        response = requests.get(f"{base_url}/ping", timeout=timeout)
    except Exception as exc:
        print(f"[api] probe {base_url} failed: {type(exc).__name__}: {exc}", flush=True)
        raise
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        print(f"[api] probe {base_url} bad status: HTTP {response.status_code} ({elapsed * 1000:.0f}ms)", flush=True)
        raise RuntimeError(f"HTTP {response.status_code}")
    print(f"[api] probe {base_url} ok: {elapsed * 1000:.0f}ms", flush=True)
    return base_url, elapsed


def resolve_fastest_api_base(*, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    global _api_base_cache_value, _api_base_cache_until

    now = time.monotonic()
    with _api_base_cache_lock:
        if not force_refresh and _api_base_cache_value and now < _api_base_cache_until:
            return _api_base_cache_value

    candidates = get_api_candidates()
    if len(candidates) == 1:
        winner = candidates[0]
        print(f"[api] using {winner} (only candidate)", flush=True)
        with _api_base_cache_lock:
            _api_base_cache_value = winner
            _api_base_cache_until = time.monotonic() + DEFAULT_CACHE_TTL_SECONDS
        return winner

    print(f"[api] resolving fastest of {len(candidates)} candidates: {candidates}", flush=True)
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

    if best_url:
        print(f"[api] resolved {best_url} ({best_latency * 1000:.0f}ms)", flush=True)
    else:
        best_url = candidates[0]
        print(f"[api] all probes failed ({'; '.join(errors)}), falling back to {best_url}", flush=True)
    with _api_base_cache_lock:
        _api_base_cache_value = best_url
        _api_base_cache_until = time.monotonic() + DEFAULT_CACHE_TTL_SECONDS
    return best_url


def get_api_base(*, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    return resolve_fastest_api_base(force_refresh=force_refresh, timeout=timeout).rstrip("/")


def build_api_url(path: str, *, force_refresh: bool = False, timeout: float = DEFAULT_PROBE_TIMEOUT) -> str:
    return f"{get_api_base(force_refresh=force_refresh, timeout=timeout)}/{path.lstrip('/')}"
