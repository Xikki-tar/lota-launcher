import { useCallback, useSyncExternalStore } from "react";

export interface ProgressEntry {
  percent: number;
  file?: string | null;
  speed?: number;
}

interface PollResult {
  progress?: number;
  state?: string;
  error?: string | null;
  result?: unknown;
  started?: boolean;
  file?: string | null;
  speed?: number;
}

const entries = new Map<string, ProgressEntry>();
const listeners = new Map<string, Set<() => void>>();
const pollIntervals = new Map<string, ReturnType<typeof setInterval>>();

function emit(id: string) {
  listeners.get(id)?.forEach(fn => fn());
}

function setEntry(id: string, entry: ProgressEntry) {
  const prev = entries.get(id);
  entries.set(id, { file: prev?.file, speed: prev?.speed, ...entry });
  emit(id);
}

export function setProgressMeta(id: string, meta: { file?: string | null; speed?: number }) {
  const entry = entries.get(id);
  if (!entry) return;
  const file = meta.file === undefined ? entry.file : meta.file;
  const speed = meta.speed === undefined ? entry.speed : meta.speed;
  if (file === entry.file && speed === entry.speed) return;
  entries.set(id, { ...entry, file, speed });
  emit(id);
}

export function startProgress(id: string) {
  setEntry(id, { percent: 0 });
}

export function applyProgress(id: string, rawPercent: number) {
  const percent = Math.max(0, Math.min(100, rawPercent));
  setEntry(id, { percent: Math.max(entries.get(id)?.percent ?? 0, percent) });
}

function stopPolling(id: string) {
  const interval = pollIntervals.get(id);
  if (interval) { clearInterval(interval); pollIntervals.delete(id); }
}

export function stopTracking(id: string) {
  stopPolling(id);
  entries.delete(id);
  emit(id);
}

export function isTracking(id: string): boolean {
  return entries.has(id);
}

export function getDisplayPercent(id: string): number | undefined {
  const entry = entries.get(id);
  return entry ? Math.round(entry.percent) : undefined;
}

export function subscribe(id: string, cb: () => void): () => void {
  let set = listeners.get(id);
  if (!set) { set = new Set(); listeners.set(id, set); }
  set.add(cb);
  return () => {
    set!.delete(cb);
    if (set!.size === 0) listeners.delete(id);
  };
}

export function trackTask(
  id: string,
  pollFn: () => Promise<PollResult>,
  opts: { intervalMs?: number; onDone?: (result: PollResult) => void; onError?: (error?: string | null) => void } = {},
): void {
  if (isTracking(id)) return;
  startProgress(id);

  const intervalMs = opts.intervalMs ?? 800;
  let stopped = false;
  let inFlight = false;

  async function tick() {
    if (stopped || inFlight) return;
    inFlight = true;
    let res: PollResult;
    try {
      res = await pollFn();
    } catch {
      inFlight = false;
      return;
    }
    inFlight = false;
    if (stopped) return;
    setProgressMeta(id, { file: res.file, speed: res.speed });

    if (res.state === "done") {
      stopped = true;
      setEntry(id, { percent: 100 });
      stopPolling(id);
      opts.onDone?.(res);
      setTimeout(() => stopTracking(id), 400);
    } else if (res.state === "error") {
      stopped = true;
      stopTracking(id);
      opts.onError?.(res.error);
    } else if (typeof res.progress === "number") {
      applyProgress(id, res.progress);
    }
  }

  pollIntervals.set(id, setInterval(tick, intervalMs));
  tick();
}

export function useProgressInfo(id: string | null): ProgressEntry | undefined {
  const subscribeFn = useCallback((cb: () => void) => (id ? subscribe(id, cb) : () => {}), [id]);
  const getSnapshot = useCallback(() => (id ? entries.get(id) : undefined), [id]);
  return useSyncExternalStore(subscribeFn, getSnapshot);
}

export function useProgress(id: string | null): number | undefined {
  const subscribeFn = useCallback((cb: () => void) => (id ? subscribe(id, cb) : () => {}), [id]);
  const getSnapshot = useCallback(() => (id ? getDisplayPercent(id) : undefined), [id]);
  return useSyncExternalStore(subscribeFn, getSnapshot);
}
