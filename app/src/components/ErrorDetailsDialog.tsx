import { useEffect, useId, useRef, useState } from "react";
import { getVersion } from "@tauri-apps/api/app";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { useI18n } from "../lib/I18nContext";
import styles from "./ErrorDetailsDialog.module.css";

interface ErrorDetailsDialogProps {
  message: string;
  details: string;
  logPath?: string | null;
  onClose: () => void;
}

type CopyState = "idle" | "copied" | "failed";

const FOCUSABLE = "button:not([disabled]), [tabindex]:not([tabindex='-1'])";
const COPY_RESET_MS = 2500;

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand("copy");
    } catch {
      return false;
    } finally {
      area.remove();
    }
  }
}

function selectContents(node: HTMLElement) {
  const range = document.createRange();
  range.selectNodeContents(node);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export default function ErrorDetailsDialog({ message, details, logPath, onClose }: ErrorDetailsDialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const messageId = useId();
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [version, setVersion] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const detailsRef = useRef<HTMLPreElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => { getVersion().then(setVersion).catch(() => {}); }, []);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    return () => previous?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !dialogRef.current) return;
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const inside = dialogRef.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (copyState === "idle") return;
    const timer = setTimeout(() => setCopyState("idle"), COPY_RESET_MS);
    return () => clearTimeout(timer);
  }, [copyState]);

  async function handleCopy() {
    const report = [version ? `Lota Launcher v${version}` : "", message, details].filter(Boolean).join("\n\n");
    const ok = await copyText(report);
    setCopyState(ok ? "copied" : "failed");
    if (!ok && detailsRef.current) selectContents(detailsRef.current);
  }

  function handleShowLog() {
    if (logPath) revealItemInDir(logPath).catch(() => {});
  }

  const copyLabel = copyState === "copied"
    ? t("play_error_copied", "Скопировано")
    : copyState === "failed"
      ? t("play_error_copy_failed", "Не удалось скопировать — выдели текст вручную")
      : t("play_error_copy", "Скопировать");

  return (
    <div className={styles.overlay} onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
      >
        <div id={titleId} className={styles.title}>{t("play_error_details", "Подробности ошибки")}</div>
        <div id={messageId} className={styles.message}>{message}</div>
        {details && <pre ref={detailsRef} className={styles.details} tabIndex={0}>{details}</pre>}
        <div className={styles.btns}>
          <button className={styles.btnCopy} onClick={handleCopy} aria-live="polite">{copyLabel}</button>
          {logPath && (
            <button className={styles.btnSecondary} onClick={handleShowLog}>
              {t("play_error_show_log", "Показать лог")}
            </button>
          )}
          <button ref={closeRef} className={styles.btnSecondary} onClick={onClose}>{t("btn_close", "Закрыть")}</button>
        </div>
      </div>
    </div>
  );
}
