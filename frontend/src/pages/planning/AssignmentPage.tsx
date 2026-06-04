import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { DutyManagementContent } from "../DutyManagementPage";
import { AlgorithmContent } from "../AlgorithmPage";

export default function AssignmentPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 1 ? raw : 0;

  const setTab = (i: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", String(i));
    // clear algorithm-specific params when leaving algorithm tab
    if (i !== 1) next.delete("jobId");
    setSearchParams(next, { replace: true });
  };

  const tabs = [t("nav.assignment_manual"), t("nav.assignment_algorithm")];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <DutyManagementContent />}
      {activeTab === 1 && <AlgorithmContent />}
    </Layout>
  );
}
