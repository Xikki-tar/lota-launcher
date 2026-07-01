import { invoke } from "@tauri-apps/api/core";

let _port: number | null = null;

export async function getPort(): Promise<number> {
  if (_port) return _port;
  _port = await invoke<number | null>("backend_port");
  if (!_port) throw new Error("Backend not started");
  return _port;
}

export async function initBackend(backendPath: string): Promise<number> {
  _port = await invoke<number>("backend_start", { backendPath });
  return _port;
}

async function url(path: string): Promise<string> {
  const port = await getPort();
  return `http://127.0.0.1:${port}${path}`;
}

export async function get<T = unknown>(path: string): Promise<T> {
  const r = await fetch(await url(path));
  return r.json();
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(await url(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}

export async function del<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(await url(path), {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return r.json();
}
