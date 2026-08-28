import { useState } from "react";
import type { PersonalConstraintWarning } from "../api/assignments";
import { formatDate } from "../utils/formatDate";

interface Props {
  warning: PersonalConstraintWarning;
}

export default function ConstraintWarningIcon({ warning }: Props) {
  const [open, setOpen] = useState(false);
  const summary = `אילוץ אישי מאושר ${formatDate(warning.start_date)}–${formatDate(warning.end_date)}`;

  return (
    <span className="relative inline-block mr-1">
      <button
        type="button"
        title={summary}
        aria-label={summary}
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        className="text-amber-500 dark:text-amber-400"
      >
        ⚠️
      </button>
      {open && (
        <div
          dir="rtl"
          onClick={(e) => e.stopPropagation()}
          className="absolute z-10 mt-1 w-56 rounded border bg-white p-2 text-xs shadow-lg dark:border-gray-600 dark:bg-gray-800"
        >
          <p className="font-medium">{summary}</p>
          <p className="mt-1 text-gray-600 dark:text-gray-300">{warning.reason}</p>
          {warning.decided_by && (
            <p className="mt-1 text-gray-400 dark:text-gray-500">
              אושר ע&quot;י {warning.decided_by}
              {warning.decided_at ? ` · ${formatDate(warning.decided_at.split('T')[0])}` : ""}
            </p>
          )}
        </div>
      )}
    </span>
  );
}
