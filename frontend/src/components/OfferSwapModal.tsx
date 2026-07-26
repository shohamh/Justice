import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { createSwap, takeDutyFree, listMySwaps, SwapRequest, EligibilityResult, getEligibleDuties, checkCoverEligibility, CoverEligibilityResult } from "../api/swaps";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";
import { useModalBackClose } from "../hooks/useModalBackClose";

interface Props {
  targetSoldierId: string;
  targetSoldierName: string;
  targetAssignmentId: string;
  targetDutyStart: string;
  targetDutyEnd: string; // exclusive end_date, per DutyShift/DutyAssignment convention
  targetDutyTypeId?: string;
  onClose: () => void;
  onDone: () => void;
}

// start/end are exclusive end_date ranges: [start, end).
function daysBetween(start: string, end: string): number {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Math.round(ms / 86400000);
}

function overlaps(aStart: string, aEnd: string, bStart: string, bEnd: string): boolean {
  return aStart < bEnd && bStart < aEnd;
}

export default function OfferSwapModal({
  targetSoldierId,
  targetSoldierName,
  targetAssignmentId,
  targetDutyStart,
  targetDutyEnd,
  targetDutyTypeId,
  onClose,
  onDone,
}: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const { user } = useAuth();
  const [mode, setMode] = useState<"swap" | "free">("swap");
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypeNames, setDutyTypeNames] = useState<Record<string, string>>({});
  const [targetDutyType, setTargetDutyType] = useState<DutyType | null>(null);
  const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [showInfo, setShowInfo] = useState(false);
  const infoRef = useRef<HTMLDivElement>(null);

  // Eligibility state
  const [conflictingDuties, setConflictingDuties] = useState<EffectiveDuty[]>([]);
  const [busyAssignmentIds, setBusyAssignmentIds] = useState<Set<string>>(new Set());
  const [serverEligibility, setServerEligibility] = useState<Record<string, EligibilityResult>>({});
  const [eligibilityLoading, setEligibilityLoading] = useState(false);
  const [freeCoverCheck, setFreeCoverCheck] = useState<CoverEligibilityResult | null>(null);
  const [freeCoverCheckLoading, setFreeCoverCheckLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    const today = new Date().toISOString().slice(0, 10);
    Promise.all([
      listEffectiveDuties(user.id, { date_from: today }),
      listDutyTypes().catch(() => [] as DutyType[]),
      listMySwaps().catch(() => [] as SwapRequest[]),
    ]).then(([duties, dts, mySwaps]) => {
      setMyDuties(duties);
      setDutyTypeNames(Object.fromEntries(dts.map((d) => [d.id, d.name])));
      if (targetDutyTypeId) {
        setTargetDutyType(dts.find((d) => d.id === targetDutyTypeId) ?? null);
      }

      // Duties that overlap with the target shift
      const conflicts = duties.filter((d) =>
        overlaps(d.start_date, d.end_date, targetDutyStart, targetDutyEnd)
      );
      setConflictingDuties(conflicts);

      // Assignments that already have an open swap → can't create another
      const busy = new Set(
        mySwaps
          .filter((s) => s.status === "open")
          .map((s) => s.duty_assignment_id)
      );
      setBusyAssignmentIds(busy);
      setLoading(false);
    });
  }, [user, targetDutyTypeId, targetDutyStart, targetDutyEnd]);

  useEffect(() => {
    setEligibilityLoading(true);
    getEligibleDuties(targetSoldierId)
      .then((results) => {
        setServerEligibility(Object.fromEntries(results.map((r) => [r.assignment_id, r])));
      })
      .catch(() => {})
      .finally(() => setEligibilityLoading(false));
  }, [targetSoldierId]);

  useEffect(() => {
    setFreeCoverCheckLoading(true);
    checkCoverEligibility(targetAssignmentId)
      .then(setFreeCoverCheck)
      .catch(() => setFreeCoverCheck({ eligible: true, reason: null }))
      .finally(() => setFreeCoverCheckLoading(false));
  }, [targetAssignmentId]);

  useEffect(() => {
    if (!showInfo) return;
    function handle(e: MouseEvent) {
      if (infoRef.current && !infoRef.current.contains(e.target as Node)) {
        setShowInfo(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [showInfo]);

  const days = daysBetween(targetDutyStart, targetDutyEnd);
  const scorePerDay = targetDutyType ? parseFloat(targetDutyType.score_per_day) : null;
  const totalPoints = scorePerDay !== null ? Math.round(scorePerDay * days * 10) / 10 : null;

  // Free take is blocked if the user has a scheduling conflict or is ineligible for the duty
  const freeConflict = conflictingDuties.length > 0;
  const freeIneligibleReason =
    !freeCoverCheckLoading && freeCoverCheck && !freeCoverCheck.eligible
      ? freeCoverCheck.reason
      : null;
  const freeBlocked = freeConflict || !!freeIneligibleReason;

  // Eligible duties to offer in swap mode:
  // - 0 conflicts → all duties (user can take on the extra shift alongside their own)
  // - 1 conflict  → only that duty (trading it away resolves the overlap)
  // - 2+ conflicts → nothing (offering just one still leaves the user double-assigned)
  const swapCandidates =
    conflictingDuties.length === 0 ? myDuties :
    conflictingDuties.length === 1 ? conflictingDuties :
    [];
  const eligibleDuties = swapCandidates.filter(
    (d) => !busyAssignmentIds.has(d.assignment_id)
  );

  async function handleSubmit() {
    setError(null);
    setWarning(null);
    try {
      if (mode === "free") {
        const result = await takeDutyFree(targetAssignmentId);
        const capNear = result.warnings?.find((w) => w.startsWith("reserve_cap_near:"));
        if (capNear) {
          const m = capNear.match(/^reserve_cap_near:(\d+)\/(\d+)\/(\d+)$/);
          if (m) {
            const headroom = parseInt(m[2]) - parseInt(m[1]);
            setWarning(t("errors.reserve_cap_near", { headroom, max: m[2], window: m[3] }));
            return;
          }
        }
      } else {
        if (!selectedDuty) return;
        await createSwap({
          duty_assignment_id: selectedDuty.assignment_id,
          target_soldier_id: targetSoldierId,
          reason: reason || null,
        });
      }
      onDone();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      if (detail) {
        const capMatch = detail.match(/^reserve_cap_exceeded:(\d+)\/(\d+)\/(\d+)$/);
        if (capMatch) {
          setError(t("errors.reserve_cap_exceeded", { current: capMatch[1], max: capMatch[2], window: capMatch[3] }));
        } else {
          setError(translateApiError(err, t, "שגיאה"));
        }
      } else {
        setError("שגיאה");
      }
    }
  }

  const canSubmit = mode === "free"
    ? !freeBlocked && !freeCoverCheckLoading
    : !!selectedDuty;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[85vh] overflow-y-auto"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">
            {t("swaps.offer_replace_title", { name: targetSoldierName })}
          </h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>

        {/* Target shift info */}
        <div className="text-xs text-gray-500 dark:text-gray-400 mb-3" dir="ltr">
          {(() => {
            const last = lastDutyDay(targetDutyEnd);
            return targetDutyStart === last ? targetDutyStart : `${targetDutyStart} → ${last}`;
          })()}
          {days > 1 && <span className="mr-1">({days} {t("swaps.days")})</span>}
        </div>

        {/* Mode selector */}
        <div className="space-y-2 mb-4">
          <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
            <input
              type="radio"
              name="offer_mode"
              checked={mode === "swap"}
              onChange={() => setMode("swap")}
            />
            {t("swaps.offer_replace_swap")}
          </label>
          <div className="flex items-center gap-2">
            <label className={`flex items-center gap-2 text-sm cursor-pointer ${freeBlocked ? "opacity-50" : "dark:text-gray-300"}`}>
              <input
                type="radio"
                name="offer_mode"
                checked={mode === "free"}
                onChange={() => !freeBlocked && setMode("free")}
                disabled={freeBlocked}
              />
              {t("swaps.offer_replace_free")}
            </label>
            <div className="relative" ref={infoRef}>
              <button
                type="button"
                className="w-5 h-5 rounded-full bg-gray-200 dark:bg-gray-600 text-gray-600 dark:text-gray-300 text-xs font-bold flex items-center justify-center hover:bg-gray-300 dark:hover:bg-gray-500"
                onClick={() => setShowInfo((v) => !v)}
                aria-label={t("swaps.free_take_info_label")}
              >
                ?
              </button>
              {showInfo && (
                <div className="absolute right-0 top-7 w-64 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg p-3 text-xs text-gray-700 dark:text-gray-200 z-10">
                  <p>{t("swaps.free_take_info", { points: totalPoints ?? "?" })}</p>
                </div>
              )}
            </div>
          </div>
          {freeConflict && mode !== "free" && (
            <p className="text-xs text-amber-600 dark:text-amber-400 pr-4">
              {t("swaps.free_blocked_conflict")}
            </p>
          )}
          {freeIneligibleReason && mode !== "free" && (
            <p className="text-xs text-amber-600 dark:text-amber-400 pr-4">
              {freeIneligibleReason}
            </p>
          )}
        </div>

        {loading ? (
          <p className="text-sm text-gray-400">{t("app.loading")}</p>
        ) : mode === "free" ? (
          totalPoints !== null && (
            <p className="text-xs text-indigo-600 dark:text-indigo-300">
              {t("swaps.free_take_points_preview", { points: totalPoints })}
            </p>
          )
        ) : eligibleDuties.length === 0 ? (
          <p className="text-sm text-gray-500">
            {conflictingDuties.length > 1
              ? t("swaps.multiple_conflicts_swap_blocked")
              : conflictingDuties.length === 1
                ? t("swaps.conflict_duties_all_busy")
                : t("swaps.no_duties")}
          </p>
        ) : (
          <div className="space-y-3">
            {conflictingDuties.length > 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                {t("swaps.must_offer_conflicting")}
              </p>
            )}
            <p className="text-xs text-gray-500">{t("swaps.select_duty_to_offer")}:</p>
            <div className="space-y-1 max-h-44 overflow-y-auto border rounded p-2 dark:border-gray-600">
              {eligibleDuties.map((d) => {
                const elig = serverEligibility[d.assignment_id];
                const isIneligible = !eligibilityLoading && elig !== undefined && !elig.eligible;
                const isMobile = navigator.maxTouchPoints > 0;
                return (
                  <label
                    key={d.assignment_id}
                    className={`flex items-center gap-2 text-xs p-1 rounded ${
                      isIneligible
                        ? "opacity-50 cursor-not-allowed border border-gray-200 dark:border-gray-700"
                        : selectedDuty?.assignment_id === d.assignment_id
                          ? "cursor-pointer bg-indigo-50 dark:bg-indigo-900"
                          : "cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
                    }`}
                    title={isIneligible && !isMobile ? (elig.reason ?? undefined) : undefined}
                    onClick={(e) => {
                      if (isIneligible && isMobile) {
                        e.preventDefault();
                        alert(elig?.reason ?? "חייל זה אינו יכול לקבל תורנות זו");
                      }
                    }}
                  >
                    <input
                      type="radio"
                      name="offer_duty"
                      checked={selectedDuty?.assignment_id === d.assignment_id}
                      onChange={() => setSelectedDuty(d)}
                      disabled={isIneligible}
                    />
                    <span className="dark:text-gray-300">
                      {dutyTypeNames[d.duty_type_id] ?? d.duty_type_id} — {d.start_date}
                      {lastDutyDay(d.end_date) !== d.start_date ? ` → ${lastDutyDay(d.end_date)}` : ""}
                    </span>
                  </label>
                );
              })}
            </div>
            <textarea
              placeholder={t("swaps.personal_message")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
          </div>
        )}

        {warning && (
          <div className="mt-3 bg-amber-50 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700 rounded p-3 text-xs text-amber-700 dark:text-amber-300 flex items-start gap-2">
            <span>⚠️</span>
            <div className="flex-1">{warning}</div>
          </div>
        )}
        {error && <p className="text-red-500 text-xs mt-2">{error}</p>}

        <div className="flex justify-end gap-2 mt-4">
          {warning ? (
            <button
              type="button"
              onClick={onDone}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
            >
              {t("app.close")}
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300"
              >
                {t("swaps.cancel")}
              </button>
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={!canSubmit}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
              >
                {t("swaps.submit_offer")}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
