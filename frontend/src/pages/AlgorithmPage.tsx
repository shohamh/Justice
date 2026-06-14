import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import AlgorithmRunForm from "../components/AlgorithmRunForm";
import AlgorithmJobTabs from "../components/AlgorithmJobTabs";
import { AlgorithmJob, JobSummaryOut, listJobs, pollJob, cancelJob } from "../api/algorithm";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

export function AlgorithmContent() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();

  const [jobs, setJobs] = useState<JobSummaryOut[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<AlgorithmJob | null>(null);
  const [showRunForm, setShowRunForm] = useState(false);
  const [rerunOverrides, setRerunOverrides] = useState<Record<string, number> | null>(null);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);

  const listPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadJobs = useCallback(async () => {
    try {
      const result = await listJobs();
      setJobs(result.items);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    Promise.all([listSoldiers(), listDutyTypes()]).then(([ss, dts]) => {
      setSoldiers(ss);
      setDutyTypes(dts);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  // Poll job list every 3s while any job is active
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "pending" || j.status === "running");
    if (hasActive) {
      listPollRef.current = setInterval(() => void loadJobs(), 3000);
    } else {
      if (listPollRef.current) clearInterval(listPollRef.current);
    }
    return () => {
      if (listPollRef.current) clearInterval(listPollRef.current);
    };
  }, [jobs, loadJobs]);

  // Pre-select job from URL param
  useEffect(() => {
    const jobIdParam = searchParams.get("jobId");
    if (jobIdParam) setSelectedJobId(jobIdParam);
  }, [searchParams]);

  // Poll selected job every 1s while pending/running
  useEffect(() => {
    if (!selectedJobId) return;
    setSelectedJob(null);

    const poll = async () => {
      try {
        const j = await pollJob(selectedJobId);
        setSelectedJob(j);
        if (j.status === "done" || j.status === "failed") {
          if (jobPollRef.current) clearInterval(jobPollRef.current);
        }
      } catch { /* ignore */ }
    };

    void poll();
    jobPollRef.current = setInterval(() => void poll(), 1000);

    return () => {
      if (jobPollRef.current) clearInterval(jobPollRef.current);
    };
  }, [selectedJobId]);

  function handleJobSubmitted(jobId: string) {
    handleCloseRunForm();
    setSelectedJobId(jobId);
    void loadJobs();
  }

  function handleRerun(overrides: Record<string, number>) {
    setRerunOverrides(overrides);
    setShowRunForm(true);
  }

  function handleCloseRunForm() {
    setShowRunForm(false);
    setRerunOverrides(null);
  }

  async function handleCancel() {
    if (!selectedJobId) return;
    try {
      await cancelJob(selectedJobId);
    } catch { /* 409 = already done, ignore */ }
  }

  const STATUS_BADGE: Record<string, string> = {
    pending: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
    running: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
    done: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
    failed: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
    published: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  };

  const STATUS_LABEL: Record<string, string> = {
    pending: "ממתין",
    running: "רץ...",
    done: "טיוטה",
    failed: "נכשל",
    published: "פורסם",
  };

  const statusIcon = (status: string) => {
    if (status === "done") return "✓";
    if (status === "failed") return "✗";
    return "⏳";
  };

  return (
    <div className="flex flex-col md:flex-row h-full gap-4 overflow-hidden" dir="rtl">
      {/* Left panel: job history */}
      <div className="w-full md:w-72 md:shrink-0 border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 flex flex-col overflow-hidden max-h-48 md:max-h-none">
        <div className="flex justify-between items-center p-3 border-b dark:border-gray-600">
          <h2 className="font-semibold text-sm">{t("algorithm.runs_title")}</h2>
          <button
            onClick={() => setShowRunForm(true)}
            className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700"
          >
            {t("algorithm.new_run")}
          </button>
        </div>
        <div className="overflow-y-auto flex-1 p-2 space-y-1">
          {jobs.length === 0 && (
            <p className="text-sm text-gray-400 text-center mt-4">{t("algorithm.no_runs")}</p>
          )}
          {jobs.map(job => (
            <button
              key={job.id}
              onClick={() => setSelectedJobId(job.id)}
              className={`w-full text-right px-3 py-2 rounded border text-sm transition-colors ${
                selectedJobId === job.id
                  ? "bg-indigo-50 dark:bg-indigo-950 border-indigo-300 dark:border-indigo-700 text-indigo-800 dark:text-indigo-200"
                  : "hover:bg-gray-50 dark:hover:bg-gray-700 border-transparent"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={job.status === "done" ? "text-green-600 dark:text-green-400" : job.status === "failed" ? "text-red-600 dark:text-red-400" : "text-gray-400"}>
                  {statusIcon(job.status)}
                </span>
                <span className="font-medium truncate text-xs">
                  {job.planning_start} — {job.planning_end}
                </span>
                <span className={`px-1.5 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[job.status] ?? STATUS_BADGE.pending}`}>
                  {STATUS_LABEL[job.status] ?? job.status}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-0.5">{job.shift_count} משמרות · {job.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Right panel: job detail */}
      <div className="flex-1 border dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 overflow-y-auto p-4">
        {!selectedJobId && (
          <p className="text-gray-400 text-sm text-center mt-16">{t("algorithm.select_run")}</p>
        )}

        {selectedJobId && !selectedJob && (
          <p className="text-sm text-gray-500 animate-pulse">{t("app.loading")}</p>
        )}

        {selectedJob && (
          <div className="space-y-4">
            {/* Job header */}
            <div className="text-sm space-y-1 border-b dark:border-gray-600 pb-3">
              <div className="flex items-center gap-3">
                <span className={`font-semibold text-base ${selectedJob.status === "done" ? "text-green-700 dark:text-green-400" : selectedJob.status === "failed" ? "text-red-600 dark:text-red-400" : "text-gray-600 dark:text-gray-400"}`}>
                  {statusIcon(selectedJob.status)}
                </span>
                <span className="font-semibold">{selectedJob.planning_start} — {selectedJob.planning_end}</span>
                <span className="text-gray-500 text-xs">{selectedJob.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</span>
              </div>
              {(selectedJob.status === "pending" || selectedJob.status === "running") && (() => {
                // The backend stores real progress as JSON {pct, label} on the job
                // (updated after every solver batch).  Fall back to an indeterminate
                // low value if it's not set yet or in an unexpected format.
                let pct = 2;
                let label: string = t("algorithm.stage_pending");
                let known = false;
                try {
                  if (selectedJob.progress_message) {
                    const p = JSON.parse(selectedJob.progress_message) as { pct?: number; label?: string };
                    if (typeof p.pct === "number") { pct = Math.max(0, Math.min(100, p.pct)); known = true; }
                    if (typeof p.label === "string") label = p.label;
                  }
                } catch { /* unknown format → keep indeterminate defaults */ }
                const elapsed = selectedJob.started_at
                  ? Math.floor((Date.now() - new Date(selectedJob.started_at).getTime()) / 1000)
                  : null;

                return (
                  <div className="space-y-2">
                    {/* Progress bar (real, batch-driven) */}
                    <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2 overflow-hidden">
                      <div
                        className={`bg-indigo-500 h-2 rounded-full transition-all duration-500 ${known ? "" : "animate-pulse"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>

                    {/* Status line */}
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-gray-600 dark:text-gray-300 text-xs">
                        <span className="font-medium tabular-nums">{pct}%</span>
                        {" — "}{label}{elapsed !== null ? ` · ${elapsed}s` : ""}
                      </p>
                      <button
                        onClick={handleCancel}
                        className="text-xs text-red-600 hover:text-red-800 border border-red-300 rounded px-2 py-0.5"
                      >
                        {t("algorithm.cancel_btn")}
                      </button>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Cancelled jobs show a simple message */}
            {selectedJob.status === "failed" && selectedJob.error_message === "cancelled_by_user" && (
              <p className="text-sm text-gray-500">{t("algorithm.cancelled")}</p>
            )}

            {/* Done/published jobs and non-cancelled failed jobs get the full tab view */}
            {(selectedJob.status === "done" || selectedJob.status === "published" || (selectedJob.status === "failed" && selectedJob.error_message !== "cancelled_by_user")) && (
              <AlgorithmJobTabs
                job={selectedJob}
                jobId={selectedJobId!}
                soldiers={soldiers}
                dutyTypes={dutyTypes}
                onProposalUpdate={setSelectedJob}
                onRerun={handleRerun}
              />
            )}
          </div>
        )}
      </div>

      {/* New run drawer */}
      {showRunForm && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={handleCloseRunForm} />
          <div className="fixed inset-y-0 right-0 w-96 bg-white dark:bg-gray-800 z-50 shadow-xl overflow-y-auto">
            <div className="p-6 space-y-4">
              <div className="flex justify-between items-center">
                <h2 className="font-semibold">{t("algorithm.new_run")}</h2>
                <button onClick={handleCloseRunForm} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
              </div>
              <AlgorithmRunForm
                dutyTypes={dutyTypes}
                onJobSubmitted={handleJobSubmitted}
                initialOverrides={rerunOverrides ?? undefined}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function AlgorithmPage() {
  const { user } = useAuth();
  const role = user?.role;
  const canManageDuties = role === "duty_manager" || role === "admin";
  if (!canManageDuties) return <Navigate to="/" replace />;
  return <Layout><AlgorithmContent /></Layout>;
}
