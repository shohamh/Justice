import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { ShiftsContent } from "../ShiftsPage";
import { DutyManagementContent } from "../DutyManagementPage";
import { AlgorithmContent } from "../AlgorithmPage";

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 2 ? raw : 0;

  const setTab = (i: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", String(i));
    if (i !== 2) next.delete("jobId");
    setSearchParams(next, { replace: true });
  };

  const tabs = [
    t("nav.shifts_tab_shifts"),
    t("nav.shifts_tab_manual"),
    t("nav.shifts_tab_algorithm"),
  ];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <ShiftsContent />}
      {activeTab === 1 && <DutyManagementContent />}
      {activeTab === 2 && <AlgorithmContent />}
    </Layout>
  );
}
