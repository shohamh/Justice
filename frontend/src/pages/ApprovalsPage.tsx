import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";
import {
  ExemptionRequest,
  approveExemptionRequest,
  listPendingExemptionRequests,
  rejectExemptionRequest,
} from "../api/exemptions";

type Tab = "constraints" | "exemptions";

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("constraints");
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [erItems, setErItems] = useState<ExemptionRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refresh = useCallback(async () => {
    setItems(await listPendingApprovals());
    setErItems(await listPendingExemptionRequests());
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

  async function onErApprove(id: string) {
    await approveExemptionRequest(id);
    await refresh();
  }
  async function onErReject(id: string) {
    const note = rejectNotes[`er-${id}`];
    if (!note) return;
    await rejectExemptionRequest(id, note);
    const next = { ...rejectNotes };
    delete next[`er-${id}`];
    setRejectNotes(next);
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}</h2>

        <div className="flex gap-4 border-b">
          <button
            className={`pb-2 text-sm ${tab === "constraints" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("constraints")}
            data-testid="approvals-tab-constraints"
          >
            {t("approvals.tab_constraints")}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "exemptions" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("exemptions")}
            data-testid="approvals-tab-exemptions"
          >
            {t("approvals.tab_exemptions")}
          </button>
        </div>

        {tab === "constraints" && (
          <>
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
          </>
        )}

        {tab === "exemptions" && (
          <>
            {erItems.length === 0 && <p className="text-sm text-gray-500">{t("approvals.exemption_none")}</p>}
            <ul className="space-y-3" data-testid="er-approvals-list">
              {erItems.map((er) => (
                <li key={er.id} className="border rounded p-3 flex items-center gap-4" data-testid={`er-approval-row-${er.id}`}>
                  <div className="flex-1">
                    <p className="text-sm"><strong>{er.soldier_id}</strong> — {er.start_date} → {er.end_date ?? t("exemptions.forever")}</p>
                    <p className="text-xs text-gray-500">{er.reason}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApprove(er.id)} data-testid={`er-approve-${er.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28"
                      value={rejectNotes[`er-${er.id}`] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [`er-${er.id}`]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`er-reject-note-${er.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[`er-${er.id}`]}
                      onClick={() => onErReject(er.id)}
                      data-testid={`er-reject-${er.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </Layout>
  );
}
