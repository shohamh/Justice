import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import { uploadSession } from "../api/importSessions";

export default function ImportUploadPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("יש להעלות קובץ בפורמט xlsx בלבד");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const { session_id } = await uploadSession(file);
      navigate(`/import/sessions/${session_id}`);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין");
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
            <code>soldiers</code>, <code>duty_shifts</code>,{" "}
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
      </div>
    </Layout>
  );
}
