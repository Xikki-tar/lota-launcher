import { useI18n } from "../lib/I18nContext";
import { useProgressInfo } from "../lib/progressStore";
import styles from "./DownloadProgress.module.css";

export default function DownloadProgress({ id }: { id: string | null }) {
  const { t } = useI18n();
  const info = useProgressInfo(id);
  if (!info) return null;

  const percent = Math.round(info.percent);
  const speed = info.speed ?? 0;
  const speedText = speed <= 0
    ? ""
    : speed >= 1024 * 1024
      ? `${(speed / (1024 * 1024)).toFixed(1)} ${t("speed_mb", "МБ/с")}`
      : `${Math.max(1, Math.round(speed / 1024))} ${t("speed_kb", "КБ/с")}`;

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <div className={styles.fill} style={{ width: `${percent}%` }} />
      </div>
      <div className={styles.meta}>
        <span className={styles.file} title={info.file ?? ""}>{info.file ?? ""}</span>
        <span className={styles.stats}>
          {speedText && <span>{speedText}</span>}
          <span>{percent}%</span>
        </span>
      </div>
    </div>
  );
}
