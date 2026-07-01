import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useBackend, apiGet, apiPost } from "../lib/BackendContext";
import { useI18n } from "../lib/I18nContext";
import type { PageContext } from "../components/Layout";
import styles from "./Friends.module.css";

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

const RANK_TAGS: Record<number, string> = {
  1: "Б", 2: "А", 3: "И", 4: "Т", 5: "Eld", 6: "Jr", 7: "Tm", 8: "Drk", 9: "Own",
};

function formatDt(value: string | undefined): string {
  if (!value) return "";
  try {
    const dt = new Date(value.replace("Z", "+00:00"));
    if (isNaN(dt.getTime())) return value;
    const d = dt.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
    const t = dt.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    return `${d} ${t}`;
  } catch { return value; }
}

interface FriendUser {
  id?: number;
  username?: string;
  online?: boolean;
  status?: string;
  sub_level?: number;
  joined_at?: string;
}

interface FriendEntry {
  user?: FriendUser;
  id?: number;
  username?: string;
  online?: boolean;
  status?: string;
  sub_level?: number;
  joined_at?: string;
  created_at?: string;
}

interface FriendsResponse {
  friends?: FriendEntry[];
  incoming?: FriendEntry[];
  outgoing?: FriendEntry[];
}

type Tab = "friends" | "requests";

function extractUser(entry: FriendEntry): FriendUser {
  if (entry.user && (entry.user.id || entry.user.username)) return entry.user;
  return {
    id: entry.id, username: entry.username,
    online: entry.online, status: entry.status,
    sub_level: entry.sub_level, joined_at: entry.joined_at,
  };
}

function RankTag({ level }: { level: number }) {
  const tag  = RANK_TAGS[level] ?? "—";
  const grad = RANK_GRADIENTS[level];
  if (!grad) {
    return <span className={styles.rankTag} style={{ background: "rgba(255,255,255,0.08)", color: "#9C8368" }}>{tag}</span>;
  }
  const [c1, c2] = grad;
  const isDark = c1 === "#0e2f29";
  return (
    <span
      className={`${styles.rankTag} ${styles.rankTagGrad}`}
      style={{ "--c1": c1, "--c2": c2, color: isDark ? "#fff" : "#111827" } as React.CSSProperties}
    >
      {tag}
    </span>
  );
}

function FriendCard({ entry, actions }: { entry: FriendEntry; actions?: React.ReactNode }) {
  const u = extractUser(entry);
  const date = formatDt(entry.created_at ?? u.joined_at ?? "");
  const level = u.sub_level ?? 0;

  return (
    <div className={styles.friendCard}>
      <div className={styles.friendCardHeader}>
        {level > 0 && <RankTag level={level} />}
        <span className={styles.friendUsername}>{u.username || "—"}</span>
      </div>
      {date && <div className={styles.friendMeta}>{date}</div>}
      {actions && <div className={styles.friendCardActions}>{actions}</div>}
    </div>
  );
}

function FriendSection({ title, count, empty, children }: {
  title: string; count: number; empty: string; children?: React.ReactNode;
}) {
  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionTitle}>{title}</span>
        <span className={styles.countBadge}>{count}</span>
      </div>
      {count === 0 ? (
        <div className={styles.empty}>{empty}</div>
      ) : (
        <div className={styles.list}>{children}</div>
      )}
    </div>
  );
}

function AddFriendDialog({ port, onClose, onSuccess }: {
  port: number | null; onClose: () => void; onSuccess: () => void;
}) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [statusMsg, setStatusMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function handleSend() {
    const nick = username.trim();
    if (!nick) { setStatusMsg(t("friends_search_placeholder", "Введите никнейм.")); return; }
    setBusy(true); setStatusMsg(t("friends_action_sending", "Отправляю запрос..."));
    try {
      const res = await apiPost<{ ok: boolean; status: number; data: Record<string, unknown> }>(
        port, "/friends/request", { username: nick }
      );
      setBusy(false);
      if (!res || res.status === 0) { setStatusMsg(t("toast_no_connection", "Нет подключения к серверу.")); return; }
      if (res.ok) { onSuccess(); return; }
      const err = String((res.data as Record<string, unknown>)?.error ?? "").toLowerCase();
      const map: Record<string, string> = {
        user_not_found:       t("friends_search_not_found", "Пользователь не найден."),
        already_friends:      t("friends_section_friends", "Вы уже друзья."),
        request_already_sent: "Запрос уже отправлен.",
        cannot_add_self:      "Нельзя добавить себя.",
        self_request:         "Нельзя добавить себя.",
      };
      setStatusMsg(map[err] ?? t("error_server", "Ошибка сервера."));
    } catch { setBusy(false); setStatusMsg(t("toast_no_connection", "Нет подключения к серверу.")); }
  }

  return (
    <div className={styles.dialogOverlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.dialog}>
        <div className={styles.dialogTitle}>{t("friends_add_dialog_title", "Добавить в друзья")}</div>
        <input
          ref={inputRef}
          className={styles.dialogInput}
          placeholder={t("friends_search_placeholder", "Введите никнейм")}
          value={username}
          onChange={e => setUsername(e.target.value)}
          onKeyDown={e => e.key === "Enter" && handleSend()}
          disabled={busy}
        />
        {statusMsg && <div className={styles.dialogStatus}>{statusMsg}</div>}
        <div className={styles.dialogBtns}>
          <button className={styles.btnDialogCancel} onClick={onClose} disabled={busy}>{t("friends_add_dialog_cancel", "Отмена")}</button>
          <button className={styles.btnDialogConfirm} onClick={handleSend} disabled={busy}>{t("friends_add_dialog_confirm", "Отправить")}</button>
        </div>
      </div>
    </div>
  );
}

export default function Friends() {
  const port = useBackend();
  const { t } = useI18n();
  const { onBack } = useOutletContext<PageContext>();
  const [data, setData] = useState<FriendsResponse>({});
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>("friends");
  const [tabAnim, setTabAnim] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 7_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [port]);

  async function load() {
    try {
      const res = await apiGet<unknown>(port, "/friends", 0);
      // апишка заворачивает в data.result блять
      const result = (res as any)?.data?.result ?? {};
      setData({
        friends:  Array.isArray(result.friends)  ? result.friends  : [],
        incoming: Array.isArray(result.incoming) ? result.incoming : [],
        outgoing: Array.isArray(result.outgoing) ? result.outgoing : [],
      });
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  function switchTab(next: Tab) {
    if (next === tab) return;
    setTabAnim(true);
    setTimeout(() => { setTab(next); setTabAnim(false); }, 120);
  }

  async function doAction(path: string, body: Record<string, unknown>) {
    if (busy) return;
    setBusy(true);
    try { await apiPost(port, path, body); await load(); }
    catch { /* ignore */ }
    finally { setBusy(false); }
  }

  const friends  = data.friends  ?? [];
  const incoming = data.incoming ?? [];
  const outgoing = data.outgoing ?? [];

  return (
    <div className="innerLayout">

      <div className="innerPanel innerPanelScroll">
        <div className={styles.content}>
          <div className={styles.pageTitle}>{t("friends_title", "Друзья")}</div>
          <div className={styles.tabTitle}>
            {tab === "friends" ? t("friends_tab_friends", "Список друзей") : t("friends_tab_requests", "Заявки в друзья")}
          </div>

          {loading ? (
            <div className={styles.loading}>Загрузка...</div>
          ) : (
            <div className={tabAnim ? styles.tabFade : ""}>
              {tab === "friends" ? (
                <FriendSection title={t("friends_section_friends", "Друзья")} count={friends.length} empty={t("friends_empty_friends", "Список друзей пока пуст.")}>
                  {friends.map((f, i) => {
                    const u = extractUser(f);
                    return (
                      <FriendCard key={i} entry={f} actions={
                        <button className={styles.btnDecline} disabled={busy}
                          onClick={() => u.id && doAction("/friends/remove", { friend_user_id: u.id })}>
                          {t("friends_remove", "Удалить")}
                        </button>
                      } />
                    );
                  })}
                </FriendSection>
              ) : (
                <div className={styles.requestsSections}>
                  <FriendSection title={t("friends_section_incoming", "Входящие заявки")} count={incoming.length} empty={t("friends_empty_incoming", "Входящих заявок нет.")}>
                    {incoming.map((f, i) => {
                      const u = extractUser(f);
                      return (
                        <FriendCard key={i} entry={f} actions={
                          <>
                            <button className={styles.btnAccept} disabled={busy}
                              onClick={() => u.id && doAction("/friends/respond", { friend_user_id: u.id, action: "accept" })}>
                              {t("friends_accept", "Принять")}
                            </button>
                            <button className={styles.btnDecline} disabled={busy}
                              onClick={() => u.id && doAction("/friends/respond", { friend_user_id: u.id, action: "decline" })}>
                              {t("friends_decline", "Отклонить")}
                            </button>
                          </>
                        } />
                      );
                    })}
                  </FriendSection>

                  <FriendSection title={t("friends_section_outgoing", "Исходящие заявки")} count={outgoing.length} empty={t("friends_empty_outgoing", "Исходящих заявок нет.")}>
                    {outgoing.map((f, i) => {
                      const u = extractUser(f);
                      return (
                        <FriendCard key={i} entry={f} actions={
                          <button className={styles.btnDecline} disabled={busy}
                            onClick={() => u.id && doAction("/friends/remove", { friend_user_id: u.id })}>
                            {t("friends_cancel", "Отменить")}
                          </button>
                        } />
                      );
                    })}
                  </FriendSection>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="innerSidebar">
        <div className={styles.sidebarSection}>{t("friends_sidebar_title", "Управление")}</div>

        <button
          className={tab === "friends" ? styles.btnNavActive : styles.btnNavInactive}
          onClick={() => switchTab("friends")}
        >{t("friends_nav_friends", "Друзья")}</button>
        <button
          className={tab === "requests" ? styles.btnNavActive : styles.btnNavInactive}
          onClick={() => switchTab("requests")}
        >{t("friends_nav_requests", "Заявки")}</button>

        <button className={styles.btnAddFriend} onClick={() => setShowAdd(true)}>
          {t("friends_nav_add", "Добавить друга")}
        </button>

        <div style={{ flex: 1 }} />
        <button className={styles.btnBack} onClick={onBack}>{t("btn_back", "Назад")}</button>
      </div>

      {showAdd && (
        <AddFriendDialog
          port={port}
          onClose={() => setShowAdd(false)}
          onSuccess={() => { setShowAdd(false); load(); }}
        />
      )}
    </div>
  );
}
