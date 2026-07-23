import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useTranslation } from "react-i18next";
import { AlgorithmJob, ProposalRow, acceptProposal, bulkAcceptProposals, bulkRejectProposals, rejectProposal } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import Combobox from "./Combobox";
import { DataTable, type ColDef } from "./DataTable";
import ExplanationModal from "./ExplanationModal";
import SoldierLink from "./SoldierLink";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
  isDraft: boolean;
}

export default function AlgorithmProposalTable({ job, jobId, soldiers, dutyTypes, onProposalUpdate, isDraft }: Props) {
  const { t } = useTranslation();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [explanationTarget, setExplanationTarget] = useState<{ jobId: string; assignmentId: string } | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectError, setRejectError] = useState<string | null>(null);

  function apiErrorMsg(e: unknown): string {
    if (axios.isAxiosError(e)) {
      const detail = e.response?.data?.detail;
      const status = e.response?.status;
      if (Array.isArray(detail)) {
        // Pydantic v2 validation errors — list of {loc, msg, type}. The msg
        // itself is English framework text, so we don't surface it — just the field.
        const fields = (detail as { loc?: string[] }[])
          .map(d => d.loc?.slice(1).join(".") ?? "?")
          .join(", ");
        return `שגיאה ${status}: נתונים לא תקינים בשדות: ${fields}`;
      }
      if (detail) return `שגיאה ${status ?? ""}: ${detail}`;
      return `שגיאה HTTP ${status ?? ""}`;
    }
    return t("errors.generic");
  }

  const soldierName = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id.slice(0, 8);
  const soldierLink = (id: string): React.ReactNode => {
    const s = soldiers.find(s => s.id === id);
    if (!s) return id.slice(0, 8);
    return <SoldierLink id={s.id} name={s.full_name} />;
  };
  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);

  function isPending(p: ProposalRow) {
    return p.status !== "published" && p.status !== "algorithm_rejected";
  }

  function toggleSelection(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleAccept(proposal: ProposalRow) {
    try {
      await acceptProposal(jobId, proposal.assignment_id);
      onProposalUpdate({
        ...job,
        proposals: job.proposals.map(p =>
          p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
        ),
      });
    } catch (e) {
      setApproveError(apiErrorMsg(e));
    }
  }

  async function handleReject(proposal: ProposalRow) {
    await rejectProposal(jobId, proposal.assignment_id);
    onProposalUpdate({
      ...job,
      proposals: job.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "algorithm_rejected" } : p
      ),
    });
  }

  async function handleApproveSelected() {
    // If nothing explicitly selected, publish all pending proposals
    const toApprove = selectedIds.size > 0
      ? job.proposals.filter(p => selectedIds.has(p.assignment_id) && isPending(p))
      : pendingProposals;
    if (toApprove.length === 0) return;
    setApproving(true);
    setApproveError(null);
    try {
      await bulkAcceptProposals(jobId, toApprove.map(p => p.assignment_id));
      const approvedIds = new Set(toApprove.map(p => p.assignment_id));
      onProposalUpdate({
        ...job,
        proposals: job.proposals.map(p =>
          approvedIds.has(p.assignment_id) && isPending(p) ? { ...p, status: "published" } : p
        ),
      });
      setSelectedIds(new Set());
    } catch (e) {
      setApproveError(apiErrorMsg(e));
    } finally {
      setApproving(false);
    }
  }

  async function handleRejectSelected() {
    const toReject = selectedIds.size > 0
      ? job.proposals.filter(p => selectedIds.has(p.assignment_id) && isPending(p))
      : pendingProposals;
    if (toReject.length === 0) return;
    const count = toReject.length;
    if (!window.confirm(`בטל ${count} טיוטות?`)) return;
    setRejecting(true);
    setRejectError(null);
    try {
      await bulkRejectProposals(jobId, toReject.map(p => p.assignment_id));
      const rejectedIds = new Set(toReject.map(p => p.assignment_id));
      onProposalUpdate({
        ...job,
        proposals: job.proposals.map(p =>
          rejectedIds.has(p.assignment_id) && isPending(p) ? { ...p, status: "algorithm_rejected" } : p
        ),
      });
      setSelectedIds(new Set());
    } catch (e) {
      setRejectError(apiErrorMsg(e));
    } finally {
      setRejecting(false);
    }
  }

  const batchRankMap = useMemo(() => {
    const sorted = [...job.proposals]
      .filter(p => p.norm_score_before !== null)
      .sort((a, b) => (a.norm_score_before ?? Infinity) - (b.norm_score_before ?? Infinity));
    const map = new Map<string, number>();
    sorted.forEach((p, i) => map.set(p.assignment_id, i + 1));
    return map;
  }, [job.proposals]);

  const hasBatches = job.proposals.some(p => p.batch_index != null);
  const batchIndices = hasBatches
    ? [...new Set(job.proposals.map(p => p.batch_index).filter((b): b is number => b != null))].sort((a, b) => a - b)
    : [];
  const [batchFilter, setBatchFilter] = useState<number | null>(null);

  useEffect(() => {
    setBatchFilter(null);
  }, [jobId]);

  const filteredProposals = batchFilter != null
    ? job.proposals.filter(p => p.batch_index === batchFilter)
    : job.proposals;

  const pendingProposals = filteredProposals.filter(isPending);
  const allPendingSelected = pendingProposals.length > 0 && pendingProposals.every(p => selectedIds.has(p.assignment_id));

  function toggleSelectAll() {
    if (allPendingSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(pendingProposals.map(p => p.assignment_id)));
  }

  const cols: ColDef<ProposalRow>[] = [
    {
      id: "select",
      header: "",
      cell: (p) => {
        const pending = isPending(p);
        return (
          <input
            type="checkbox"
            checked={pending ? selectedIds.has(p.assignment_id) : p.status === "published"}
            disabled={!pending}
            onChange={() => pending && toggleSelection(p.assignment_id)}
            className="cursor-pointer disabled:cursor-default"
          />
        );
      },
    },
    { id: "date", header: t("algorithm.col_date"), cell: (p) => p.start_date, sortValue: (p) => p.start_date },
    { id: "type", header: t("algorithm.col_type"), cell: (p) => typeName(p.duty_type_id), sortValue: (p) => typeName(p.duty_type_id), filterValue: (p) => typeName(p.duty_type_id) },
    { id: "soldier", header: t("algorithm.col_soldier"), cell: (p) => soldierLink(p.soldier_id), sortValue: (p) => soldierName(p.soldier_id), filterValue: (p) => soldierName(p.soldier_id) },
    { id: "reserve", header: t("algorithm.col_reserve"), cell: (p) => p.reserve_soldier_id ? soldierLink(p.reserve_soldier_id) : "—" },
    { id: "score_before", header: t("algorithm.col_score_before"), cell: (p) => p.norm_score_before?.toFixed(3) ?? "—", sortValue: (p) => p.norm_score_before ?? null },
    { id: "score_after", header: t("algorithm.col_score_after"), cell: (p) => p.norm_score_after?.toFixed(3) ?? "—", sortValue: (p) => p.norm_score_after ?? null },
    { id: "batch_rank", header: t("algorithm.col_batch_rank"), cell: (p) => batchRankMap.get(p.assignment_id)?.toString() ?? "—", sortValue: (p) => batchRankMap.get(p.assignment_id) ?? null },
    ...(hasBatches ? [{
      id: "batch",
      header: "קבוצה",
      cell: (p: ProposalRow) => p.batch_index != null
        ? <span className="px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 text-xs font-mono">B{(p.batch_index ?? 0) + 1}</span>
        : <span className="text-gray-400">—</span>,
    }] as ColDef<ProposalRow>[] : []),
    {
      id: "slot_rank",
      header: t("algorithm.col_slot_rank"),
      cell: (p) => p.candidate_rank != null && p.candidate_pool_size ? `${p.candidate_rank} / ${p.candidate_pool_size}` : "—",
      sortValue: (p) => p.candidate_rank ?? null,
    },
    {
      id: "actions",
      header: t("algorithm.col_actions"),
      cell: (p) => {
        const isAccepted = p.status === "published";
        const isRejected = p.status === "algorithm_rejected";
        return (
          <span className="space-x-1 space-x-reverse">
            {!isAccepted && !isRejected && (
              <>
                <button type="button" onClick={() => handleAccept(p)} className="text-green-700 font-bold hover:underline">{t("algorithm.accept")}</button>{" "}
                <button type="button" onClick={() => handleReject(p)} className="text-red-700 hover:underline">{t("algorithm.reject")}</button>{" "}
              </>
            )}
            <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 dark:text-blue-400 hover:underline">
              {t("algorithm.why_button")}
            </button>
          </span>
        );
      },
    },
  ];

  const hasUnfilledShifts = (job.batch_results ?? []).some(br => br.unassigned_count > 0);
  const hasBatchIssues = (job.batch_results ?? []).some(br => br.outcome === "INFEASIBLE");
  const publishedWithIssues = !isDraft && (hasUnfilledShifts || hasBatchIssues);

  return (
    <div className="space-y-3" dir="rtl">
      {isDraft ? (
        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-700 rounded p-3 text-sm text-amber-700 dark:text-amber-300 font-medium">
          {"⚠️ טיוטה — תוצאות לא פורסמו. לחץ \"אשר ופרסם (הפוך לרשמי)\" להחלת השיבוצים."}
        </div>
      ) : publishedWithIssues ? (
        <div className="bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-700 rounded p-3 text-sm text-amber-700 dark:text-amber-300 font-medium">
          ⚠ פורסם — אך חלק מהמשמרות לא אוישו במלואן. ראה לשונית <strong>בעיות</strong> לפרטים.
        </div>
      ) : (
        <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-700 rounded p-3 text-sm text-green-700 dark:text-green-300 font-medium">
          ✓ פורסם — כל השיבוצים פעילים.
        </div>
      )}
      {job.proposals.length === 0 ? (
        <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
      ) : (
        <>
          <div className="flex items-center gap-3 text-sm flex-wrap">
            {hasBatches && (
              <div className="w-40">
                <Combobox
                  items={batchIndices.map(bi => ({ id: String(bi), name: `קבוצה ${bi + 1}` }))}
                  value={batchFilter === null ? "" : String(batchFilter)}
                  onChange={id => setBatchFilter(id === "" ? null : Number(id))}
                  placeholder="כל הקבוצות"
                />
              </div>
            )}
            <button type="button" onClick={toggleSelectAll} className="text-blue-600 dark:text-blue-400 hover:underline">
              {allPendingSelected ? "בטל בחירה הכל" : "בחר הכל"}
            </button>
            <button
              type="button"
              onClick={handleApproveSelected}
              disabled={pendingProposals.length === 0 || approving}
              className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700 disabled:opacity-40 flex items-center gap-1.5"
            >
              {approving && (
                <svg className="animate-spin h-3 w-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              )}
              {(() => {
                const count = selectedIds.size > 0 ? selectedIds.size : pendingProposals.length;
                return approving ? `מפרסם... (${count})` : `אשר ופרסם (הפוך לרשמי) (${count})`;
              })()}
            </button>
            <button
              type="button"
              onClick={handleRejectSelected}
              disabled={pendingProposals.length === 0 || rejecting}
              className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-40 flex items-center gap-1.5"
            >
              {rejecting && (
                <svg className="animate-spin h-3 w-3 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                </svg>
              )}
              {(() => {
                const count = selectedIds.size > 0 ? selectedIds.size : pendingProposals.length;
                return rejecting ? `מבטל... (${count})` : `בטל טיוטות (${count})`;
              })()}
            </button>
            {approveError && (
              <span className="text-xs text-red-600 dark:text-red-400">{approveError}</span>
            )}
            {rejectError && (
              <span className="text-xs text-red-600 dark:text-red-400">{rejectError}</span>
            )}
          </div>
          <DataTable
            columns={cols}
            data={filteredProposals}
            filterPlaceholder={t("table.filter_placeholder")}
            rowClassName={(p) =>
              p.status === "published" ? "bg-green-50 dark:bg-green-950" : p.status === "algorithm_rejected" ? "bg-gray-100 dark:bg-gray-700 opacity-50" : ""
            }
          />
        </>
      )}

      {explanationTarget && (
        <ExplanationModal
          jobId={explanationTarget.jobId}
          assignmentId={explanationTarget.assignmentId}
          onClose={() => setExplanationTarget(null)}
        />
      )}
    </div>
  );
}
