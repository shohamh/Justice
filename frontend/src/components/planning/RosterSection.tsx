import type { ReactNode } from "react";
import AssignmentRow from "./AssignmentRow";
import type { AssignmentRowData } from "./AssignmentRow";

export type RosterKind = "primary" | "reserve";

export interface RosterSectionProps {
  kind: RosterKind;
  assignments: AssignmentRowData[];
  count?: number;
  title?: ReactNode;
  emptyMessage?: ReactNode;
  assignmentActionRenderer?: (assignment: AssignmentRowData) => ReactNode;
}

export function RosterSection({ kind, assignments, count, title, emptyMessage = "אין שיבוצים", assignmentActionRenderer }: RosterSectionProps) {
  const defaultTitle = kind === "primary" ? "ראשיים" : "רזרבה";
  return (
    <section className="mb-5">
      <h4 className="mb-2 text-sm font-semibold text-gray-600 dark:text-gray-300">{title ?? defaultTitle}{count == null ? "" : ` (${assignments.length}/${count})`}</h4>
      <div className="space-y-2">
        {assignments.length === 0 ? <p className="text-xs text-gray-400">{emptyMessage}</p> : assignments.map(assignment => (
          <AssignmentRow
            key={assignment.id}
            assignment={assignment}
            actionSlot={assignmentActionRenderer?.(assignment)}
          />
        ))}
      </div>
    </section>
  );
}

export default RosterSection;