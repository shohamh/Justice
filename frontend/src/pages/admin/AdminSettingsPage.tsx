import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import TabBar from "../../components/TabBar";
import { SystemSettingsContent, ChangelogContent } from "../SystemSettingsPage";
import { AdminInviteCodesContent } from "../AdminInviteCodesPage";
import { BugReportsContent } from "./BugReportsContent";
import AuditLogContent from "./AuditLogContent";
import { ErrorsContent } from "./ErrorsContent";
import { getAdminBugReportUnreadCount, getAdminErrorUnreadCount } from "../../api/bugReports";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

export const ADMIN_SETTINGS_TAB_ORDER = ["settings", "invite-codes", "changelog", "bug-reports", "errors", "audit-log"] as const;

export default function AdminSettingsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get("tab") ?? "0");
  const activeTab = raw >= 0 && raw <= 5 ? raw : 0;
  const setTab = (i: number) => setSearchParams({ tab: String(i) }, { replace: true });
  const queryClient = useQueryClient();
  const errorUnread = useQuery({ queryKey: ["admin-errors-unread"], queryFn: getAdminErrorUnreadCount, enabled: activeTab >= 0 });
  const bugUnread = useQuery({ queryKey: ["admin-bug-reports-unread"], queryFn: getAdminBugReportUnreadCount, enabled: activeTab >= 0 });

  useEffect(() => {
    if (activeTab !== 3) return;
    void queryClient.invalidateQueries({ queryKey: ["admin-bug-reports"] });
  }, [activeTab, queryClient]);

  const tabs = [
    t("nav.admin_settings"),
    t("nav.admin_invite_codes"),
    t("nav.admin_changelog"),
    t("nav.admin_bug_reports"),
    t("nav.admin_errors", { defaultValue: "\u05e9\u05d2\u05d9\u05d0\u05d5\u05ea" }),
    t("nav.admin_audit_log"),
  ];

  return (
    <Layout>
      <TabBar tabs={tabs} active={activeTab} onChange={setTab} badges={[null, null, null, bugUnread.data ?? null, errorUnread.data ?? null, null]} />
      {activeTab === 0 && <SystemSettingsContent />}
      {activeTab === 1 && <AdminInviteCodesContent />}
      {activeTab === 2 && <ChangelogContent />}
      {activeTab === 3 && <BugReportsContent />}
      {activeTab === 4 && <ErrorsContent />}
      {activeTab === 5 && <AuditLogContent />}
    </Layout>
  );
}
