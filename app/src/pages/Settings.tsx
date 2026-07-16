import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { useBackend, apiGet, apiPost, invalidateCache } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import type { PageContext } from "../components/Layout";
import UpdateDialog from "../components/UpdateDialog";
import LoadingDots from "../components/LoadingDots";
import { checkForUpdate, isInAppUpdateMode, type UpdateCheckResult, type UpdateMode } from "../lib/update";
import styles from "./Settings.module.css";

const LANGUAGES = ["Українська", "Русский", "English"];

interface SettingsData {
  language?: string;
  java_path?: string;
  mem_min_mb?: number;
  mem_max_mb?: number;
  jvm_args?: string;
  auto_java_version?: boolean;
  disable_openal?: boolean;
  debug_mode?: boolean;
}

interface JavaCandidate {
  path: string;
  major: number | null;
}

export default function Settings() {
  const port = useBackend();
  const { t, refresh: refreshI18n } = useI18n();
  const { onBack } = useOutletContext<PageContext>();
  const [form, setForm] = useState<SettingsData>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [javaList, setJavaList] = useState<JavaCandidate[]>([]);
  const [scanning, setScanning] = useState(false);
  const [themesNote, setThemesNote] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [appVersion, setAppVersion] = useState("");
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [updateMode, setUpdateMode] = useState<UpdateMode>(null);
  const [updateNote, setUpdateNote] = useState("");
  const [updateInfo, setUpdateInfo] = useState<UpdateCheckResult | null>(null);

  useEffect(() => { load(); }, [port]);
  useEffect(() => { getVersion().then(setAppVersion).catch(() => {}); }, []);

  // тихая проверка режима апдейта (и заодно наличия обновления для appimage) при заходе в настройки
  useEffect(() => {
    if (!appVersion) return;
    checkForUpdate(port, appVersion).then(info => {
      setUpdateMode(info.mode);
      if (isInAppUpdateMode(info.mode) && info.update_available && info.url) setUpdateInfo(info);
    }).catch(() => {});
  }, [port, appVersion]);

  async function handleCheckUpdate() {
    setCheckingUpdate(true);
    setUpdateNote("");
    try {
      const info = await checkForUpdate(port, appVersion);
      setUpdateMode(info.mode);
      if (!isInAppUpdateMode(info.mode)) return;
      if (info.update_available && info.url) {
        setUpdateInfo(info);
      } else {
        setUpdateNote(t("update_none_found", "Обновлений не найдено."));
      }
    } catch {
      setUpdateNote(t("error_conn_refused", "Ошибка соединения."));
    } finally {
      setCheckingUpdate(false);
    }
  }

  async function handleRestartToUpdater() {
    setCheckingUpdate(true);
    setUpdateNote("");
    try {
      const play = await apiGet<{ state?: string }>(port, "/play/state", 0);
      if (play.state === "running" || play.state === "launched") {
        setUpdateNote(t("update_game_running", "Нельзя обновиться, пока игра запущена."));
        return;
      }
      if (!window.confirm(t("update_restart_confirm", "Перезапустить лаунчер для проверки обновлений?"))) {
        return;
      }
      await invoke("restart_to_updater");
    } catch {
      setUpdateNote(t("error_conn_refused", "Ошибка соединения."));
    } finally {
      setCheckingUpdate(false);
    }
  }

  async function load() {
    setLoading(true);
    try {
      const data = await apiGet<SettingsData>(port, "/settings", 60_000);
      setForm(data);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  async function save() {
    setSaving(true);
    try {
      await apiPost(port, "/settings", form);
      invalidateCache("/settings");
      await refreshI18n();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function scanJava() {
    setScanning(true);
    try {
      const res = await apiGet<{ candidates: JavaCandidate[] }>(port, "/java/scan", 0);
      const cands = res?.candidates ?? [];
      setJavaList(cands);
      const java21 = cands.find(c => c.major === 21);
      const best = java21 ?? cands[0];
      if (best) set("java_path", best.path);
    } catch { /* ignore */ }
    finally { setScanning(false); }
  }

  function handleBrowse(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const path = (file as any).path ?? file.name;
    set("java_path", path);
    e.target.value = "";
  }

  function set<K extends keyof SettingsData>(key: K, value: SettingsData[K]) {
    setForm(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  const selectedJava = javaList.find(c => c.path === form.java_path);
  const javaVersionLabel = selectedJava
    ? `${t("settings_java_version", "Версия:")} Java ${selectedJava.major ?? "?"}`
    : t("settings_java_version", "Версия: —");

  return (
    <div className="innerLayout">
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={handleBrowse}
      />

      <div className="innerPanel innerPanelScroll">
        <div className={styles.content}>
          <div className={styles.pageTitle}>{t("settings_title", "Настройки")}</div>

          {loading ? (
            <div className={styles.loading}><LoadingDots label="Загрузка" /></div>
          ) : (
            <div className={styles.groups}>
              <fieldset className={styles.group}>
                <legend className={styles.groupTitle}>{t("settings_group_language", "Язык")}</legend>
                <select
                  className={styles.select}
                  value={form.language ?? "Русский"}
                  onChange={e => set("language", e.target.value)}
                >
                  {LANGUAGES.map(l => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </fieldset>

              <fieldset className={styles.group}>
                <legend className={styles.groupTitle}>{t("settings_group_java", "Java")}</legend>

                <div className={styles.memRow}>
                  <div className={styles.memField}>
                    <label className={styles.caption}>{t("settings_min_mem", "Минимальный объём (MB):")}</label>
                    <input
                      type="number"
                      className={styles.spinbox}
                      min={256}
                      max={form.mem_max_mb ?? 65536}
                      step={256}
                      value={form.mem_min_mb ?? 1024}
                      onChange={e => set("mem_min_mb", Number(e.target.value))}
                    />
                  </div>
                  <div className={styles.memField}>
                    <label className={styles.caption}>{t("settings_max_mem", "Максимальный объём (MB):")}</label>
                    <input
                      type="number"
                      className={styles.spinbox}
                      min={form.mem_min_mb ?? 512}
                      max={65536}
                      step={256}
                      value={form.mem_max_mb ?? 4096}
                      onChange={e => set("mem_max_mb", Number(e.target.value))}
                    />
                  </div>
                </div>

                <input
                  type="text"
                  className={styles.field}
                  placeholder={t("settings_java_path_placeholder", "Путь к Java (java / javaw / бинарник)")}
                  value={form.java_path ?? ""}
                  disabled={form.auto_java_version === true}
                  onChange={e => set("java_path", e.target.value)}
                />

                <div className={styles.pathBtns}>
                  <button
                    className={styles.btnSmall}
                    disabled={form.auto_java_version === true}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {t("btn_browse", "Обзор")}
                  </button>
                  <button
                    className={styles.btnSmall}
                    disabled={scanning || form.auto_java_version === true}
                    onClick={scanJava}
                  >
                    {scanning ? "Поиск..." : t("btn_auto_detect", "Автоопределение")}
                  </button>
                </div>

                <label className={styles.checkRow}>
                  <input
                    type="checkbox"
                    checked={form.auto_java_version ?? false}
                    onChange={e => set("auto_java_version", e.target.checked)}
                  />
                  <span>{t("settings_auto_java", "Автоопределение версии Java")}</span>
                </label>

                <div className={styles.javaList}>
                  {javaList.length === 0 ? (
                    <div className={styles.javaListEmpty}>
                      {scanning ? "Поиск Java..." : "Нет обнаруженных установок Java"}
                    </div>
                  ) : (
                    javaList.map((c, i) => (
                      <button
                        key={i}
                        className={`${styles.javaListItem} ${form.java_path === c.path ? styles.javaListItemActive : ""}`}
                        onClick={() => set("java_path", c.path)}
                      >
                        <span className={styles.javaItemPath}>{c.path}</span>
                        <span className={styles.javaItemVersion}>Java {c.major ?? "?"}</span>
                      </button>
                    ))
                  )}
                </div>

                <div className={styles.caption}>{javaVersionLabel}</div>
                <div className={styles.caption}>{t("settings_java_recommended", "Рекомендуемая версия: Java 21")}</div>

                <label className={styles.caption}>
                  {t("settings_jvm_args", "Аргументы JVM:")}
                </label>
                <input
                  type="text"
                  className={styles.field}
                  placeholder="-XX:+UseG1GC -Dfile.encoding=UTF-8 ..."
                  value={form.jvm_args ?? ""}
                  onChange={e => set("jvm_args", e.target.value)}
                />

                <label className={styles.checkRow}>
                  <input
                    type="checkbox"
                    checked={form.disable_openal ?? false}
                    onChange={e => set("disable_openal", e.target.checked)}
                  />
                  <span>{t("settings_disable_openal", "Использовать системный OpenAL")}</span>
                </label>
              </fieldset>

              <fieldset className={styles.group}>
                <legend className={styles.groupTitle}>Отладка</legend>
                <label className={styles.checkRow}>
                  <input
                    type="checkbox"
                    checked={form.debug_mode ?? false}
                    onChange={e => set("debug_mode", e.target.checked)}
                  />
                  <span>Режим отладки (консоль логов)</span>
                </label>
              </fieldset>

              {isInAppUpdateMode(updateMode) && (
                <fieldset className={styles.group}>
                  <legend className={styles.groupTitle}>{t("settings_group_updates", "Обновления")}</legend>
                  <div className={styles.caption}>
                    {t("update_current_version", "Текущая версия:")} {appVersion || "—"}
                  </div>
                  {updateNote && <div className={styles.caption}>{updateNote}</div>}
                  <div className={styles.pathBtns}>
                    <button className={styles.btnSmall} onClick={handleCheckUpdate} disabled={checkingUpdate}>
                      {checkingUpdate ? t("update_checking", "Проверяю...") : t("update_btn_check", "Проверить обновления")}
                    </button>
                  </div>
                </fieldset>
              )}

              {updateMode === "external" && (
                <fieldset className={styles.group}>
                  <legend className={styles.groupTitle}>{t("settings_group_updates", "Обновления")}</legend>
                  <div className={styles.caption}>
                    {t("update_current_version", "Текущая версия:")} {appVersion || "—"}
                  </div>
                  {updateNote && <div className={styles.caption}>{updateNote}</div>}
                  <div className={styles.pathBtns}>
                    <button className={styles.btnSmall} onClick={handleRestartToUpdater} disabled={checkingUpdate}>
                      {checkingUpdate ? t("update_checking", "Проверяю...") : t("update_btn_check", "Проверить обновления")}
                    </button>
                  </div>
                </fieldset>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="innerSidebar">
        <button className={styles.btnThemes} onClick={() => setThemesNote(n => !n)}>
          {t("btn_themes", "Темы")}
        </button>

        {themesNote && (
          <div className={styles.themesNote}>
            {t("settings_themes_text", "Эта функция ещё не сделана, ожидайте её в ближайших обновлениях лаунчера.")}
          </div>
        )}

        <div style={{ flex: 1 }} />

        {saved && <div className={styles.savedMsg}>{t("settings_saved_title", "Сохранено")}!</div>}

        <button className={styles.btnSave} onClick={save} disabled={saving || loading}>
          {saving ? "Сохранение..." : t("btn_save", "Сохранить")}
        </button>

        <button className={styles.btnBack} onClick={onBack}>{t("btn_back", "Назад")}</button>
      </div>

      {updateInfo && (
        <UpdateDialog port={port} info={updateInfo} onClose={() => setUpdateInfo(null)} />
      )}
    </div>
  );
}
