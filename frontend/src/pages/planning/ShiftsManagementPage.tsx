import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [latestJobId, setLatestJobId] = useState<string | null>(null);
  const runsRef = useRef<HTMLElement | null>(null);

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
            <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
              {runsOpen ? "▲" : "▼"}
            </span>
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
