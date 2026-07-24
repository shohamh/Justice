import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { uploadSession } from "../api/importSessions";
import { translateApiError } from "../utils/translateApiError";
import { validateFileSignature, XLSX_SIGNATURES } from "../utils/fileValidation";

export default function ImportUploadPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const MAX_IMPORT_BYTES = 20 * 1024 * 1024;

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("יש להעלות קובץ בפורמט xlsx בלבד");
      return;
    }
    if (file.size > MAX_IMPORT_BYTES) {
      setError("הקובץ גדול מדי — מקסימום 20 MB");
      return;
    }
    const signatureOk = await validateFileSignature(file, {
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XLSX_SIGNATURES[
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      ],
      "application/zip": XLSX_SIGNATURES["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
      "": XLSX_SIGNATURES["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    });
    if (!signatureOk) {
      setError("תוכן הקובץ אינו תואם קובץ xlsx תקין");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await uploadSession(file);
      navigate(`/import/sessions/${session_id}`);
    } catch (err: unknown) {
      setError(translateApiError(err, t, "שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <div className="max-w-3xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">ייבוא חדש</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4 text-center">
          <p className="text-gray-600 dark:text-gray-400 text-sm">
            העלה קובץ Excel עם גיליונות:{" "}
            <code>soldiers</code>, <code>duty_shifts</code>, <code>assignments</code>
          </p>
          <p>
            <a
              href="/api/import/template"
              className="text-indigo-600 hover:underline text-sm"
            >
              הורד תבנית לדוגמה ›
            </a>
          </p>
          <p>
            <Link
              to="/planning/export"
              className="text-indigo-600 hover:underline text-sm"
            >
              ייצוא המצב הנוכחי ›
            </Link>
          </p>
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
      </div>
    </Layout>
  );
}
