import styles from "./LoadingDots.module.css";

export default function LoadingDots({ label }: { label?: string }) {
  return (
    <span className={styles.wrap}>
      {label && <span>{label}</span>}
      <span className={styles.dots}>
        <span className={styles.dot} />
        <span className={styles.dot} />
        <span className={styles.dot} />
      </span>
    </span>
  );
}
