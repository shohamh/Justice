import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { EnrollmentRequestDTO } from "../../api/enrollment";
import { SwapRequest } from "../../api/swaps";
import { TransferRequest } from "../../api/hierarchyTransfers";

type DashboardScope = "personal" | "command";

interface Props {
  pendingEnrollments: EnrollmentRequestDTO[];
  pendingSwaps: SwapRequest[];
  pendingConstraints: number;
  pendingExemptions: number;
  pendingFieldUpdates: number;
  pendingTransfers: TransferRequest[];
  scope?: DashboardScope;
}

function CountChip({ n }: { n: number }) {
  return (
    <span className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full font-medium text-xs">
      {n}
    </span>
  );
}

export default function PendingApprovalsWidget({
  pendingEnrollments,
  pendingSwaps,
  pendingConstraints,
  pendingExemptions,
  pendingFieldUpdates,
  pendingTransfers,
  scope = "command",
}: Props) {
  const { t } = useTranslation();
  const total = pendingEnrollments.length + pendingSwaps.length + pendingConstraints + pendingExemptions + pendingFieldUpdates + pendingTransfers.length;
  if (total === 0) return null;
  const title =
    scope === "command"
      ? t("command_dashboard.pending_approvals_scope_command")
      : t("home.pending_approvals_scope_personal");

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-4" dir="rtl">
      <h2 className="text-lg font-semibold mb-3">{title}</h2>
      <ul className="space-y-2 text-sm">
        {pendingEnrollments.length > 0 && (
          <li>
            <Link to="/approvals?tab=enrollment" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_enrollments")}</span>
              <CountChip n={pendingEnrollments.length} />
            </Link>
          </li>
        )}
        {pendingSwaps.length > 0 && (
          <li>
            <Link to="/swaps?tab=pending" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_swaps")}</span>
              <CountChip n={pendingSwaps.length} />
            </Link>
          </li>
        )}
        {pendingConstraints > 0 && (
          <li>
            <Link to="/approvals?tab=constraints" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_constraints")}</span>
              <CountChip n={pendingConstraints} />
            </Link>
          </li>
        )}
        {pendingExemptions > 0 && (
          <li>
            <Link to="/approvals?tab=exemptions" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_exemptions")}</span>
              <CountChip n={pendingExemptions} />
            </Link>
          </li>
        )}
        {pendingFieldUpdates > 0 && (
          <li>
            <Link to="/approvals?tab=field_updates" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_field_updates")}</span>
              <CountChip n={pendingFieldUpdates} />
            </Link>
          </li>
        )}
        {pendingTransfers.length > 0 && (
          <li>
            <Link to="/approvals?tab=transfers" className="flex items-center justify-between hover:text-indigo-600">
              <span>{t("command_dashboard.pending_transfers")}</span>
              <CountChip n={pendingTransfers.length} />
            </Link>
          </li>
        )}
      </ul>
    </section>
  );
}
