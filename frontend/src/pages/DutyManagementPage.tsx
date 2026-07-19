import { FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import Combobox from "../components/Combobox";
import ExplanationModal from "../components/ExplanationModal";
import { Assignment, cancelAssignment, listAssignments, setOverride } from "../api/assignments";
import { createAdjustment } from "../api/scoreAdjustments";
import { listSoldiers } from "../api/soldiers";
import { getDraftsPreview, resetDrafts, resetPublished } from "../api/algorithm";
import { lastDutyDay } from "../utils/formatDate";

export function DutyManagementContent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [soldierId, setSoldierId] = useState("");
  const [adjDelta, setAdjDelta] = useState("");
  const [adjReason, setAdjReason] = useState("");

  const [explanationId, setExplanationId] = useState<string | null>(null);

  // Bulk cancel state
  const [draftsExpanded, setDraftsExpanded] = useState(false);
  const [cancelDraftsLoading, setCancelDraftsLoading] = useState(false);
  const [cancelDraftsMsg, setCancelDraftsMsg] = useState<string | null>(null);
  const [cancelPublishedLoading, setCancelPublishedLoading] = useState(false);
  const [cancelPublishedMsg, setCancelPublishedMsg] = useState<string | null>(null);
  const draftsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const publishedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const soldiersQuery = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const soldiers = soldiersQuery.data ?? [];

  useEffect(() => {
    if (!soldierId && soldiersQuery.data?.[0]) setSoldierId(soldiersQuery.data[0].id);
  }, [soldiersQuery.data, soldierId]);

  const assignmentsQuery = useQuery({
    queryKey: queryKeys.assignments(soldierId),
    queryFn: () => listAssignments(soldierId),
    enabled: !!soldierId,
  });
  const rows: Assignment[] = assignmentsQuery.data ?? [];

  // DM-only endpoint — non-managers get a 403; treat that the same as "no drafts" without surfacing an error.
  const draftsQuery = useQuery({
    queryKey: queryKeys.draftsPreview(),
    queryFn: getDraftsPreview,
    retry: false,
  });
  const draftCount = draftsQuery.data?.count ?? 0;
  const draftItems = draftsQuery.data?.items ?? [];

  useEffect(() => {
    return () => {
      if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
      if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    };
  }, []);

  async function doCancel(id: string) {
    const reason = window.prompt(t("duty_management.cancel_reason"));
    if (!reason) return;
    await cancelAssignment(id, reason);
    await queryClient.invalidateQueries({ queryKey: queryKeys.assignments(soldierId) });
  }

  async function doOverride(id: string) {
    const day = window.prompt(t("duty_management.override_day"));
    if (!day) return;
    const repl = window.prompt(t("duty_management.replacement"));
    await setOverride(id, day, { effective_soldier_id: repl || null, reason: repl ? "replacement" : "cancelled" });
    await queryClient.invalidateQueries({ queryKey: queryKeys.assignments(soldierId) });
  }

  async function submitAdj(e: FormEvent) {
    e.preventDefault();
    await createAdjustment({ soldier_id: soldierId, delta: adjDelta, reason: adjReason });
    setAdjDelta(""); setAdjReason("");
  }

  async function handleCancelDrafts() {
    if (!window.confirm(t("duty_management.cancel_drafts_confirm", { count: draftCount }))) return;
    setCancelDraftsLoading(true);
    setCancelDraftsMsg(null);
    if (draftsTimerRef.current) clearTimeout(draftsTimerRef.current);
    try {
      const result = await resetDrafts(0);
      const msg = result.rejected === 0
        ? t("duty_management.cancel_drafts_none")
        : t("duty_management.cancel_drafts_result", { count: result.rejected });
      setCancelDraftsMsg(msg);
      draftsTimerRef.current = setTimeout(() => setCancelDraftsMsg(null), 5000);
      await queryClient.invalidateQueries({ queryKey: queryKeys.draftsPreview() });
      setDraftsExpanded(false);
    } catch {
      setCancelDraftsMsg(t("errors.generic"));
      draftsTimerRef.current = setTimeout(() => setCancelDraftsMsg(null), 5000);
    } finally {
      setCancelDraftsLoading(false);
    }
  }

  async function handleCancelPublished() {
    if (!window.confirm(t("duty_management.cancel_published_confirm"))) return;
    setCancelPublishedLoading(true);
    setCancelPublishedMsg(null);
    if (publishedTimerRef.current) clearTimeout(publishedTimerRef.current);
    try {
      const result = await resetPublished(0);
      const msg = result.cancelled === 0
        ? t("duty_management.cancel_published_none")
        : t("duty_management.cancel_published_result", { count: result.cancelled });
      setCancelPublishedMsg(msg);
      publishedTimerRef.current = setTimeout(() => setCancelPublishedMsg(null), 5000);
      await queryClient.invalidateQueries({ queryKey: queryKeys.draftsPreview() });
    } catch {
      setCancelPublishedMsg(t("errors.generic"));
      publishedTimerRef.current = setTimeout(() => setCancelPublishedMsg(null), 5000);
    } finally {
      setCancelPublishedLoading(false);
    }
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6" data-testid="duty-management-page">
      <h2 className="text-xl font-semibold">{t("duty_management.title")}</h2>

      <div className="block text-sm">
        <span className="block mb-0.5">{t("duty_management.soldier")}</span>
        <Combobox
          items={soldiers.map(s => ({ id: s.id, name: s.full_name }))}
          value={soldierId}
          onChange={setSoldierId}
          testId="dm-soldier"
        />
      </div>

      <ul className="text-sm space-y-1" data-testid="assignment-list">
        {rows.length === 0 && <li data-testid="dm-empty">{t("duty_management.none")}</li>}
        {rows.map((a) => (
          <li key={a.id} data-testid={`assignment-row-${a.id}`} className="flex items-center gap-2">
            <span dir="ltr">{a.start_date} → {lastDutyDay(a.end_date)}</span>
            <button className="text-xs text-indigo-600 dark:text-indigo-300" onClick={() => doOverride(a.id)} data-testid={`override-${a.id}`}>{t("duty_management.override")}</button>
            <button className="text-xs text-red-600" onClick={() => doCancel(a.id)} data-testid={`cancel-${a.id}`}>{t("duty_management.cancel")}</button>
            <button
              className="text-gray-400 hover:text-indigo-600 text-xs font-bold border border-gray-300 dark:border-gray-600 rounded-full w-5 h-5 inline-flex items-center justify-center"
              onClick={() => setExplanationId(a.id)}
              title="למה קיבל חייל זה תורנות זו?"
            >
              ?
            </button>
          </li>
        ))}
      </ul>

      <form onSubmit={submitAdj} className="flex items-end gap-2 border-t dark:border-gray-600 pt-4" data-testid="adjustment-form">
        <h3 className="font-medium">{t("duty_management.score_adjustment")}</h3>
        <input className="border rounded p-1 w-24 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} placeholder={t("duty_management.delta")} required data-testid="adj-delta" />
        <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder={t("duty_management.reason")} required data-testid="adj-reason" />
        <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="adj-submit">{t("duty_management.apply")}</button>
      </form>

      <div className="border-t dark:border-gray-600 pt-4 space-y-4" dir="rtl">
        <h3 className="font-medium text-sm text-gray-700 dark:text-gray-300">
          {t("duty_management.bulk_cancel_section_title")}
        </h3>

        {/* Drafts row */}
        <div className="space-y-2">
          <div className="flex items-center gap-3 flex-wrap text-sm">
            <span className="text-gray-700 dark:text-gray-300">
              {t("duty_management.drafts_from_today_label")}
            </span>
            <button
              type="button"
              onClick={() => setDraftsExpanded(v => !v)}
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                draftCount > 0
                  ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-200 dark:hover:bg-amber-800"
                  : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
              }`}
            >
              {draftCount > 0
                ? t("duty_management.drafts_badge", { count: draftCount })
                : t("duty_management.drafts_badge_none")}
              {draftCount > 0 ? ` ${draftsExpanded ? t("duty_management.drafts_toggle_hide") : t("duty_management.drafts_toggle_show")}` : ""}
            </button>
            <button
              type="button"
              onClick={handleCancelDrafts}
              disabled={cancelDraftsLoading || draftCount === 0}
              className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-40"
            >
              {t("duty_management.cancel_drafts_btn")}
            </button>
            {cancelDraftsMsg && (
              <span className="text-xs text-gray-600 dark:text-gray-400">{cancelDraftsMsg}</span>
            )}
          </div>
          {draftsExpanded && draftItems.length > 0 && (
            <ul className="text-xs space-y-0.5 pr-2 max-h-40 overflow-y-auto border rounded dark:border-gray-600 p-2">
              {draftItems.map(item => (
                <li key={item.assignment_id} className="text-gray-700 dark:text-gray-300">
                  {item.soldier_name} · {item.duty_type_name} · {item.start_date}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Published row */}
        <div className="flex items-center gap-3 flex-wrap text-sm">
          <span className="text-gray-700 dark:text-gray-300">
            {t("duty_management.published_from_today_label")}
          </span>
          <button
            type="button"
            onClick={handleCancelPublished}
            disabled={cancelPublishedLoading}
            className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-40"
          >
            {t("duty_management.cancel_published_btn")}
          </button>
          {cancelPublishedMsg && (
            <span className="text-xs text-gray-600 dark:text-gray-400">{cancelPublishedMsg}</span>
          )}
        </div>
      </div>
      {explanationId && (
        <ExplanationModal assignmentId={explanationId} onClose={() => setExplanationId(null)} />
      )}
    </section>
  );
}

export default function DutyManagementPage() {
  return <Layout><DutyManagementContent /></Layout>;
}
