import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { formatDate } from "../utils/formatDate";
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
import { isValidIsraeliPhone } from "../utils/phoneValidation";
import ExemptionsPanel from "../components/ExemptionsPanel";
import SoldierLink from "../components/SoldierLink";
import { useAuth } from "../auth/AuthContext";
import {
  submitFieldUpdate,
  listFieldUpdates,
  getRanks,
} from "../api/soldiers";
import { setEmail } from "../api/auth";
import { getRegistrationPublicSettings } from "../api/registrationSettings";
import { generateTelegramCode, getTelegramStatus, unlinkTelegram } from "../api/telegram";
import { getPreferences, updatePreferences, listCommanderScopes, addCommanderScope, removeCommanderScope, NotificationPref } from "../api/notifications";
import { fetchTree, NodeDTO } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "../components/Combobox";
import DateInput from "../components/DateInput";
import { usePublicSettings } from "../hooks/usePublicSettings";

export default function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const publicSettings = usePublicSettings();
  const telegramEnabled = publicSettings?.["telegram.enabled"] === true;

  const [mitvahimReq, setMitvahimReq] = useState("");
  const [alalReq, setAlalReq] = useState("");
  const [mandatoryEndReq, setMandatoryEndReq] = useState("");
  const [dischargeReq, setDischargeReq] = useState("");
  const [genderReq, setGenderReq] = useState("");
  const [rankReq, setRankReq] = useState("");
  const [phoneReq, setPhoneReq] = useState("");
  const [licenseHasReq, setLicenseHasReq] = useState(false);
  const [licenseExpiryReq, setLicenseExpiryReq] = useState("");
  const [emailReq, setEmailReq] = useState(user?.email ?? "");
  const [emailSaving, setEmailSaving] = useState(false);
  const [emailMsg, setEmailMsg] = useState<string | null>(null);
  const registrationSettingsQuery = useQuery({
    queryKey: queryKeys.registrationPublicSettings(),
    queryFn: getRegistrationPublicSettings,
  });
  const emailDomainHint = registrationSettingsQuery.data?.email_domain_hint;
  const emailPlaceholder = emailDomainHint ? `שם@${emailDomainHint}` : "כתובת אימייל";
  const [tgCode, setTgCode] = useState<string | null>(null);
  const [tgBotUsername, setTgBotUsername] = useState<string | null>(null);
  const [tgPolling, setTgPolling] = useState(false);
  const [prefs, setPrefs] = useState<NotificationPref[]>([]);
  const latestPrefsRef = useRef<NotificationPref[]>([]);
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [addNodeId, setAddNodeId] = useState("");
  const [addDepth, setAddDepth] = useState<number>(-1);
  const [addingScopeLoading, setAddingScopeLoading] = useState(false);

  const isCommanderLike = !!(user?.role === "admin" || user?.is_commander || user?.is_duty_manager);

  const fieldUpdatesQuery = useQuery({
    queryKey: user ? queryKeys.fieldUpdates(user.id) : ["soldiers", "fieldUpdates", "anonymous"],
    queryFn: () => listFieldUpdates(user!.id),
    enabled: !!user,
  });
  const fieldUpdates = fieldUpdatesQuery.data ?? [];

  const ranksQuery = useQuery({ queryKey: queryKeys.ranks(), queryFn: getRanks });
  const ranks = ranksQuery.data ?? { enlisted: [], officers: [] };

  // Poll while tgPolling is true (i.e. while waiting for the user to confirm
  // the link code via the Telegram bot); stop once verified.
  const tgStatusQuery = useQuery({
    queryKey: queryKeys.telegramStatus(),
    queryFn: getTelegramStatus,
    refetchInterval: tgPolling ? 3000 : false,
  });
  const tgStatus = tgStatusQuery.data ?? null;

  useEffect(() => {
    if (tgPolling && tgStatus?.is_verified) {
      setTgPolling(false);
      setTgCode(null);
    }
  }, [tgPolling, tgStatus]);

  const prefsQuery = useQuery({ queryKey: queryKeys.notificationPreferences(), queryFn: getPreferences });

  // prefs/latestPrefsRef mirror the query result but are then edited locally
  // (optimistic toggling + a debounced write-back), so they stay useState fed
  // by an effect rather than reading straight from the query on every render.
  useEffect(() => {
    if (prefsQuery.data) {
      latestPrefsRef.current = prefsQuery.data;
      setPrefs(prefsQuery.data);
    }
  }, [prefsQuery.data]);

  const scopesQuery = useQuery({
    queryKey: queryKeys.commanderScopes(),
    queryFn: listCommanderScopes,
    enabled: isCommanderLike,
  });
  const scopes = scopesQuery.data ?? [];

  const hierarchyTreeQuery = useQuery({
    queryKey: queryKeys.hierarchyTreeVisible(),
    queryFn: fetchTree,
    enabled: isCommanderLike,
  });
  const hierarchyNodes = useMemo(() => {
    const flat: NodeDTO[] = [];
    function flatten(ns: NodeDTO[]) { for (const n of ns) { flat.push(n); if (n.children) flatten(n.children); } }
    flatten(hierarchyTreeQuery.data ?? []);
    return flat;
  }, [hierarchyTreeQuery.data]);

  function militaryLicensePayload(hasLicense: boolean, expiry: string): string {
    return JSON.stringify({ has_license: hasLicense, expiry_date: expiry || null });
  }

  async function requestUpdate(field: string, value: string) {
    if (!user || !value) return;
    try {
      await submitFieldUpdate(user.id, field, value);
      await queryClient.invalidateQueries({ queryKey: queryKeys.fieldUpdates(user.id) });
      if (field === "last_mitvahim_date") setMitvahimReq("");
      if (field === "last_alal_date") setAlalReq("");
      if (field === "mandatory_end_date") setMandatoryEndReq("");
      if (field === "discharge_date") setDischargeReq("");
      if (field === "gender") setGenderReq("");
      if (field === "rank") setRankReq("");
      if (field === "phone") setPhoneReq("");
      if (field === "military_driving_license") { setLicenseHasReq(false); setLicenseExpiryReq(""); }
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
    await queryClient.invalidateQueries({ queryKey: queryKeys.telegramStatus() });
  }

  function scheduleSyncPrefs() {
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(async () => {
      syncTimerRef.current = null;
      try {
        await updatePreferences(latestPrefsRef.current);
      } catch {
        await prefsQuery.refetch();
      }
    }, 300);
  }

  function handleTogglePref(nt: string, field: "in_app_enabled" | "push_enabled" | "email_enabled") {
    const updated = latestPrefsRef.current.map((p) => p.notification_type === nt ? { ...p, [field]: !p[field] } : p);
    latestPrefsRef.current = updated;
    setPrefs(updated);
    scheduleSyncPrefs();
  }

  function handleToggleAll(field: "in_app_enabled" | "push_enabled" | "email_enabled") {
    const allOn = latestPrefsRef.current.every((p) => p[field]);
    const updated = latestPrefsRef.current.map((p) => ({ ...p, [field]: !allOn }));
    latestPrefsRef.current = updated;
    setPrefs(updated);
    scheduleSyncPrefs();
  }

  async function handleAddScope(e: React.FormEvent) {
    e.preventDefault();
    if (!addNodeId) return;
    setAddingScopeLoading(true);
    try {
      await addCommanderScope(addNodeId, addDepth);
      await queryClient.invalidateQueries({ queryKey: queryKeys.commanderScopes() });
      setAddNodeId("");
      setAddDepth(-1);
    } catch {
      alert(t("notifications.scope_add_error"));
    } finally {
      setAddingScopeLoading(false);
    }
  }

  async function handleRemoveScope(id: string) {
    await removeCommanderScope(id);
    await queryClient.invalidateQueries({ queryKey: queryKeys.commanderScopes() });
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-3">
        <div className="flex items-center gap-4">
          {user?.profile_picture_url ? (
            <img
              src={user.profile_picture_url}
              alt={user.full_name}
              className="w-16 h-16 rounded-full object-cover shrink-0 border border-gray-200 dark:border-gray-600"
            />
          ) : (
            <div className="w-16 h-16 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0 border border-gray-200 dark:border-gray-600">
              <span className="text-xl font-semibold text-indigo-600 dark:text-indigo-300">
                {user?.full_name?.charAt(0) ?? "?"}
              </span>
            </div>
          )}
          <h2 className="text-xl font-semibold">{user?.full_name}</h2>
        </div>
        <p>{t("team.personal_number")}: {user?.personal_number}</p>
        <p>{t("team.role")}: {user?.role}</p>
        <Link to="/change-password" className="text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200" data-testid="profile-change-password">
          {t("profile.change_password")}
        </Link>
        <Link to="/my-bug-reports" className="text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200" data-testid="profile-my-bug-reports">
          {t("profile.my_bug_reports")}
        </Link>
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} canApproveDutyManagerStep={false} />
          </div>
        )}
      </section>

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-4" dir="rtl">
        <h3 className="text-lg font-semibold">{t("soldier_profile.section_title")}</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {user?.gender && <div><span className="font-medium">{t("soldier_profile.gender")}:</span> {user.gender === "male" ? t("soldier_profile.gender_male") : user.gender === "female" ? t("soldier_profile.gender_female") : user.gender}</div>}
          {user?.rank && <div><span className="font-medium">{t("soldier_profile.rank")}:</span> {user.rank}</div>}
          {user?.phone && <div><span className="font-medium">{t("soldier_profile.phone")}:</span> <span dir="ltr">{user.phone}</span></div>}
          {user?.is_officer !== null && user?.is_officer !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.is_officer")}:</span> {user.is_officer ? t("common.yes") : t("common.no")}</div>
          )}
          {user?.bahad1_graduate !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.bahad1_graduate")}:</span> {user.bahad1_graduate ? "✓" : "—"}</div>
          )}
          {user?.has_military_driving_license !== undefined && user?.has_military_driving_license !== null && (
            <div>
              <span className="font-medium">{t("soldier_profile.military_driving_license")}:</span>{" "}
              {user.has_military_driving_license
                ? (user.military_driving_license_expiry
                    ? `✓ (${t("soldier_profile.military_driving_license_expiry")}: ${formatDate(user.military_driving_license_expiry)})`
                    : "✓")
                : "—"}
            </div>
          )}
          {user?.enlistment_date && <div><span className="font-medium">{t("soldier_profile.enlistment_date")}:</span> {formatDate(user.enlistment_date)}</div>}
          {user?.mandatory_end_date && <div><span className="font-medium">{t("soldier_profile.mandatory_end_date")}:</span> {formatDate(user.mandatory_end_date)}</div>}
          {user?.discharge_date && <div><span className="font-medium">{t("soldier_profile.discharge_date")}:</span> {formatDate(user.discharge_date)}</div>}
          {user?.last_mitvahim_date && <div><span className="font-medium">{t("soldier_profile.last_mitvahim_date")}:</span> {formatDate(user.last_mitvahim_date)}</div>}
          {user?.last_alal_date && <div><span className="font-medium">{t("soldier_profile.last_alal_date")}:</span> {formatDate(user.last_alal_date)}</div>}
          {user?.direct_commander_id && user?.direct_commander_name && (
            <div>
              <span className="font-medium">{t("soldier_profile.direct_commander")}:</span>{" "}
              <SoldierLink id={user.direct_commander_id} name={user.direct_commander_name} />
            </div>
          )}
        </div>

        <div className="space-y-2 text-sm">
          <p className="font-medium">{t("soldier_profile.submit_update")}</p>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.gender")}</label>
            <select value={genderReq} onChange={e => setGenderReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
              <option value="">—</option>
              <option value="male">{t("soldier_profile.gender_male")}</option>
              <option value="female">{t("soldier_profile.gender_female")}</option>
              <option value="other">{t("soldier_profile.gender_other")}</option>
            </select>
            <button type="button" onClick={() => requestUpdate("gender", genderReq)} disabled={!genderReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.rank")}</label>
            <div className="flex-1">
              <Combobox
                items={[
                  ...ranks.enlisted.map(r => ({ id: r, name: r, group: t("soldier_profile.enlisted") })),
                  ...ranks.officers.map(r => ({ id: r, name: r, group: t("soldier_profile.officers") })),
                ]}
                value={rankReq}
                onChange={setRankReq}
                placeholder="—"
              />
            </div>
            <button type="button" onClick={() => requestUpdate("rank", rankReq)} disabled={!rankReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.phone")}</label>
            <input type="tel" value={phoneReq} onChange={e => setPhoneReq(e.target.value)} className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder="05X-XXXXXXX" dir="ltr" />
            <button type="button" onClick={() => requestUpdate("phone", phoneReq)} disabled={!phoneReq || !isValidIsraeliPhone(phoneReq)} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          {phoneReq && !isValidIsraeliPhone(phoneReq) && (
            <p className="text-red-600 text-xs">מספר טלפון לא תקין</p>
          )}
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_mitvahim_date")}</label>
            <DateInput value={mitvahimReq} onChange={setMitvahimReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_mitvahim_date", mitvahimReq)} disabled={!mitvahimReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.last_alal_date")}</label>
            <DateInput value={alalReq} onChange={setAlalReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_alal_date", alalReq)} disabled={!alalReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.mandatory_end_date")}</label>
            <DateInput value={mandatoryEndReq} onChange={setMandatoryEndReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("mandatory_end_date", mandatoryEndReq)} disabled={!mandatoryEndReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.discharge_date")}</label>
            <DateInput value={dischargeReq} onChange={setDischargeReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("discharge_date", dischargeReq)} disabled={!dischargeReq} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.military_driving_license")}</label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={licenseHasReq} onChange={e => setLicenseHasReq(e.target.checked)} />
              {t("soldier_profile.military_driving_license_has")}
            </label>
            <label htmlFor="military-license-expiry-input" className="text-sm text-gray-500 dark:text-gray-400">
              {t("soldier_profile.military_driving_license_expiry")}
            </label>
            <DateInput
              id="military-license-expiry-input"
              value={licenseExpiryReq}
              onChange={setLicenseExpiryReq}
              disabled={!licenseHasReq}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => requestUpdate("military_driving_license", militaryLicensePayload(licenseHasReq, licenseExpiryReq))}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="space-y-1">
            <div className="flex gap-2 items-center">
              <label className="w-40">{t("profile.email")}</label>
              <input type="email" value={emailReq} onChange={e => { setEmailReq(e.target.value); setEmailMsg(null); }} className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder={emailPlaceholder} />
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
                      <button type="button" className="text-indigo-600 dark:text-indigo-300 hover:underline" onClick={async () => {
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
                  {t("soldier_profile.previous_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.previous_value, t)}</span>
                </div>
                <div className="text-gray-500">
                  {t("soldier_profile.new_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.new_value, t)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {telegramEnabled && (
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
                className="inline-block text-sm text-indigo-600 dark:text-indigo-300 hover:text-indigo-800 dark:hover:text-indigo-200 underline"
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
      )}

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
        <h3 className="text-lg font-semibold">{t("notifications.preferences")}</h3>
        {(() => {
          const prefColumns = (
            ["in_app_enabled", "push_enabled", "email_enabled"] as const
          ).filter((field) => field !== "push_enabled" || telegramEnabled);
          return (
            <div className="text-sm" style={{ display: "grid", gridTemplateColumns: `1fr repeat(${prefColumns.length}, 4.5rem)` }}>
              {/* header — column labels with select-all checkboxes */}
              <div className="py-1 border-b dark:border-gray-600" />
              {prefColumns.map((field) => {
            const allOn = prefs.length > 0 && prefs.every((p) => p[field]);
            const someOn = prefs.some((p) => p[field]);
            return (
              <label key={field} className="py-1 border-b dark:border-gray-600 flex flex-col items-center gap-1 cursor-pointer select-none font-medium">
                <input
                  type="checkbox"
                  checked={allOn}
                  ref={(el) => { if (el) el.indeterminate = someOn && !allOn; }}
                  onChange={() => handleToggleAll(field)}
                />
                <span className="text-xs text-center leading-tight">
                  {field === "in_app_enabled" ? t("notifications.in_app") : field === "push_enabled" ? t("notifications.push") : t("notifications.email")}
                </span>
              </label>
            );
          })}
          {/* preference rows */}
          {prefs.map((p) => (
            <React.Fragment key={p.notification_type}>
              <div className="py-1 border-b dark:border-gray-600 flex items-center">{t(`notifications.type_${p.notification_type}`)}</div>
              {prefColumns.map((field) => (
                <div key={field} className="py-1 border-b dark:border-gray-600 flex items-center justify-center">
                  <input
                    type="checkbox"
                    checked={p[field]}
                    onChange={() => handleTogglePref(p.notification_type, field)}
                  />
                </div>
              ))}
            </React.Fragment>
          ))}
            </div>
          );
        })()}
      </section>

      {(user?.role === "admin" || user?.is_commander || user?.is_duty_manager) && (
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
          <h3 className="text-lg font-semibold">{t("notifications.commander_scopes")}</h3>
          <p className="text-xs text-gray-500">{t("notifications.commander_scopes_hint")}</p>
          {scopes.length === 0 ? (
            <p className="text-sm text-gray-500">{t("notifications.no_scopes")}</p>
          ) : (
            <ul className="space-y-3">
              {scopes.map((s) => (
                <li key={s.id} className="border dark:border-gray-600 rounded p-3 space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-medium">{s.node_name ?? s.hierarchy_node_id}</span>
                      <span className="text-xs text-gray-500 mr-2">
                        {s.depth === -1 ? t("notifications.depth_unlimited") : t("notifications.depth_levels", { count: s.depth })}
                      </span>
                    </div>
                    <button onClick={() => handleRemoveScope(s.id)} className="text-red-500 hover:text-red-700 text-xs">
                      {t("notifications.remove")}
                    </button>
                  </div>
                  {s.soldiers.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-500 font-medium mb-1">{t("notifications.subscribed_soldiers")} ({s.soldiers.length})</p>
                      <div className="flex flex-wrap gap-1">
                        {s.soldiers.map(sol => (
                          <span key={sol.id} className="text-xs bg-gray-100 dark:bg-gray-700 px-2 py-0.5 rounded">
                            {sol.full_name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={handleAddScope} className="flex flex-wrap gap-2 items-end pt-2 border-t dark:border-gray-600">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">{t("notifications.scope_node")}</label>
              <div className="min-w-[180px]">
                <Combobox
                  items={sortNodesByTree(hierarchyNodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={addNodeId}
                  onChange={setAddNodeId}
                  placeholder="— בחר ענף —"
                />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">{t("notifications.scope_depth")}</label>
              <select
                value={addDepth}
                onChange={(e) => setAddDepth(Number(e.target.value))}
                className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              >
                <option value={-1}>כל הרמות</option>
                <option value={1}>רמה 1 (ישיר)</option>
                <option value={2}>עד 2 רמות</option>
                <option value={3}>עד 3 רמות</option>
                <option value={4}>עד 4 רמות</option>
                <option value={5}>עד 5 רמות</option>
              </select>
            </div>
            <button
              type="submit"
              disabled={!addNodeId || addingScopeLoading}
              className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              {addingScopeLoading ? "מוסיף..." : "+ הוסף"}
            </button>
          </form>
        </section>
      )}
    </Layout>
  );
}
