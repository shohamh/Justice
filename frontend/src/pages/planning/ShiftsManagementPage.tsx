import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../../components/Layout";
import { queryKeys } from "../../queryKeys";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";
import { listJobs } from "../../api/algorithm";
import { computeRunBadgeCounts } from "../../utils/algorithmRunBadges";
import { useSeenJobs } from "../../contexts/AlgorithmSeenContext";

const RUN_BADGES_LIMIT = 50;
const RUN_BADGES_OFFSET = 0;

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [latestJobId, setLatestJobId] = useState<string | null>(null);
  const runsRef = useRef<HTMLElement | null>(null);
  const { seenIds, seedSeenIds, markAllSeen } = useSeenJobs();

  // Poll the job list every 30s to keep the run badges (running/draft/done/
  // failed counts) fresh even while this collapsible section is closed.
  const jobsQuery = useQuery({
    queryKey: queryKeys.algorithmJobs(RUN_BADGES_LIMIT, RUN_BADGES_OFFSET),
    queryFn: () => listJobs(RUN_BADGES_LIMIT, RUN_BADGES_OFFSET),
    refetchInterval: 30_000,
  });
  const rawJobs = useMemo(() => jobsQuery.data?.items ?? [], [jobsQuery.data]);
  const runBadgeCounts = useMemo(() => computeRunBadgeCounts(rawJobs, seenIds), [rawJobs, seenIds]);

  useEffect(() => {
    if (jobsQuery.data) seedSeenIds(jobsQuery.data.items);
  }, [jobsQuery.data, seedSeenIds]);

  function handleJobSubmitted(jobId: string) {
    setLatestJobId(jobId);
    setRunsOpen(true);
    void queryClient.invalidateQueries({ queryKey: queryKeys.algorithmJobs(RUN_BADGES_LIMIT, RUN_BADGES_OFFSET) });
    setTimeout(() => runsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  return (
    <Layout>
      <div className="space-y-6">
        {/* Templates collapsible */}
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
          <button
            type="button"
            onClick={() => setTemplatesOpen(o => !o)}
            className="flex w-full justify-between items-center gap-2 text-right"
          >
            <h2 className="text-xl font-semibold">{t("nav.planning_templates")}</h2>
            <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
              {templatesOpen ? "▲" : "▼"}
            </span>
          </button>
          {templatesOpen && <ShiftTemplatesContent />}
        </section>

        {/* Algorithm runs collapsible */}
        <section
          ref={runsRef}
          className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4"
          dir="rtl"
        >
          <button
            type="button"
            onClick={() => setRunsOpen(o => !o)}
            className="flex w-full justify-between items-center gap-2 text-right"
          >
            <h2 className="text-xl font-semibold">ריצות אלגוריתם</h2>
            <div className="flex items-center gap-2">
              {(runBadgeCounts.done > 0 || runBadgeCounts.failed > 0 || runBadgeCounts.draft > 0) && (
                <button
                  type="button"
                  onClick={() => void markAllSeen(
                    rawJobs
                      .filter(j => (j.status === "done" || j.status === "failed") && j.error_message !== "cancelled_by_user")
                      .map(j => j.id)
                  )}
                  className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                >
                  סמן הכל כנראה
                </button>
              )}
              {runBadgeCounts.running > 0 && (
                <span data-testid="algo-badge-running" className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                  {runBadgeCounts.running}
                </span>
              )}
              {runBadgeCounts.draft > 0 && (
                <span data-testid="algo-badge-draft" className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
                  {runBadgeCounts.draft}
                </span>
              )}
              {runBadgeCounts.done > 0 && (
                <span data-testid="algo-badge-done" className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                  {runBadgeCounts.done}
                </span>
              )}
              {runBadgeCounts.failed > 0 && (
                <span data-testid="algo-badge-failed" className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
                  {runBadgeCounts.failed}
                </span>
              )}
              <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
                {runsOpen ? "▲" : "▼"}
              </span>
            </div>
          </button>
          {runsOpen && (
            <div className="h-[600px]" data-testid={latestJobId ? `algorithm-run-review-${latestJobId}` : "algorithm-run-review"}>
              <AlgorithmContent initialJobId={latestJobId} />
            </div>
          )}
        </section>

        {/* Shifts table */}
        <ShiftsContent onJobSubmitted={handleJobSubmitted} />
      </div>
    </Layout>
  );
}
