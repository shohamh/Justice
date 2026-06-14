import { Link } from "react-router-dom";
import { EnrollmentRequestDTO } from "../../api/enrollment";
import { SwapRequest } from "../../api/swaps";

interface Props {
  pendingEnrollments: EnrollmentRequestDTO[];
  pendingSwaps: SwapRequest[];
  pendingConstraints: number;
  pendingExemptions: number;
  pendingFieldUpdates: number;
}

function CountChip({ n }: { n: number }) {
  return (
    <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium text-xs">
      {n}
    </span>
  );
}

export default function PendingApprovalsWidget({
  pendingEnrollments, pendingSwaps, pendingConstraints, pendingExemptions, pendingFieldUpdates,
}: Props) {
  const total = pendingEnrollments.length + pendingSwaps.length + pendingConstraints + pendingExemptions + pendingFieldUpdates;
  if (total === 0) return null;

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">ממתינים לאישורך</h2>
      <ul className="space-y-2 text-sm">
        {pendingEnrollments.length > 0 && (
          <li>
            <Link to="/approvals?tab=enrollment" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות הצטרפות</span>
              <CountChip n={pendingEnrollments.length} />
            </Link>
          </li>
        )}
        {pendingSwaps.length > 0 && (
          <li>
            <Link to="/swaps?tab=pending" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות החלפה</span>
              <CountChip n={pendingSwaps.length} />
            </Link>
          </li>
        )}
        {pendingConstraints > 0 && (
          <li>
            <Link to="/approvals?tab=constraints" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות אישי</span>
              <CountChip n={pendingConstraints} />
            </Link>
          </li>
        )}
        {pendingExemptions > 0 && (
          <li>
            <Link to="/approvals?tab=exemptions" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות פטור</span>
              <CountChip n={pendingExemptions} />
            </Link>
          </li>
        )}
        {pendingFieldUpdates > 0 && (
          <li>
            <Link to="/approvals?tab=field_updates" className="flex items-center justify-between hover:text-indigo-600">
              <span>עדכוני פרופיל</span>
              <CountChip n={pendingFieldUpdates} />
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
