import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { queryKeys } from "../queryKeys";
import Layout from "../components/Layout";
import {
  HakpazaSoldierRosterItemDTO,
  SoldierDTO,
  getSoldier,
  isStaleHakpazaSoldierRosterCursorError,
  listHakpazaSoldierRosterPage,
} from "../api/soldiers";
import { Assignment, listAssignments } from "../api/assignments";
import { Candidate, createHakpaza, findCandidates } from "../api/hakpaza";
import { formatDate, formatDutyRange, lastDutyDay, todayIso } from "../utils/formatDate";
import DateInput from "../components/DateInput";

type Step = 1 | 2 | 3 | 4 | 5;

const DISTANCE_LABEL: Record<number, string> = {
  0: "אותו מדור",
  1: "מדור אחות",
  2: "ענף אחר",
};

const PICKER_ROW_HEIGHT = 56;
const PICKER_VIEWPORT_HEIGHT = 240;
const PICKER_OVERSCAN = 6;

export default function HakpazaPage() {
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>(1);
  const [pulledSoldier, setPulledSoldier] = useState<Pick<SoldierDTO, "id" | "full_name" | "rank"> | null>(null);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selectedAssignment, setSelectedAssignment] = useState<Assignment | null>(null);
  const [pullDate, setPullDate] = useState("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [soldierSearch, setSoldierSearch] = useState("");
  const [debouncedSoldierSearch, setDebouncedSoldierSearch] = useState("");
  const [rosterScrollTop, setRosterScrollTop] = useState(0);
  const rosterListRef = useRef<HTMLDivElement>(null);
  const restartingStaleRosterRef = useRef(false);

  const today = todayIso();

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedSoldierSearch(soldierSearch), 250);
    return () => window.clearTimeout(timeout);
  }, [soldierSearch]);

  const rosterQuery = useInfiniteQuery({
    queryKey: queryKeys.hakpazaSoldierRoster(today, debouncedSoldierSearch),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => listHakpazaSoldierRosterPage({
      as_of_date: today,
      search: debouncedSoldierSearch,
      page_size: 100,
      cursor: pageParam ?? undefined,
      signal,
    }),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  });
  const rosterItems = rosterQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const staleRosterContinuationError =
    rosterQuery.isFetchNextPageError &&
    isStaleHakpazaSoldierRosterCursorError(rosterQuery.error);
  const retryableRosterContinuationError =
    rosterQuery.isFetchNextPageError && !staleRosterContinuationError;
  const searchIsPending = soldierSearch !== debouncedSoldierSearch;
  const pickerItems = searchIsPending ? [] : rosterItems;
  const rosterWindowStart = Math.max(
    0,
    Math.floor(rosterScrollTop / PICKER_ROW_HEIGHT) - PICKER_OVERSCAN,
  );
  const rosterWindowEnd = Math.min(
    pickerItems.length,
    Math.ceil((rosterScrollTop + PICKER_VIEWPORT_HEIGHT) / PICKER_ROW_HEIGHT) + PICKER_OVERSCAN,
  );
  const visibleRosterItems = pickerItems.slice(rosterWindowStart, rosterWindowEnd);

  useEffect(() => {
    setRosterScrollTop(0);
    if (rosterListRef.current) rosterListRef.current.scrollTop = 0;
  }, [debouncedSoldierSearch]);

  useEffect(() => {
    if (
      step === 1 &&
      rosterWindowEnd >= pickerItems.length - 12 &&
      rosterQuery.hasNextPage &&
      !rosterQuery.isFetchingNextPage &&
      !rosterQuery.isFetchNextPageError
    ) {
      void rosterQuery.fetchNextPage();
    }
  }, [
    step,
    rosterWindowEnd,
    pickerItems.length,
    rosterQuery.hasNextPage,
    rosterQuery.isFetchingNextPage,
    rosterQuery.isFetchNextPageError,
    rosterQuery.fetchNextPage,
  ]);

  useEffect(() => {
    if (!rosterQuery.isFetchNextPageError) {
      restartingStaleRosterRef.current = false;
      return;
    }
    if (
      restartingStaleRosterRef.current ||
      !isStaleHakpazaSoldierRosterCursorError(rosterQuery.error)
    ) {
      return;
    }
    restartingStaleRosterRef.current = true;
    void queryClient.resetQueries({
      queryKey: queryKeys.hakpazaSoldierRoster(today, debouncedSoldierSearch),
      exact: true,
    });
  }, [
    queryClient,
    today,
    debouncedSoldierSearch,
    rosterQuery.isFetchNextPageError,
    rosterQuery.error,
  ]);

  // Pre-fill from ?soldierId=&assignmentId= (deep link, e.g. a "הקפץ" button
  // elsewhere in the app). Applied once, on mount — a soldier picked manually
  // afterwards must not be overridden by a stale query-param re-application.
  const soldierIdParam = searchParams.get("soldierId");
  const assignmentIdParam = searchParams.get("assignmentId");
  const hasPrefillParams = !!soldierIdParam && !!assignmentIdParam;
  const prefillAppliedRef = useRef(false);

  const prefillSoldierQuery = useQuery({
    queryKey: queryKeys.soldierDetail(soldierIdParam ?? "none"),
    queryFn: () => getSoldier(soldierIdParam!),
    enabled: hasPrefillParams,
  });
  const prefillAssignmentsQuery = useQuery({
    queryKey: queryKeys.assignments(soldierIdParam ?? "none", { date_from: today }),
    queryFn: () => listAssignments(soldierIdParam!, { date_from: today }),
    enabled: hasPrefillParams,
  });

  useEffect(() => {
    if (!hasPrefillParams || prefillAppliedRef.current) return;
    if (prefillSoldierQuery.isPending || prefillAssignmentsQuery.isPending) return;
    prefillAppliedRef.current = true;

    if (prefillSoldierQuery.isError || prefillAssignmentsQuery.isError || !prefillSoldierQuery.data) {
      setError("לא נמצאה התורנות המבוקשת — בחר חייל ידנית");
      return;
    }
    const published = (prefillAssignmentsQuery.data ?? []).filter((a) => a.status === "published");
    const match = published.find((a) => a.id === assignmentIdParam);
    setPulledSoldier(prefillSoldierQuery.data);
    setAssignments(published);
    if (match) {
      setSelectedAssignment(match);
      setPullDate(match.start_date >= today ? match.start_date : today);
      setStep(2);
    } else {
      setError("לא נמצאה התורנות המבוקשת — בחר חייל ידנית");
    }
  }, [
    hasPrefillParams,
    assignmentIdParam,
    today,
    prefillSoldierQuery.isPending,
    prefillSoldierQuery.isError,
    prefillSoldierQuery.data,
    prefillAssignmentsQuery.isPending,
    prefillAssignmentsQuery.isError,
    prefillAssignmentsQuery.data,
  ]);

  async function handleSoldierSelect(
    soldier: Pick<SoldierDTO, "id" | "full_name" | "rank"> | null,
  ) {
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
      const asgns = await queryClient.fetchQuery({
        queryKey: queryKeys.assignments(soldier.id, { date_from: today }),
        queryFn: () => listAssignments(soldier.id, { date_from: today }),
      });
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
      if (pulledSoldier) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.assignments(pulledSoldier.id, { date_from: today }) });
      }
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
      <div className="space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">הקפצה פיקודית</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
        )}

        {/* Explanation */}
        <div className="bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-lg p-4 text-sm space-y-2" dir="rtl">
          <p className="font-semibold text-blue-800 dark:text-blue-200">מה זה הקפצה פיקודית?</p>
          <p className="text-blue-700 dark:text-blue-300">
            הקפצה פיקודית מיועדת לנסיבות חריגות מבצעיות או אישיות בלבד.
            המערכת מחפשת את המחליף המתאים ביותר לפי ניקוד, ומציגה את הרשימה לבחירה.
            הבקשה עוברת לאישור מנהל תורניות לפני הפעלה.
          </p>
        </div>

        {/* Step 1: Select soldier */}
        <div className={`bg-white dark:bg-gray-800 rounded-lg shadow p-4 space-y-3 ${step > 1 ? "opacity-60" : ""}`}>
          <h2 className="font-medium text-sm text-gray-500">שלב 1 — בחר חייל להקפיץ</h2>
          {step === 1 ? (
            <div className="space-y-2">
              <input
                type="text"
                placeholder="חיפוש לפי שם..."
                value={soldierSearch}
                onChange={(e) => setSoldierSearch(e.target.value)}
                className="w-full border rounded p-2 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                dir="rtl"
              />
              {(rosterQuery.isPending || searchIsPending) && (
                <p className="text-xs text-gray-400 px-3 py-1">
                  {searchIsPending ? "מחפש חיילים..." : "טוען תורנויות..."}
                </p>
              )}
              {rosterQuery.isError && !rosterQuery.isFetchNextPageError && (
                <p className="text-sm text-red-600 p-2 text-right">שגיאה בטעינת החיילים</p>
              )}
              <div
                ref={rosterListRef}
                className="h-60 overflow-y-auto border rounded dark:border-gray-700"
                onScroll={(event) => setRosterScrollTop(event.currentTarget.scrollTop)}
                aria-busy={rosterQuery.isFetchingNextPage || searchIsPending}
              >
                {pickerItems.length === 0 &&
                !rosterQuery.isPending &&
                !searchIsPending &&
                !rosterQuery.isError ? (
                  <p className="text-sm text-gray-500 p-3 text-right">לא נמצאו חיילים</p>
                ) : (
                  <div>
                    <div style={{ height: rosterWindowStart * PICKER_ROW_HEIGHT }} aria-hidden="true" />
                    {visibleRosterItems.map((soldier: HakpazaSoldierRosterItemDTO) => (
                      <button
                        data-testid={`hakpaza-soldier-${soldier.id}`}
                        key={soldier.id}
                        type="button"
                        style={{ height: PICKER_ROW_HEIGHT }}
                        className="w-full shrink-0 border-b border-gray-100 px-3 py-2 text-right text-sm hover:bg-indigo-50 dark:border-gray-700 dark:hover:bg-indigo-950 flex items-center justify-between gap-2"
                        onClick={() => { void handleSoldierSelect(soldier); }}
                      >
                        <div className="text-right">
                          <span className="font-medium">{soldier.full_name}</span>
                          {soldier.rank && <span className="text-xs text-gray-400 mr-1">{soldier.rank}</span>}
                          {soldier.next_shift_date ? (
                            <p className="text-xs text-indigo-600 dark:text-indigo-300 mt-0.5">
                              {soldier.next_shift_type_name ?? "תורנות"} — {formatDate(soldier.next_shift_date)}
                            </p>
                          ) : (
                            <p className="text-xs text-gray-400 mt-0.5">אין תורנות קרובה</p>
                          )}
                        </div>
                      </button>
                    ))}
                    <div
                      style={{ height: (pickerItems.length - rosterWindowEnd) * PICKER_ROW_HEIGHT }}
                      aria-hidden="true"
                    />
                  </div>
                )}
              </div>
              {rosterQuery.isFetchingNextPage && (
                <p className="text-xs text-gray-400 px-3 py-1">טוען עוד חיילים...</p>
              )}
              {retryableRosterContinuationError && (
                <button
                  type="button"
                  className="text-xs text-indigo-600 hover:underline px-3 py-1"
                  onClick={() => { void rosterQuery.fetchNextPage(); }}
                >
                  {t("common.retry")}
                </button>
              )}
            </div>
          ) : (
            pulledSoldier && (
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">{pulledSoldier.full_name}</p>
                <button
                  type="button"
                  className="text-xs text-indigo-600 hover:underline"
                  onClick={() => { setPulledSoldier(null); setStep(1); setAssignments([]); setSelectedAssignment(null); setSoldierSearch(""); }}
                >
                  שנה
                </button>
              </div>
            )
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
                    data-testid={`hakpaza-assignment-${a.id}`}
                    className={`flex items-center gap-3 p-2 border rounded cursor-pointer ${
                      selectedAssignment?.id === a.id
                        ? "border-indigo-500 bg-indigo-50 dark:bg-indigo-950"
                        : "border-gray-200 dark:border-gray-700"
                    }`}
                  >
                      <input
                        data-testid={`hakpaza-assignment-radio-${a.id}`}
                      type="radio"
                      name="assignment"
                      onChange={() => {
                        setSelectedAssignment(a);
                        setPullDate(a.start_date >= today ? a.start_date : today);
                      }}
                    />
                    <span className="text-sm">{formatDutyRange(a.start_date, a.end_date)}</span>
                  </label>
                ))}
              </div>
            )}

            {selectedAssignment && selectedAssignment.start_date < today && (
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  תאריך הקפצה (מתי החייל יוחלף):
                </label>
                <DateInput
                  min={today}
                  max={lastDutyDay(selectedAssignment.end_date)}
                  value={pullDate}
                  onChange={(isoValue) => setPullDate(isoValue)}
                  className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                />
              </div>
            )}

            {step === 2 && (
              <button
                data-testid="hakpaza-find-candidates"
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
                        data-testid={`hakpaza-candidate-${c.soldier_id}`}
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
                        <td className="py-1">{c.current_score.toFixed(3)}</td>
                        <td className="py-1">{c.recent_forced_callups_decayed.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {step === 3 && selectedCandidate && (
              <button
                data-testid="hakpaza-review-candidate"
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
                {formatDutyRange(pullDate || selectedAssignment.start_date, selectedAssignment.end_date)}
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
                data-testid="hakpaza-back-to-candidates"
                className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => setStep(3)}
              >
                חזור
              </button>
              <button
                data-testid="hakpaza-submit"
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
