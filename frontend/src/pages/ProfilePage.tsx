import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import ExemptionsPanel from "../components/ExemptionsPanel";
import { useAuth } from "../auth/AuthContext";
import {
  FieldUpdateDTO,
  submitFieldUpdate,
  listFieldUpdates,
} from "../api/soldiers";
import { setEmail } from "../api/auth";
import { generateTelegramCode, getTelegramStatus, unlinkTelegram, TelegramStatus } from "../api/telegram";
import { getPreferences, updatePreferences, listCommanderScopes, addCommanderScope, removeCommanderScope, NotificationPref, CommanderScope } from "../api/notifications";

export default function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [fieldUpdates, setFieldUpdates] = useState<FieldUpdateDTO[]>([]);
  const [mitvahimReq, setMitvahimReq] = useState("");
  const [alalReq, setAlalReq] = useState("");
  const [genderReq, setGenderReq] = useState("");
  const [emailReq, setEmailReq] = useState(user?.email ?? "");
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailMsg, setEmailMsg] = useState<string | null>(null);
  const [tgStatus, setTgStatus] = useState<TelegramStatus | null>(null);
  const [tgCode, setTgCode] = useState<string | null>(null);
  const [tgBotUsername, setTgBotUsername] = useState<string | null>(null);
  const [tgPolling, setTgPolling] = useState(false);
  const [prefs, setPrefs] = useState<NotificationPref[]>([]);
  const [scopes, setScopes] = useState<CommanderScope[]>([]);

  useEffect(() => {
    if (user) {
      void (async () => {
        const updates = await listFieldUpdates(user.id);
        setFieldUpdates(updates);
      })();
    }
  }, [user]);

  useEffect(() => {
    getTelegramStatus().then(setTgStatus).catch(() => {});
    getPreferences().then(setPrefs).catch(() => {});
    if (user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") {
      listCommanderScopes().then(setScopes).catch(() => {});
    }
  }, [user]);

  useEffect(() => {
    if (!tgPolling) return;
    const interval = setInterval(async () => {
      try {
        const s = await getTelegramStatus();
        setTgStatus(s);
        if (s?.is_verified) {
          setTgPolling(false);
          setTgCode(null);
        }
      } catch { setTgPolling(false); }
    }, 3000);
    return () => clearInterval(interval);
  }, [tgPolling]);

  async function requestUpdate(field: string, value: string) {
    if (!user || !value) return;
    try {
      await submitFieldUpdate(user.id, field, value);
      const updated = await listFieldUpdates(user.id);
      setFieldUpdates(updated);
      if (field === "last_mitvahim_date") setMitvahimReq("");
      if (field === "last_alal_date") setAlalReq("");
      if (field === "gender") setGenderReq("");
    } catch {
      // submission failed silently — backend returns error detail
    }
  }

  async function handleLinkTelegram() {
    try {
      const { code, bot_username } = await generateTelegramCode();
      setTgCode(code);
      setTgBotUsername(bot_username || null);
      setTgPolling(true);
    } catch {
      alert(t("notifications.link_error"));
    }
  }

  async function handleUnlinkTelegram() {
    await unlinkTelegram();
    setTgStatus({ is_verified: false });
  }

  async function handleTogglePref(nt: string, field: "in_app_enabled" | "push_enabled") {
    const updated = prefs.map((p) => p.notification_type === nt ? { ...p, [field]: !p[field] } : p);
    setPrefs(updated);
    await updatePreferences(updated.map((p) => ({ notification_type: p.notification_type, in_app_enabled: p.in_app_enabled, push_enabled: p.push_enabled })));
  }

  async function handleAddScope() {
    const nodeId = prompt(t("notifications.enter_node_id"));
    if (!nodeId) return;
    try {
      const scope = await addCommanderScope(nodeId);
      setScopes((prev) => [...prev, scope]);
    } catch { alert(t("notifications.scope_add_error")); }
  }

  async function handleRemoveScope(id: string) {
    await removeCommanderScope(id);
    setScopes((prev) => prev.filter((s) => s.id !== id));
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-3">
        <h2 className="text-xl font-semibold">{t("profile.title")}</h2>
        <p>{t("team.full_name")}: {user?.full_name}</p>
        <p>{t("team.personal_number")}: {user?.personal_number}</p>
        <p>{t("team.role")}: {user?.role}</p>
        <Link to="/change-password" className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300" data-testid="profile-change-password">
          {t("profile.change_password")}
        </Link>
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} />
          </div>
        )}
      </section>

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-4" dir="rtl">
        <h3 className="text-lg font-semibold">{t("soldier_profile.section_title")}</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {user?.gender && <div><span className="font-medium">{t("soldier_profile.gender")}:</span> {user.gender === "male" ? t("soldier_profile.gender_male") : user.gender === "female" ? t("soldier_profile.gender_female") : user.gender}</div>}
          {user?.rank && <div><span className="font-medium">{t("soldier_profile.rank")}:</span> {user.rank}</div>}
          {user?.is_officer !== null && user?.is_officer !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.is_officer")}:</span> {user.is_officer ? t("soldier_profile.is_officer") : t("soldier_profile.is_enlisted")}</div>
          )}
          {user?.bahad1_graduate !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.bahad1_graduate")}:</span> {user.bahad1_graduate ? "✓" : "—"}</div>
          )}
          {user?.enlistment_date && <div><span className="font-medium">{t("soldier_profile.enlistment_date")}:</span> {user.enlistment_date}</div>}
          {user?.mandatory_end_date && <div><span className="font-medium">{t("soldier_profile.mandatory_end_date")}:</span> {user.mandatory_end_date}</div>}
          {user?.discharge_date && <div><span className="font-medium">{t("soldier_profile.discharge_date")}:</span> {user.discharge_date}</div>}
          {user?.last_mitvahim_date && <div><span className="font-medium">{t("soldier_profile.last_mitvahim_date")}:</span> {user.last_mitvahim_date}</div>}
          {user?.last_alal_date && <div><span className="font-medium">{t("soldier_profile.last_alal_date")}:</span> {user.last_alal_date}</div>}
        </div>

        <div className="space-y-2 text-sm">
          <p className="font-medium">{t("soldier_profile.submit_update")}</p>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.gender")}</label>
            <select value={genderReq} onChange={e => setGenderReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
              <option value="">—</option>
              <option value="male">{t("soldier_profile.gender_male")}</option>
              <option value="female">{t("soldier_profile.gender_female")}</option>
            </select>
            <button type="button" onClick={() => requestUpdate("gender", genderReq)} disabled={!genderReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_mitvahim_date")}</label>
            <input type="date" value={mitvahimReq} onChange={e => setMitvahimReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_mitvahim_date", mitvahimReq)} disabled={!mitvahimReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_alal_date")}</label>
            <input type="date" value={alalReq} onChange={e => setAlalReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_alal_date", alalReq)} disabled={!alalReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="space-y-1">
            <div className="flex gap-2 items-center">
              <label className="w-40">{t("profile.email")}</label>
              <input type="email" value={emailReq} onChange={e => { setEmailReq(e.target.value); setEmailMsg(null); }} className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder="כתובת אימייל" />
              <button type="button" disabled={emailSaving} onClick={async () => {
                setEmailSaving(true); setEmailMsg(null);
                try {
                  await setEmail(emailReq || null);
                  setEmailMsg(emailReq ? t("profile.email_verification_sent") : t("profile.email_cleared"));
                } catch { setEmailMsg(t("login.errors.network")); }
                finally { setEmailSaving(false); }
              }} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
                {emailSaving ? "..." : t("approvals.approve")}
              </button>
            </div>
            <div className="flex items-center gap-2 text-xs mr-40 pr-2">
              {user?.email_verified
                ? <span className="text-green-600">✓ {t("profile.email_verified")}</span>
                : user?.email
                  ? <><span className="text-yellow-600">{t("profile.email_unverified")}</span>
                      <button type="button" className="text-indigo-600 dark:text-indigo-400 hover:underline" onClick={async () => {
                        await setEmail(user.email ?? null);
                        setEmailMsg(t("profile.email_verification_sent"));
                      }}>{t("profile.resend_verification")}</button>
                    </>
                  : null}
              {emailMsg && <span className="text-gray-500">{emailMsg}</span>}
            </div>
          </div>
        </div>

        {fieldUpdates.length > 0 && (
          <div className="space-y-2 text-sm">
            <p className="font-medium">{t("soldier_profile.field_updates_tab")}</p>
            {fieldUpdates.map((u) => (
              <div key={u.id} className="border dark:border-gray-600 rounded p-3 space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{t(`soldier_profile.${u.field_name}`)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${u.status === "pending" ? "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" : u.status === "approved" ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
                    {t(`soldier_profile.update_${u.status}`)}
                  </span>
                </div>
                <div className="text-gray-500">
                  {t("soldier_profile.previous_value")}: <span className="font-mono">{u.previous_value ? (u.field_name === "gender" ? t(`soldier_profile.gender_${u.previous_value}`) : u.previous_value) : "—"}</span>
                </div>
                <div className="text-gray-500">
                  {t("soldier_profile.new_value")}: <span className="font-mono">{u.new_value ? (u.field_name === "gender" ? t(`soldier_profile.gender_${u.new_value}`) : u.new_value) : "—"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
        <h3 className="text-lg font-semibold">{t("notifications.telegram")}</h3>
        {tgCode ? (
          <div className="space-y-2">
            <p className="text-sm">{t("notifications.send_code_to_bot")}</p>
            {tgBotUsername && (
              <a
                href={`https://t.me/${tgBotUsername}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-block text-sm text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 underline"
              >
                @{tgBotUsername}
              </a>
            )}
            <div className="flex items-center gap-2">
              <code className="bg-gray-100 dark:bg-gray-700 px-3 py-1 rounded text-lg font-mono">{tgCode}</code>
              <button onClick={() => navigator.clipboard.writeText(tgCode)} className="text-xs text-indigo-600 hover:text-indigo-800">
                {t("notifications.copy")}
              </button>
            </div>
            <div className="flex items-center gap-2">
              <code className="bg-gray-100 dark:bg-gray-700 px-2 py-1 rounded text-sm font-mono text-gray-700 dark:text-gray-200">/verify {tgCode}</code>
              <button onClick={() => navigator.clipboard.writeText(`/verify ${tgCode}`)} className="text-xs text-indigo-600 hover:text-indigo-800">
                {t("notifications.copy")}
              </button>
            </div>
            {tgPolling && <p className="text-xs text-gray-500">{t("notifications.waiting_for_verification")}</p>}
          </div>
        ) : tgStatus?.is_verified ? (
          <div>
            <p className="text-sm">✅ {t("notifications.linked_to")} @{tgStatus.telegram_username || "?"}</p>
            <button onClick={handleUnlinkTelegram} className="text-sm text-red-600 hover:text-red-800 mt-2">
              {t("notifications.unlink")}
            </button>
          </div>
        ) : (
          <button onClick={handleLinkTelegram} className="bg-indigo-600 text-white px-4 py-2 rounded text-sm hover:bg-indigo-700">
            {t("notifications.link_telegram")}
          </button>
        )}
      </section>

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
        <h3 className="text-lg font-semibold">{t("notifications.preferences")}</h3>
        <div className="space-y-2">
          {prefs.map((p) => (
            <div key={p.notification_type} className="flex items-center justify-between py-1 border-b dark:border-gray-600 text-sm">
              <span>{t(`notifications.type_${p.notification_type}`)}</span>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={p.in_app_enabled} onChange={() => handleTogglePref(p.notification_type, "in_app_enabled")} />
                  <span className="text-xs">{t("notifications.in_app")}</span>
                </label>
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={p.push_enabled} onChange={() => handleTogglePref(p.notification_type, "push_enabled")} />
                  <span className="text-xs">{t("notifications.push")}</span>
                </label>
              </div>
            </div>
          ))}
        </div>
      </section>

      {(user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") && (
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
          <h3 className="text-lg font-semibold">{t("notifications.commander_scopes")}</h3>
          <p className="text-xs text-gray-500">{t("notifications.commander_scopes_hint")}</p>
          {scopes.length === 0 ? (
            <p className="text-sm text-gray-500">{t("notifications.no_scopes")}</p>
          ) : (
            <ul className="space-y-1">
              {scopes.map((s) => (
                <li key={s.id} className="flex items-center justify-between text-sm py-1 border-b dark:border-gray-600">
                  <span>{s.hierarchy_node_id}</span>
                  <button onClick={() => handleRemoveScope(s.id)} className="text-red-500 hover:text-red-700 text-xs">
                    {t("notifications.remove")}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button onClick={handleAddScope} className="text-sm text-indigo-600 hover:text-indigo-800">
            + {t("notifications.add_scope")}
          </button>
        </section>
      )}
    </Layout>
  );
}
