import { Link } from "react-router-dom";
import { EnrollmentRequestDTO } from "../../api/enrollment";
import { SwapRequest } from "../../api/swaps";

interface Props {
  pendingEnrollments: EnrollmentRequestDTO[];
  pendingSwaps: SwapRequest[];
}

export default function PendingApprovalsWidget({ pendingEnrollments, pendingSwaps }: Props) {
  if (pendingEnrollments.length === 0 && pendingSwaps.length === 0) return null;

  return (
    <section className="bg-white rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">ממתינים לאישורך</h2>
      <ul className="space-y-2 text-sm">
        {pendingEnrollments.length > 0 && (
          <li>
            <Link to="/approvals" className="flex items-center justify-between hover:text-indigo-600">
              <span>בקשות הצטרפות ממתינות</span>
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                {pendingEnrollments.length}
              </span>
            </Link>
          </li>
        )}
        {pendingSwaps.length > 0 && (
          <li>
            <Link to="/swaps" className="flex items-center justify-between hover:text-indigo-600">
              <span>החלפות הממתינות לאישור</span>
              <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium">
                {pendingSwaps.length}
              </span>
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
