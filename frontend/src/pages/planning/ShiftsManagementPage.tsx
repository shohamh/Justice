import { useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <Layout>
      <div className="space-y-6">
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
          <div className="flex flex-wrap justify-between items-center gap-2">
            <h2 className="text-xl font-semibold">{t("nav.planning_templates")}</h2>
            <button
              type="button"
              onClick={() => setOpen(o => !o)}
              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1"
            >
              {open ? "▲" : "▼"}
            </button>
          </div>
          {open && <ShiftTemplatesContent />}
        </section>
        <ShiftsContent />
      </div>
    </Layout>
  );
}
