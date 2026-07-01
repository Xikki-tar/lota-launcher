import { createContext, useContext } from "react";

const BackendContext = createContext<number | null>(null);

export const BackendProvider = BackendContext.Provider;

export function useBackend() {
  return useContext(BackendContext);
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

  const r = await fetch(`http://127.0.0.1:${port}${path}`);
  const data = await r.json() as T;

  if (ttlMs > 0) _cache.set(`${port}${path}`, { data, ts: Date.now() });

  return data;
}

export async function apiPost<T = unknown>(port: number | null, path: string, body?: unknown): Promise<T> {
  if (!port) throw new Error("Backend not ready");
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export async function apiDelete<T = unknown>(port: number | null, path: string, body?: unknown): Promise<T> {
  if (!port) throw new Error("Backend not ready");
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}
