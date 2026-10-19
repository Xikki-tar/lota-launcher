import { createContext, useContext } from "react";

const BackendContext = createContext<number | null>(null);

export const BackendProvider = BackendContext.Provider;

export function useBackend() {
  return useContext(BackendContext);
}

let _backendKey = "";

export function setBackendKey(key: string) {
  _backendKey = key;
}

export function backendHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { ...extra, "X-Lota-Key": _backendKey };
}

export function backendUrl(port: number | null, path: string): string {
  const sep = path.includes("?") ? "&" : "?";
  return `http://127.0.0.1:${port}${path}${sep}key=${encodeURIComponent(_backendKey)}`;
}

// кеш чтобы при переходе между страницами не долбить бек снова
interface CacheEntry { data: unknown; ts: number; }
const _cache = new Map<string, CacheEntry>();

export function invalidateCache(path?: string) {
  if (path === undefined) {
    _cache.clear();
  } else {
    for (const k of _cache.keys()) {
      if (k.endsWith(path)) _cache.delete(k);
    }
  }
}

// ttlMs = 0 -> не кешировать для реалтайм
export async function apiGet<T = unknown>(port: number | null, path: string, ttlMs = 30_000): Promise<T> {
  if (!port) throw new Error("Backend not ready");

  if (ttlMs > 0) {
    const key = `${port}${path}`;
    const hit = _cache.get(key);
    if (hit && Date.now() - hit.ts < ttlMs) return hit.data as T;
  }

  const r = await fetch(`http://127.0.0.1:${port}${path}`, { headers: backendHeaders() });
  const data = await r.json() as T;

  if (ttlMs > 0) _cache.set(`${port}${path}`, { data, ts: Date.now() });

  return data;
}

export async function apiPost<T = unknown>(port: number | null, path: string, body?: unknown): Promise<T> {
  if (!port) throw new Error("Backend not ready");
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "POST",
    headers: backendHeaders({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export async function apiDelete<T = unknown>(port: number | null, path: string, body?: unknown): Promise<T> {
  if (!port) throw new Error("Backend not ready");
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "DELETE",
    headers: backendHeaders({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}
