import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { invoke } from "@tauri-apps/api/core";
import { useBackend, apiGet, apiPost, apiDelete, invalidateCache } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import type { PageContext } from "../components/Layout";
import LoadingDots from "../components/LoadingDots";
import styles from "./Library.module.css";

interface Build {
  id: number | string;
  name?: string;
  version?: string;
  description?: string;
  image?: string;
  is_instance?: boolean;
  _source_build_id?: number;
  _installed: boolean;
  _up_to_date: boolean;
  _build_key: string;
}

interface TaskStatus { progress?: number; state?: string; error?: string | null; }

interface OverlayState {
  mode: "create" | "edit";
  instance?: Build;
}

interface OverlayProps {
  mode: "create" | "edit";
  instance?: Build;
  builds: Build[];
  port: number | null;
  onClose: () => void;
  onSaved: () => void;
}

function InstanceOverlay({ mode, instance, builds, port, onClose, onSaved }: OverlayProps) {
  const { t } = useI18n();
  const [visible, setVisible] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const sourceBuilds = builds.filter(b => !b.is_instance);

  const [name, setName]   = useState(instance?.name ?? "");
  const [desc, setDesc]   = useState(instance?.description ?? "");
  const [image, setImage] = useState(instance?.image ?? "");
  const [buildIdx, setBuildIdx] = useState(0);
  const [busy, setBusy]   = useState(false);
  const [err, setErr]     = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const nameDirty  = useRef(!!instance);
  const descDirty  = useRef(!!instance);
  const imageDirty = useRef(!!instance);

  useEffect(() => {
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, []);

  // подтягиваем данные из выбранной сборки при создании
  useEffect(() => {
    if (mode === "edit") return;
    const src = sourceBuilds[buildIdx];
    if (!src) return;
    if (!nameDirty.current)  setName(src.name ?? "");
    if (!descDirty.current)  setDesc(src.description ?? "");
    if (!imageDirty.current && src.image) setImage(src.image);
  }, [buildIdx]);

  function handleClose() {
    setVisible(false);
    closeTimer.current = setTimeout(onClose, 180);
  }

  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);

  async function handleSubmit() {
    if (!name.trim()) { setErr(t("library_instance_error_name", "Введите название экземпляра.")); return; }
    if (mode === "create" && sourceBuilds.length === 0) { setErr(t("library_instance_error_build", "Нет доступных сборок.")); return; }
    setBusy(true); setErr("");
    try {
      if (mode === "create") {
        const src = sourceBuilds[buildIdx];
        await apiPost(port, "/library/instance/create", {
          name: name.trim(),
          description: desc.trim(),
          image: image.trim(),
          build: src,
          _source_build_id: src?.id,
        });
      } else if (instance) {
        await apiPost(port, "/library/instance/update", {
          id: instance.id,
          name: name.trim(),
          description: desc.trim(),
          image: image.trim(),
        });
      }
      invalidateCache("/library/catalog");
      onSaved();
      handleClose();
    } catch { setErr("Ошибка сохранения."); }
    finally { setBusy(false); }
  }

  async function handleDelete() {
    if (!instance) return;
    setBusy(true);
    try {
      await apiDelete(port, "/library/instance", { id: instance.id });
      invalidateCache("/library/catalog");
      onSaved();
      handleClose();
    } catch { setErr("Ошибка удаления."); }
    finally { setBusy(false); }
  }

  function onImageFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) { setImage((file as any).path ?? file.name); imageDirty.current = true; }
    e.target.value = "";
  }

  const overlayClass = `${styles.instanceOverlay} ${visible ? styles.instanceOverlayVisible : ""}`;

  return (
    <div className={overlayClass} onClick={e => e.target === e.currentTarget && handleClose()}>
      <div className={styles.instancePanel}>
        <div className={styles.instanceTitle}>
          {mode === "create" ? t("library_instance_title", "Новый экземпляр") : t("library_btn_edit_instance", "Изменить") + " экземпляр"}
        </div>
        <div className={styles.instanceSubtitle}>{t("library_instance_subtitle", "Задайте основные параметры сборки.")}</div>

        <div className={styles.instanceFieldLabel}>{t("library_instance_name", "Название")}</div>
        <input
          className={styles.instanceField}
          value={name}
          onChange={e => { setName(e.target.value); nameDirty.current = true; }}
          placeholder={t("library_instance_name", "Название экземпляра")}
        />

        <div className={styles.instanceFieldLabel}>{t("library_instance_desc", "Описание")}</div>
        <textarea
          className={styles.instanceTextarea}
          value={desc}
          onChange={e => { setDesc(e.target.value); descDirty.current = true; }}
          placeholder={t("library_instance_desc", "Описание (необязательно)")}
        />

        <div className={styles.instanceFieldLabel}>{t("library_instance_image", "Картинка")}</div>
        <div className={styles.instanceRow}>
          <input
            className={`${styles.instanceField} ${styles.instanceFieldGrow}`}
            value={image}
            onChange={e => { setImage(e.target.value); imageDirty.current = true; }}
            placeholder={t("library_instance_image", "Путь к изображению")}
          />
          <button className={styles.ghostBtn} onClick={() => fileRef.current?.click()}>{t("library_instance_browse", "Обзор")}</button>
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={onImageFile} />
        </div>

        {mode === "create" && (
          <>
            <div className={styles.instanceFieldLabel}>{t("library_instance_build", "Версия сборки")}</div>
            <select
              className={styles.instanceField}
              value={buildIdx}
              onChange={e => setBuildIdx(Number(e.target.value))}
              disabled={sourceBuilds.length === 0}
            >
              {sourceBuilds.length === 0
                ? <option>{t("library_instance_error_build", "Нет доступных сборок")}</option>
                : sourceBuilds.map((b, i) => (
                    <option key={i} value={i}>{b.name ?? "—"} {b.version ?? ""}</option>
                  ))
              }
            </select>
          </>
        )}

        {err && <div className={styles.instanceError}>{err}</div>}

        <div className={styles.instanceBtns}>
          <button className={styles.ghostBtn} onClick={handleClose} disabled={busy}>{t("library_instance_cancel", "Отмена")}</button>
          {mode === "edit" && (
            <button className={styles.btnSecondary} onClick={handleDelete} disabled={busy}>{t("library_instance_delete", "Удалить")}</button>
          )}
          <button className={styles.btnAccent} onClick={handleSubmit} disabled={busy}>
            {busy ? "..." : mode === "create" ? t("library_instance_create", "Создать") : t("library_instance_save", "Сохранить")}
          </button>
        </div>
      </div>
    </div>
  );
}

function InfoCard({ build, port }: { build: Build; port: number | null }) {
  const imgSrc = build.image && port
    ? `http://127.0.0.1:${port}/library/image?path=${encodeURIComponent(build.image)}`
    : null;

  return (
    <div className={styles.infoCard}>
      <div className={styles.infoTitle}>{build.name || `Сборка #${build.id}`}</div>
      {build.version && <div className={styles.infoMeta}>{build.version}</div>}
      {build.description && <div className={styles.infoBody}>{build.description}</div>}
      {imgSrc && (
        <div className={styles.infoImageWrap}>
          <img src={imgSrc} alt="" className={styles.infoImage} />
        </div>
      )}
    </div>
  );
}

export default function Library() {
  const port = useBackend();
  const { t } = useI18n();
  const { onBack } = useOutletContext<PageContext>();
  const [builds, setBuilds] = useState<Build[]>([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [activeBuild, setActiveBuild] = useState<Build | null>(null); // что показываем в инфопанели, не то что выбрано для запуска
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<Record<string, number>>({});
  const [deleting, setDeleting] = useState<Record<string, boolean>>({});
  const [overlay, setOverlay] = useState<OverlayState | null>(null);
  const pollRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  useEffect(() => {
    loadCatalog();
    return () => { Object.values(pollRefs.current).forEach(clearInterval); };
  }, [port]);

  async function loadCatalog() {
    setLoading(true);
    try {
      const data = await apiGet<{ builds: Build[]; selected_build: string }>(port, "/library/catalog", 0);
      const list = data.builds ?? [];
      setBuilds(list);
      setSelectedKey(data.selected_build ?? "");
      // обновляем activeBuild чтоб не потерять выбор после рефреша
      setActiveBuild(prev => {
        if (!prev) return null;
        return list.find(b => b._build_key === prev._build_key) ?? null;
      });
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  async function handleSelect(build: Build) {
    setActiveBuild(build);
    try {
      await apiPost(port, "/library/select", { build_key: build._build_key });
      setSelectedKey(build._build_key);
    } catch { /* ignore */ }
  }

  async function handleDownload(buildKey: string) {
    try {
      const res = await apiPost<{ ok: boolean; task_id?: string }>(port, "/library/download", { build_key: buildKey });
      if (res.ok && res.task_id) {
        setDownloading(prev => ({ ...prev, [buildKey]: 0 }));
        pollRefs.current[buildKey] = setInterval(() => pollTask(buildKey, res.task_id!), 800);
      }
    } catch { /* ignore */ }
  }

  async function pollTask(buildKey: string, taskId: string) {
    try {
      const t = await apiGet<TaskStatus>(port, `/task/${taskId}`, 0);
      setDownloading(prev => ({ ...prev, [buildKey]: t.progress ?? 0 }));
      if (t.state === "done" || t.state === "error") {
        clearInterval(pollRefs.current[buildKey]);
        delete pollRefs.current[buildKey];
        setDownloading(prev => { const n = { ...prev }; delete n[buildKey]; return n; });
        invalidateCache("/library/catalog");
        await loadCatalog();
      }
    } catch { /* ignore */ }
  }

  async function handleDelete(buildKey: string) {
    setDeleting(prev => ({ ...prev, [buildKey]: true }));
    try {
      await apiDelete(port, "/library/build", { build_key: buildKey });
      invalidateCache("/library/catalog");
      await loadCatalog();
    } catch { /* ignore */ }
    finally { setDeleting(prev => { const n = { ...prev }; delete n[buildKey]; return n; }); }
  }

  async function handleOpenFolder(build: Build) {
    if (!port) return;
    try {
      const res = await apiGet<{ ok: boolean; path?: string }>(
        port, `/library/build/folder?build_key=${encodeURIComponent(build._build_key)}`, 0
      );
      if (res.ok && res.path) {
        await invoke("plugin:opener|open_path", { path: res.path }).catch(() => {});
      }
    } catch { /* ignore */ }
  }

  const dlPct = activeBuild ? downloading[activeBuild._build_key] : undefined;
  const isDl  = dlPct !== undefined;
  const isDel = activeBuild ? !!deleting[activeBuild._build_key] : false;

  return (
    <div className="innerLayout">

      {/* ── Left panel — info ── */}
      <div className="innerPanel">
        <div className={styles.infoContent}>
          <div className={styles.pageTitle}>{t("btn_library", "Библиотека")}</div>
          <div className={styles.sectionLabel}>{t("library_info_section", "Информация")}</div>

          {loading ? (
            <div className={styles.loading}><LoadingDots label="Загрузка" /></div>
          ) : !activeBuild ? (
            <div className={styles.infoEmpty}>
              <div className={styles.infoEmptyTitle}>{t("library_info_empty_title", "Выберите элемент")}</div>
              <div className={styles.infoEmptyBody}>
                {t("library_info_empty_body", "Нажмите на экземпляр, чтобы его изменить или выбрать.\nЧтобы добавить сборку, нажмите «Добавить экземпляр».")}
              </div>
            </div>
          ) : (
            <>
              <InfoCard build={activeBuild} port={port} />

              <div className={styles.infoBadges}>
                {activeBuild._installed
                  ? <span className={`${styles.badge} ${activeBuild._up_to_date ? styles.badgeOk : styles.badgeWarn}`}>
                      {activeBuild._up_to_date ? "Актуальная" : "Устарела"}
                    </span>
                  : <span className={styles.badge}>Не установлена</span>
                }
                {selectedKey === activeBuild._build_key && (
                  <span className={`${styles.badge} ${styles.badgeSelected}`}>{t("library_btn_selected", "Выбрана")}</span>
                )}
              </div>

              {isDl && (
                <div className={styles.dlProgress}>
                  <div className={styles.dlBar}>
                    <div className={styles.dlFill} style={{ width: `${dlPct}%` }} />
                  </div>
                  <span className={styles.dlText}>{dlPct}%</span>
                </div>
              )}

              <div className={styles.infoActions}>
                {(!activeBuild._installed || !activeBuild._up_to_date) && (
                  <button
                    className={styles.btnAccent}
                    onClick={() => handleDownload(activeBuild._build_key)}
                    disabled={isDl}
                  >
                    {isDl ? t("library_btn_downloading", "Скачивается...") : activeBuild._installed ? "Обновить" : t("library_btn_download", "Скачать")}
                  </button>
                )}

                {activeBuild.is_instance && activeBuild._installed && (
                  <button
                    className={styles.btnPrimary}
                    onClick={() => setOverlay({ mode: "edit", instance: activeBuild })}
                  >
                    {t("library_btn_edit_instance", "Изменить")}
                  </button>
                )}

                {activeBuild._installed && (
                  <button className={styles.btnGhost} onClick={() => handleOpenFolder(activeBuild)}>
                    {t("library_btn_open_folder", "Открыть папку")}
                  </button>
                )}

                {activeBuild._installed && (
                  <button
                    className={styles.btnGhost}
                    onClick={() => handleDelete(activeBuild._build_key)}
                    disabled={isDel}
                  >
                    {isDel ? "..." : t("library_instance_delete", "Удалить")}
                  </button>
                )}
              </div>
            </>
          )}

          <div style={{ flex: 1 }} />
        </div>
      </div>

      {/* ── Right sidebar — builds list ── */}
      <div className="innerSidebar">
        <div className={styles.sidebarSection}>{t("library_tab_builds", "Сборки")}</div>

        <div className={styles.buildList}>
          {!loading && builds.length === 0 && (
            <div className={styles.empty}>Список пуст.</div>
          )}
          {builds.map(build => {
            const key = build._build_key;
            const isActive = activeBuild?._build_key === key;
            const isSelected = selectedKey === key;
            const dlPctItem = downloading[key];
            return (
              <button
                key={key}
                className={`${styles.buildItem} ${isActive ? styles.buildItemActive : ""} ${isSelected ? styles.buildItemSelected : ""}`}
                onClick={() => handleSelect(build)}
              >
                <div className={styles.buildItemName}>{build.name || `Сборка #${build.id}`}</div>
                {build.version && <div className={styles.buildItemMeta}>{build.version}</div>}
                {dlPctItem !== undefined && (
                  <div className={styles.buildItemBar}>
                    <div className={styles.buildItemFill} style={{ width: `${dlPctItem}%` }} />
                  </div>
                )}
                {deleting[key] && <div className={styles.buildItemMeta}>Удаление...</div>}
              </button>
            );
          })}
        </div>

        <button
          className={styles.btnAddInstance}
          onClick={() => setOverlay({ mode: "create" })}
        >
          {t("library_btn_add_instance", "Добавить экземпляр")}
        </button>
        <button className={styles.btnBack} onClick={onBack}>{t("btn_back", "Назад")}</button>
      </div>

      {/* ── Instance overlay ── */}
      {overlay && (
        <InstanceOverlay
          mode={overlay.mode}
          instance={overlay.instance}
          builds={builds}
          port={port}
          onClose={() => setOverlay(null)}
          onSaved={loadCatalog}
        />
      )}
    </div>
  );
}
