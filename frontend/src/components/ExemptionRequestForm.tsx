import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import DateInput from "./DateInput";
import Combobox from "./Combobox";
import { ExemptionType } from "../api/dutyConfig";
import { isDateRangeValid } from "../utils/formatDate";
import { validateFileSignature, PDF_IMAGE_SIGNATURES } from "../utils/fileValidation";
import { translateApiError } from "../utils/translateApiError";

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface ExemptionRequestFormInput {
  exemption_type_id: string;
  start_date: string | null;
  end_date: string | null;
  reason: string | null;
}

interface Props {
  exemptionTypes: ExemptionType[];
  onSubmit: (input: ExemptionRequestFormInput, files: File[]) => Promise<void>;
  submitDisabledExtra?: boolean;
}

/**
 * The exemption-request form — used both for a soldier's own request
 * (MyRequestsPage) and for a commander/duty-manager logging an exemption on
 * a soldier's behalf (ExemptionsPanel, inside the soldier-edit modal). Owns
 * all its own field/validation/file-upload state; the caller only decides
 * what happens with the finished payload.
 */
export default function ExemptionRequestForm({ exemptionTypes, onSubmit, submitDisabledExtra }: Props) {
  const { t } = useTranslation();
  const [typeId, setTypeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");
  const [permanent, setPermanent] = useState(false);
  const [medical, setMedical] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [sizeErrors, setSizeErrors] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const selectedType = exemptionTypes.find((et) => et.id === typeId);
  const isMedical = medical || (selectedType?.is_medical ?? false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!permanent && !isDateRangeValid(start, end)) {
      setError(t("errors.date_range_invalid"));
      return;
    }
    setSubmitting(true);
    try {
      await onSubmit(
        {
          exemption_type_id: typeId,
          start_date: permanent ? null : start,
          end_date: permanent ? null : (end || null),
          reason: reason || null,
        },
        files,
      );
      setTypeId(""); setStart(""); setEnd(""); setReason("");
      setFiles([]); setSizeErrors([]); setMedical(false); setPermanent(false);
    } catch (err: unknown) {
      setError(translateApiError(err, t));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-3" dir="rtl">
      {error && <div className="text-red-600 dark:text-red-400 text-sm" data-testid="er-error">{error}</div>}
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex flex-wrap gap-2 items-end">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.type")}</label>
            <Combobox
              items={exemptionTypes.map(et => ({ id: et.id, name: `${et.name}${et.is_medical ? " 🏥" : ""}` }))}
              value={typeId}
              onChange={(nextTypeId) => {
                setTypeId(nextTypeId);
                setFiles([]); setSizeErrors([]);
                const type = exemptionTypes.find(et => et.id === nextTypeId);
                setMedical(type?.is_medical ?? false);
              }}
              placeholder={`— ${t("exemption_requests.type")} —`}
              testId="er-type"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.start_date")}</label>
            <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={permanent ? "" : start} onChange={(iso) => setStart(iso)} max={end || undefined} disabled={permanent} required={!permanent} showHolidays data-testid="er-start" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.end_date")}</label>
            <DateInput className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={permanent ? "" : end} onChange={(iso) => setEnd(iso)} min={start || undefined} disabled={permanent} required={!permanent} showHolidays data-testid="er-end" />
            <label className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 mt-1">
              <input
                type="checkbox"
                checked={permanent}
                onChange={(e) => {
                  setPermanent(e.target.checked);
                  if (e.target.checked) { setStart(""); setEnd(""); }
                }}
                data-testid="er-permanent"
              />
              {t("exemption_requests.permanent")}
            </label>
          </div>
          <div className="flex flex-col gap-1 flex-1 min-w-32">
            <label className="text-xs text-gray-500 dark:text-gray-400">{t("exemption_requests.reason")}</label>
            <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 w-full" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("exemption_requests.reason")} data-testid="er-reason" />
          </div>
        </div>

        {/* Medical checkbox */}
        <label className="flex items-center gap-2 cursor-pointer w-fit" data-testid="er-medical-check">
          <input
            type="checkbox"
            checked={medical}
            onChange={(e) => { setMedical(e.target.checked); setFiles([]); setSizeErrors([]); }}
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
              {files.length > 0
                ? `${files.length} ${files.length === 1 ? "קובץ נבחר" : "קבצים נבחרו"}`
                : "בחר קבצים"}
            </span>
            <span className="text-xs text-gray-400">PDF, JPG, PNG, GIF · {t("exemption_requests.max_file_size")}</span>
            <input
              type="file"
              multiple
              accept=".pdf,image/*"
              className="hidden"
              onChange={async e => {
                const picked = Array.from(e.target.files ?? []);
                e.target.value = "";
                const withinSize = picked.filter(f => f.size <= MAX_FILE_BYTES);
                const oversized = picked.filter(f => f.size > MAX_FILE_BYTES).map(f => f.name);
                const signatureChecks = await Promise.all(
                  withinSize.map(f => validateFileSignature(f, PDF_IMAGE_SIGNATURES)),
                );
                const valid = withinSize.filter((_, i) => signatureChecks[i]);
                const invalidType = withinSize.filter((_, i) => !signatureChecks[i]).map(f => f.name);
                setFiles(prev => {
                  const merged = [...prev, ...valid.filter(v => !prev.some(p => p.name === v.name))];
                  return merged;
                });
                setSizeErrors([...oversized, ...invalidType]);
              }}
              data-testid="er-files"
            />
          </label>
          {sizeErrors.length > 0 && (
            <div className="rounded p-2 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800">
              <p className="text-xs font-medium text-red-700 dark:text-red-300">{t("exemption_requests.file_too_large")}</p>
              <ul className="text-xs text-red-600 dark:text-red-400 mt-0.5 list-disc list-inside">
                {sizeErrors.map(name => <li key={name}>{name}</li>)}
              </ul>
            </div>
          )}
          {files.length > 0 && (
            <ul className="text-xs space-y-0.5">
              {files.map((f, i) => (
                <li key={i} className={`flex items-center gap-1 ${isMedical ? "text-blue-700 dark:text-blue-300" : "text-gray-600 dark:text-gray-300"}`}>
                  <span>📄</span>
                  <span className="truncate max-w-48">{f.name}</span>
                  <span className="text-gray-400 dark:text-gray-500 shrink-0">({formatBytes(f.size)})</span>
                  <button
                    type="button"
                    className="text-red-400 hover:text-red-600 mr-1 shrink-0"
                    onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                  >✕</button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="submit"
          className="bg-indigo-600 text-white px-4 py-1.5 rounded disabled:opacity-50 text-sm"
          disabled={submitting || !typeId || (isMedical && files.length === 0) || !!submitDisabledExtra || (!permanent && (!isDateRangeValid(start, end) || !start || !end))}
          data-testid="er-submit"
        >
          {submitting ? t("app.loading") : t("exemption_requests.send")}
        </button>
        {isMedical && files.length === 0 && (
          <p className="text-xs text-amber-600 dark:text-amber-400">{t("exemption_requests.upload_required_hint")}</p>
        )}
      </form>
    </div>
  );
}
