import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { batchAssignRange, getRangeCandidates, RangeCandidate, RangeEvent } from "../../api/ranges";
import { EventDetailModal } from "../planning";
import OverrideReasonModal from "../OverrideReasonModal";
import { formatDate } from "../../utils/formatDate";
import { translateApiError } from "../../utils/translateApiError";
import SoldierLink from "../SoldierLink";

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
  const systemReason = (candidate: RangeCandidate) => {
    const date = candidate.system_reason_date
      ? candidate.system_reason_date.split("-").reverse().join(".")
      : "";
    const templates: Record<string, [string, string]> = {
      recent: ["ranges.system_reason_recent", "מטווחים בוצעו לאחרונה, יפוג תוקף ב־{{date}}"],
      valid_expiring: ["ranges.system_reason_valid", "מטווחים בתוקף, עומדים לפוג ב־{{date}}"],
      last_completed: ["ranges.system_reason_last", "מטווח אחרון ב־{{date}}"],
      never_completed: ["ranges.system_reason_never", "מעולם לא ביצע מטווחים"],
    };
    const template = templates[candidate.system_reason_code ?? ""];
    if (template) {
      const translated = t(template[0], { date });
      return translated === template[0] ? template[1].replace("{{date}}", date) : translated;
    }
    return text(`ranges.assignment_reasons.${candidate.reason_code}`, candidate.explanation || candidate.reason_code);
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
    void Promise.allSettled(selectedEvents.map(async event => {
      try {
        return { event, response: await getRangeCandidates(event.id) };
      } catch (err) {
        throw new BulkAutoAssignError(event, err);
      }
    }))
      .then(results => {
        if (cancelled) return;
        const successful = results.flatMap(result => result.status === "fulfilled" ? [result.value] : []);
        const failures = results.flatMap(result => result.status === "rejected" && result.reason instanceof BulkAutoAssignError ? [result.reason] : []);
        if (failures.length > 0) {
          setError(failures.map(failure => {
            const detail = translateApiError(
              failure.cause,
              translationRef.current,
              translationRef.current("ranges.errors.auto_assign"),
            );
            return `${failure.event.location} (${formatDate(failure.event.date)}): ${detail}`;
          }).join("\n"));
        }
        const usedByDate = new Map<string, Set<string>>();
        const nextPlans = successful.map(({ event, response }) => {
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
      .catch(err => setError(translateApiError(err, translationRef.current, translationRef.current("ranges.errors.auto_assign", "השיבוץ האוטומטי נכשל"))))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [canManage, open, selectedEvents]);

  const totalAssignments = plans.reduce((sum, plan) => sum + plan.primaries.length + plan.reserves.length, 0);
  const personalConstraintConflict = plans.some(plan =>
    plan.primaries.concat(plan.reserves).some(candidate => candidate.personal_constraint_conflict),
  );

  function toggleCandidate(eventId: string, soldierId: string) {
    setPlans(current => current.map(plan => plan.event.id !== eventId ? plan : {
      ...plan,
      primaries: plan.primaries.filter(candidate => candidate.soldier_id !== soldierId),
      reserves: plan.reserves.filter(candidate => candidate.soldier_id !== soldierId),
    }));
  }

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
                    <thead><tr className="border-t dark:border-gray-600"><th className="p-2 w-8" aria-label={text("ranges.select_label", "בחירה")}></th><th className="p-2 text-right">{text("ranges.name_label", "חייל")}</th><th className="p-2 text-right">{text("ranges.type_label", "סוג")}</th><th className="p-2 text-right">{text("ranges.system_reason_label", "סיבת מערכת")}</th></tr></thead>
                    <tbody>
                      {plan.primaries.map(candidate => <tr key={`p-${candidate.soldier_id}`} className="border-t dark:border-gray-600"><td className="p-2"><input type="checkbox" data-testid={`bulk-auto-assign-checkbox-${candidate.soldier_id}`} checked onChange={() => toggleCandidate(plan.event.id, candidate.soldier_id)} /></td><td className="p-2"><SoldierLink id={candidate.soldier_id} name={candidate.full_name} /></td><td className="p-2">{text("ranges.primary_short", "ראשי")}</td><td className="p-2">{systemReason(candidate)}</td></tr>)}
                      {plan.reserves.map(candidate => <tr key={`r-${candidate.soldier_id}`} className="border-t dark:border-gray-600"><td className="p-2"><input type="checkbox" data-testid={`bulk-auto-assign-checkbox-${candidate.soldier_id}`} checked onChange={() => toggleCandidate(plan.event.id, candidate.soldier_id)} /></td><td className="p-2"><SoldierLink id={candidate.soldier_id} name={candidate.full_name} /></td><td className="p-2">{text("ranges.reserve_short", "רזרבה")}</td><td className="p-2">{systemReason(candidate)}</td></tr>)}
                      {plan.primaries.length + plan.reserves.length === 0 && <tr><td colSpan={4} className="p-2 text-center text-gray-400">{t("ranges.no_available_soldiers", "אין חיילים זמינים")}</td></tr>}
                    </tbody>
                  </table>
                  {shortfall(plan) > 0 && <p className="border-t p-2 text-xs text-amber-700 dark:text-amber-300">{t("ranges.auto_assign_shortfall", { count: shortfall(plan) })}</p>}
                </section>
              ))}
            </div>
            {error && <p role="alert" className="whitespace-pre-line rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
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
