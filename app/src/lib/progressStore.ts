import { useCallback, useSyncExternalStore } from "react";

const FAKE_CAP = 27;
const TRANSITION_MS = 1000;

type Phase = "fake" | "transition" | "real";

interface ProgressEntry {
  percent: number;
  phase: Phase;
}

interface PollResult {
  progress?: number;
  state?: string;
  error?: string | null;
  result?: unknown;
  started?: boolean;
}

const entries = new Map<string, ProgressEntry>();
const listeners = new Map<string, Set<() => void>>();
const fakeTimers = new Map<string, ReturnType<typeof setTimeout>>();
const transitionRafs = new Map<string, number>();
const pollIntervals = new Map<string, ReturnType<typeof setInterval>>();

function emit(id: string) {
  listeners.get(id)?.forEach(fn => fn());
}

function setEntry(id: string, entry: ProgressEntry) {
  entries.set(id, entry);
  emit(id);
}

function clearFakeTimer(id: string) {
  const timer = fakeTimers.get(id);
  if (timer) { clearTimeout(timer); fakeTimers.delete(id); }
}

function clearTransition(id: string) {
  const raf = transitionRafs.get(id);
  if (raf !== undefined) { cancelAnimationFrame(raf); transitionRafs.delete(id); }
}

function scheduleFakeStep(id: string) {
  const entry = entries.get(id);
  if (!entry || entry.phase !== "fake") return;
  const x = entry.percent;
  const delay = (1 + x * 0.5) * 1000;
  const timer = setTimeout(() => {
    const cur = entries.get(id);
    if (!cur || cur.phase !== "fake") return;
    setEntry(id, { percent: Math.min(FAKE_CAP - 1, cur.percent + 1), phase: "fake" });
    scheduleFakeStep(id);
  }, delay);
  fakeTimers.set(id, timer);
}

export function startFakeProgress(id: string) {
  clearFakeTimer(id);
  clearTransition(id);
  setEntry(id, { percent: 0, phase: "fake" });
  scheduleFakeStep(id);
}

function beginRealProgress(id: string) {
  clearFakeTimer(id);
  clearTransition(id);
  const from = entries.get(id)?.percent ?? 0;
  const start = performance.now();

  function tick(now: number) {
    const t = Math.min(1, (now - start) / TRANSITION_MS);
    setEntry(id, { percent: from + (FAKE_CAP - from) * t, phase: "transition" });
    if (t < 1) {
      transitionRafs.set(id, requestAnimationFrame(tick));
    } else {
      transitionRafs.delete(id);
      setEntry(id, { percent: FAKE_CAP, phase: "real" });
    }
  }
  transitionRafs.set(id, requestAnimationFrame(tick));
}

export function applyRealProgress(id: string, rawPercent: number) {
  const entry = entries.get(id);
  if (!entry) return;
  if (entry.phase === "fake") { beginRealProgress(id); return; }
  if (entry.phase === "transition") return;
  const mapped = FAKE_CAP + Math.max(0, Math.min(100, rawPercent)) * (100 - FAKE_CAP) / 100;
  setEntry(id, { percent: Math.max(entry.percent, mapped), phase: "real" });
}

function stopPolling(id: string) {
  const interval = pollIntervals.get(id);
  if (interval) { clearInterval(interval); pollIntervals.delete(id); }
}

export function stopTracking(id: string) {
  stopPolling(id);
  clearFakeTimer(id);
  clearTransition(id);
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
  startFakeProgress(id);

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

    if (res.state === "done") {
      stopped = true;
      setEntry(id, { percent: 100, phase: "real" });
      stopPolling(id);
      clearFakeTimer(id);
      clearTransition(id);
      opts.onDone?.(res);
      setTimeout(() => stopTracking(id), 400);
    } else if (res.state === "error") {
      stopped = true;
      stopTracking(id);
      opts.onError?.(res.error);
    } else if (typeof res.progress === "number") {
      applyRealProgress(id, res.progress);
    } else if (res.started && entries.get(id)?.phase === "fake") {
      beginRealProgress(id);
    }
  }

  pollIntervals.set(id, setInterval(tick, intervalMs));
  tick();
}

export function useProgress(id: string | null): number | undefined {
  const subscribeFn = useCallback((cb: () => void) => (id ? subscribe(id, cb) : () => {}), [id]);
  const getSnapshot = useCallback(() => (id ? getDisplayPercent(id) : undefined), [id]);
  return useSyncExternalStore(subscribeFn, getSnapshot);
}
