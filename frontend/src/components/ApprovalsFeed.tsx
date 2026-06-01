import { useTranslation } from "react-i18next";
import type { ApprovalItem } from "../api/commanderDashboard";

interface Props {
  data: ApprovalItem[] | null;
}

export default function ApprovalsFeed({ data }: Props) {
  const { t } = useTranslation();
  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_pending_approvals")}</p>;
  return (
    <div className="space-y-2" data-testid="approvals-feed">
      {data.map((item) => (
        <div key={item.id} className="flex items-center justify-between border rounded p-2 text-sm">
          <div>
            <span className="font-medium">{item.soldier_name}</span>
            <span className="mx-1 text-gray-400">·</span>
            <span className="text-gray-500">{item.summary}</span>
          </div>
          <span className="text-xs text-gray-400">{new Date(item.created_at).toLocaleDateString("he-IL")}</span>
        </div>
      ))}
    </div>
  );
}
