import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { batchAssignRange, getRangeCandidates, RangeCandidate, RangeEvent } from "../../api/ranges";
import { EventDetailModal } from "../planning";
import OverrideReasonModal from "../OverrideReasonModal";
import { formatDate } from "../../utils/formatDate";
import { translateApiError } from "../../utils/translateApiError";

interface AssignmentPlan {
  event: RangeEvent;
  primaries: RangeCandidate[];
  reserves: RangeCandidate[];
}

interface Props {
  open: boolean;
  events: RangeEvent[];
  canManage: boolean;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

class BulkAutoAssignError extends Error {
  constructor(public readonly event: RangeEvent, public readonly cause: unknown) {
    super("bulk_auto_assign_failed");
  }
}

const filled = (event: RangeEvent, reserve: boolean) =>
  reserve ? event.reserve_filled ?? event.assignments.filter(a => a.is_reserve && !a.is_draft).length
    : event.primary_filled ?? event.assignments.filter(a => !a.is_reserve && !a.is_draft).length;

export default function RangeBulkAutoAssignModal({ open, events, canManage, onClose, onChanged }: Props) {
  const { t } = useTranslation();
  const translationRef = useRef(t);
  translationRef.current = t;
  const text = (key: string, fallback: string) => {
    const translated = t(key);
    return translated === key ? fallback : translated;
  };
  const [plans, setPlans] = useState<AssignmentPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [pendingOverride, setPendingOverride] = useState(false);

  const selectedEvents = useMemo(
    () => events.filter(event => event.status === "planned").sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id)),
    [events],
  );

  useEffect(() => {
    if (!open || !canManage) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setPlans([]);
    void Promise.all(selectedEvents.map(async event => {
      try {
        return { event, response: await getRangeCandidates(event.id) };
      } catch (err) {
        throw new BulkAutoAssignError(event, err);
      }
    }))
      .then(results => {
        if (cancelled) return;
        const usedByDate = new Map<string, Set<string>>();
        const nextPlans = results.map(({ event, response }) => {
          const used = usedByDate.get(event.date) ?? new Set<string>();
          usedByDate.set(event.date, used);
          const available = response.candidates.filter(candidate =>
            candidate.auto_selectable !== false && !used.has(candidate.soldier_id),
          );
          const existingPrimary = filled(event, false);
          const existingReserve = filled(event, true);
          const primaries = available.slice(0, Math.max(0, event.required_count - existingPrimary));
          const primaryIds = new Set(primaries.map(candidate => candidate.soldier_id));
          const reserves = available
            .filter(candidate => !primaryIds.has(candidate.soldier_id))
            .slice(0, Math.max(0, event.reserve_count - existingReserve));
          primaries.concat(reserves).forEach(candidate => used.add(candidate.soldier_id));
          return { event, primaries, reserves };
        });
        setPlans(nextPlans);
      })
      .catch(err => {
        const failure = err instanceof BulkAutoAssignError ? err : null;
        if (failure) {
          const detail = translateApiError(
            failure.cause,
            translationRef.current,
            translationRef.current("ranges.errors.auto_assign"),
          );
          setError(`${failure.event.location} (${formatDate(failure.event.date)}): ${detail}`);
          return [];
        }
        throw err;
      })
      .catch(err => setError(translateApiError(err, translationRef.current, translationRef.current("ranges.errors.auto_assign", "השיבוץ האוטומטי נכשל"))))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [canManage, open, selectedEvents]);

  const totalAssignments = plans.reduce((sum, plan) => sum + plan.primaries.length + plan.reserves.length, 0);
  const personalConstraintConflict = plans.some(plan =>
    plan.primaries.concat(plan.reserves).some(candidate => candidate.personal_constraint_conflict),
  );

  async function confirm(overrideReason?: string) {
    if (saving || totalAssignments === 0) return;
    setSaving(true);
    setError("");
    try {
      for (const plan of plans) {
        if (plan.primaries.length === 0 && plan.reserves.length === 0) continue;
        try {
          await batchAssignRange(plan.event.id, {
            primaries: plan.primaries.map(candidate => candidate.soldier_id),
            reserves: plan.reserves.map(candidate => candidate.soldier_id),
            ...(overrideReason ? { override_reason: overrideReason } : {}),
          });
        } catch (err) {
          throw new BulkAutoAssignError(plan.event, err);
        }
      }
      await onChanged();
      onClose();
    } catch (err) {
      if (err instanceof BulkAutoAssignError) {
        const detail = translateApiError(
          err.cause,
          t,
          t("ranges.errors.confirm_assignments"),
        );
        setError(`${err.event.location} (${formatDate(err.event.date)}): ${detail}`);
        return;
      }
      setError(translateApiError(err, t, t("ranges.errors.confirm_assignments", "אישור השיבוצים נכשל")));
    } finally {
      setSaving(false);
      setPendingOverride(false);
    }
  }

  const shortfall = (plan: AssignmentPlan) =>
    Math.max(0, plan.event.required_count - filled(plan.event, false) - plan.primaries.length) +
    Math.max(0, plan.event.reserve_count - filled(plan.event, true) - plan.reserves.length);

  return (
    <>
      <EventDetailModal
        open={open}
        title={t("ranges.bulk_auto_assign_title", "שיבוץ אוטומטי למספר מטווחים")}
        subtitle={text("ranges.bulk_auto_assign_subtitle", `${selectedEvents.length} מטווחים נבחרו`)}
        onClose={onClose}
      >
        {loading ? <p className="text-sm text-gray-500">{t("ranges.loading_candidates", "טוען מועמדים...")}</p> : (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {text("ranges.bulk_auto_assign_summary", "המועמדים המדורגים ביותר נבחרו לכל מטווח. מטווחים באותו יום אינם חולקים חיילים.")}
            </p>
            <div className="max-h-[55vh] overflow-y-auto space-y-3">
              {plans.map(plan => (
                <section key={plan.event.id} className="rounded border dark:border-gray-600">
                  <header className="flex items-center justify-between gap-2 bg-gray-50 px-3 py-2 text-sm dark:bg-gray-700">
                    <span className="font-medium">{plan.event.location}</span>
                    <span className="text-gray-500 dark:text-gray-300">{formatDate(plan.event.date)}</span>
                  </header>
                  <table className="w-full text-xs">
                    <thead><tr className="border-t dark:border-gray-600"><th className="p-2 text-right">{t("ranges.name_label", "חייל")}</th><th className="p-2 text-right">{t("ranges.type_label", "סוג")}</th></tr></thead>
                    <tbody>
                      {plan.primaries.map(candidate => <tr key={`p-${candidate.soldier_id}`} className="border-t dark:border-gray-600"><td className="p-2">{candidate.full_name}</td><td className="p-2">{t("ranges.primary_short", "ראשי")}</td></tr>)}
                      {plan.reserves.map(candidate => <tr key={`r-${candidate.soldier_id}`} className="border-t dark:border-gray-600"><td className="p-2">{candidate.full_name}</td><td className="p-2">{t("ranges.reserve_short", "רזרבה")}</td></tr>)}
                      {plan.primaries.length + plan.reserves.length === 0 && <tr><td colSpan={2} className="p-2 text-center text-gray-400">{t("ranges.no_available_soldiers", "אין חיילים זמינים")}</td></tr>}
                    </tbody>
                  </table>
                  {shortfall(plan) > 0 && <p className="border-t p-2 text-xs text-amber-700 dark:text-amber-300">{t("ranges.auto_assign_shortfall", { count: shortfall(plan) })}</p>}
                </section>
              ))}
            </div>
            {error && <p role="alert" className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} disabled={saving} className="rounded border px-3 py-1.5 text-sm dark:border-gray-600">{t("ranges.close", "סגור")}</button>
              <button type="button" data-testid="confirm-bulk-auto-assign" onClick={() => personalConstraintConflict ? setPendingOverride(true) : void confirm()} disabled={saving || totalAssignments === 0} className="rounded bg-green-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
                {saving ? t("ranges.saving", "שומר...") : `${t("ranges.confirm_all", "אשר הכל")} (${totalAssignments})`}
              </button>
            </div>
          </div>
        )}
      </EventDetailModal>
      <OverrideReasonModal open={pendingOverride} count={totalAssignments} onCancel={() => setPendingOverride(false)} onConfirm={reason => void confirm(reason)} />
    </>
  );
}
