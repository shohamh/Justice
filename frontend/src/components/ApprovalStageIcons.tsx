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

function StageIcon({ value, label, title, testId }: { value: StageValue; label: string; title?: string; testId?: string }) {
  if (value === "skipped") return null;
  const symbol = value === "approved" ? "✓" : value === "rejected" ? "✗" : "…";
  const colorClass =
    value === "approved" ? "text-green-600" : value === "rejected" ? "text-red-500" : "text-gray-400";
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-bold ${colorClass}`} title={title ?? label} data-testid={testId}>
      {symbol}
      <span className="font-normal">{label}</span>
    </span>
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
          ? `אושר על ידי ${request.commander_approved_by.name} בתאריך ${new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(request.commander_approved_at))}`
          : request.commander_approved_by ? `אושר על ידי ${request.commander_approved_by.name}` : undefined}
        testId={request.commander_approved_by ? "commander-approval-checkmark" : undefined}
      />
      <StageIcon value={dutyManagerStage(request)} label={t("deputies.role_duty_manager")} />
    </span>
  );
}
