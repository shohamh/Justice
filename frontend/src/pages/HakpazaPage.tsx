import { useState } from "react";
import Layout from "../components/Layout";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import { SoldierDTO } from "../api/soldiers";
import { Assignment, listAssignments } from "../api/assignments";
import { Candidate, createHakpaza, findCandidates } from "../api/hakpaza";
import { formatDateRange } from "../utils/formatDate";

type Step = 1 | 2 | 3 | 4 | 5;

const DISTANCE_LABEL: Record<number, string> = {
  0: "אותו מדור",
  1: "מדור אחות",
  2: "ענף אחר",
};

export default function HakpazaPage() {
  const [step, setStep] = useState<Step>(1);
  const [pulledSoldier, setPulledSoldier] = useState<SoldierDTO | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selectedAssignment, setSelectedAssignment] = useState<Assignment | null>(null);
  const [pullDate, setPullDate] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const today = new Date().toISOString().split("T")[0];

  async function handleSoldierSelect(soldier: SoldierDTO | null) {
    if (!soldier) {
      setPulledSoldier(null);
      setStep(1);
      setAssignments([]);
      setSelectedAssignment(null);
      return;
    }
    setPulledSoldier(soldier);
    setLoading(true);
    setError(null);
    try {
      const asgns = await listAssignments(soldier.id, { date_from: today });
      setAssignments(asgns.filter((a) => a.status === "published"));
      setStep(2);
    } catch {
      setError("שגיאה בטעינת תורנויות החייל");
    } finally {
      setLoading(false);
    }
  }

  async function handleFindCandidates() {
    if (!selectedAssignment) return;
    setLoading(true);
    setError(null);
    try {
      const effectivePullDate = pullDate || selectedAssignment.start_date;
      const cands = await findCandidates(selectedAssignment.id, effectivePullDate);
      setCandidates(cands);
      setStep(3);
    } catch {
      setError("שגיאה בחיפוש מחליפים");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit() {
    if (!selectedAssignment || !selectedCandidate) return;
    setLoading(true);
    setError(null);
    try {
      await createHakpaza(
        selectedAssignment.id,
        pullDate || selectedAssignment.start_date,
        selectedCandidate.soldier_id,
      );
      setDone(true);
      setStep(5);
    } catch {
      setError("שגיאה ביצירת בקשת ההקפצה");
    } finally {
      setLoading(false);
    }
  }

  function handleReset() {
    setStep(1);
    setPulledSoldier(null);
    setAssignments([]);
    setSelectedAssignment(null);
    setPullDate("");
    setCandidates([]);
    setSelectedCandidate(null);
    setDone(false);
    setError(null);
  }

  return (
    <Layout>
      <div className="max-w-2xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">הקפצה פיקודית</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
        )}

        {/* Step 1: Select soldier */}
        <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 1 ? "opacity-60" : ""}`}>
          <h2 className="font-medium text-sm text-gray-500">שלב 1 — בחר חייל להקפיץ</h2>
          {step === 1 ? (
            <SoldierSearchAutocomplete
              onSelect={(s) => { void handleSoldierSelect(s); }}
              onCreateNew={() => {}}
            />
          ) : (
            pulledSoldier && <p className="text-sm font-medium">{pulledSoldier.full_name}</p>
          )}
        </div>

        {/* Step 2: Select assignment + pull date */}
        {step >= 2 && (
          <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 2 ? "opacity-60" : ""}`}>
            <h2 className="font-medium text-sm text-gray-500">שלב 2 — בחר תורנות ותאריך הקפצה</h2>
            {assignments.length === 0 ? (
              <p className="text-sm text-gray-500">אין תורנויות עתידיות לחייל זה</p>
            ) : (
              <div className="space-y-2">
                {assignments.map((a) => (
                  <label
                    key={a.id}
                    className={`flex items-center gap-3 p-2 border rounded cursor-pointer ${
                      selectedAssignment?.id === a.id
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
                        : "border-gray-200 dark:border-gray-700"
                    }`}
                  >
                    <input
                      type="radio"
                      name="assignment"
                      onChange={() => {
                        setSelectedAssignment(a);
                        setPullDate(a.start_date >= today ? a.start_date : today);
                      }}
                    />
                    <span className="text-sm">{formatDateRange(a.start_date, a.end_date)}</span>
                  </label>
                ))}
              </div>
            )}

            {selectedAssignment && selectedAssignment.start_date < today && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  תאריך הקפצה (מתי החייל יוחלף):
                </label>
                <input
                  type="date"
                  min={today}
                  max={selectedAssignment.end_date}
                  value={pullDate}
                  onChange={(e) => setPullDate(e.target.value)}
                  className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </div>
            )}

            {step === 2 && (
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={!selectedAssignment || loading}
                onClick={() => void handleFindCandidates()}
              >
                {loading ? "מחפש מחליפים..." : "חפש מחליפים ›"}
              </button>
            )}
          </div>
        )}

        {/* Step 3: Candidates table */}
        {step >= 3 && (
          <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 3 ? "opacity-60" : ""}`}>
            <h2 className="font-medium text-sm text-gray-500">
              שלב 3 — בחר מחליף ({candidates.length} אפשרויות)
            </h2>
            {candidates.length === 0 ? (
              <p className="text-sm text-gray-500">לא נמצאו מחליפים כשירים</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b dark:border-gray-700">
                      <th className="text-right pb-1 w-6"></th>
                      <th className="text-right pb-1">שם</th>
                      <th className="text-right pb-1">מדור</th>
                      <th className="text-right pb-1">קרבה</th>
                      <th className="text-right pb-1">ניקוד</th>
                      <th className="text-right pb-1">הקפצות אחרונות</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c) => (
                      <tr
                        key={c.soldier_id}
                        className={`border-b dark:border-gray-700 cursor-pointer ${
                          selectedCandidate?.soldier_id === c.soldier_id
                            ? "bg-indigo-50 dark:bg-indigo-950"
                            : "hover:bg-gray-50 dark:hover:bg-gray-700"
                        }`}
                        onClick={() => setSelectedCandidate(c)}
                      >
                        <td className="py-1">
                          <input
                            type="radio"
                            name="candidate"
                            checked={selectedCandidate?.soldier_id === c.soldier_id}
                            onChange={() => setSelectedCandidate(c)}
                          />
                        </td>
                        <td className="py-1 font-medium">{c.full_name}</td>
                        <td className="py-1">{c.hierarchy_node_name}</td>
                        <td className="py-1">{DISTANCE_LABEL[c.hierarchy_distance] ?? `${c.hierarchy_distance} רמות`}</td>
                        <td className="py-1">{c.current_score.toFixed(1)}</td>
                        <td className="py-1">{c.recent_forced_callups_decayed.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {step === 3 && selectedCandidate && (
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700"
                onClick={() => setStep(4)}
              >
                המשך עם {selectedCandidate.full_name} ›
              </button>
            )}
          </div>
        )}

        {/* Step 4: Confirmation */}
        {step === 4 && selectedCandidate && selectedAssignment && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3">
            <h2 className="font-medium text-sm text-gray-500">שלב 4 — אישור הקפצה</h2>
            <div className="bg-amber-50 dark:bg-amber-950 rounded p-3 text-sm space-y-1">
              <p>
                <span className="text-gray-500">חייל מוקפץ: </span>
                <strong>{selectedCandidate.full_name}</strong>
              </p>
              <p>
                <span className="text-gray-500">תורנות: </span>
                {formatDateRange(pullDate || selectedAssignment.start_date, selectedAssignment.end_date)}
              </p>
              <p>
                <span className="text-gray-500">ימים: </span>
                {selectedCandidate.days_remaining}
              </p>
              <p className="text-xs text-gray-500 mt-2">
                הבקשה תישלח לאישור מנהל תורניות. עד אז השיבוץ המקורי נשאר בתוקף.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => setStep(3)}
              >
                חזור
              </button>
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={loading}
                onClick={() => void handleSubmit()}
              >
                {loading ? "שולח..." : "שלח לאישור"}
              </button>
            </div>
          </div>
        )}

        {/* Step 5: Done */}
        {step === 5 && done && (
          <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg p-6 text-center space-y-3">
            <p className="text-green-700 dark:text-green-300 font-semibold">בקשת ההקפצה נשלחה</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              מנהל התורניות יאשר את ההחלפה. תישלח הודעה בסיום.
            </p>
            <button
              className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              onClick={handleReset}
            >
              הקפצה חדשה
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
}
