import { useState } from "react";
import { AlgorithmJob } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import AlgorithmProposalTable from "./AlgorithmProposalTable";
import BatchesTab from "./BatchesTab";
import IssuesTab from "./IssuesTab";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
  onRerun?: (overrides: Record<string, number>) => void;
}

type Tab = "proposals" | "batches" | "issues";

export default function AlgorithmJobTabs({ job, jobId, soldiers, dutyTypes, onProposalUpdate, onRerun }: Props) {
  const [tab, setTab] = useState<Tab>("proposals");

  const shiftNames: Record<string, string> = {};

  const hasAnyUnfilled = job.batch_results.some(br => br.unassigned_count > 0);
  const hasInfeasible = job.batch_results.some(br => br.outcome === "INFEASIBLE");
  const hasIssues = hasAnyUnfilled || hasInfeasible || job.status === "failed";

  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: "proposals", label: "הצעות" },
    { id: "batches", label: "אצוות" },
    { id: "issues", label: "בעיות", badge: hasIssues ? "!" : undefined },
  ];

  const meta = job.result_metadata;

  return (
    <div className="space-y-3">
      {meta?.fairness_before && (
        <div className="space-y-2" dir="rtl">
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
        </div>
      )}
      <div className="flex gap-1 border-b dark:border-gray-600" dir="rtl">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
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
          onRerun={onRerun}
        />
      )}
    </div>
  );
}
