import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import AlgorithmRunForm from "../components/AlgorithmRunForm";
import AlgorithmProposalTable from "../components/AlgorithmProposalTable";
import { AlgorithmJob, JobSummaryOut, listJobs, pollJob } from "../api/algorithm";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

export default function AlgorithmPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();

  const role = user?.role;
  const canManageDuties = role === "duty_manager" || role === "admin";

  const [jobs, setJobs] = useState<JobSummaryOut[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<AlgorithmJob | null>(null);
  const [showRunForm, setShowRunForm] = useState(false);
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

  if (!canManageDuties) return <Navigate to="/" replace />;

  function handleJobSubmitted(jobId: string) {
    setShowRunForm(false);
    setSelectedJobId(jobId);
    void loadJobs();
  }

  const statusIcon = (status: string) => {
    if (status === "done") return "✓";
    if (status === "failed") return "✗";
    return "⏳";
  };

  return (
    <Layout>
      <div className="flex h-full gap-4 overflow-hidden" dir="rtl">
        {/* Left panel: job history */}
        <div className="w-72 shrink-0 border rounded-lg bg-white flex flex-col overflow-hidden">
          <div className="flex justify-between items-center p-3 border-b">
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
                    ? "bg-indigo-50 border-indigo-300 text-indigo-800"
                    : "hover:bg-gray-50 border-transparent"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={job.status === "done" ? "text-green-600" : job.status === "failed" ? "text-red-600" : "text-gray-400"}>
                    {statusIcon(job.status)}
                  </span>
                  <span className="font-medium truncate text-xs">
                    {job.planning_start} — {job.planning_end}
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{job.shift_count} משמרות · {job.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Right panel: job detail */}
        <div className="flex-1 border rounded-lg bg-white overflow-y-auto p-4">
          {!selectedJobId && (
            <p className="text-gray-400 text-sm text-center mt-16">{t("algorithm.select_run")}</p>
          )}

          {selectedJobId && !selectedJob && (
            <p className="text-sm text-gray-500 animate-pulse">{t("app.loading")}</p>
          )}

          {selectedJob && (
            <div className="space-y-4">
              {/* Job header */}
              <div className="text-sm space-y-1 border-b pb-3">
                <div className="flex items-center gap-3">
                  <span className={`font-semibold text-base ${selectedJob.status === "done" ? "text-green-700" : selectedJob.status === "failed" ? "text-red-600" : "text-gray-600"}`}>
                    {statusIcon(selectedJob.status)}
                  </span>
                  <span className="font-semibold">{selectedJob.planning_start} — {selectedJob.planning_end}</span>
                  <span className="text-gray-500 text-xs">{selectedJob.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</span>
                </div>
                {(selectedJob.status === "pending" || selectedJob.status === "running") && (
                  <p className="text-gray-600 animate-pulse">{t("algorithm.running")}</p>
                )}
              </div>

              {/* Failed state */}
              {selectedJob.status === "failed" && (() => {
                let parsed: { reasons?: string[] } | null = null;
                try { parsed = JSON.parse(selectedJob.error_message ?? "{}"); } catch { /* plain string */ }
                const reasons = parsed?.reasons ?? [];
                return (
                  <div className="text-red-600 text-sm space-y-1">
                    <p className="font-medium">{t("algorithm.failed")}</p>
                    {reasons.length > 0 && (
                      <ul className="list-disc pr-5 space-y-0.5 text-xs">
                        {reasons.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    )}
                    {reasons.length === 0 && selectedJob.error_message && (
                      <p className="text-xs">{selectedJob.error_message}</p>
                    )}
                  </div>
                );
              })()}

              {/* Proposals table */}
              {selectedJob.status === "done" && (
                <AlgorithmProposalTable
                  job={selectedJob}
                  jobId={selectedJobId!}
                  soldiers={soldiers}
                  dutyTypes={dutyTypes}
                  onProposalUpdate={setSelectedJob}
                />
              )}
            </div>
          )}
        </div>

        {/* New run drawer */}
        {showRunForm && (
          <>
            <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setShowRunForm(false)} />
            <div className="fixed inset-y-0 right-0 w-96 bg-white z-50 shadow-xl overflow-y-auto">
              <div className="p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <h2 className="font-semibold">{t("algorithm.new_run")}</h2>
                  <button onClick={() => setShowRunForm(false)} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
                </div>
                <AlgorithmRunForm
                  dutyTypes={dutyTypes}
                  onJobSubmitted={handleJobSubmitted}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
