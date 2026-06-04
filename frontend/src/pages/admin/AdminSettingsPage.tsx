import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { SystemSettingsContent } from "../SystemSettingsPage";
import { AdminInviteCodesContent } from "../AdminInviteCodesPage";

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 1 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [t("nav.admin_settings"), t("nav.admin_invite_codes")];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
    </Layout>
  );
}
