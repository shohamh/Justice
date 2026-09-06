import type { PersonalConstraintWarning } from "../api/assignments";
import { formatDate } from "../utils/formatDate";
import Tooltip from "./Tooltip";

interface Props {
  warning: PersonalConstraintWarning;
}

export default function ConstraintWarningIcon({ warning }: Props) {
  const summary = `אילוץ אישי מאושר ${formatDate(warning.start_date)}–${formatDate(warning.end_date)}`;

  return (
    <Tooltip
      className="mr-1 text-amber-500 dark:text-amber-400"
      title={summary}
      ariaLabel={summary}
      label={summary}
      content={
        <>
          <p className="text-gray-600 dark:text-gray-300">{warning.reason}</p>
          {warning.decided_by && (
            <p className="mt-1 text-gray-400 dark:text-gray-500">
              אושר ע&quot;י {warning.decided_by}
              {warning.decided_at ? ` · ${formatDate(warning.decided_at.split('T')[0])}` : ""}
            </p>
          )}
        </>
      }
    >
      ⚠️
    </Tooltip>
  );
}
