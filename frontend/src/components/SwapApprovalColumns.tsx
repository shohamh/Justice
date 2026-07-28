import { useTranslation } from "react-i18next";
import DirectCommanderApproval, { DirectCommanderApprovalRow, isSideSatisfied } from "./DirectCommanderApproval";

export interface SwapApprovalColumn {
  label: string;
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

const STATUS_STYLES: Record<ColumnStatus, { bg: string; text: string; icon: string }> = {
  approved: { bg: "bg-green-50 dark:bg-green-950/40", text: "text-green-700 dark:text-green-300", icon: "✓" },
  rejected: { bg: "bg-red-50 dark:bg-red-950/40", text: "text-red-600 dark:text-red-300", icon: "✗" },
  pending: { bg: "bg-amber-50 dark:bg-amber-950/40", text: "text-amber-700 dark:text-amber-300", icon: "⋯" },
  neutral: { bg: "", text: "text-gray-500 dark:text-gray-400", icon: "" },
};

function SoldierApprovalDot({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}

export default function SwapApprovalColumns({ columns }: { columns: SwapApprovalColumn[] }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex divide-x divide-x-reverse dark:divide-gray-600 border rounded dark:border-gray-600 overflow-hidden text-xs"
      dir="rtl"
    >
      {columns.map((column, i) => {
        const status = computeColumnStatus(column);
        const style = STATUS_STYLES[status];
        return (
          <div key={i} className={`flex-1 min-w-[130px] p-2 space-y-1 ${style.bg}`}>
            <div className={`flex items-center justify-between font-medium ${style.text}`}>
              <span>{column.label}</span>
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
