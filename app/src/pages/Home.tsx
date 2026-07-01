import { useEffect, useRef, useState } from "react";
import { useBackend, apiGet } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import styles from "./Home.module.css";

function newsImageUrl(port: number | null, path: string | undefined): string | null {
  if (!path || !port) return null;
  return `http://127.0.0.1:${port}/news/image?path=${encodeURIComponent(path)}`;
}

type Localized = { en?: string; ru?: string; uk?: string; [k: string]: string | undefined };

interface NewsItem {
  id?: string;
  type?: string | Localized;
  title?: string | Localized;
  date?: string | Localized;
  body?: string | Localized;
  details?: string | Localized;
  changes?: (string | Localized)[];
  image?: string;
}

type LangCode = "ru" | "uk" | "en";

function langCode(language: string): LangCode {
  if (language === "Українська") return "uk";
  if (language === "English") return "en";
  return "ru";
}

function loc(v: string | Localized | undefined, lang: LangCode = "ru"): string {
  if (!v) return "";
  if (typeof v === "string") return v;
  return v[lang] ?? v.ru ?? v.en ?? v.uk ?? Object.values(v).find(Boolean) ?? "";
}

function typeKey(type?: string | Localized): string {
  return loc(type).toLowerCase() || "news";
}

function NewsCard({ item, port, onOpen }: { item: NewsItem; port: number | null; onOpen: (item: NewsItem) => void }) {
  const { t, language } = useI18n();
  const lang = langCode(language);
  const key = typeKey(item.type);
  const badgeClass = styles[`badge_${key}` as keyof typeof styles] as string | undefined;
  const imgSrc = newsImageUrl(port, item.image);

  const TYPE_MAP: Record<string, string> = {
    update: t("news_type_update", "Обновление"),
    news:   t("news_type_news",   "Новость"),
    patch:  t("news_type_patch",  "Патч"),
    fix:    t("news_type_patch",  "Патч"),
    hotfix: t("news_type_patch",  "Патч"),
    event:  t("news_type_event",  "Событие"),
  };

  const typeLabel = TYPE_MAP[key] ?? loc(item.type, lang) ?? t("news_type_news", "Новость");

  return (
    <div className={styles.card}>
      <span className={`${styles.badge} ${badgeClass ?? ""}`}>
        {typeLabel}
      </span>

      <div className={styles.cardTitle}>{loc(item.title, lang) || "—"}</div>

      {loc(item.date, lang) && <div className={styles.cardDate}>{loc(item.date, lang)}</div>}

      {loc(item.body, lang) && <div className={styles.cardBody}>{loc(item.body, lang)}</div>}

      {imgSrc && (
        <div className={styles.cardImage}>
          <img src={imgSrc} alt="" className={styles.cardImageInner} />
        </div>
      )}

      <div className={styles.cardFooter}>
        <button className={styles.ghostBtn} onClick={() => onOpen(item)}>
          {t("news_more", "Подробнее")}
        </button>
      </div>
    </div>
  );
}

interface OverlayProps {
  item: NewsItem;
  port: number | null;
  onClose: () => void;
}

function NewsOverlay({ item, port, onClose }: OverlayProps) {
  const { t, language } = useI18n();
  const lang = langCode(language);
  const [visible, setVisible] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  function handleClose() {
    setVisible(false);
    timerRef.current = setTimeout(onClose, 180);
  }

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const body = loc(item.details, lang) || loc(item.body, lang);
  const changesText = (item.changes ?? []).map(c => loc(c, lang)).filter(Boolean).join("\n");
  const overlayImgSrc = newsImageUrl(port, item.image);

  return (
    <div
      className={`${styles.overlay} ${visible ? styles.overlayVisible : ""}`}
      onClick={(e) => e.target === e.currentTarget && handleClose()}
    >
      <div className={styles.overlayPanel} onClick={(e) => e.stopPropagation()}>
        <div className={styles.overlayTitle}>{loc(item.title, lang) || "—"}</div>
        {loc(item.date, lang) && <div className={styles.overlayDate}>{loc(item.date, lang)}</div>}
        {overlayImgSrc && (
          <div className={styles.overlayImage}>
            <img src={overlayImgSrc} alt="" className={styles.overlayImageInner} />
          </div>
        )}
        {body && <div className={styles.overlayBody}>{body}</div>}
        {changesText && (
          <>
            <div className={styles.overlaySection}>{t("news_changes", "Список изменений")}</div>
            <div className={styles.overlayChanges}>{changesText}</div>
          </>
        )}
        <div className={styles.overlayFooter}>
          <button className={styles.ghostBtn} onClick={handleClose}>{t("btn_close", "Закрыть")}</button>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const port = useBackend();
  const { t } = useI18n();
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<NewsItem | null>(null);

  useEffect(() => { loadNews(); }, [port]);

  async function loadNews() {
    setLoading(true);
    try {
      const data = await apiGet<{ items?: NewsItem[] }>(port, "/news", 5 * 60_000);
      setNews(data?.items ?? []);
    } catch {
      setNews([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.pageTitle}>{t("home_title", "Главное меню")}</div>
      <div className={styles.newsLabel}>{t("news_title", "Новости")}</div>
      <div className={styles.newsList}>
        {loading ? (
          <div className={styles.empty}>Загрузка...</div>
        ) : news.length === 0 ? (
          <div className={styles.empty}>{t("news_empty", "Новостей пока нет.")}</div>
        ) : (
          news.map((item, i) => (
            <NewsCard key={item.id ?? i} item={item} port={port} onOpen={setSelected} />
          ))
        )}
      </div>
      {selected && (
        <NewsOverlay item={selected} port={port} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
