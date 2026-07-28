import { useTranslation } from "react-i18next";
import DirectCommanderApproval, { DirectCommanderApprovalRow, groupByKind, isSideSatisfied } from "./DirectCommanderApproval";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import { SwapRequest } from "../api/swaps";

export interface SwapApprovalColumn {
  label: string;
  soldierId: string;
  soldierApprovalLabel?: string;
  soldierApproved?: boolean | null;
  commanderApprovals: DirectCommanderApprovalRow[];
  dutyManagerApprovals: DirectCommanderApprovalRow[];
  showDutyManagerRow: boolean;
}

export type ColumnStatus = "approved" | "rejected" | "pending" | "neutral";
type ReqStatus = "approved" | "rejected" | "pending" | "none";

function soldierReqStatus(value?: boolean | null): ReqStatus {
  if (value === undefined) return "none";
  if (value === true) return "approved";
  if (value === false) return "rejected";
  return "pending";
}

function chainReqStatus(rows: DirectCommanderApprovalRow[]): ReqStatus {
  if (rows.length === 0) return "none";
  if (rows.some((r) => r.rejected)) return "rejected";
  if (isSideSatisfied(rows)) return "approved";
  return "pending";
}

export function computeColumnStatus(column: SwapApprovalColumn): ColumnStatus {
  const statuses: ReqStatus[] = [
    soldierReqStatus(column.soldierApproved),
    chainReqStatus(column.commanderApprovals),
    column.showDutyManagerRow ? chainReqStatus(column.dutyManagerApprovals) : "none",
  ];
  if (statuses.some((s) => s === "rejected")) return "rejected";
  if (statuses.every((s) => s === "none")) return "neutral";
  if (statuses.some((s) => s === "pending")) return "pending";
  return "approved";
}

// Any translucent warm/cool tint washed over a near-black card background
// desaturates toward mud, however light the source shade — a full-area dark
// fill just isn't legible here. Dark mode instead gets a solid, saturated
// top-border accent; the label/icon color (already -300, bright enough on
// dark) carries the rest of the signal.
//
// The `!` (important) modifier is required: the wrapper's `divide-x-reverse
// dark:divide-gray-600` sets `border-color` (the shorthand, all four sides)
// on every non-first child via Tailwind's divide-* utilities, which
// otherwise silently overrides this per-column border-top color on every
// column except the first.
const STATUS_STYLES: Record<ColumnStatus, { bg: string; text: string; icon: string }> = {
  approved: { bg: "bg-green-50 dark:bg-transparent dark:border-t-2 dark:!border-t-green-500", text: "text-green-700 dark:text-green-300", icon: "✓" },
  rejected: { bg: "bg-red-50 dark:bg-transparent dark:border-t-2 dark:!border-t-red-500", text: "text-red-600 dark:text-red-300", icon: "✗" },
  pending: { bg: "bg-amber-50 dark:bg-transparent dark:border-t-2 dark:!border-t-amber-500", text: "text-amber-700 dark:text-amber-300", icon: "⋯" },
  neutral: { bg: "", text: "text-gray-500 dark:text-gray-400", icon: "" },
};

function SoldierApprovalDot({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}

export function requesterColumn(
  swap: SwapRequest, requireDutyManagerApproval: boolean, label: string, t: (k: string) => string,
): SwapApprovalColumn {
  const groups = groupByKind(swap.requester_manager_approvals);
  return {
    label,
    soldierId: swap.requesting_soldier_id,
    soldierApprovalLabel: t("swaps.requester_approval"),
    soldierApproved: swap.requester_side_approved,
    commanderApprovals: groups.commander,
    dutyManagerApprovals: groups.duty_manager,
    showDutyManagerRow: requireDutyManagerApproval,
  };
}

export function candidateColumn(
  candidate: SwapRequest["candidates"][number], requireDutyManagerApproval: boolean, label: string, t: (k: string) => string,
): SwapApprovalColumn {
  const groups = groupByKind(candidate.manager_approvals);
  return {
    label,
    soldierId: candidate.soldier_id,
    soldierApprovalLabel: t("swaps.covering_approval"),
    soldierApproved: candidate.soldier_side_approved,
    commanderApprovals: groups.commander,
    dutyManagerApprovals: groups.duty_manager,
    showDutyManagerRow: requireDutyManagerApproval,
  };
}

export default function SwapApprovalColumns({ columns }: { columns: SwapApprovalColumn[] }) {
  const { t } = useTranslation();
  const { openSoldierModal } = useSoldierModal();
  return (
    <div
      // overflow-x-auto (not overflow-hidden): each column has a min-width
      // floor, so 3+ participants (requester + multiple candidates) can
      // exceed a narrow/mobile viewport — clipping silently dropped whole
      // columns (and the only place some candidates' names appeared) instead
      // of making them reachable by scrolling.
      className="flex divide-x divide-x-reverse dark:divide-gray-600 border rounded dark:border-gray-600 overflow-x-auto text-xs"
      dir="rtl"
    >
      {columns.map((column, i) => {
        const status = computeColumnStatus(column);
        const style = STATUS_STYLES[status];
        return (
          <div key={i} className={`flex-1 min-w-[130px] p-2 space-y-1 ${style.bg}`}>
            <div className={`flex items-center justify-between font-medium ${style.text}`}>
              <button
                type="button"
                className="hover:underline"
                onClick={(e) => { e.stopPropagation(); void openSoldierModal(column.soldierId); }}
              >
                {column.label}
              </button>
              {style.icon && <span>{style.icon}</span>}
            </div>
            <ul className="space-y-0.5 list-disc list-inside text-gray-600 dark:text-gray-300">
              {column.soldierApproved !== undefined && column.soldierApprovalLabel && (
                <li>
                  {column.soldierApprovalLabel}: <SoldierApprovalDot value={column.soldierApproved ?? null} />
                </li>
              )}
              {column.commanderApprovals.length > 0 && (
                <li>
                  {t("swaps.approver_kind_commander")}:{" "}
                  <DirectCommanderApproval approvals={column.commanderApprovals} approverKind="commander" />
                </li>
              )}
              {column.showDutyManagerRow && (
                <li>
                  {t("swaps.approver_kind_duty_manager")}:{" "}
                  <DirectCommanderApproval approvals={column.dutyManagerApprovals} approverKind="duty_manager" />
                </li>
              )}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
