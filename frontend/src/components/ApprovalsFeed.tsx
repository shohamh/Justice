import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ApprovalItem } from "../api/commanderDashboard";
import { approveFieldUpdate, rejectFieldUpdate } from "../api/soldiers";
import { approveExemptionRequest, rejectExemptionRequest } from "../api/exemptions";

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
        await approveExemptionRequest(item.id, notes[item.id]);
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
        <div key={item.id} className="border rounded p-2 text-sm">
          <div className="flex items-center justify-between mb-1">
            <div>
              <span className="font-medium">{item.soldier_name}</span>
              <span className="mx-1 text-gray-400">·</span>
              <span className="text-gray-500">{item.summary}</span>
            </div>
            <span className="text-xs text-gray-400">{new Date(item.created_at).toLocaleDateString("he-IL")}</span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <input
              className="border rounded px-2 py-1 text-xs flex-1"
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
