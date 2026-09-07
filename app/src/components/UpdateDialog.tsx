import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../lib/I18nContext";
import { pollUpdateTask, startUpdateInstall, type UpdateCheckResult } from "../lib/update";
import { trackTask, useProgress } from "../lib/progressStore";
import styles from "./UpdateDialog.module.css";

interface UpdateDialogProps {
  port: number | null;
  info: UpdateCheckResult;
  onClose: () => void;
}

type Phase = "confirm" | "installing" | "error";

const UPDATE_TASK_ID = "update-install";

export default function UpdateDialog({ port, info, onClose }: UpdateDialogProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("confirm");
  const [error, setError] = useState("");
  const progress = useProgress(UPDATE_TASK_ID) ?? 0;

  function handleInstall() {
    const url = info.url;
    if (!url) return;
    setPhase("installing");
    setError("");

    let taskId: string | null = null;
    let startAttempts = 0;
    trackTask(UPDATE_TASK_ID, async () => {
      if (!taskId) {
        startAttempts++;
        try {
          const res = await startUpdateInstall(port, {
            url,
            sha256: info.sha256,
            size: info.size,
            version: info.version,
          });
          if (res.ok && res.task_id) { taskId = res.task_id; return { started: true }; }
        } catch { /* ignore */ }
        if (startAttempts >= 5) return { state: "error", error: "start_failed" };
        return {};
      }
      return await pollUpdateTask(port, taskId);
    }, {
      onDone: async res => {
        const path = (res.result as { relaunch_path?: string } | null)?.relaunch_path;
        if (!path) {
          setPhase("error");
          setError(t("update_install_failed", "Не удалось запустить обновление."));
          return;
        }
        await invoke("apply_update", { path });
      },
      onError: err => {
        setPhase("error");
        setError(err || t("update_install_failed", "Не удалось запустить обновление."));
      },
    });
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
