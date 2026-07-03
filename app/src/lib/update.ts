import { apiGet, apiPost } from "./BackendContext";

export type UpdateMode = "appimage" | "macos-app" | "external" | null;

export interface UpdateCheckResult {
  ok: boolean;
  mode: UpdateMode;
  update_available: boolean;
  version?: string;
  url?: string;
  sha256?: string;
  size?: number;
  error?: string;
}

export interface UpdateTaskStatus {
  state?: string;
  progress?: number;
  error?: string | null;
  result?: { relaunch_path?: string; version?: string } | null;
}

export function checkForUpdate(port: number | null, localVersion: string) {
  return apiGet<UpdateCheckResult>(port, `/update/check?version=${encodeURIComponent(localVersion)}`, 0);
}

export function startUpdateInstall(
  port: number | null,
  info: { url: string; sha256?: string; size?: number; version?: string },
) {
  return apiPost<{ ok: boolean; task_id?: string }>(port, "/update/install", info);
}

export function pollUpdateTask(port: number | null, taskId: string) {
  return apiGet<UpdateTaskStatus>(port, `/task/${taskId}`, 0);
}

// AppImage и macOS-бандл апдейтятся одинаково — прямо внутри приложения,
// через UpdateDialog. Только Windows (mode === "external") идёт другим путём.
export function isInAppUpdateMode(mode: UpdateMode): boolean {
  return mode === "appimage" || mode === "macos-app";
}
