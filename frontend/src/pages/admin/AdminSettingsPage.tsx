import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { SystemSettingsContent, ChangelogContent } from "../SystemSettingsPage";
import { AdminInviteCodesContent } from "../AdminInviteCodesPage";

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 2 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });

  const tabs = [t("nav.admin_settings"), t("nav.admin_invite_codes"), t("nav.admin_changelog")];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
      {activeTab === 2 && <ChangelogContent />}
    </Layout>
  );
}
