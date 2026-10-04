import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useBackend, apiGet, apiPost, apiDelete, invalidateCache } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import styles from "./Login.module.css";

interface ApiResp {
  ok: boolean;
  status: number;
  data: Record<string, unknown>;
}

function extractStatus(data: Record<string, unknown>): string {
  const nested = data.data;
  const merged = typeof nested === "object" && nested !== null
    ? { ...data, ...nested as Record<string, unknown> }
    : data;
  for (const key of ["status", "state", "registration_status", "telegram_status"]) {
    const v = String(merged[key] ?? "").trim().toLowerCase();
    if (v) return v;
  }
  for (const key of ["verified", "confirmed", "telegram_verified", "is_verified"]) {
    if (merged[key] === true) return "verified";
  }
  if (merged.completed === true) return "completed";
  return "";
}

function normalizeTelegramUrl(url: string): string {
  return url.replace("LotaTest_bot", "LotaManagerBot");
}

type RegStep = "choice" | "waiting" | "complete";

interface RegisterModalProps {
  port: number | null;
  onClose: () => void;
  onSuccess: () => void;
}

function RegisterModal({ port, onClose, onSuccess }: RegisterModalProps) {
  const { t } = useI18n();
  const [step, setStep] = useState<RegStep>("choice");
  const [linkToken, setLinkToken] = useState("");
  const [telegramUrl, setTelegramUrl] = useState("");
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // восстанавливаем ссылку если юзер закрыл окно и открыл снова
  useEffect(() => {
    apiGet<{ link_token?: string; telegram_url?: string }>(port, "/register/link", 0)
      .then((saved) => {
        if (saved?.link_token && saved.telegram_url) {
          setLinkToken(saved.link_token);
          setTelegramUrl(normalizeTelegramUrl(saved.telegram_url));
          setStep("waiting");
          startPolling(saved.link_token);
        }
      })
      .catch(() => {});
    return () => stopPolling();
  }, []);

  function startPolling(token: string) {
    stopPolling();
    pollRef.current = setInterval(() => doPoll(token), 3000);
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function doPoll(token: string) {
    try {
      const res = await apiGet<ApiResp>(port, `/register/poll?link_token=${encodeURIComponent(token)}`, 0);
      if (!res.ok && res.status === 0) { stopPolling(); setError(t("toast_no_connection", "Нет подключения к серверу.")); return; }
      if (res.status === 404) { stopPolling(); resetToChoice(); setError(t("register_invalid_link", "Ссылка не найдена. Создайте новую.")); return; }
      if (!res.ok) return;
      const status = extractStatus(res.data);
      if (status === "pending") { setError(""); return; }
      if (["verified", "confirmed", "approved", "success"].includes(status)) { stopPolling(); setError(""); setStep("complete"); return; }
      if (status === "expired") { stopPolling(); resetToChoice(); setError(t("register_link_expired", "Ссылка истекла. Запросите новую.")); return; }
      if (status === "denied") { stopPolling(); resetToChoice(); setError(t("register_denied", "Регистрация отклонена.")); return; }
      if (status === "completed") { stopPolling(); resetToChoice(); setError(t("register_already_completed", "Эта регистрация уже завершена.")); }
    } catch {
      stopPolling();
      setError(t("toast_no_connection", "Нет подключения к серверу."));
    }
  }

  function resetToChoice(clearLink = true) {
    stopPolling();
    if (clearLink) {
      setLinkToken(""); setTelegramUrl("");
      apiDelete(port, "/register/link").catch(() => {});
    }
    setUsername(""); setError(""); setStep("choice");
  }

  async function requestTelegramLink() {
    if (linkToken && telegramUrl) { setStep("waiting"); setError(""); startPolling(linkToken); return; }
    setStep("waiting");
    setError(t("register_creating_link", "Создаю ссылку..."));
    setBusy(true);
    try {
      const res = await apiPost<ApiResp>(port, "/register/telegram-link");
      setBusy(false);
      if (!res.ok || res.status === 0) { resetToChoice(); setError(t("toast_no_connection", "Нет подключения к серверу.")); return; }
      if (res.status === 429) { resetToChoice(); setError(t("register_rate_limited", "Слишком много запросов. Попробуйте позже.")); return; }
      if (res.status !== 200) { resetToChoice(); setError(t("error_server", "Ошибка сервера.")); return; }
      const token = String(res.data.link_token ?? "").trim();
      const url = normalizeTelegramUrl(String(res.data.telegram_url ?? "").trim());
      if (!token || !url) { resetToChoice(); setError(t("error_server", "Ошибка сервера.")); return; }
      setLinkToken(token); setTelegramUrl(url);
      await apiPost(port, "/register/link", { link_token: token, telegram_url: url });
      setError(""); startPolling(token);
    } catch { setBusy(false); resetToChoice(); setError(t("toast_no_connection", "Нет подключения к серверу.")); }
  }

  async function completeRegistration() {
    if (!username.trim()) { setError(t("error_enter_login", "Введите никнейм.")); return; }
    setBusy(true); setError("");
    try {
      const res = await apiPost<ApiResp>(port, "/register/complete", { link_token: linkToken, username: username.trim() });
      setBusy(false);
      if (!res.ok && res.status === 0) { setError(t("toast_no_connection", "Нет подключения к серверу.")); return; }
      if (res.status === 200 && res.ok) {
        await apiDelete(port, "/register/link").catch(() => {});
        await apiPost(port, "/auth/save", {
          token: String(res.data.token ?? ""),
          username: String(res.data.username ?? ""),
          status: String(res.data.status ?? "active"),
          sub_level: Number(res.data.sub_level ?? 0),
          player_uuid: String(res.data.player_uuid ?? ""),
        });
        invalidateCache("/auth/load");
        onSuccess();
        return;
      }
      const err = String(res.data.error ?? "").trim().toLowerCase();
      if (res.status === 412) { setError(t("register_username_required", "Ник обязателен.")); return; }
      if (res.status === 409 && err === "username_taken") { setError(t("register_username_taken", "Ник уже занят.")); return; }
      if (res.status === 409 && err === "telegram_not_verified") { setError(t("register_not_verified", "Telegram ещё не подтверждён.")); return; }
      if (res.status === 409) { setError(t("register_already_completed", "Эта регистрация уже завершена.")); return; }
      if (res.status === 410) { resetToChoice(); setError(t("register_link_expired", "Ссылка истекла. Запросите новую.")); return; }
      if (res.status === 400 && err.startsWith("bad_username")) { setError(t("register_username_invalid", "Ник 4-32 символа, только латиница, цифры и _.")); return; }
      setError(t("error_server", "Ошибка сервера."));
    } catch { setBusy(false); setError(t("toast_no_connection", "Нет подключения к серверу.")); }
  }

  function openTelegram() {
    if (telegramUrl) invoke("plugin:opener|open_url", { url: telegramUrl });
  }

  function copyLink() {
    if (telegramUrl) navigator.clipboard.writeText(telegramUrl);
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalTitle}>{t("register_links_title", "Регистрация")}</div>

        {step === "choice" && (
          <>
            <div className={styles.modalText}>{t("register_links_subtitle", "Выберите способ регистрации.")}</div>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={requestTelegramLink} disabled={busy}>{t("register_telegram", "Telegram")}</button>
          </>
        )}

        {step === "waiting" && (
          <>
            <div className={styles.modalText}>{t("register_waiting_text", "Скопируйте ссылку или откройте Telegram, подтвердьте аккаунт через бота.")}</div>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={openTelegram} disabled={busy || !telegramUrl}>{t("register_open_link", "Открыть Telegram")}</button>
            <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={copyLink} disabled={busy || !telegramUrl}>{t("register_copy_link", "Скопировать ссылку")}</button>
            <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={() => resetToChoice()} disabled={busy}>{t("btn_back", "Назад")}</button>
          </>
        )}

        {step === "complete" && (
          <>
            <div className={styles.modalText}>{t("register_verified_text", "Telegram подтверждён. Введите ник для аккаунта.")}</div>
            <input className={styles.input} placeholder={t("register_username_placeholder", "Никнейм")} value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && completeRegistration()}
              disabled={busy} autoFocus />
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={completeRegistration} disabled={busy}>{t("register_complete_button", "Завершить регистрацию")}</button>
          </>
        )}

        {error && <div className={styles.error}>{error}</div>}
        <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={onClose} disabled={busy}>{t("btn_close", "Закрыть")}</button>
      </div>
    </div>
  );
}

interface LoginProps {
  onLogin?: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const port = useBackend();
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  async function handleLogin() {
    if (!username.trim()) { setError(t("error_enter_login", "Введите никнейм.")); return; }
    if (!code.trim()) { setError(t("error_enter_code", "Введите пароль.")); return; }
    setBusy(true); setError("");
    try {
      const res = await apiPost<ApiResp>(port, "/login", { username: username.trim(), code: code.trim() });
      setBusy(false);
      if (!res.ok && res.status === 0) { setError(t("toast_no_connection", "Нет подключения к серверу.")); return; }
      if (res.status === 200 && res.ok) {
        const d = res.data;
        await apiPost(port, "/auth/save", {
          token: String(d.token ?? ""),
          username: String(d.username ?? username.trim()),
          status: String(d.status ?? "active"),
          sub_level: Number(d.sub_level ?? 0),
          player_uuid: String(d.player_uuid ?? ""),
        });
        invalidateCache("/auth/load");
        onLogin?.();
        return;
      }
      const err = String(res.data.error ?? "").trim().toLowerCase();
      if (err === "missing_username") { setError(t("error_enter_login", "Введите никнейм.")); return; }
      if (err === "missing_code") { setError(t("error_enter_code", "Введите пароль.")); return; }
      if (err === "user_not_found") { setError(t("error_bad_login", "Пользователь не найден.")); return; }
      if (err === "invalid_credentials") { setError(t("error_bad_code", "Неверный пароль.")); return; }
      if (err === "inactive") { setError(t("error_inactive_account", "Аккаунт заблокирован.")); return; }
      if (res.status >= 500) { setError(t("error_server", "Ошибка сервера. Попробуйте позже.")); return; }
      setError(t("error_auth", "Ошибка авторизации."));
    } catch {
      setBusy(false);
      setError(t("toast_no_connection", "Нет подключения к серверу."));
    }
  }

  function onRegisterSuccess() {
    setShowRegister(false);
    onLogin?.();
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.title}>{t("login_title", "Вход в аккаунт")}</div>
        <div className={styles.subtitle}>{t("login_subtitle", "Введи ник и пароль, чтобы получить доступ к сборке.")}</div>

        <input className={styles.input} placeholder={t("login_placeholder_username", "Никнейм")} value={username}
          onChange={(e) => setUsername(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
          disabled={busy} autoFocus />
        <input className={styles.input} type="password" placeholder={t("login_placeholder_code", "Пароль")} value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLogin()}
          disabled={busy} />

        <div className={styles.loginBtnWrap}>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleLogin} disabled={busy}>
            {busy ? "..." : t("login_button", "Войти")}
          </button>
        </div>
        <button className={styles.btnRegister} onClick={() => setShowRegister(true)} disabled={busy}>
          {t("register_button", "Зарегистрироваться")}
        </button>

        {error && <div className={styles.error}>{error}</div>}
      </div>

      {showRegister && (
        <RegisterModal port={port} onClose={() => setShowRegister(false)} onSuccess={onRegisterSuccess} />
      )}
    </div>
  );
}
