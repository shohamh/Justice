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
  uploadExemptionFile,
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
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadSizeErrors, setUploadSizeErrors] = useState<string[]>([]);
  const [erMedical, setErMedical] = useState(false);

  const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB

  function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  const selectedExemptionType = exemptionTypes.find(et => et.id === erTypeId);
  const isMedical = erMedical || (selectedExemptionType?.is_medical ?? false);

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
        setError(t(`errors.${code}` as Parameters<typeof t>[0]) || t("errors.generic"));
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
      const createdReq = await submitExemptionRequest({
        exemption_type_id: erTypeId,
        start_date: erStart,
        end_date: erEnd || null,
        reason: erReason || null,
      });
      // Upload any attached files automatically
      for (const f of uploadFiles) {
        await uploadExemptionFile(createdReq.id, f);
      }
      setErTypeId(""); setErStart(""); setErEnd(""); setErReason("");
      setUploadFiles([]); setUploadSizeErrors([]); setErMedical(false);
      await refresh();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { detail?: string } } };
        const code = axiosErr.response?.data?.detail;
        setErError(t(`errors.${code}` as Parameters<typeof t>[0]) || t("errors.generic"));
      } else {
        setErError(t("errors.generic"));
      }
    } finally {
      setErSubmitting(false);
    }
  }

  const statusBadge = (status: string) => {
    const colors: Record<string, string> = {
      pending: "text-amber-600 dark:text-amber-400",
      approved: "text-green-600 dark:text-green-400",
      rejected: "text-red-600 dark:text-red-400",
    };
    return <span className={colors[status] ?? ""}>{t(`my_requests.${status}`)}</span>;
  };

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6 dark:bg-gray-800">
        <h2 className="text-xl font-semibold">{t("my_requests.title")}</h2>

        <div className="border-b dark:border-gray-600 pb-4 space-y-3">
          <h3 className="font-medium">{t("my_requests.section_constraints")}</h3>
          {error && <div className="text-red-600 text-sm" data-testid="req-error">{error}</div>}
        </div>

        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2 border-b dark:border-gray-600 pb-4">
          <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="req-start" />
          <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="req-end" />
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("my_requests.reason")} required data-testid="req-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={submitting} data-testid="req-submit">
            {submitting ? t("app.loading") : t("my_requests.send")}
          </button>
        </form>

        {items.length === 0 && <p className="text-sm text-gray-500">{t("my_requests.none")}</p>}

        <ul className="text-sm space-y-2" data-testid="constraints-list">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-3" data-testid={`constraint-row-${c.id}`}>
              <span dir="ltr">{c.start_date} → {c.end_date}</span>
              <span className="text-gray-700 dark:text-gray-300">{c.reason}</span>
              {statusBadge(c.status)}
              {c.status === "pending" && (
                <button className="text-red-500 text-xs" onClick={() => onCancel(c.id)} data-testid={`cancel-${c.id}`}>
                  {t("my_requests.cancel")}
                </button>
              )}
            </li>
          ))}
        </ul>

        <div className="pt-4 border-t dark:border-gray-600">
          <h3 className="font-medium">{t("exemption_requests.title")}</h3>
          {erError && <div className="text-red-600 dark:text-red-400 text-sm" data-testid="er-error">{erError}</div>}
          <form onSubmit={onErSubmit} className="mt-2 space-y-3" dir="rtl">
            <div className="flex flex-wrap gap-2 items-end">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.type")}</label>
                <select
                  className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  value={erTypeId}
                  onChange={(e) => {
                    const typeId = e.target.value;
                    setErTypeId(typeId);
                    setUploadFiles([]); setUploadSizeErrors([]);
                    const type = exemptionTypes.find(et => et.id === typeId);
                    setErMedical(type?.is_medical ?? false);
                  }}
                  required
                  data-testid="er-type"
                >
                  <option value="">— {t("exemption_requests.type")} —</option>
                  {exemptionTypes.map((et) => (
                    <option key={et.id} value={et.id}>
                      {et.name}{et.is_medical ? " 🏥" : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.start_date")}</label>
                <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erStart} onChange={(e) => setErStart(e.target.value)} required data-testid="er-start" />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.end_date")}</label>
                <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={erEnd} onChange={(e) => setErEnd(e.target.value)} data-testid="er-end" />
              </div>
              <div className="flex flex-col gap-1 flex-1 min-w-32">
                <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.reason")}</label>
                <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 w-full" value={erReason} onChange={(e) => setErReason(e.target.value)} placeholder={t("exemption_requests.reason")} data-testid="er-reason" />
              </div>
            </div>

            {/* Medical checkbox */}
            <label className="flex items-center gap-2 cursor-pointer w-fit" data-testid="er-medical-check">
              <input
                type="checkbox"
                checked={erMedical}
                onChange={(e) => { setErMedical(e.target.checked); setUploadFiles([]); setUploadSizeErrors([]); }}
                className="w-4 h-4 accent-blue-600"
              />
              <span className="text-sm font-medium text-blue-700 dark:text-blue-300">
                🏥 {t("duty_config.medical")}
              </span>
            </label>

            {/* File upload — always available, required for medical types */}
            <div className={`rounded-lg border-2 border-dashed p-4 space-y-2 ${
              isMedical
                ? "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950"
                : "border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700"
            }`}>
              <div className="flex items-center gap-2">
                <span className="text-lg">{isMedical ? "🏥" : "📎"}</span>
                <div>
                  <p className={`text-sm font-medium ${isMedical ? "text-blue-800 dark:text-blue-200" : "text-gray-700 dark:text-gray-300"}`}>
                    {isMedical ? t("exemption_requests.upload_required") : t("exemption_requests.upload_optional")}
                  </p>
                  <p className={`text-xs ${isMedical ? "text-blue-600 dark:text-blue-400" : "text-gray-500 dark:text-gray-400"}`}>
                    {t("exemption_requests.upload_hint")}
                  </p>
                </div>
              </div>
              <label className={`flex flex-col items-center justify-center gap-2 cursor-pointer rounded-lg border p-3 transition-colors ${
                isMedical
                  ? "border-blue-200 dark:border-blue-700 bg-white dark:bg-gray-800 hover:bg-blue-50 dark:hover:bg-gray-700"
                  : "border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700"
              }`}>
                <span className="text-2xl">📎</span>
                <span className={`text-sm font-medium ${isMedical ? "text-blue-700 dark:text-blue-300" : "text-gray-600 dark:text-gray-300"}`}>
                  {uploadFiles.length > 0
                    ? `${uploadFiles.length} ${uploadFiles.length === 1 ? "קובץ נבחר" : "קבצים נבחרו"}`
                    : "בחר קבצים"}
                </span>
                <span className="text-xs text-gray-400">PDF, JPG, PNG, GIF · {t("exemption_requests.max_file_size")}</span>
                <input
                  type="file"
                  multiple
                  accept=".pdf,image/*"
                  className="hidden"
                  onChange={e => {
                    const picked = Array.from(e.target.files ?? []);
                    const valid = picked.filter(f => f.size <= MAX_FILE_BYTES);
                    const oversized = picked.filter(f => f.size > MAX_FILE_BYTES).map(f => f.name);
                    setUploadFiles(prev => {
                      const merged = [...prev, ...valid.filter(v => !prev.some(p => p.name === v.name))];
                      return merged;
                    });
                    setUploadSizeErrors(oversized);
                    e.target.value = "";
                  }}
                  data-testid="er-files"
                />
              </label>
              {uploadSizeErrors.length > 0 && (
                <div className="rounded p-2 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
                  <p className="text-xs font-medium text-red-700 dark:text-red-300">{t("exemption_requests.file_too_large")}</p>
                  <ul className="text-xs text-red-600 dark:text-red-400 mt-0.5 list-disc list-inside">
                    {uploadSizeErrors.map(name => <li key={name}>{name}</li>)}
                  </ul>
                </div>
              )}
              {uploadFiles.length > 0 && (
                <ul className="text-xs space-y-0.5">
                  {uploadFiles.map((f, i) => (
                    <li key={i} className={`flex items-center gap-1 ${isMedical ? "text-blue-700 dark:text-blue-300" : "text-gray-600 dark:text-gray-300"}`}>
                      <span>📄</span>
                      <span className="truncate max-w-48">{f.name}</span>
                      <span className="text-gray-400 dark:text-gray-500 shrink-0">({formatBytes(f.size)})</span>
                      <button
                        type="button"
                        className="text-red-400 hover:text-red-600 mr-1 shrink-0"
                        onClick={() => setUploadFiles(prev => prev.filter((_, j) => j !== i))}
                      >✕</button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <button
              type="submit"
              className="bg-indigo-600 text-white px-4 py-1.5 rounded disabled:opacity-50 text-sm"
              disabled={erSubmitting || (isMedical && uploadFiles.length === 0)}
              data-testid="er-submit"
            >
              {erSubmitting ? t("app.loading") : t("exemption_requests.send")}
            </button>
            {isMedical && uploadFiles.length === 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">{t("exemption_requests.upload_required_hint")}</p>
            )}
          </form>

          {exemptionRequests.length === 0 && <p className="text-sm text-gray-500 mt-2">{t("exemption_requests.none")}</p>}
          <ul className="text-sm space-y-1 mt-2" data-testid="er-list">
            {exemptionRequests.map((er) => (
              <li key={er.id} className="flex items-center gap-3">
                <span>{exemptionTypes.find((et) => et.id === er.exemption_type_id)?.name ?? er.exemption_type_id}</span>
                <span dir="ltr">{er.start_date} → {er.end_date ?? t("exemptions.forever")}</span>
                {er.reason && <span className="text-gray-700 dark:text-gray-300">{er.reason}</span>}
                <span className={`text-xs ${
                  er.status === "approved" ? "text-green-600 dark:text-green-400" :
                  er.status === "rejected" ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"
                }`}>{t(`exemption_requests.${er.status}`)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="pt-4 border-t dark:border-gray-600">
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
