import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setItems(await listPendingApprovals());
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onApprove(id: string) {
    await approveConstraint(id);
    await refresh();
  }

  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectConstraint(id, note);
    const next = { ...rejectNotes };
    delete next[id];
    setRejectNotes(next);
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}</h2>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("approvals.none")}</p>}

        <ul className="space-y-3" data-testid="approvals-list">
          {items.map((c) => (
            <li key={c.id} className="border rounded p-3 flex items-center gap-4" data-testid={`approval-row-${c.id}`}>
              <div className="flex-1">
                <p className="text-sm"><strong>{c.soldier_id}</strong> — {c.start_date} → {c.end_date}</p>
                <p className="text-xs text-gray-500">{c.reason}</p>
              </div>
              <div className="flex items-center gap-2">
                <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                  {t("approvals.approve")}
                </button>
                <input
                  className="border rounded p-1 text-sm w-28"
                  value={rejectNotes[c.id] ?? ""}
                  onChange={(e) => setRejectNotes((prev) => ({ ...prev, [c.id]: e.target.value }))}
                  placeholder={t("approvals.decision_note")}
                  data-testid={`reject-note-${c.id}`}
                />
                <button
                  className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                  disabled={!rejectNotes[c.id]}
                  onClick={() => onReject(c.id)}
                  data-testid={`reject-${c.id}`}
                >
                  {t("approvals.reject")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </Layout>
  );
}
