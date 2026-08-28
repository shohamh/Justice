import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ApprovalItem } from "../api/commanderDashboard";
import { approveFieldUpdate, rejectFieldUpdate } from "../api/soldiers";
import { approveExemptionRequestCommanderStep, rejectExemptionRequest } from "../api/exemptions";
import SoldierLink from "./SoldierLink";
import { formatDateTimeIsrael } from "../utils/formatDate";

interface Props {
  data: ApprovalItem[] | null;
  onRefresh: () => void;
}

export default function ApprovalsFeed({ data, onRefresh }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});

  if (!data || data.length === 0) return <p className="text-gray-500">{t("command_dashboard.no_pending_approvals")}</p>;

  async function handleApprove(item: ApprovalItem) {
    setBusy(item.id);
    try {
      if (item.request_type === "field_update") {
        await approveFieldUpdate(item.soldier_id, item.id, notes[item.id]);
      } else if (item.request_type === "exemption") {
        // ApprovalItem has no status field to distinguish stage; this component is
        // currently unused (not imported anywhere), so default to the first-stage action.
        await approveExemptionRequestCommanderStep(item.id);
      }
      onRefresh();
    } catch { /* ignore */ }
    setBusy(null);
  }

  async function handleReject(item: ApprovalItem) {
    setBusy(item.id);
    try {
      if (item.request_type === "field_update") {
        await rejectFieldUpdate(item.soldier_id, item.id, notes[item.id] || "");
      } else if (item.request_type === "exemption") {
        await rejectExemptionRequest(item.id, notes[item.id] || "");
      }
      onRefresh();
    } catch { /* ignore */ }
    setBusy(null);
  }

  return (
    <div className="space-y-2" data-testid="approvals-feed">
      {data.map((item) => (
        <div key={item.id} className="border dark:border-gray-600 rounded p-2 text-sm">
          <div className="flex items-center justify-between mb-1">
            <div>
              <SoldierLink id={item.soldier_id} name={item.soldier_name} className="font-medium" />
              <span className="mx-1 text-gray-400">·</span>
              <span className="text-gray-500">{item.summary}</span>
            </div>
            <span className="text-xs text-gray-400">{formatDateTimeIsrael(item.created_at)}</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <input
              className="border rounded px-2 py-1 text-xs flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              placeholder={t("approvals.decision_note")}
              value={notes[item.id] ?? ""}
              onChange={(e) => setNotes((prev) => ({ ...prev, [item.id]: e.target.value }))}
            />
            <button
              onClick={() => handleApprove(item)}
              disabled={busy === item.id}
              className="bg-green-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
            >
              {t("approvals.approve")}
            </button>
            <button
              onClick={() => handleReject(item)}
              disabled={busy === item.id}
              className="bg-red-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
            >
              {t("approvals.reject")}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
