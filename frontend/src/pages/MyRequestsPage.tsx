import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Exemption, listExemptions } from "../api/exemptions";
import { ExemptionType, listExemptionTypes } from "../api/dutyConfig";
import {
  PersonalConstraint,
  cancelConstraint,
  listMyConstraints,
  submitConstraint,
} from "../api/constraints";
import {
  ExemptionRequest,
  listMyExemptionRequests,
  submitExemptionRequest,
} from "../api/exemptions";

export default function MyRequestsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Exemption request state
  const [exemptionRequests, setExemptionRequests] = useState<ExemptionRequest[]>([]);
  const [exemptionTypes, setExemptionTypes] = useState<ExemptionType[]>([]);
  const [erTypeId, setErTypeId] = useState("");
  const [erStart, setErStart] = useState("");
  const [erEnd, setErEnd] = useState("");
  const [erReason, setErReason] = useState("");
  const [erError, setErError] = useState<string | null>(null);
  const [erSubmitting, setErSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    setItems(await listMyConstraints());
    setExemptionRequests(await listMyExemptionRequests());
    setExemptionTypes(await listExemptionTypes().catch(() => []));
    if (user) {
      setExemptions(await listExemptions(user.id));
    }
  }, [user]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await submitConstraint({
        start_date: start,
        end_date: end,
        reason,
      });
      setStart(""); setEnd(""); setReason("");
      await refresh();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        const code = axiosErr.response?.data?.detail;
        setError(t(`errors.${code}` as any) || t("errors.generic"));
      } else {
        setError(t("errors.generic"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onCancel(id: string) {
    if (!confirm(t("my_requests.cancel") + "?")) return;
    await cancelConstraint(id);
    await refresh();
  }

  async function onErSubmit(e: FormEvent) {
    e.preventDefault();
    setErError(null);
    setErSubmitting(true);
    try {
      await submitExemptionRequest({
        exemption_type_id: erTypeId,
        start_date: erStart,
        end_date: erEnd || null,
        reason: erReason || null,
      });
      setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
      await refresh();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        const code = axiosErr.response?.data?.detail;
        setErError(t(`errors.${code}` as any) || t("errors.generic"));
      } else {
        setErError(t("errors.generic"));
      }
    } finally {
      setErSubmitting(false);
    }
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

        {error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}

        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 border-b pb-4">
          <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="req-start" />
          <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="req-end" />
          <input className="border rounded p-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={submitting} data-testid="req-submit">
            {submitting ? t("app.loading") : t("my_requests.send")}
          </button>
        </form>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.none")}</p>}

        <ul className="text-sm space-y-2" data-testid="constraints-list">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-3" data-testid={`constraint-row-${c.id}`}>
              <span dir="ltr">{c.start_date} → {c.end_date}</span>
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
          <h3 className="font-medium">{t("exemption_requests.title")}</h3>
          {erError && <div className="text-red-600 text-sm" data-testid="er-error">{erError}</div>}
          <form onSubmit={onErSubmit} className="flex flex-wrap items-end gap-2 mt-2">
            <select className="border rounded p-1" value={erTypeId} onChange={(e) => setErTypeId(e.target.value)} required data-testid="er-type">
              <option value="">{t("exemption_requests.type")}</option>
              {exemptionTypes.map((et) => (
                <option key={et.id} value={et.id}>{et.name}</option>
              ))}
            </select>
            <input type="date" className="border rounded p-1" value={erStart} onChange={(e) => setErStart(e.target.value)} required data-testid="er-start" />
            <input type="date" className="border rounded p-1" value={erEnd} onChange={(e) => setErEnd(e.target.value)} data-testid="er-end" />
            <input className="border rounded p-1" value={erReason} onChange={(e) => setErReason(e.target.value)} placeholder={t("exemption_requests.reason")} data-testid="er-reason" />
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={erSubmitting} data-testid="er-submit">
              {erSubmitting ? t("app.loading") : t("exemption_requests.send")}
            </button>
          </form>

          {exemptionRequests.length === 0 && <p className="text-sm text-gray-500 mt-2">{t("exemption_requests.none")}</p>}
          <ul className="text-sm space-y-1 mt-2" data-testid="er-list">
            {exemptionRequests.map((er) => (
              <li key={er.id} className="flex items-center gap-3">
                <span>{exemptionTypes.find((et) => et.id === er.exemption_type_id)?.name ?? er.exemption_type_id}</span>
                <span dir="ltr">{er.start_date} → {er.end_date ?? t("exemptions.forever")}</span>
                {er.reason && <span className="text-gray-500">{er.reason}</span>}
                <span className={`text-xs ${
                  er.status === "approved" ? "text-green-600" :
                  er.status === "rejected" ? "text-red-600" : "text-amber-600"
                }`}>{t(`exemption_requests.${er.status}`)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="pt-4 border-t">
          <h3 className="font-medium">{t("my_requests.my_exemptions")}</h3>
          {exemptions.length === 0 && <p className="text-sm text-gray-500">{t("exemptions.none")}</p>}
          <ul className="text-sm space-y-1">
            {exemptions.map((ex) => (
              <li key={ex.id} dir="ltr">{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</li>
            ))}
          </ul>
        </div>
      </section>
    </Layout>
  );
}
