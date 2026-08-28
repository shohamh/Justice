import { useTranslation } from "react-i18next";
import SoldierLink from "./SoldierLink";

export interface DirectCommanderApprovalRow {
  commander_id: string;
  commander_name?: string | null;
  approved: boolean;
  approved_by_name?: string | null;
  approved_at?: string | null;
  rejected?: boolean;
  rejected_by_name?: string | null;
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

function ApprovalDot({ value, approvedAt }: { value: boolean | null; approvedAt?: string | null }) {
  if (value === true) {
    const title = approvalTime(approvedAt) ?? "אושר";
    return <button type="button" data-testid="approval-checkmark" className="text-green-600 font-bold" title={title} aria-label={title}>✓</button>;
  }
  if (value === false) return <span className="text-red-500 font-bold">×</span>;
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
      <ApprovalDot value={dotValue} approvedAt={displayedApprover.approved_at} />
      {rejectedRow && <span className="text-red-500 text-xs">{t("swaps.rejected_by", { name: rejectedRow.rejected_by_name ?? rejectedRow.commander_name ?? rejectedRow.commander_id.slice(0, 8) })}</span>}
    </span>
  );
}
