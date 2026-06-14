import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";

export default function ShiftsManagementPage() {
  const { t } = useTranslation();

  return (
    <Layout>
      <div className="space-y-6">
        <details className="border dark:border-gray-600 rounded-lg">
          <summary className="cursor-pointer px-4 py-3 font-medium text-sm select-none hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg">
            {t("nav.planning_templates")}
          </summary>
          <div className="px-4 pb-4 pt-2">
            <ShiftTemplatesContent />
          </div>
        </details>
        <ShiftsContent />
      </div>
    </Layout>
  );
}
