import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { listExemptions, Exemption } from "../api/exemptions";
import {
  PersonalConstraint,
  cancelConstraint,
  listMyConstraints,
  submitConstraint,
} from "../api/constraints";

export default function MyRequestsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");

  const refresh = useCallback(async () => {
    setItems(await listMyConstraints());
    if (user) {
      setExemptions(await listExemptions(user.id));
    }
  }, [user]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await submitConstraint({
      start_date: start,
      end_date: end,
      reason,
    });
    setStart(""); setEnd(""); setReason("");
    await refresh();
  }

  async function onCancel(id: string) {
    if (!confirm(t("my_requests.cancel") + "?")) return;
    await cancelConstraint(id);
    await refresh();
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "text-amber-600",
      approved: "text-green-600",
      rejected: "text-red-600",
    };
    return <span className={colors[status] ?? ""}>{t(`my_requests.${status}`)}</span>;
  };

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6">
        <h2 className="text-xl font-semibold">{t("my_requests.title")}</h2>

        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 border-b pb-4">
          <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="req-start" />
          <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="req-end" />
          <input className="border rounded p-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="req-submit">{t("my_requests.send")}</button>
        </form>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.none")}</p>}

        <ul className="text-sm space-y-2" data-testid="constraints-list">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-3" data-testid={`constraint-row-${c.id}`}>
              <span>{c.start_date} → {c.end_date}</span>
              <span className="text-gray-500">{c.reason}</span>
              {statusBadge(c.status)}
              {c.status === "pending" && (
                <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                  {t("my_requests.cancel")}
                </button>
              )}
            </li>
          ))}
        </ul>

        <div className="pt-4 border-t">
          <h3 className="font-medium">{t("my_requests.my_exemptions")}</h3>
          {exemptions.length === 0 && <p className="text-sm text-gray-500">{t("exemptions.none")}</p>}
          <ul className="text-sm space-y-1">
            {exemptions.map((ex) => (
              <li key={ex.id}>{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</li>
            ))}
          </ul>
        </div>
      </section>
    </Layout>
  );
}
