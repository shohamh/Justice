import { useState } from "react";
import { useTranslation } from "react-i18next";
import SoldierLink from "./SoldierLink";

export interface DirectCommanderApprovalRow {
  commander_id: string;
  commander_name?: string | null;
  approved: boolean;
  approved_by_name?: string | null;
  approved_at?: string | null;
  decision_note?: string | null;
  rejected?: boolean;
  rejected_by_name?: string | null;
  rejected_at?: string | null;
  rejected_note?: string | null;
  approver_kind?: "commander" | "duty_manager";
}

export function groupByKind(approvals: (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]) {
  return {
    commander: approvals.filter((a) => a.approver_kind === "commander"),
    duty_manager: approvals.filter((a) => a.approver_kind === "duty_manager"),
  };
}

export function isSideSatisfied(approvals: DirectCommanderApprovalRow[]): boolean {
  return approvals.length === 0 || approvals.some((a) => a.approved);
}

function approvalTime(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  return new Intl.DateTimeFormat("he-IL", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function ApprovalDot({ value, approvedBy, approvedAt, note, testId }: { value: boolean | null; approvedBy?: string | null; approvedAt?: string | null; note?: string | null; testId?: string }) {
  const [open, setOpen] = useState(false);
  const [detailsTop, setDetailsTop] = useState<number | null>(null);
  const when = approvalTime(approvedAt);
  const verb = value === false ? "נדחה" : "אושר";
  const title = approvedBy && when ? `${verb} על ידי ${approvedBy} בתאריך ${when}` : approvedBy ? `${verb} על ידי ${approvedBy}` : when ? `${verb} בתאריך ${when}` : verb;
  const details = [approvedBy && `${verb} על ידי: ${approvedBy}`, when && `מתי: ${when}`, note && `סיבה: ${note}`].filter(Boolean).join(" · ");
  if (value === true) {
    return <span className="relative inline-flex"><button type="button" data-testid={testId ?? "approval-checkmark"} className="text-green-600 font-bold" title={title} aria-label={title} aria-expanded={open} onClick={(event) => setOpen((v) => { const next = !v; setDetailsTop(next ? event.currentTarget.getBoundingClientRect().bottom + 4 : null); return next; })}>✓</button>{open && <span role="status" data-testid="approval-decision-details" style={{ top: detailsTop ?? 0, left: "50%", transform: "translateX(-50%)" }} className="fixed z-50 w-[calc(100vw-1rem)] max-w-[20rem] whitespace-normal break-words rounded bg-gray-900 px-2 py-1 text-right text-xs text-white shadow-lg">{details || "אושר"}</span>}</span>;
  }
  if (value === false) return <span className="relative inline-flex"><button type="button" data-testid={testId ?? "approval-rejection"} className="text-red-500 font-bold" title={title} aria-label={title} aria-expanded={open} onClick={(event) => setOpen((v) => { const next = !v; setDetailsTop(next ? event.currentTarget.getBoundingClientRect().bottom + 4 : null); return next; })}>×</button>{open && <span role="status" data-testid="approval-decision-details" style={{ top: detailsTop ?? 0, left: "50%", transform: "translateX(-50%)" }} className="fixed z-50 w-[calc(100vw-1rem)] max-w-[20rem] whitespace-normal break-words rounded bg-gray-900 px-2 py-1 text-right text-xs text-white shadow-lg">{details || "נדחה"}</span>}</span>;
  return <span className="text-gray-400">—</span>;
}

export default function DirectCommanderApproval({
  approvals,
  approverKind = "commander",
}: {
  approvals: DirectCommanderApprovalRow[];
  approverKind?: "commander" | "duty_manager";
}) {
  const { t } = useTranslation();
  if (approvals.length === 0) {
    const emptyKey = approverKind === "duty_manager" ? "swaps.no_duty_manager_assigned" : "swaps.no_managers_required";
    return <span className="text-gray-400">{t(emptyKey)}</span>;
  }
  const direct = approvals[0];
  const satisfied = isSideSatisfied(approvals);
  const approvedByOther = !direct.approved ? approvals.find((a) => a.approved) : undefined;
  const displayedApprover = approvedByOther ?? direct;
  const rejectedRow = approvals.find((a) => a.rejected);
  const dotValue = rejectedRow ? false : satisfied ? true : null;

  return (
    <span className="inline-flex items-center gap-1 flex-wrap">
      <SoldierLink id={displayedApprover.commander_id} name={displayedApprover.approved_by_name ?? displayedApprover.commander_name ?? displayedApprover.commander_id.slice(0, 8)} />
      <ApprovalDot testId={dotValue === false ? "approval-rejection" : undefined} value={dotValue} approvedBy={dotValue === false ? rejectedRow?.rejected_by_name ?? rejectedRow?.commander_name : displayedApprover.approved_by_name ?? displayedApprover.commander_name} approvedAt={dotValue === false ? rejectedRow?.rejected_at : displayedApprover.approved_at} note={dotValue === false ? rejectedRow?.rejected_note ?? rejectedRow?.decision_note : displayedApprover.decision_note} />
      {rejectedRow && <span className="text-red-500 text-xs">{t("swaps.rejected_by", { name: rejectedRow.rejected_by_name ?? rejectedRow.commander_name ?? rejectedRow.commander_id.slice(0, 8) })}</span>}
    </span>
  );
}
