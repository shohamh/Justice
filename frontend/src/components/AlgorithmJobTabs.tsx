import { useEffect, useState } from "react";
import { AlgorithmJob } from "../api/algorithm";
import { api } from "../api/client";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import { DutyShift, listShifts } from "../api/shifts";
import AlgorithmProposalTable from "./AlgorithmProposalTable";
import BatchesTab from "./BatchesTab";
import IssuesTab from "./IssuesTab";
import { lastDutyDay } from "../utils/formatDate";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
  onRerun?: (overrides: Record<string, number>) => void;
  onRetried?: (newJobId: string) => void;
}

type Tab = "proposals" | "batches" | "issues";

export default function AlgorithmJobTabs({ job, jobId, soldiers, dutyTypes, onProposalUpdate, onRerun, onRetried }: Props) {
  const hasAnyUnfilledInit = job.batch_results.some(br => br.unassigned_count > 0);
  const hasInfeasibleInit = job.batch_results.some(br => br.outcome === "INFEASIBLE");
  const hasIssuesInit = hasAnyUnfilledInit || hasInfeasibleInit || job.status === "failed";
  const [tab, setTab] = useState<Tab>(hasIssuesInit ? "issues" : "proposals");
  const [shiftsById, setShiftsById] = useState<Record<string, DutyShift>>({});
  // null = idle, -1 = indeterminate (server processing), 0-100 = download progress
  const [exportProgress, setExportProgress] = useState<number | null>(null);

  async function handleDownload() {
    if (exportProgress !== null) return;
    setExportProgress(-1);
    try {
      const resp = await api.get(`/algorithm/jobs/${jobId}/export-inputs`, {
        responseType: "blob",
        onDownloadProgress: (e) => {
          if (e.total) setExportProgress(Math.round((e.loaded / e.total) * 100));
        },
      });
      setExportProgress(100);
      const url = URL.createObjectURL(resp.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `solver_dump_${jobId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => {
        URL.revokeObjectURL(url);
        setExportProgress(null);
      }, 1000);
    } catch (err) {
      console.error("Export failed:", err);
      setExportProgress(null);
    }
  }

  useEffect(() => {
    listShifts({ date_from: job.planning_start, date_to: job.planning_end })
      .then(shifts => {
        const map: Record<string, DutyShift> = {};
        for (const s of shifts) map[s.id] = s;
        setShiftsById(map);
      })
      .catch(() => {/* silently ignore — names just won't resolve */});
  }, [job.planning_start, job.planning_end]);

  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? "";
  const shiftNames: Record<string, string> = Object.fromEntries(
    Object.values(shiftsById).map(s => [
      s.id,
      `${typeName(s.duty_type_id)} · ${s.start_date}–${lastDutyDay(s.end_date)}`,
    ])
  );

  const hasAnyUnfilled = job.batch_results.some(br => br.unassigned_count > 0);
  const hasInfeasible = job.batch_results.some(br => br.outcome === "INFEASIBLE");
  const hasIssues = hasAnyUnfilled || hasInfeasible || job.status === "failed";

  const totalUnfilled = job.batch_results.reduce((sum, br) => sum + br.unassigned_count, 0);
  const issuesBadge = hasIssues ? (totalUnfilled > 0 ? String(totalUnfilled) : "!") : undefined;

  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: "proposals", label: "הצעות" },
    { id: "batches", label: "קבוצות" },
    { id: "issues", label: "בעיות", badge: issuesBadge },
  ];

  const meta = job.result_metadata;

  const totalDuties = job.batch_results.reduce((s, br) => s + br.duty_count, 0);
  const assignedDuties = job.batch_results.reduce((s, br) => s + br.assigned_count, 0);
  const hasDutyCount = totalDuties > 0;

  const outcomeLabel: Record<string, string> = {
    OPTIMAL: "אופטימלי ✓",
    FEASIBLE: "כדאי (לא מוכח אופטימלי)",
    INFEASIBLE: "לא פתיר",
    CANCELLED: "בוטל",
  };
  const outcomeClass: Record<string, string> = {
    OPTIMAL: "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 border-green-300 dark:border-green-700",
    FEASIBLE: "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 border-yellow-300 dark:border-yellow-700",
    INFEASIBLE: "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200 border-red-300 dark:border-red-700",
    CANCELLED: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 border-gray-300 dark:border-gray-600",
  };

  return (
    <div className="space-y-3">
      {meta?.fairness_before && (
        <div className="space-y-2" dir="rtl">
          {meta.outcome && (
            <div className="flex items-center gap-3 flex-wrap">
              <span className={`inline-flex items-center px-2.5 py-1 rounded border text-xs font-semibold ${outcomeClass[meta.outcome] ?? outcomeClass.FEASIBLE}`}>
                {outcomeLabel[meta.outcome] ?? meta.outcome}
              </span>
              {hasDutyCount && (
                <span className={`text-xs font-medium tabular-nums ${assignedDuties < totalDuties ? "text-red-600 dark:text-red-400" : "text-green-700 dark:text-green-400"}`}>
                  {assignedDuties}/{totalDuties}
                </span>
              )}
              {meta.solver_metrics?.wall_time != null && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  זמן: {meta.solver_metrics.wall_time.toFixed(1)}s
                  {meta.solver_metrics.conflicts != null && ` | conflicts: ${meta.solver_metrics.conflicts}`}
                </span>
              )}
              <button
                onClick={handleDownload}
                disabled={exportProgress !== null}
                className="mr-auto text-xs text-indigo-600 dark:text-indigo-300 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {exportProgress !== null ? "מייצר..." : "⬇ ייצוא קלטי ופלטי solver"}
              </button>
            </div>
          )}
          {exportProgress !== null && (
            <div className="h-1 w-full bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden -mt-1">
              <div
                className={`h-full bg-indigo-500 rounded-full ${exportProgress < 0 ? "w-full animate-pulse" : "transition-all duration-300"}`}
                style={exportProgress >= 0 ? { width: `${exportProgress}%` } : undefined}
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 dark:bg-gray-700 rounded p-3 border border-gray-200 dark:border-gray-600 text-center">
              <p className="text-xs text-gray-500 dark:text-gray-400">CV לפני (count-space)</p>
              <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">
                {meta.fairness_before.cv != null ? (meta.fairness_before.cv * 100).toFixed(1) + "%" : "—"}
              </p>
            </div>
            <div className={`rounded p-3 border text-center ${
              (meta.fairness_after?.cv ?? 1) < 0.25
                ? "bg-green-50 dark:bg-green-950 border-green-300 dark:border-green-700"
                : (meta.fairness_after?.cv ?? 1) < 0.5
                  ? "bg-yellow-50 dark:bg-yellow-950 border-yellow-300 dark:border-yellow-700"
                  : "bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-700"
            }`}>
              <p className="text-xs text-gray-500 dark:text-gray-400">CV אחרי (count-space)</p>
              <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">
                {meta.fairness_after?.cv != null ? (meta.fairness_after.cv * 100).toFixed(1) + "%" : "—"}
              </p>
            </div>
          </div>
          {meta.fairness_after && (
            <p className="text-xs text-gray-500 dark:text-gray-400 text-right">
              count-space: ממוצע {meta.fairness_after.mean} | סטיית תקן {meta.fairness_after.stddev} | טווח {meta.fairness_after.min}–{meta.fairness_after.max}
            </p>
          )}
          {!meta.outcome && job.status === "done" && (
            <div className="space-y-1">
              <div className="flex justify-end">
                <button
                  onClick={handleDownload}
                  disabled={exportProgress !== null}
                  className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {exportProgress !== null ? "מייצר..." : "⬇ ייצוא קלטי ופלטי solver"}
                </button>
              </div>
              {exportProgress !== null && (
                <div className="h-1 w-full bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full bg-indigo-500 rounded-full ${exportProgress < 0 ? "w-full animate-pulse" : "transition-all duration-300"}`}
                    style={exportProgress >= 0 ? { width: `${exportProgress}%` } : undefined}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}
      <div className="flex gap-1 border-b dark:border-gray-600" dir="rtl">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-300"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {t.label}
            {t.badge && (
              <span className="mr-1.5 px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-xs font-bold">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "proposals" && (
        <AlgorithmProposalTable
          job={job}
          jobId={jobId}
          soldiers={soldiers}
          dutyTypes={dutyTypes}
          onProposalUpdate={onProposalUpdate}
          isDraft={job.proposals.some(p => p.status === "algorithm_draft")}
        />
      )}

      {tab === "batches" && (
        <BatchesTab batchResults={job.batch_results} shiftNames={shiftNames} />
      )}

      {tab === "issues" && (
        <IssuesTab
          job={job}
          dutyTypes={dutyTypes}
          shiftNames={shiftNames}
          shiftsById={shiftsById}
          onRerun={onRerun}
          onRetried={onRetried}
        />
      )}
    </div>
  );
}
