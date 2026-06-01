import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlgorithmJob,
  ProposalRow,
  SolverSettings,
  acceptProposal,
  pollJob,
  rejectProposal,
  submitJob,
} from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import ExplanationModal from "./ExplanationModal";
import SubHierarchySelector from "./SubHierarchySelector";
import { DataTable, type ColDef } from "./DataTable";

interface Props {
  dutyTypes: DutyType[];
  soldiers: SoldierDTO[];
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 7, W: 14, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

const FILL_COLORS: Record<string, string> = {
  empty: "text-red-600",
  partial: "text-amber-600",
  full: "text-green-600",
};

export default function AlgorithmPlanningWindow({ dutyTypes, soldiers }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<AlgorithmJob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [explanationTarget, setExplanationTarget] = useState<{
    jobId: string;
    assignmentId: string;
  } | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  const loadShifts = useCallback(async () => {
    if (!open) return;
    const ss = await listShifts({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
    setAvailableShifts(ss.filter(s => s.fill_status !== "full"));
  }, [open, dateFrom, dateTo]);

  useEffect(() => {
    void loadShifts();
  }, [loadShifts]);

  useEffect(() => {
    if (!jobId) return;
    startTimeRef.current = Date.now();
    pollRef.current = setInterval(async () => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
      try {
        const j = await pollJob(jobId);
        setJob(j);
        if (j.status === "done" || j.status === "failed") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
        }
      } catch {
        clearInterval(pollRef.current!);
      }
    }, 1000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId]);

  function toggleShift(id: string) {
    setSelectedShiftIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function handleRun() {
    setError(null);
    setJob(null);
    setJobId(null);
    setSelectedIds(new Set());
    if (selectedShiftIds.length === 0) {
      setError("נא לבחור לפחות משמרת אחת");
      return;
    }
    try {
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode, settings });
      setJobId(resp.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    }
  }

  async function handleAccept(proposal: ProposalRow) {
    if (!jobId) return;
    await acceptProposal(jobId, proposal.assignment_id);
    setJob(prev => prev ? {
      ...prev,
      proposals: prev.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
      ),
    } : prev);
  }

  async function handleReject(proposal: ProposalRow) {
    if (!jobId) return;
    await rejectProposal(jobId, proposal.assignment_id);
    setJob(prev => prev ? {
      ...prev,
      proposals: prev.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "algorithm_rejected" } : p
      ),
    } : prev);
  }

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

  async function handleApproveSelected() {
    const toApprove = job?.proposals.filter(p => selectedIds.has(p.assignment_id) && isPending(p)) ?? [];
    await Promise.all(toApprove.map(p => handleAccept(p)));
    setSelectedIds(new Set());
  }

  const soldierName = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id.slice(0, 8);
  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (${shift.assigned_count}/${shift.required_count})`;

  const isRunning = !!jobId && (job === null || job.status === "pending" || job.status === "running");

  const batchRankMap = useMemo(() => {
    if (!job?.proposals) return new Map<string, number>();
    const sorted = [...job.proposals]
      .filter((p) => p.norm_score_before !== null)
      .sort((a, b) => (a.norm_score_before ?? Infinity) - (b.norm_score_before ?? Infinity));
    const map = new Map<string, number>();
    sorted.forEach((p, i) => map.set(p.assignment_id, i + 1));
    return map;
  }, [job?.proposals]);

  return (
    <div className="border rounded-lg mt-6" dir="rtl">
      <button
        className="w-full flex justify-between items-center px-4 py-3 font-medium text-right bg-gray-50 rounded-lg hover:bg-gray-100"
        onClick={() => setOpen(o => {
          if (o) {
            setSelectedShiftIds([]);
            setAvailableShifts([]);
          }
          return !o;
        })}
      >
        <span>{t("algorithm.title")}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="p-4 space-y-4">
          {/* Date filter for shifts */}
          <div className="grid grid-cols-2 gap-4">
            <label className="block text-sm">
              {t("shifts.filter_from")}
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
            </label>
            <label className="block text-sm">
              {t("shifts.filter_to")}
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
            </label>
          </div>

          {/* Shift selector */}
          {availableShifts.length > 0 && (
            <div className="text-sm">
              <div className="flex items-center gap-3 mb-1">
                <p className="font-medium">בחר משמרות להרצה</p>
                <button type="button" onClick={() => setSelectedShiftIds(availableShifts.map(s => s.id))} className="text-xs text-blue-600 hover:underline">בחר הכל</button>
                <button type="button" onClick={() => setSelectedShiftIds([])} className="text-xs text-blue-600 hover:underline">בטל בחירה</button>
              </div>
              <div className="space-y-1 max-h-40 overflow-y-auto border rounded p-2">
                {availableShifts.map(shift => (
                  <label key={shift.id} className="flex items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      checked={selectedShiftIds.includes(shift.id)}
                      onChange={() => toggleShift(shift.id)}
                    />
                    <span className={FILL_COLORS[shift.fill_status]}>
                      {shiftLabel(shift)}
                    </span>
                  </label>
                ))}
              </div>
            </div>
          )}
          {availableShifts.length === 0 && (
            <p className="text-sm text-gray-400">
              {dateFrom || dateTo ? "אין משמרות פתוחות בטווח הנבחר" : "הזן טווח תאריכים לצפייה במשמרות"}
            </p>
          )}

          {/* Mode */}
          <label className="block text-sm">
            {t("algorithm.mode_label")}
            <select value={mode} onChange={e => setMode(e.target.value as "shadow" | "dm_reviewed")} className="mt-1 block w-full border rounded p-1 text-sm">
              <option value="shadow">{t("algorithm.shadow_mode")}</option>
              <option value="dm_reviewed">{t("algorithm.dm_reviewed_mode")}</option>
            </select>
          </label>

          {/* Advanced settings */}
          <button type="button" className="text-xs text-blue-600 underline" onClick={() => setShowSettings(s => !s)}>
            {t("algorithm.settings")}
          </button>
          {showSettings && (
            <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 p-3 rounded">
              {(["K", "T", "W", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
                <label key={key} className="block">
                  {key}
                  <input
                    type="number"
                    value={settings[key]}
                    onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                    className="mt-1 block w-full border rounded p-1"
                    step={key === "alpha" || key === "beta" ? 0.1 : 1}
                  />
                </label>
              ))}
            </div>
          )}

          <details className="border rounded p-2 mt-2">
            <summary className="text-sm font-medium cursor-pointer">{t("algorithm.restrict_to_subtree")}</summary>
            <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
          </details>

          {error && <p className="text-red-500 text-sm">{error}</p>}

          <button
            onClick={handleRun}
            disabled={isRunning || selectedShiftIds.length === 0}
            type="button"
            className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50"
          >
            {t("algorithm.run_button")} {selectedShiftIds.length > 0 && `(${selectedShiftIds.length} משמרות)`}
          </button>

          {isRunning && (
            <p className="text-sm text-gray-600 animate-pulse">{t("algorithm.running")} ({elapsed}s)</p>
          )}

          {job?.status === "failed" && (() => {
            let parsed: { relaxed?: string[]; reasons?: string[]; status?: string } | null = null;
            try { parsed = JSON.parse(job.error_message ?? "{}"); } catch { /* plain string error */ }
            const reasons = parsed?.reasons ?? [];
            return (
              <div className="text-red-600 text-sm space-y-1">
                <p className="font-medium">{t("algorithm.failed")}</p>
                {reasons.length > 0 && (
                  <ul className="list-disc pr-5 space-y-0.5 text-xs">
                    {reasons.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                )}
                {reasons.length === 0 && job.error_message && (
                  <p className="text-xs">{job.error_message}</p>
                )}
                {job.relaxed.length > 0 && (
                  <p className="text-xs text-red-400">{t("algorithm.relaxed_attempts")}: {job.relaxed.join(", ")}</p>
                )}
              </div>
            );
          })()}

          {job?.status === "done" && (
            <div>
              <p className="font-medium text-sm mb-2">{t("algorithm.done")}</p>
              {job.proposals.length === 0 ? (
                <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
              ) : (() => {
                const pendingProposals = job.proposals.filter(isPending);
                const allPendingSelected =
                  pendingProposals.length > 0 &&
                  pendingProposals.every(p => selectedIds.has(p.assignment_id));

                function toggleSelectAll() {
                  if (allPendingSelected) {
                    setSelectedIds(new Set());
                  } else {
                    setSelectedIds(new Set(pendingProposals.map(p => p.assignment_id)));
                  }
                }

                const proposalCols: ColDef<ProposalRow>[] = [
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
                  {
                    id: "date",
                    header: t("algorithm.col_date"),
                    cell: (p) => p.start_date,
                    sortValue: (p) => p.start_date,
                  },
                  {
                    id: "type",
                    header: t("algorithm.col_type"),
                    cell: (p) => typeName(p.duty_type_id),
                    sortValue: (p) => typeName(p.duty_type_id),
                    filterValue: (p) => typeName(p.duty_type_id),
                  },
                  {
                    id: "soldier",
                    header: t("algorithm.col_soldier"),
                    cell: (p) => soldierName(p.soldier_id),
                    sortValue: (p) => soldierName(p.soldier_id),
                    filterValue: (p) => soldierName(p.soldier_id),
                  },
                  {
                    id: "reserve",
                    header: t("algorithm.col_reserve"),
                    cell: (p) => p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—",
                  },
                  {
                    id: "score_before",
                    header: t("algorithm.col_score_before"),
                    cell: (p) => p.norm_score_before?.toFixed(3) ?? "—",
                    sortValue: (p) => p.norm_score_before ?? null,
                  },
                  {
                    id: "score_after",
                    header: t("algorithm.col_score_after"),
                    cell: (p) => p.norm_score_after?.toFixed(3) ?? "—",
                    sortValue: (p) => p.norm_score_after ?? null,
                  },
                  {
                    id: "batch_rank",
                    header: t("algorithm.col_batch_rank"),
                    cell: (p) => batchRankMap.get(p.assignment_id)?.toString() ?? "—",
                    sortValue: (p) => batchRankMap.get(p.assignment_id) ?? null,
                  },
                  {
                    id: "slot_rank",
                    header: t("algorithm.col_slot_rank"),
                    cell: (p) =>
                      p.candidate_rank !== null && p.candidate_rank !== undefined && p.candidate_pool_size
                        ? `${p.candidate_rank} / ${p.candidate_pool_size}`
                        : "—",
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
                          {jobId && (
                            <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 hover:underline">
                              {t("algorithm.why_button")}
                            </button>
                          )}
                        </span>
                      );
                    },
                  },
                ];
                return (
                  <div className="space-y-2">
                    <div className="flex items-center gap-3 text-sm">
                      <button
                        type="button"
                        onClick={toggleSelectAll}
                        className="text-blue-600 hover:underline"
                      >
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
                    columns={proposalCols}
                    data={job.proposals}
                    filterPlaceholder={t("table.filter_placeholder")}
                    rowClassName={(p) =>
                      p.status === "published" ? "bg-green-50" : p.status === "algorithm_rejected" ? "bg-gray-100 opacity-50" : ""
                    }
                  />
                  </div>
                );
              })()}
            </div>
          )}
        </div>
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
