import { useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  type ApplyRequest,
  type ApplySoldierRow,
  type PreviewResult,
  applyImport,
  previewImport,
} from "../api/importExcel";

type Step = "upload" | "review" | "done";

const ACTION_CHIP: Record<string, string> = {
  new: "bg-green-100 text-green-700",
  update: "bg-blue-100 text-blue-700",
  error: "bg-red-100 text-red-700",
  skip: "bg-gray-100 text-gray-500",
};
const ACTION_LABEL: Record<string, string> = {
  new: "חדש",
  update: "עדכון",
  error: "שגיאה",
  skip: "דלג",
};

export default function ImportPage() {
  const [step, setStep] = useState<Step>("upload");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [soldierActions, setSoldierActions] = useState<
    Record<number, "new" | "update" | "skip">
  >({});
  const [tab, setTab] = useState<"soldiers" | "assignments" | "templates">(
    "soldiers"
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    created: number;
    updated: number;
    skipped: number;
  } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setLoading(true);
    setError(null);
    try {
      const p = await previewImport(file);
      setPreview(p);
      const defaults: Record<number, "new" | "update" | "skip"> = {};
      for (const row of p.soldiers) {
        if (row.action !== "error")
          defaults[row.row] = row.action as "new" | "update";
      }
      setSoldierActions(defaults);
      setStep("review");
    } catch {
      setError(
        "שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין עם גיליונות בשמות הנכונים"
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleApply() {
    if (!preview) return;
    setLoading(true);
    const req: ApplyRequest = {
      soldiers: preview.soldiers
        .filter((r) => r.action !== "error")
        .map((r): ApplySoldierRow => ({ ...r, action: soldierActions[r.row] ?? "skip" })),
      assignments: preview.assignments
        .filter(
          (r) =>
            r.action === "new" &&
            r.resolved_soldier_id &&
            r.resolved_duty_type_id
        )
        .map((r) => ({
          row: r.row,
          action: "new" as const,
          resolved_soldier_id: r.resolved_soldier_id!,
          resolved_duty_type_id: r.resolved_duty_type_id!,
          start_date: r.start_date,
          end_date: r.end_date,
          is_reserve: r.is_reserve,
        })),
      shift_templates: preview.shift_templates
        .filter((r) => r.action === "new" && r.resolved_duty_type_id)
        .map((r) => ({
          row: r.row,
          action: "new" as const,
          name: r.name,
          resolved_duty_type_id: r.resolved_duty_type_id!,
          days_of_week: r.days_of_week,
          required_primary: r.required_primary,
          required_reserve: r.required_reserve,
        })),
    };
    try {
      const res = await applyImport(req);
      setResult(res);
      setStep("done");
    } catch {
      setError("שגיאה בייבוא — אין שינויים שנשמרו");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <div className="max-w-3xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">ייבוא מ-Excel</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Step 1: Upload */}
        {step === "upload" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4 text-center">
            <p className="text-gray-600 dark:text-gray-400 text-sm">
              העלה קובץ Excel עם גיליונות:{" "}
              <code>soldiers</code>, <code>assignments</code>,{" "}
              <code>shift_templates</code>
            </p>
            <a
              href="/api/import/template"
              className="text-indigo-600 hover:underline text-sm"
            >
              הורד תבנית לדוגמה ›
            </a>
            <div>
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.[0]) void handleUpload(e.target.files[0]);
                }}
              />
              <button
                className="bg-indigo-600 text-white px-6 py-2 rounded font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={loading}
                onClick={() => fileRef.current?.click()}
              >
                {loading ? "טוען..." : "בחר קובץ"}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Review */}
        {step === "review" && preview && (
          <div className="space-y-4">
            <div className="flex gap-1 border-b dark:border-gray-700">
              {(["soldiers", "assignments", "templates"] as const).map((t) => (
                <button
                  key={t}
                  className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
                    tab === t
                      ? "border-indigo-600 text-indigo-600"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                  onClick={() => setTab(t)}
                >
                  {t === "soldiers"
                    ? `חיילים (${preview.soldiers.length})`
                    : t === "assignments"
                    ? `שיבוצים (${preview.assignments.length})`
                    : `תבניות (${preview.shift_templates.length})`}
                </button>
              ))}
            </div>

            {tab === "soldiers" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">שם</th>
                    <th className="text-right pb-1">מ&quot;א</th>
                    <th className="text-right pb-1">סטטוס</th>
                    <th className="text-right pb-1">פעולה</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.soldiers.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.full_name}</td>
                      <td className="py-1">{row.personal_number}</td>
                      <td className="py-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}
                        >
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.length > 0 && (
                          <span className="text-red-500 text-xs mr-1">
                            {row.errors.join("; ")}
                          </span>
                        )}
                      </td>
                      <td className="py-1">
                        {row.action !== "error" && (
                          <select
                            className="border rounded text-xs p-0.5 dark:bg-gray-700"
                            value={soldierActions[row.row] ?? row.action}
                            onChange={(e) =>
                              setSoldierActions((prev) => ({
                                ...prev,
                                [row.row]: e.target.value as
                                  | "new"
                                  | "update"
                                  | "skip",
                              }))
                            }
                          >
                            {row.action === "update" && (
                              <option value="update">עדכן</option>
                            )}
                            {row.action === "new" && (
                              <option value="new">צור</option>
                            )}
                            <option value="skip">דלג</option>
                          </select>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === "assignments" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">מ&quot;א</th>
                    <th className="text-right pb-1">סוג תורנות</th>
                    <th className="text-right pb-1">תאריכים</th>
                    <th className="text-right pb-1">סטטוס</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.assignments.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.personal_number}</td>
                      <td className="py-1">{row.duty_type_name}</td>
                      <td className="py-1">
                        {row.start_date} – {row.end_date}
                      </td>
                      <td className="py-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}
                        >
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.map((e, i) => (
                          <span key={i} className="text-red-500 text-xs mr-1">
                            {e}
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === "templates" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">שם</th>
                    <th className="text-right pb-1">סוג</th>
                    <th className="text-right pb-1">ימים</th>
                    <th className="text-right pb-1">נדרש</th>
                    <th className="text-right pb-1">סטטוס</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.shift_templates.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.name}</td>
                      <td className="py-1">{row.duty_type_name}</td>
                      <td className="py-1">{row.days_of_week.join(",")}</td>
                      <td className="py-1">
                        {row.required_primary}+{row.required_reserve}
                      </td>
                      <td className="py-1">
                        <span
                          className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}
                        >
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.map((e, i) => (
                          <span key={i} className="text-red-500 text-xs mr-1">
                            {e}
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="flex gap-3 justify-end pt-2">
              <button
                className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => setStep("upload")}
              >
                חזור
              </button>
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={loading}
                onClick={() => void handleApply()}
              >
                {loading ? "מייבא..." : "אשר וייבא"}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === "done" && result && (
          <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg p-6 text-center space-y-3">
            <p className="text-green-700 dark:text-green-300 font-semibold text-lg">
              ייבוא הושלם בהצלחה
            </p>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              נוצרו: {result.created} · עודכנו: {result.updated} · דולגו:{" "}
              {result.skipped}
            </p>
            <button
              className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              onClick={() => {
                setStep("upload");
                setPreview(null);
                setResult(null);
              }}
            >
              ייבוא נוסף
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
}
