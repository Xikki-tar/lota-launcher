import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { win } from "../lib/tauri";
import styles from "./TitleBar.module.css";

const appWin = getCurrentWindow();

interface Props {
  title?: string;
  version?: string;
}

export default function TitleBar({ title = "Lota Launcher", version }: Props) {
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    appWin.isMaximized().then(setMaximized).catch(() => {});
    const unlisten = appWin.onResized(() => {
      appWin.isMaximized().then(setMaximized).catch(() => {});
    });
    return () => { unlisten.then(fn => fn()).catch(() => {}); };
  }, []);

  return (
    <div className={styles.bar} data-tauri-drag-region>

      <div className={styles.left} data-tauri-drag-region>
        <div className={styles.logoWrap}>
          <img src="/logo.png" className={styles.logo} alt="" draggable={false} />
        </div>

        <span className={styles.title} data-tauri-drag-region>{title}</span>
        {version && <span className={styles.version} data-tauri-drag-region>{version}</span>}
      </div>

      <div className={styles.controls}>
        <button className={styles.btn} onClick={() => win.minimize()}>-</button>
        <button className={styles.btn} onClick={() => win.toggleMaximize()}>
          {maximized ? "o" : "[]"}
        </button>
        <button className={`${styles.btn} ${styles.close}`} onClick={() => win.close()}>X</button>
      </div>

    </div>
  );
}
