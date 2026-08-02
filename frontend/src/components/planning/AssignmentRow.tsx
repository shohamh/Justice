import type { ReactNode } from "react";
import SoldierLink from "../SoldierLink";

export interface AssignmentRowData {
  id: string;
  soldierId?: string;
  soldierName: string;
  profilePictureUrl?: string | null;
  status?: ReactNode;
  isDraft?: boolean;
}

export interface AssignmentRowProps {
  assignment: AssignmentRowData;
  actionSlot?: ReactNode;
  detailSlot?: ReactNode;
}

export function AssignmentRow({ assignment, actionSlot, detailSlot }: AssignmentRowProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm dark:border-gray-600">
      <div className="flex min-w-0 items-center gap-2">
        {assignment.soldierId ? <SoldierLink id={assignment.soldierId} name={assignment.soldierName} className="font-medium" /> : <span className="font-medium">{assignment.soldierName}</span>}
        {assignment.status && <span className="text-xs text-gray-500 dark:text-gray-400">{assignment.status}</span>}
        {assignment.isDraft && <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs text-indigo-700 dark:bg-indigo-900 dark:text-indigo-200">Draft</span>}
        {detailSlot}
      </div>
      {actionSlot && <div className="flex shrink-0 items-center gap-1">{actionSlot}</div>}
    </div>
  );
}

export default AssignmentRow;
