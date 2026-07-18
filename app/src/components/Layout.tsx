import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { useEffect, useRef, useState, useCallback } from "react";
import { useBackend, apiGet, apiPost, invalidateCache } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import { win } from "../lib/tauri";
import styles from "./Layout.module.css";

const PAGE_EXIT_MS  = 150;
const PAGE_ENTER_MS = 220;

interface LayoutProps {
  onLogout: () => void;
}

export interface PlayState {
  state?: string;   // "idle" | "running" | "launched" | "error"
  status?: string;
  progress?: number;
  error?: string | null;
  pid?: number | null;
}

export interface PageContext {
  onBack: () => void;
  onLogout: () => void;
}

function SkinHead({ port, username }: { port: number | null; username: string }) {
  const [failed, setFailed] = useState(false);
  const src = port ? `http://127.0.0.1:${port}/skin/head?size=40&_t=${port}` : null;

  if (!src || failed) {
    return <div className={styles.profileAvatar}>{username[0]?.toUpperCase() ?? "?"}</div>;
  }
  return (
    <img
      key={src}
      className={styles.profileAvatarImg}
      src={src}
      alt=""
      onError={() => setFailed(true)}
      onLoad={() => setFailed(false)}
    />
  );
}

function DebugConsole({ port }: { port: number | null }) {
  const [lines, setLines] = useState<string[]>([]);
  const offsetRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef   = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    async function poll() {
      if (!port) return;
      try {
        const res = await fetch(
          `http://127.0.0.1:${port}/debug/logs?since=${offsetRef.current}`
        );
        if (!res.ok) return;
        const data: { lines: string[]; total: number } = await res.json();
        if (data.lines.length > 0) {
          offsetRef.current = data.total;
          setLines(prev => {
            const next = [...prev, ...data.lines];
            return next.length > 500 ? next.slice(next.length - 500) : next;
          });
        }
      } catch { /* ignore */ }
    }
    poll();
    pollRef.current = setInterval(poll, 500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [port]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className={styles.debugConsole}>
      <div className={styles.debugHeader}>
        <span className={styles.debugTitle}>Консоль</span>
        <button className={styles.debugClear} onClick={() => { setLines([]); }}>Очистить</button>
      </div>
      <div className={styles.debugBody}>
        {lines.map((l, i) => (
          <div key={i} className={`${styles.debugLine} ${
            l.startsWith("[ERR]") ? styles.debugLineErr :
            l.startsWith("[MC]")  ? styles.debugLineMc  : ""
          }`}>{l}</div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export default function Layout({ onLogout }: LayoutProps) {
  const port = useBackend();
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("—");
  const [playState, setPlayState] = useState<PlayState>({ state: "idle" });
  const [playBusy, setPlayBusy] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevPlayStateRef = useRef<string>("idle");

  const [pageAnim, setPageAnim] = useState<"enter" | "exit" | "">( "enter");
  const [sidebarAnim, setSidebarAnim] = useState<"enter" | "exit" | "">("enter");
  const animTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isHome = location.pathname === "/home";

  // анимация при смене маршрута + перезагрузка дебаг-режима на главной
  useEffect(() => {
    setPageAnim("enter");
    const t = setTimeout(() => setPageAnim(""), PAGE_ENTER_MS);
    if (location.pathname === "/home") {
      setSidebarAnim("enter");
      loadDebugMode();
    }
    return () => clearTimeout(t);
  }, [location.pathname]);

  const navigateAnimated = useCallback((to: string) => {
    if (animTimerRef.current) clearTimeout(animTimerRef.current);
    const leavingHome = location.pathname === "/home" && to !== "/home";
    if (leavingHome) setSidebarAnim("exit");
    setPageAnim("exit");
    animTimerRef.current = setTimeout(() => {
      navigate(to);
    }, PAGE_EXIT_MS);
  }, [location.pathname, navigate]);

  useEffect(() => {
    loadUsername();
    loadDebugMode();
    pollPlayState();
    pollRef.current = setInterval(pollPlayState, 5000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [port]);

  async function loadDebugMode() {
    try {
      const s = await apiGet<{ debug_mode?: boolean }>(port, "/settings", 0);
      setDebugMode(!!s?.debug_mode);
    } catch { /* ignore */ }
  }

  async function loadUsername() {
    try {
      const data = await apiGet<{ username?: string }>(port, "/auth/load", 5 * 60_000);
      setUsername(data?.username || "—");
    } catch { /* ignore */ }
  }

  async function pollPlayState() {
    try {
      const data = await apiGet<PlayState>(port, "/play/state", 0);
      if (!data || typeof data !== "object") return;

      const newState = data.state ?? "idle";
      const prevState = prevPlayStateRef.current;
      if (newState === "launched" && prevState !== "launched") {
        win.hide().catch(() => {});
      } else if (prevState === "launched" && newState !== "launched") {
        win.show().catch(() => {});
      }
      prevPlayStateRef.current = newState;

      setPlayState(data);
      setPlayBusy(false);
    } catch { /* ignore */ }
  }

  async function handlePlay() {
    if (playBusy) return;
    const ps = playState.state ?? "idle";
    if (ps === "running") return; // preparing — not clickable
    setPlayBusy(true);
    try {
      if (ps === "launched") {
        await apiPost(port, "/play/stop");
      } else {
        await apiPost(port, "/play/start");
      }
      await pollPlayState();
    } catch {
      setPlayBusy(false);
    }
  }

  async function handleLogout() {
    await apiPost(port, "/auth/clear").catch(() => {});
    invalidateCache();
    onLogout();
    navigate("/login");
  }

  const nav = [
    { path: "/account",  label: t("btn_account",  "Аккаунт")   },
    { path: "/library",  label: t("btn_library",  "Библиотека") },
    { path: "/friends",  label: t("btn_friends",  "Друзья")     },
    { path: "/settings", label: t("btn_settings", "Настройки")  },
  ];

  const ps          = playState.state ?? "idle";
  const isLaunched  = ps === "launched";
  const isPreparing = ps === "running";
  const isError     = ps === "error";
  const progress    = playState.progress ?? 0;
  const statusText  = isError
    ? (playState.error ?? "Ошибка")
    : (playState.status ?? "");

  const pageCtx: PageContext = {
    onBack:   () => navigateAnimated("/home"),
    onLogout: handleLogout,
  };

  const pageAnimClass = pageAnim === "enter" ? styles.pageEnter
                      : pageAnim === "exit"  ? styles.pageExit
                      : "";

  const sidebarAnimClass = sidebarAnim === "enter" ? styles.sidebarEnter
                         : sidebarAnim === "exit"  ? styles.sidebarExit
                         : "";

  return (
    <div className={styles.appRoot}>
    <div className={`${styles.layout} ${isHome ? styles.layoutHome : ""}`}>
      {/* Content area */}
      <main className={`${styles.main} ${isHome ? styles.mainPanel : styles.mainPage}`}>
        <div className={`${styles.pageWrap} ${pageAnimClass}`}>
          <Outlet context={pageCtx} />
        </div>
      </main>

      {isHome && (
        <aside className={`${styles.sidebar} ${sidebarAnimClass}`}
          onAnimationEnd={() => { if (sidebarAnim === "enter") setSidebarAnim(""); }}
        >
          <div className={styles.sidebarInner}>
            <div className={styles.navLabel}>{t("nav_header", "Навигация")}</div>

            <button
              className={`${styles.btnPlay} ${isLaunched ? styles.btnStop : ""}`}
              onClick={handlePlay}
              disabled={playBusy || isPreparing}
            >
              {isPreparing
                ? t("play_status_preparing", "Подготовка...")
                : isLaunched
                  ? t("btn_close", "Закрыть")
                  : t("btn_play", "Играть")
              }
            </button>

            {(isPreparing || isLaunched || isError) && (
              <div className={`${styles.playStatus} ${isError ? styles.playError : ""}`}>
                {statusText}
                {isPreparing && progress > 0 && (
                  <div className={styles.progressBar}>
                    <div className={styles.progressFill} style={{ width: `${progress}%` }} />
                  </div>
                )}
              </div>
            )}

            <nav className={styles.nav}>
              {nav.map(item => (
                <button
                  key={item.path}
                  className={`${styles.navBtn} ${location.pathname === item.path ? styles.navBtnActive : ""}`}
                  onClick={() => navigateAnimated(item.path)}
                >
                  {item.label}
                </button>
              ))}
            </nav>

            <div className={styles.spacer} />

            <div
              className={styles.profileCard}
              onClick={() => navigateAnimated("/account")}
              title="Аккаунт"
            >
              <SkinHead port={port} username={username} />
              <div className={styles.profileName}>{username}</div>
            </div>

            <button className={styles.btnExit} onClick={() => win.close()}>
              {t("btn_exit", "Выход")}
            </button>
          </div>
        </aside>
      )}
    </div>
    {debugMode && <DebugConsole port={port} />}
    </div>
  );
}
