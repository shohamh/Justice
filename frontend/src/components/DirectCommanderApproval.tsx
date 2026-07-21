import { useTranslation } from "react-i18next";
import SoldierLink from "./SoldierLink";

/** Minimal shape needed from SwapManagerApproval (see api/swaps.ts) to render
 * the direct-commander-approval widget, kept structural so callers don't
 * need to import the full SwapManagerApproval type. */
export interface DirectCommanderApprovalRow {
  commander_id: string;
  commander_name?: string | null;
  approved: boolean;
  approved_by_name?: string | null;
  approver_kind?: "commander" | "duty_manager";
}

/** Splits a flat list of approval rows into per-kind groups so callers can
 * render commander and duty-manager approval status as separate rows. */
export function groupByKind(approvals: (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]) {
  return {
    commander: approvals.filter((a) => a.approver_kind === "commander"),
    duty_manager: approvals.filter((a) => a.approver_kind === "duty_manager"),
  };
}

/** A side (requester/covering) is satisfied if it has no required chain
 * commanders at all, or if any one of them has approved — matching the
 * backend's "any single chain commander suffices" semantics. */
export function isSideSatisfied(approvals: DirectCommanderApprovalRow[]): boolean {
  return approvals.length === 0 || approvals.some((a) => a.approved);
}

function ApprovalDot({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}

/**
 * Shows only the soldier's direct (nearest) commander for one side of a swap
 * — approvals[0] is guaranteed nearest-first by the backend — while still
 * reflecting whether the side as a whole is satisfied (any chain commander
 * approving counts, not just the direct one). If someone other than the
 * direct commander was the one who actually approved, a small note names
 * them.
 */
export default function DirectCommanderApproval({
  approvals,
}: {
  approvals: DirectCommanderApprovalRow[];
}) {
  const { t } = useTranslation();
  if (approvals.length === 0) {
    return <span className="text-gray-400">{t("swaps.no_managers_required")}</span>;
  }
  const direct = approvals[0];
  const satisfied = isSideSatisfied(approvals);
  const approvedByOther = !direct.approved ? approvals.find((a) => a.approved) : undefined;

  return (
    <span className="inline-flex items-center gap-1 flex-wrap">
      <SoldierLink id={direct.commander_id} name={direct.commander_name ?? direct.commander_id.slice(0, 8)} />
      <ApprovalDot value={satisfied ? true : null} />
      {approvedByOther && (
        <span className="text-gray-400 text-xs">
          {t("swaps.approved_by_other", {
            name: approvedByOther.approved_by_name ?? approvedByOther.commander_name ?? approvedByOther.commander_id.slice(0, 8),
          })}
        </span>
      )}
    </span>
  );
}
