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

  return (
    <div className="space-y-3">
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
