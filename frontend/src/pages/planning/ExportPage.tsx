import { useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { downloadTransparencyExport, downloadSubUnitsExport } from "../../api/scoring";

export default function ExportPage() {
  const { t } = useTranslation();
  const [loadingTransparency, setLoadingTransparency] = useState(false);
  const [loadingSubUnits, setLoadingSubUnits] = useState(false);

  async function handleTransparencyExport() {
    setLoadingTransparency(true);
    try {
      await downloadTransparencyExport(null);
    } finally {
      setLoadingTransparency(false);
    }
  }

  async function handleSubUnitsExport() {
    setLoadingSubUnits(true);
    try {
      await downloadSubUnitsExport();
    } finally {
      setLoadingSubUnits(false);
    }
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6">
        <h2 className="text-xl font-semibold">{t("nav.planning_export")}</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="border dark:border-gray-700 rounded-lg p-5 space-y-3">
            <h3 className="font-medium">{t("export.transparency_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">{t("export.transparency_desc")}</p>
            <button
              onClick={handleTransparencyExport}
              disabled={loadingTransparency}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded"
            >
              {loadingTransparency ? t("export.downloading") : t("export.download")}
            </button>
          </div>
          <div className="border dark:border-gray-700 rounded-lg p-5 space-y-3">
            <h3 className="font-medium">{t("export.sub_units_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">{t("export.sub_units_desc")}</p>
            <button
              onClick={handleSubUnitsExport}
              disabled={loadingSubUnits}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white px-4 py-2 rounded"
            >
              {loadingSubUnits ? t("export.downloading") : t("export.download")}
            </button>
          </div>
        </div>
      </section>
    </Layout>
  );
}
