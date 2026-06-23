import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";
import { listJobs } from "../../api/algorithm";

interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

const EMPTY_COUNTS: RunBadgeCounts = { running: 0, draft: 0, done: 0, failed: 0 };

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [latestJobId, setLatestJobId] = useState<string | null>(null);
  const [runBadgeCounts, setRunBadgeCounts] = useState<RunBadgeCounts>(EMPTY_COUNTS);
  const runsRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    async function fetchRunBadgeCounts() {
      try {
        const result = await listJobs(50);
        const counts = result.items.reduce(
          (acc, job) => {
            if (job.status === "pending" || job.status === "running") {
              acc.running += 1;
            } else if (job.status === "done" && job.mode === "shadow") {
              acc.draft += 1;
            } else if (job.status === "done" && job.mode === "dm_reviewed") {
              acc.done += 1;
            } else if (job.status === "failed") {
              acc.failed += 1;
            }
            return acc;
          },
          { running: 0, draft: 0, done: 0, failed: 0 }
        );
        setRunBadgeCounts(counts);
      } catch {
        // ignore — leave last known counts in place
      }
    }

    void fetchRunBadgeCounts();
    const interval = setInterval(() => void fetchRunBadgeCounts(), 30_000);
    return () => clearInterval(interval);
  }, [latestJobId]);

  function handleJobSubmitted(jobId: string) {
    setLatestJobId(jobId);
    setRunsOpen(true);
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
              {runBadgeCounts.running > 0 && (
                <span
                  data-testid="algo-badge-running"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                >
                  {runBadgeCounts.running}
                </span>
              )}
              {runBadgeCounts.draft > 0 && (
                <span
                  data-testid="algo-badge-draft"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
                >
                  {runBadgeCounts.draft}
                </span>
              )}
              {runBadgeCounts.done > 0 && (
                <span
                  data-testid="algo-badge-done"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                >
                  {runBadgeCounts.done}
                </span>
              )}
              {runBadgeCounts.failed > 0 && (
                <span
                  data-testid="algo-badge-failed"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                >
                  {runBadgeCounts.failed}
                </span>
              )}
              <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
                {runsOpen ? "▲" : "▼"}
              </span>
            </div>
          </button>
          {runsOpen && (
            <div className="h-[600px]">
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
