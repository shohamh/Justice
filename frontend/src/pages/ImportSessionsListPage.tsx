import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Layout from "../components/Layout";
import {
  type SessionSummary,
  cancelSession,
  listSessions,
  markSessionDone,
} from "../api/importSessions";

const STATUS_LABEL: Record<SessionSummary["status"], string> = {
  draft: "טיוטה",
  confirmed: "אושר",
  cancelled: "בוטל",
  done: "בוצע",
};

const STATUS_CHIP: Record<SessionSummary["status"], string> = {
  draft: "bg-yellow-100 text-yellow-700",
  confirmed: "bg-blue-100 text-blue-700",
  cancelled: "bg-gray-100 text-gray-500",
  done: "bg-green-100 text-green-700",
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("he-IL", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function ImportSessionsListPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listSessions(
        showAll ? "draft,confirmed,cancelled,done" : undefined,
      );
      setSessions(result);
    } finally {
      setLoading(false);
    }
  }, [showAll]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  async function handleCancel(id: string) {
    await cancelSession(id);
    await loadSessions();
  }

  async function handleMarkDone(id: string) {
    await markSessionDone(id);
    await loadSessions();
  }

  return (
    <Layout>
      <div className="max-w-4xl mx-auto space-y-4" dir="rtl">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">ייבוא מ-Excel</h1>
          <button
            className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700"
            onClick={() => navigate("/import/upload")}
          >
            ייבוא חדש
          </button>
        </div>

        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
          />
          הצג הכל (כולל בוצע/בוטל)
        </label>

        <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-500 border-b dark:border-gray-700">
                <th className="text-right p-3">קובץ</th>
                <th className="text-right p-3">נוצר בתאריך</th>
                <th className="text-right p-3">סטטוס</th>
                <th className="text-right p-3">סיכום</th>
                <th className="text-right p-3">פעולות</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id} className="border-b dark:border-gray-700">
                  <td className="p-3">{session.filename}</td>
                  <td className="p-3">{formatDate(session.created_at)}</td>
                  <td className="p-3">
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_CHIP[session.status]}`}
                    >
                      {STATUS_LABEL[session.status]}
                    </span>
                  </td>
                  <td className="p-3">
                    {session.row_summary.soldiers} חיילים /{" "}
                    {session.row_summary.duty_shifts} משמרות /{" "}
                    {session.row_summary.shift_templates} תבניות
                  </td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      {session.status === "draft" && (
                        <>
                          <button
                            className="text-indigo-600 hover:underline text-sm"
                            onClick={() =>
                              navigate(`/import/sessions/${session.id}`)
                            }
                          >
                            המשך
                          </button>
                          <button
                            className="text-red-600 hover:underline text-sm"
                            onClick={() => void handleCancel(session.id)}
                          >
                            בטל
                          </button>
                        </>
                      )}
                      {session.status === "confirmed" && (
                        <>
                          <button
                            className="text-indigo-600 hover:underline text-sm"
                            onClick={() =>
                              navigate(`/import/sessions/${session.id}`)
                            }
                          >
                            צפה
                          </button>
                          <button
                            className="text-green-600 hover:underline text-sm"
                            onClick={() => void handleMarkDone(session.id)}
                          >
                            סמן כבוצע
                          </button>
                        </>
                      )}
                      {(session.status === "done" ||
                        session.status === "cancelled") && (
                        <button
                          className="text-indigo-600 hover:underline text-sm"
                          onClick={() =>
                            navigate(`/import/sessions/${session.id}`)
                          }
                        >
                          צפה
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {sessions.length === 0 && !loading && (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-gray-400">
                    אין ייבואים להצגה
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Layout>
  );
}
