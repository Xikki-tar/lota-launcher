import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/I18nContext";
import { pollUpdateTask, startUpdateInstall, type UpdateCheckResult } from "../lib/update";
import styles from "./UpdateDialog.module.css";

interface UpdateDialogProps {
  port: number | null;
  info: UpdateCheckResult;
  onClose: () => void;
}

type Phase = "confirm" | "installing" | "error";

export default function UpdateDialog({ port, info, onClose }: UpdateDialogProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("confirm");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  async function handleInstall() {
    if (!info.url) return;
    setPhase("installing");
    setError("");
    try {
      const res = await startUpdateInstall(port, {
        url: info.url,
        sha256: info.sha256,
        size: info.size,
        version: info.version,
      });
      if (!res.ok || !res.task_id) {
        setPhase("error");
        setError(t("update_install_failed", "Не удалось запустить обновление."));
        return;
      }
      pollRef.current = setInterval(() => pollTask(res.task_id!), 800);
    } catch {
      setPhase("error");
      setError(t("error_conn_refused", "Ошибка соединения."));
    }
  }

  async function pollTask(taskId: string) {
    try {
      const status = await pollUpdateTask(port, taskId);
      setProgress(status.progress ?? 0);
      if (status.state === "done") {
        if (pollRef.current) clearInterval(pollRef.current);
        const path = status.result?.relaunch_path;
        if (!path) {
          setPhase("error");
          setError(t("update_install_failed", "Не удалось запустить обновление."));
          return;
        }
        await invoke("apply_update", { path });
      } else if (status.state === "error") {
        if (pollRef.current) clearInterval(pollRef.current);
        setPhase("error");
        setError(status.error || t("update_install_failed", "Не удалось запустить обновление."));
      }
    } catch {
      /* transient poll failure — try again next tick */
    }
  }

  return (
    <div className={styles.dialogOverlay} onClick={e => phase === "confirm" && e.target === e.currentTarget && onClose()}>
      <div className={styles.dialog}>
        <div className={styles.dialogTitle}>{t("update_dialog_title", "Обновление лаунчера")}</div>

        {phase === "confirm" && (
          <>
            <div className={styles.dialogText}>
              {t("update_dialog_text", "Доступно обновление лаунчера: {version}.\n\nОбновить сейчас?").replace("{version}", info.version || "")}
            </div>
            <div className={styles.dialogBtns}>
              <button className={styles.btnDialogPrimary} onClick={handleInstall}>
                {t("update_btn_install", "Обновить")}
              </button>
              <button className={styles.btnDialogClose} onClick={onClose}>
                {t("update_btn_later", "Позже")}
              </button>
            </div>
          </>
        )}

        {phase === "installing" && (
          <>
            <div className={styles.dialogText}>{t("update_installing", "Скачиваю и устанавливаю обновление...")}</div>
            <div className={styles.dlProgress}>
              <div className={styles.dlBar}>
                <div className={styles.dlFill} style={{ width: `${progress}%` }} />
              </div>
              <span className={styles.dlText}>{progress}%</span>
            </div>
          </>
        )}

        {phase === "error" && (
          <>
            <div className={styles.dialogText}>{error}</div>
            <div className={styles.dialogBtns}>
              <button className={styles.btnDialogClose} onClick={onClose}>{t("btn_close", "Закрыть")}</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
