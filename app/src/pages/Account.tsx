import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useBackend, apiGet, apiPost } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import type { PageContext } from "../components/Layout";
import LoadingDots from "../components/LoadingDots";
import styles from "./Account.module.css";

interface AccountData {
  username?: string;
  status?: string;
  sub_level?: number;
  player_uuid?: string;
}

const RANK_NAMES: Record<number, string> = {
  1: "Барон",
  2: "Аристократ",
  3: "Инвестор",
  4: "Тестер",
  5: "Старейшина",
  6: "Junior",
  7: "Team",
  8: "Дракон",
  9: "Автор",
};

const RANK_GRADIENTS: Record<number, [string, string]> = {
  1: ["#269ff5", "#005eff"],
  2: ["#fff600", "#9e9300"],
  3: ["#e26bff", "#06ff76"],
  4: ["#c8ff6b", "#9fc1ff"],
  5: ["#d363ff", "#7600b0"],
  6: ["#0e2f29", "#79d8bb"],
  7: ["#00719a", "#5ce8f4"],
  8: ["#6112f4", "#4c168e"],
};

function ModelPicker({ onChoose, onClose }: { onChoose: (m: "classic" | "slim") => void; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className={styles.dialogOverlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.dialog}>
        <div className={styles.dialogTitle}>{t("account_skin_model_title", "Модель скина")}</div>
        <button className={styles.btnDialogFull} onClick={() => onChoose("classic")}>{t("account_skin_model_classic", "Classic")}</button>
        <button className={styles.btnDialogFull} onClick={() => onChoose("slim")}>{t("account_skin_model_slim", "Slim")}</button>
        <button className={styles.btnDialogClose} onClick={onClose}>{t("btn_close", "Закрыть")}</button>
      </div>
    </div>
  );
}

function DiscordDialog({ command, discordUrl, onClose }: { command: string; discordUrl: string; onClose: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  function copyCommand() {
    navigator.clipboard.writeText(command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  }

  return (
    <div className={styles.dialogOverlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.dialog}>
        <div className={styles.dialogTitle}>{t("account_discord_link_title", "Привязка Discord")}</div>
        <div className={styles.dialogText}>
          {t("account_discord_link_text", "Перейди по ссылке и вставь команду в личке с ботом, чтобы слинковать аккаунты.")}
        </div>
        <div className={styles.dialogCommand}>{command}</div>
        <div className={styles.dialogBtns}>
          {discordUrl && (
            <button className={styles.btnDialogFull} onClick={() => window.open(discordUrl, "_blank")}>
              {t("account_discord_open", "Открыть Discord")}
            </button>
          )}
          <button className={styles.btnDialogPrimary} onClick={copyCommand}>
            {copied ? t("account_discord_command_copied", "Скопировано!") : t("account_discord_copy", "Скопировать команду")}
          </button>
          <button className={styles.btnDialogClose} onClick={onClose}>{t("btn_close", "Закрыть")}</button>
        </div>
      </div>
    </div>
  );
}

export default function Account() {
  const port = useBackend();
  const { t } = useI18n();
  const { onBack } = useOutletContext<PageContext>();
  const [data, setData] = useState<AccountData | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);
  const [skinVersion, setSkinVersion] = useState(0);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [discordState, setDiscordState] = useState<{ command: string; url: string } | null>(null);
  const [discordBusy, setDiscordBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const modelRef = useRef<"classic" | "slim">("classic");

  useEffect(() => { load(); }, [port]);

  async function load() {
    setLoading(true);
    try {
      const d = await apiGet<AccountData>(port, "/account", 5 * 60_000);
      setData(d);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  function openSkinPicker() {
    setMessage(null);
    setShowModelPicker(true);
  }

  function onModelChosen(model: "classic" | "slim") {
    modelRef.current = model;
    setShowModelPicker(false);
    fileInputRef.current?.click();
  }

  async function onFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !port) return;
    e.target.value = "";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("model", modelRef.current);

    try {
      const r = await fetch(`http://127.0.0.1:${port}/account/skin/upload`, { method: "POST", body: formData });
      const res = await r.json();
      if (res.ok) {
        setMessage({ text: t("account_skin_uploaded", "Скин загружен."), ok: true });
        setSkinVersion(v => v + 1);
      } else {
        const errMap: Record<string, string> = {
          skin_too_large:      t("account_skin_too_large",      "Скин слишком большой. Максимум: 16 KiB."),
          skin_bad_dimensions: t("account_skin_bad_dimensions", "Размер скина должен быть 64×32 или 64×64."),
          skin_bad_format:     t("account_skin_bad_format",     "Файл должен быть PNG-скином."),
        };
        setMessage({ text: errMap[res.error] ?? res.error ?? t("account_skin_save_failed", "Не удалось загрузить скин."), ok: false });
      }
    } catch {
      setMessage({ text: t("error_conn_refused", "Ошибка соединения."), ok: false });
    }
  }

  async function handleDiscordLink() {
    if (discordBusy || !port) return;
    setMessage(null);
    setDiscordBusy(true);
    try {
      const res = await apiPost<{ ok: boolean; data?: { command?: string; url?: string; error?: string } }>(
        port, "/account/discord/link"
      );
      if (res?.ok && res.data?.command) {
        setDiscordState({ command: res.data.command, url: res.data.url ?? "" });
      } else if (res?.data?.error === "already_linked") {
        setMessage({ text: t("account_discord_already_linked", "Discord уже привязан к этому аккаунту."), ok: true });
      } else {
        setMessage({ text: t("account_skin_upload_failed", "Не удалось получить ссылку."), ok: false });
      }
    } catch {
      setMessage({ text: t("error_conn_refused", "Ошибка соединения."), ok: false });
    } finally {
      setDiscordBusy(false);
    }
  }

  const username = data?.username || "—";
  const level = data?.sub_level ?? 0;
  const isActive = (data?.status || "") === "active";
  const rankName = RANK_NAMES[level] ?? t("account_no_subscription", "Нет подписки");
  const grad = RANK_GRADIENTS[level];

  const gradVars = grad ? ({ "--c1": grad[0], "--c2": grad[1] } as React.CSSProperties) : {};
  const skinSrc = port ? `http://127.0.0.1:${port}/skin/model?w=220&h=360&_v=${skinVersion}` : null;

  return (
    <div className="innerLayout">

      {/* ── Left panel — profile info ── */}
      <div className="innerPanel">
        <div className={styles.content}>
          <div className={styles.pageTitle}>{t("btn_account", "Аккаунт")}</div>

          {loading ? (
            <div className={styles.loading}><LoadingDots label="Загрузка" /></div>
          ) : (
            <>
              <div className={styles.sectionLabel}>{t("account_profile", "Профиль")}</div>

              <div className={styles.captionLabel}>{t("account_nick", "Ник")}</div>
              <div className={styles.nickCard}>
                <span className={`${styles.nickText} ${grad ? styles.nickGrad : ""}`} style={gradVars}>
                  {username}
                </span>
              </div>

              <div className={styles.captionLabel}>{t("account_level", "Уровень")}</div>
              <div className={`${styles.rankCard} ${grad ? styles.rankGrad : ""}`} style={gradVars}>
                <span className={styles.rankText}>{rankName}</span>
              </div>

              <div className={styles.captionLabel}>{t("account_updates", "Доступ к обновлениям")}</div>
              <div className={`${styles.statusBadge} ${isActive ? styles.statusActive : styles.statusInactive}`}>
                {isActive ? "ACTIVE" : "EXPIRED"}
              </div>
            </>
          )}

          <div style={{ flex: 1 }} />
        </div>
      </div>

      {/* ── Center panel — skin viewer ── */}
      <div className="innerPanel">
        <div className={styles.skinContent}>
          <div className={styles.sectionLabel}>{t("account_skin", "Скин персонажа")}</div>
          <div className={styles.skinViewer}>
            {skinSrc
              ? <img key={skinSrc} src={skinSrc} alt="" className={styles.skinImg} />
              : <div className={styles.skinPlaceholder}>{t("skin_no_skin", "Нет скина")}</div>
            }
          </div>
        </div>
      </div>

      {/* ── Right sidebar — actions ── */}
      <div className="innerSidebar">
        <div className={styles.sidebarSection}>{t("account_section", "Аккаунт")}</div>

        <button className={styles.btnAction} onClick={openSkinPicker}>
          {t("btn_change_skin", "Изменить скин")}
        </button>
        <button
          className={`${styles.btnAction} ${styles.btnActionTall}`}
          onClick={handleDiscordLink}
          disabled={discordBusy}
        >
          {discordBusy ? "..." : t("btn_link_discord", "Привязать Discord")}
        </button>

        {message && (
          <div className={`${styles.msgBox} ${message.ok ? styles.msgOk : styles.msgError}`}>
            {message.text}
          </div>
        )}

        <div style={{ flex: 1 }} />

        <button className={styles.btnBack} onClick={onBack}>{t("btn_back", "Назад")}</button>
      </div>

      {/* ── Dialogs ── */}
      {showModelPicker && (
        <ModelPicker onChoose={onModelChosen} onClose={() => setShowModelPicker(false)} />
      )}
      {discordState && (
        <DiscordDialog command={discordState.command} discordUrl={discordState.url} onClose={() => setDiscordState(null)} />
      )}

      {/* Hidden file input */}
      <input ref={fileInputRef} type="file" accept=".png,image/png" style={{ display: "none" }} onChange={onFileChosen} />
    </div>
  );
}
