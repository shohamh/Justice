import { useCallback, useEffect, useRef, useState } from "react";
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
import { DutyType, DutyLocation } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import ExplanationModal from "./ExplanationModal";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
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

export default function AlgorithmPlanningWindow({ dutyTypes, locations: _locations, soldiers }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);

  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<AlgorithmJob | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
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
    }, 3000);
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

  const soldierName = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id.slice(0, 8);
  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (${shift.assigned_count}/${shift.required_count})`;

  const isRunning = !!jobId && (job === null || job.status === "pending" || job.status === "running");

  return (
    <div className="border rounded-lg mt-6" dir="rtl">
      <button
        className="w-full flex justify-between items-center px-4 py-3 font-medium text-right bg-gray-50 rounded-lg hover:bg-gray-100"
        onClick={() => setOpen(o => !o)}
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
              <p className="font-medium mb-1">בחר משמרות להרצה</p>
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

          {job?.status === "failed" && (
            <div className="text-red-600 text-sm space-y-1">
              <p>{t("algorithm.failed")}: {job.error_message}</p>
              {job.relaxed.map((r, i) => <p key={i} className="text-xs">{r}</p>)}
            </div>
          )}

          {job?.status === "done" && (
            <div>
              <p className="font-medium text-sm mb-2">{t("algorithm.done")}</p>
              {job.proposals.length === 0 ? (
                <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
              ) : (
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-gray-50 text-right">
                      <th className="border px-2 py-1">{t("algorithm.col_date")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_type")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_soldier")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_reserve")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_score_before")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_score_after")}</th>
                      <th className="border px-2 py-1">{t("algorithm.col_actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {job.proposals.map(p => {
                      const isAccepted = p.status === "published";
                      const isRejected = p.status === "algorithm_rejected";
                      return (
                        <tr
                          key={p.assignment_id}
                          className={isAccepted ? "bg-green-50" : isRejected ? "bg-gray-100 opacity-50" : ""}
                        >
                          <td className="border px-2 py-1">{p.start_date}</td>
                          <td className="border px-2 py-1">{typeName(p.duty_type_id)}</td>
                          <td className="border px-2 py-1">{soldierName(p.soldier_id)}</td>
                          <td className="border px-2 py-1">{p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—"}</td>
                          <td className="border px-2 py-1">{p.norm_score_before?.toFixed(3) ?? "—"}</td>
                          <td className="border px-2 py-1">{p.norm_score_after?.toFixed(3) ?? "—"}</td>
                          <td className="border px-2 py-1 space-x-1 space-x-reverse">
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
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
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
