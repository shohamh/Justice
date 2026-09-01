import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import { formatDate } from "../utils/formatDate";
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
import { isValidIsraeliPhone } from "../utils/phoneValidation";
import ExemptionsPanel from "../components/ExemptionsPanel";
import SoldierLink from "../components/SoldierLink";
import DeputiesPanel from "../components/DeputiesPanel";
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
import { parseRankSelectionId, rankSelectionId } from "../constants/ranks";
import DateInput from "../components/DateInput";
import { usePublicSettings } from "../hooks/usePublicSettings";
import { getSoldierRangeStatus } from "../api/rangeStatus";
import { formatRangeStatus } from "../utils/rangeEligibilityExplanation";
import MessageDialog from "../components/MessageDialog";
import ConfirmDialog from "../components/ConfirmDialog";
import { UNIT_JOIN_DATE_CONFIRMATION } from "../constants/activeDays";

// Notification types that are never sent to a plain soldier — only to their
// commander(s), duty managers, or admins (see notify_* call sites in
// backend/app/services/notifications.py). Hiding them for everyone else
// avoids showing preference toggles a soldier can never actually trigger.
const MANAGER_ONLY_NOTIFICATION_TYPES = new Set([
  "algorithm_job_done", "algorithm_job_failed",
  "enrollment_request_received", "constraint_pending", "exemption_request_pending",
  "swap_pending_approval", "transfer_request_pending", "transfer_request_rejected",
  "range_reminder_shortfall", "range_excusal_no_backfill", "range_absence_reported_to_commander",
]);

export default function ProfilePage() {
  const { t } = useTranslation();
  const [message, setMessage] = useState<string | null>(null);
  const location = useLocation();
  const { user, refreshMe } = useAuth();
  const queryClient = useQueryClient();
  const publicSettings = usePublicSettings();
  const telegramEnabled = publicSettings?.["telegram.enabled"] === true;

  useEffect(() => {
    refreshMe().catch(() => {});
  }, [refreshMe]);

  const [mitvahimReq, setMitvahimReq] = useState("");
  const [alalReq, setAlalReq] = useState("");
  const [mandatoryEndReq, setMandatoryEndReq] = useState("");
  const [dischargeReq, setDischargeReq] = useState("");
  const [unitJoinDateReq, setUnitJoinDateReq] = useState("");
  const [unitJoinDateToConfirm, setUnitJoinDateToConfirm] = useState<string | null>(null);
  const [genderReq, setGenderReq] = useState("");
  const [rankReq, setRankReq] = useState("");
  const [phoneReq, setPhoneReq] = useState("");
  const [licenseHasReq, setLicenseHasReq] = useState(false);
  const [licenseExpiryReq, setLicenseExpiryReq] = useState("");
  const [foodTypeReq, setFoodTypeReq] = useState("");
  const [foodConstraintsReq, setFoodConstraintsReq] = useState("");
  const [showFoodConstraintsHelp, setShowFoodConstraintsHelp] = useState(false);
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

  useEffect(() => {
    if (!location.hash) return;
    const target = document.getElementById(location.hash.slice(1));
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("ring-2", "ring-indigo-500", "ring-offset-2");
    const timer = window.setTimeout(() => {
      target.classList.remove("ring-2", "ring-indigo-500", "ring-offset-2");
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [location.hash]);

  const isCommanderLike = !!(user?.role === "admin" || user?.is_commander || user?.is_duty_manager);
  const canRequestUnitJoinDate = !!user?.enrolled_at && !user?.left_at;

  const visiblePrefs = useMemo(
    () => isCommanderLike ? prefs : prefs.filter((p) => !MANAGER_ONLY_NOTIFICATION_TYPES.has(p.notification_type)),
    [prefs, isCommanderLike]
  );

  const fieldUpdatesQuery = useQuery({
    queryKey: user ? queryKeys.fieldUpdates(user.id) : ["soldiers", "fieldUpdates", "anonymous"],
    queryFn: () => listFieldUpdates(user!.id),
    enabled: !!user,
  });
  const fieldUpdates = useMemo(() => fieldUpdatesQuery.data ?? [], [fieldUpdatesQuery.data]);

  const ranksQuery = useQuery({ queryKey: queryKeys.ranks(), queryFn: getRanks });
  const ranks = useMemo(
    () => ranksQuery.data ?? { enlisted: [], officers: [], officer_academic: [] },
    [ranksQuery.data],
  );

  // Effective value per editable field = stored DB value overlaid with the
  // newest pending field-update's new_value (i.e. what the value will become
  // once that request is approved).
  const pendingByField = useMemo(() => {
    const m = new Map<string, string>();
    for (const u of fieldUpdates) {
      if (["pending", "pending_commander", "pending_duty_manager"].includes(u.status) && u.new_value != null && !m.has(u.field_name)) {
        m.set(u.field_name, u.new_value);
      }
    }
    return m;
  }, [fieldUpdates]);

  const rankItems = useMemo(() => [
    ...ranks.enlisted.map((r) => ({ id: rankSelectionId("enlisted", r), name: r, group: t("soldier_profile.enlisted") })),
    ...ranks.officers.map((r) => ({ id: rankSelectionId("officer", r), name: r, group: t("soldier_profile.officers") })),
    ...ranks.officer_academic.map((r) => ({ id: rankSelectionId("officer_academic", r), name: r, group: "קצינים אקדמאים" })),
  ], [ranks, t]);

  const effectiveValues = useMemo(() => {
    const strPending = (field: string) => {
      const raw = pendingByField.get(field);
      if (raw != null && raw.trim() !== "") {
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object" && "rank" in parsed) return String(parsed.rank);
        } catch { /* plain string */ }
        return raw;
      }
      return null;
    };
    const license = (() => {
      const raw = pendingByField.get("military_driving_license");
      if (raw != null) {
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object") {
            return {
              has: !!parsed.has_license,
              expiry: typeof parsed.expiry_date === "string" ? parsed.expiry_date : "",
            };
          }
        } catch { /* fall back to DB */ }
      }
      return {
        has: !!user?.has_military_driving_license,
        expiry: user?.military_driving_license_expiry ?? "",
      };
    })();
    const rank = (() => {
      const dbRank = user?.rank ?? "";
      const dbTrack = user?.rank_track ?? "";
      const raw = pendingByField.get("rank");
      let rankName = dbRank;
      let track = dbTrack;
      if (raw != null) {
        try {
          const parsed = JSON.parse(raw);
          if (parsed && typeof parsed === "object" && "rank" in parsed) {
            rankName = String(parsed.rank ?? dbRank);
            track = typeof parsed.rank_track === "string" ? parsed.rank_track : dbTrack;
          }
        } catch { rankName = raw; }
      }
      if (!rankName) return "";
      const item = rankItems.find((i) => i.name === rankName);
      if (item) return item.id;
      return track ? `${track}:${rankName}` : "";
    })();
    return {
      gender: strPending("gender") ?? user?.gender ?? "",
      phone: strPending("phone") ?? user?.phone ?? "",
      last_mitvahim_date: strPending("last_mitvahim_date") ?? user?.last_mitvahim_date ?? "",
      last_alal_date: strPending("last_alal_date") ?? user?.last_alal_date ?? "",
      mandatory_end_date: strPending("mandatory_end_date") ?? user?.mandatory_end_date ?? "",
      discharge_date: strPending("discharge_date") ?? user?.discharge_date ?? "",
      unit_join_date: strPending("unit_join_date") ?? user?.unit_join_date ?? "",
      rank_selection_id: rank,
      license,
    };
  }, [pendingByField, user, rankItems]);

  // Seed the editable controls with their effective current value once per
  // user (after field updates have loaded, so pending overlays are included).
  const seededUserIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!user || fieldUpdatesQuery.isLoading || seededUserIdRef.current === user.id) return;
    seededUserIdRef.current = user.id;
    setGenderReq(effectiveValues.gender);
    setPhoneReq(effectiveValues.phone);
    setMitvahimReq(effectiveValues.last_mitvahim_date);
    setAlalReq(effectiveValues.last_alal_date);
    setMandatoryEndReq(effectiveValues.mandatory_end_date);
    setDischargeReq(effectiveValues.discharge_date);
    setUnitJoinDateReq(effectiveValues.unit_join_date);
    setRankReq(effectiveValues.rank_selection_id);
    setLicenseHasReq(effectiveValues.license.has);
    setLicenseExpiryReq(effectiveValues.license.expiry);
  }, [user, fieldUpdatesQuery.isLoading, effectiveValues]);

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

  const { data: rangeStatus } = useQuery({
    queryKey: ["soldierRangeStatus", user?.id],
    queryFn: () => getSoldierRangeStatus(user!.id),
    enabled: !!user?.id,
  });

  function militaryLicensePayload(hasLicense: boolean, expiry: string): string {
    return JSON.stringify({ has_license: hasLicense, expiry_date: expiry || null });
  }

  async function requestUpdate(field: string, value: string) {
    if (!user || !value) return;
    try {
      await submitFieldUpdate(user.id, field, value);
      await queryClient.invalidateQueries({ queryKey: queryKeys.fieldUpdates(user.id) });
    } catch {
      // submission failed silently — backend returns error detail
    }
  }

  function requestUnitJoinDateUpdate() {
    if (unitJoinDateReq && unitJoinDateReq !== effectiveValues.unit_join_date) {
      setUnitJoinDateToConfirm(unitJoinDateReq);
    }
  }

  async function confirmUnitJoinDateUpdate() {
    if (!unitJoinDateToConfirm) return;
    await requestUpdate("unit_join_date", unitJoinDateToConfirm);
    setUnitJoinDateToConfirm(null);
  }

  async function handleLinkTelegram() {
    try {
      const { code, bot_username } = await generateTelegramCode();
      setTgCode(code);
      setTgBotUsername(bot_username || null);
      setTgPolling(true);
    } catch {
      setMessage(t("notifications.link_error"));
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

  function handleToggleAll(field: "in_app_enabled" | "push_enabled" | "email_enabled", visibleTypes: Set<string>) {
    const visible = latestPrefsRef.current.filter((p) => visibleTypes.has(p.notification_type));
    const allOn = visible.length > 0 && visible.every((p) => p[field]);
    const updated = latestPrefsRef.current.map((p) =>
      visibleTypes.has(p.notification_type) ? { ...p, [field]: !allOn } : p
    );
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
      setMessage(t("notifications.scope_add_error"));
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
        {user?.id && (
          <div className="pt-4 border-t">
            <ExemptionsPanel soldierId={user.id} canManage={false} canApproveDutyManagerStep={false} />
          </div>
        )}
      </section>

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-4" dir="rtl">
        <h3 className="text-lg font-semibold">{t("soldier_profile.section_title")}</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          {user?.is_officer !== null && user?.is_officer !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.is_officer")}:</span> {user.is_officer ? t("common.yes") : t("common.no")}</div>
          )}
          {user?.bahad1_graduate !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.bahad1_graduate")}:</span> {user.bahad1_graduate ? "✓" : "—"}</div>
          )}
          {user?.enlistment_date && <div><span className="font-medium">{t("soldier_profile.enlistment_date")}:</span> {formatDate(user.enlistment_date)}</div>}
          {user?.unit_join_date && <div><span className="font-medium">{t("soldier_profile.unit_join_date")}:</span> {formatDate(user.unit_join_date)}</div>}
          {rangeStatus && rangeStatus.statuses.length > 0 && (
            <div className="col-span-2">
              <span className="font-medium">{t("range_qualification.status.sectionTitle")}:</span>
              <ul className="mt-1 space-y-1">
                {rangeStatus.statuses.map((s) => (
                  <li key={s.required_range_type} className="text-xs">
                    {formatRangeStatus(s, t)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {user?.direct_commander_id && user?.direct_commander_name && (
            <div>
              <span className="font-medium">{t("soldier_profile.direct_commander")}:</span>{" "}
              <SoldierLink id={user.direct_commander_id} name={user.direct_commander_name} />
            </div>
          )}
        </div>

        <div className="space-y-2 text-sm">
          <p className="font-medium">{t("soldier_profile.submit_update")}</p>
          {canRequestUnitJoinDate && <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.unit_join_date")}</label>
            <DateInput
              data-testid="unit-join-date-request-input"
              value={unitJoinDateReq}
              onChange={setUnitJoinDateReq}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <button
              type="button"
              data-testid="unit-join-date-submit"
              onClick={requestUnitJoinDateUpdate}
              disabled={!unitJoinDateReq || unitJoinDateReq === effectiveValues.unit_join_date}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>}
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.gender")}</label>
            <select value={genderReq} onChange={e => setGenderReq(e.target.value)} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100">
              <option value="">—</option>
              <option value="male">{t("soldier_profile.gender_male")}</option>
              <option value="female">{t("soldier_profile.gender_female")}</option>
              <option value="other">{t("soldier_profile.gender_other")}</option>
            </select>
            <button type="button" onClick={() => requestUpdate("gender", genderReq)} disabled={genderReq === effectiveValues.gender} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.rank")}</label>
            <div className="flex-1">
              <Combobox
                items={rankItems}
              value={rankReq}
              onChange={setRankReq}
                placeholder="—"
              />
            </div>
            <button type="button" onClick={() => {
              const selection = parseRankSelectionId(rankReq);
              if (selection) void requestUpdate("rank", JSON.stringify({ rank: selection.rank, rank_track: selection.rankTrack }));
            }} disabled={!rankReq || rankReq === effectiveValues.rank_selection_id} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.phone")}</label>
            <input type="tel" value={phoneReq} onChange={e => setPhoneReq(e.target.value)} className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder="05X-XXXXXXX" dir="ltr" />
            <button type="button" onClick={() => requestUpdate("phone", phoneReq)} disabled={!phoneReq || !isValidIsraeliPhone(phoneReq) || phoneReq.trim() === effectiveValues.phone.trim()} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          {phoneReq && !isValidIsraeliPhone(phoneReq) && (
            <p className="text-red-600 text-xs">מספר טלפון לא תקין</p>
          )}
          <div id="last-mitvahim-field" className="flex flex-col sm:flex-row gap-2 sm:items-center scroll-mt-24">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.last_mitvahim_date")}</label>
            <DateInput value={mitvahimReq} onChange={setMitvahimReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_mitvahim_date", mitvahimReq)} disabled={!mitvahimReq || mitvahimReq === effectiveValues.last_mitvahim_date} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div id="last-alal-field" className="flex flex-col sm:flex-row gap-2 sm:items-center scroll-mt-24">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.last_alal_date")}</label>
            <DateInput value={alalReq} onChange={setAlalReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("last_alal_date", alalReq)} disabled={!alalReq || alalReq === effectiveValues.last_alal_date} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.mandatory_end_date")}</label>
            <DateInput value={mandatoryEndReq} onChange={setMandatoryEndReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("mandatory_end_date", mandatoryEndReq)} disabled={!mandatoryEndReq || mandatoryEndReq === effectiveValues.mandatory_end_date} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.discharge_date")}</label>
            <DateInput value={dischargeReq} onChange={setDischargeReq} className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
            <button type="button" onClick={() => requestUpdate("discharge_date", dischargeReq)} disabled={!dischargeReq || dischargeReq === effectiveValues.discharge_date} className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50">
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.military_driving_license")}</label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={licenseHasReq} onChange={e => setLicenseHasReq(e.target.checked)} />
              {t("soldier_profile.military_driving_license_has")}
            </label>
            <button
              type="button"
              onClick={() => requestUpdate("military_driving_license", militaryLicensePayload(licenseHasReq, effectiveValues.license.expiry))}
              disabled={licenseHasReq === effectiveValues.license.has}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label htmlFor="military-license-expiry-input" className="w-full sm:w-40 shrink-0">
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
              disabled={militaryLicensePayload(licenseHasReq, licenseExpiryReq) === militaryLicensePayload(effectiveValues.license.has, effectiveValues.license.expiry)}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-full sm:w-40 shrink-0">{t("soldier_profile.food_type")}</label>
            <select
              data-testid="food-type-select"
              value={foodTypeReq}
              onChange={e => setFoodTypeReq(e.target.value)}
              className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="">{t("soldier_profile.food_type_select")}</option>
              <option value="regular">{t("soldier_profile.food_regular")}</option>
              <option value="vegetarian">{t("soldier_profile.food_vegetarian")}</option>
              <option value="vegan">{t("soldier_profile.food_vegan")}</option>
              <option value="gluten_free">{t("soldier_profile.food_gluten_free")}</option>
              <option value="kosher_le_mehadrin">{t("soldier_profile.food_kosher_le_mehadrin")}</option>
            </select>
            <button
              type="button"
              onClick={() => requestUpdate("food_type", foodTypeReq)}
              disabled={!foodTypeReq}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <label className="w-40 shrink-0 flex items-center gap-1">
              {t("soldier_profile.food_constraints")}
              <button
                type="button"
                data-testid="food-constraints-help-toggle"
                onClick={() => setShowFoodConstraintsHelp(v => !v)}
                className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-gray-400 text-[10px] text-gray-400 hover:border-indigo-500 hover:text-indigo-600"
                aria-label={t("soldier_profile.food_constraints_help")}
              >
                ?
              </button>
            </label>
            <input
              type="text"
              data-testid="food-constraints-input"
              value={foodConstraintsReq}
              onChange={e => setFoodConstraintsReq(e.target.value)}
              className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              placeholder={t("soldier_profile.food_constraints_placeholder")}
            />
            <button
              type="button"
              onClick={() => requestUpdate("food_constraints", foodConstraintsReq)}
              disabled={!foodConstraintsReq.trim()}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
          {showFoodConstraintsHelp && (
            <p className="text-xs text-gray-500 dark:text-gray-400 sm:mr-40">
              {t("soldier_profile.food_constraints_help")}
            </p>
          )}
          <div className="space-y-1">
            <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
              <label className="w-full sm:w-40 shrink-0">{t("profile.email")}</label>
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
                  <span className={`text-xs px-1.5 py-0.5 rounded ${["pending", "pending_commander", "pending_duty_manager"].includes(u.status) ? "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" : u.status === "approved" ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
                    {t(`soldier_profile.update_${["pending_commander", "pending_duty_manager"].includes(u.status) ? "pending" : u.status}`)}
                  </span>
                </div>
                {u.status === "pending_commander" && <p className="text-xs text-amber-700 dark:text-amber-400">ממתין לאישור מפקד</p>}
                {u.status === "pending_duty_manager" && <p className="text-xs text-amber-700 dark:text-amber-400">ממתין לאישור אחראי תורנויות</p>}
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
      <ConfirmDialog
        open={unitJoinDateToConfirm !== null}
        title={t("soldier_profile.unit_join_date")}
        message={UNIT_JOIN_DATE_CONFIRMATION}
        confirmLabel={t("soldier_profile.submit_update")}
        confirmDisabled={fieldUpdatesQuery.isFetching}
        onConfirm={() => void confirmUnitJoinDateUpdate()}
        onClose={() => setUnitJoinDateToConfirm(null)}
      />

      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3">
        <h3 className="text-lg font-semibold">{t("notifications.preferences")}</h3>
        {(() => {
          const prefColumns = (
            ["in_app_enabled", "push_enabled", "email_enabled"] as const
          ).filter((field) => field !== "push_enabled" || telegramEnabled);
          const visibleTypes = new Set(visiblePrefs.map((p) => p.notification_type));
          return (
            <div className="text-sm" style={{ display: "grid", gridTemplateColumns: `1fr repeat(${prefColumns.length}, 4.5rem)` }}>
              {/* header — column labels with select-all checkboxes */}
              <div className="py-1 border-b dark:border-gray-600" />
              {prefColumns.map((field) => {
            const allOn = visiblePrefs.length > 0 && visiblePrefs.every((p) => p[field]);
            const someOn = visiblePrefs.some((p) => p[field]);
            return (
              <label key={field} className="py-1 border-b dark:border-gray-600 flex flex-col items-center gap-1 cursor-pointer select-none font-medium">
                <input
                  type="checkbox"
                  checked={allOn}
                  ref={(el) => { if (el) el.indeterminate = someOn && !allOn; }}
                  onChange={() => handleToggleAll(field, visibleTypes)}
                />
                <span className="text-xs text-center leading-tight">
                  {field === "in_app_enabled" ? t("notifications.in_app") : field === "push_enabled" ? t("notifications.push") : t("notifications.email")}
                </span>
              </label>
            );
          })}
          {/* preference rows */}
          {visiblePrefs.map((p) => (
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

      {isCommanderLike && user?.id && (
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3" dir="rtl">
          <DeputiesPanel
            principalId={user.id}
            principalRoles={{ isCommander: !!user?.is_commander, isDutyManager: !!user?.is_duty_manager }}
          />
        </section>
      )}

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
      <MessageDialog open={message !== null} title={t("common.error", "שגיאה")} message={message ?? ""} onClose={() => setMessage(null)} />
    </Layout>
  );
}
