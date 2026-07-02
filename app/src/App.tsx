import { useEffect, useState } from "react";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import TitleBar from "./components/TitleBar";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Library from "./pages/Library";
import Settings from "./pages/Settings";
import Account from "./pages/Account";
import Friends from "./pages/Friends";
import ErrorBoundary from "./components/ErrorBoundary";
import UpdateDialog from "./components/UpdateDialog";
import { BackendProvider } from "./lib/BackendContext";
import { I18nProvider } from "./lib/I18nContext";
import { checkForUpdate, type UpdateCheckResult } from "./lib/update";
import "./App.css";

type AppState = "loading" | "login" | "main";

async function resolvePort(): Promise<number> {
  // дев: порт из env, продакшн: tauri стартует питон и отдаёт порт
  const envPort = Number(import.meta.env.VITE_BACKEND_PORT);
  if (envPort) return envPort;

  return invoke<number>("backend_start");
}

export default function App() {
  const [state, setState] = useState<AppState>("loading");
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResult | null>(null);

  useEffect(() => {
    initApp();
  }, []);

  useEffect(() => {
    if (state !== "main") return;
    const timer = setTimeout(async () => {
      try {
        const version = await getVersion();
        const info = await checkForUpdate(backendPort, version);
        if (info.supported && info.update_available && info.url) setUpdateInfo(info);
      } catch { /* ignore — silent background check */ }
    }, 3000);
    return () => clearTimeout(timer);
  }, [state, backendPort]);

  async function initApp() {
    try {
      const port = await resolvePort();
      console.log("[App] port resolved:", port);
      setBackendPort(port);
      const auth = await fetch(`http://127.0.0.1:${port}/auth/load`).then(r => r.json());
      console.log("[App] auth/load →", JSON.stringify(auth));
      setState(auth?.token ? "main" : "login");
    } catch (e) {
      console.error("[App] initApp failed:", e);
      setState("login");
    }
  }

  if (state === "loading") {
    return (
      <div className="app">
        <TitleBar version="v0.1.0" />
        <div className="splash">Загрузка...</div>
      </div>
    );
  }

  return (
    <BackendProvider value={backendPort}>
      <I18nProvider>
      <HashRouter>
        <div className="app">
          <TitleBar version="v0.1.0" />
          <div className="content">
            <ErrorBoundary>
            <Routes>
              <Route
                path="/login"
                element={state === "main"
                  ? <Navigate to="/home" replace />
                  : <Login onLogin={() => setState("main")} />}
              />
              <Route element={<Layout onLogout={() => setState("login")} />}>
                <Route path="/home" element={<Home />} />
                <Route path="/library" element={<Library />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/account" element={<Account />} />
                <Route path="/friends" element={<Friends />} />
              </Route>
              <Route path="*" element={<Navigate to={state === "main" ? "/home" : "/login"} replace />} />
            </Routes>
            </ErrorBoundary>
          </div>
        </div>
        {updateInfo && (
          <UpdateDialog port={backendPort} info={updateInfo} onClose={() => setUpdateInfo(null)} />
        )}
      </HashRouter>
      </I18nProvider>
    </BackendProvider>
  );
}
