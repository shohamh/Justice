import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { DutyConfigContent } from "../DutyConfigPage";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";

export default function ConfigPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 2 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [
    t("nav.config_duty_types"),
    t("nav.config_shifts"),
    t("nav.config_templates"),
  ];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <DutyConfigContent />}
      {activeTab === 1 && <ShiftsContent />}
      {activeTab === 2 && <ShiftTemplatesContent />}
    </Layout>
  );
}
