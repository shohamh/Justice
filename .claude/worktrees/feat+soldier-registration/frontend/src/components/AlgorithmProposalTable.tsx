import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlgorithmJob, ProposalRow, acceptProposal, rejectProposal, resetDrafts, resetPublished } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import { DataTable, type ColDef } from "./DataTable";
import ExplanationModal from "./ExplanationModal";
import SoldierLink from "./SoldierLink";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
}

export default function AlgorithmProposalTable({ job, jobId, soldiers, dutyTypes, onProposalUpdate }: Props) {
  const { t } = useTranslation();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [explanationTarget, setExplanationTarget] = useState<{ jobId: string; assignmentId: string } | null>(null);
  const [resetPublishedDays, setResetPublishedDays] = useState(30);
  const [resetDraftsDays, setResetDraftsDays] = useState(30);
  const [resetPublishedMsg, setResetPublishedMsg] = useState<string | null>(null);
  const [resetDraftsMsg, setResetDraftsMsg] = useState<string | null>(null);
  const [resetPublishedLoading, setResetPublishedLoading] = useState(false);
  const [resetDraftsLoading, setResetDraftsLoading] = useState(false);

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
    await acceptProposal(jobId, proposal.assignment_id);
    onProposalUpdate({
      ...job,
      proposals: job.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
      ),
    });
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
    const toApprove = job.proposals.filter(p => selectedIds.has(p.assignment_id) && isPending(p));
    await Promise.all(toApprove.map(p => handleAccept(p)));
    setSelectedIds(new Set());
  }

  async function handleResetPublished() {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() + resetPublishedDays);
    const dateStr = cutoff.toISOString().slice(0, 10);
    if (!window.confirm(t("algorithm.reset_confirm_published", { date: dateStr }))) return;
    setResetPublishedLoading(true);
    setResetPublishedMsg(null);
    try {
      const result = await resetPublished(resetPublishedDays);
      setResetPublishedMsg(
        result.cancelled === 0 ? t("algorithm.reset_none") : t("algorithm.reset_result_cancelled", { count: result.cancelled })
      );
    } catch {
      setResetPublishedMsg(t("errors.generic"));
    } finally {
      setResetPublishedLoading(false);
    }
  }

  async function handleResetDrafts() {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() + resetDraftsDays);
    const dateStr = cutoff.toISOString().slice(0, 10);
    if (!window.confirm(t("algorithm.reset_confirm_drafts", { date: dateStr }))) return;
    setResetDraftsLoading(true);
    setResetDraftsMsg(null);
    try {
      const result = await resetDrafts(resetDraftsDays);
      setResetDraftsMsg(
        result.rejected === 0 ? t("algorithm.reset_none") : t("algorithm.reset_result_rejected", { count: result.rejected })
      );
    } catch {
      setResetDraftsMsg(t("errors.generic"));
    } finally {
      setResetDraftsLoading(false);
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

  const pendingProposals = job.proposals.filter(isPending);
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
            <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 hover:underline">
              {t("algorithm.why_button")}
            </button>
          </span>
        );
      },
    },
  ];

  return (
    <div className="space-y-3" dir="rtl">
      {job.proposals.length === 0 ? (
        <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
      ) : (
        <>
          <div className="flex items-center gap-3 text-sm">
            <button type="button" onClick={toggleSelectAll} className="text-blue-600 hover:underline">
              {allPendingSelected ? "בטל בחירה הכל" : "בחר הכל"}
            </button>
            <button
              type="button"
              onClick={handleApproveSelected}
              disabled={selectedIds.size === 0}
              className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700 disabled:opacity-40"
            >
              {`אשר נבחרים (${selectedIds.size})`}
            </button>
          </div>
          <DataTable
            columns={cols}
            data={job.proposals}
            filterPlaceholder={t("table.filter_placeholder")}
            rowClassName={(p) =>
              p.status === "published" ? "bg-green-50" : p.status === "algorithm_rejected" ? "bg-gray-100 opacity-50" : ""
            }
          />
        </>
      )}

      <div className="border-t pt-3 space-y-3">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-gray-700">{t("algorithm.reset_published_label")}</span>
          <input type="number" min={1} value={resetPublishedDays} onChange={e => setResetPublishedDays(Math.max(1, parseInt(e.target.value) || 1))} className="w-16 border rounded p-1 text-sm text-center" />
          <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
          <button type="button" onClick={handleResetPublished} disabled={resetPublishedLoading} className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-50">
            {t("algorithm.reset_published_btn")}
          </button>
          {resetPublishedMsg && <span className="text-xs text-gray-600">{resetPublishedMsg}</span>}
        </div>
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-gray-700">{t("algorithm.reset_drafts_label")}</span>
          <input type="number" min={1} value={resetDraftsDays} onChange={e => setResetDraftsDays(Math.max(1, parseInt(e.target.value) || 1))} className="w-16 border rounded p-1 text-sm text-center" />
          <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
          <button type="button" onClick={handleResetDrafts} disabled={resetDraftsLoading} className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-50">
            {t("algorithm.reset_drafts_btn")}
          </button>
          {resetDraftsMsg && <span className="text-xs text-gray-600">{resetDraftsMsg}</span>}
        </div>
      </div>

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
