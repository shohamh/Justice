import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Minimal shape needed to derive per-stage ✓/✗ status from a two-step
 * (commander → duty manager) approval request. `commander_approved_by` is
 * set once the commander step completes; the final `status` tells us
 * whether the request overall was approved, rejected, or is still pending,
 * and at which step. */
export interface ApprovalStageStatus {
  status: string;
  commander_approved_by?: { name: string } | null;
  commander_approved_at?: string | null;
  commander_approval_note?: string | null;
  decision_by?: { name: string } | null;
  decision_at?: string | null;
  decision_note?: string | null;
}

type StageValue = "approved" | "rejected" | "pending" | "skipped";

function commanderStage(r: ApprovalStageStatus): StageValue {
  if (r.commander_approved_by || r.status === "pending_duty_manager" || r.status === "approved") return "approved";
  if (r.status === "rejected") return "rejected";
  return "pending";
}

function dutyManagerStage(r: ApprovalStageStatus): StageValue {
  if (r.status === "approved") return "approved";
  if (r.status === "rejected") return r.commander_approved_by ? "rejected" : "skipped";
  if (r.status === "pending_duty_manager") return "pending";
  return "skipped";
}

function StageIcon({ value, label, title, testId, details }: { value: StageValue; label: string; title?: string; testId?: string; details?: string }) {
  const [open, setOpen] = useState(false);
  const [detailsTop, setDetailsTop] = useState<number | null>(null);
  if (value === "skipped") return null;
  const symbol = value === "approved" ? "✓" : value === "rejected" ? "✗" : "…";
  const colorClass =
    value === "approved" ? "text-green-600" : value === "rejected" ? "text-red-500" : "text-gray-400";
  return (
    <span className="relative inline-flex"><button type="button" className={`inline-flex items-center gap-0.5 text-xs font-bold ${colorClass}`} title={title ?? label} data-testid={testId} aria-expanded={open} onClick={(event) => (value === "approved" || value === "rejected") && setOpen((v) => { const next = !v; setDetailsTop(next ? event.currentTarget.getBoundingClientRect().bottom + 4 : null); return next; })}>
      {symbol}
      <span className="font-normal">{label}</span>
    </button>{open && details && <span role="status" data-testid="approval-decision-details" style={{ top: detailsTop ?? 0, left: "50%", transform: "translateX(-50%)" }} className="fixed z-50 w-[calc(100vw-1rem)] max-w-[20rem] whitespace-normal break-words rounded bg-gray-900 px-2 py-1 text-right text-xs text-white shadow-lg">{details}</span>}</span>
  );
}

/** Renders ✓/✗/… icons for the commander and duty-manager approval steps of
 * a two-stage request, so a partial approval is visible at a glance instead
 * of only a generic "pending" status badge. */
export default function ApprovalStageIcons({ request }: { request: ApprovalStageStatus }) {
  const { t } = useTranslation();
  if (request.status === "cancelled") return null;
  return (
    <span className="inline-flex items-center gap-2">
      <StageIcon
        value={commanderStage(request)}
        label={t("deputies.role_commander")}
        title={request.commander_approved_by && request.commander_approved_at
          ? `אושר על ידי ${request.commander_approved_by.name} בתאריך ${new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(request.commander_approved_at))}${request.commander_approval_note ? ` · סיבה: ${request.commander_approval_note}` : ""}`
          : request.commander_approved_by ? `אושר על ידי ${request.commander_approved_by.name}${request.commander_approval_note ? ` · סיבה: ${request.commander_approval_note}` : ""}` : undefined}
        testId={request.commander_approved_by ? "commander-approval-checkmark" : request.status === "rejected" ? "commander-approval-rejection" : undefined}
        details={request.commander_approved_by
          ? `אושר על ידי ${request.commander_approved_by.name}${request.commander_approved_at ? ` בתאריך ${new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(request.commander_approved_at))}` : ""}${request.commander_approval_note ? ` · סיבה: ${request.commander_approval_note}` : ""}`
          : request.status === "rejected" && request.decision_by
          ? `נדחה על ידי ${request.decision_by.name}${request.decision_at ? ` בתאריך ${new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(request.decision_at))}` : ""}${request.decision_note ? ` · סיבה: ${request.decision_note}` : ""}`
          : request.status === "rejected" ? "נדחה" : undefined}
      />
      <StageIcon value={dutyManagerStage(request)} label={t("deputies.role_duty_manager")} />
    </span>
  );
}
