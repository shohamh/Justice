import { useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../auth/AuthContext";
import { getTransparencyAuthorizationScope } from "../../api/auth";
import { canPlan } from "../../auth/permissions";
import { queryKeys } from "../../queryKeys";
import { getRangeEvent, getRangeExcusalRequests, excuseRangeAssignment, decideRangeExcusal } from "../../api/ranges";
import { lookupSoldierNames } from "../../api/soldiers";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../../utils/rangeLabels";
import { formatDate } from "../../utils/formatDate";
import { EventDetailModal } from "../planning";
import RangeDetailContent from "./RangeDetailContent";

interface Props {
  rangeId: string;
  onClose: () => void;
}

export default function RangeDetailModal({ rangeId, onClose }: Props) {
  const { t } = useTranslation();
  const { user, authScopeReady } = useAuth();
  const queryClient = useQueryClient();
  const manage = canPlan(user);
  const rangeEventQuery = useQuery({
    queryKey: queryKeys.rangeEvent(rangeId),
    queryFn: () => getRangeEvent(rangeId),
  });
  const authorizationScope = authScopeReady ? getTransparencyAuthorizationScope(user) : null;
  const soldierIds = useMemo(() => {
    const ids = new Set(rangeEventQuery.data?.assignments.map(a => a.soldier_id) ?? []);
    if (rangeEventQuery.data?.responsible_duty_manager_id) {
      ids.add(rangeEventQuery.data.responsible_duty_manager_id);
    }
    return [...ids].sort();
  }, [rangeEventQuery.data]);
  const soldiersQuery = useQuery({
    queryKey: queryKeys.soldierNames(soldierIds, authorizationScope),
    queryFn: () => lookupSoldierNames(soldierIds),
    enabled: !!authorizationScope && soldierIds.length > 0,
  });
  const soldierNames = useMemo(
    () => new Map(soldiersQuery.data?.map(s => [s.id, s.full_name] as const) ?? []),
    [soldiersQuery.data],
  );
  const excusalQuery = useQuery({
    queryKey: queryKeys.rangeExcusalRequests(rangeId),
    queryFn: () => getRangeExcusalRequests(rangeId),
    enabled: !!user?.is_duty_manager,
  });
  const soldierName = (id: string) => soldierNames.get(id) ?? id;
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(rangeId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(rangeId) });
    // Excusals and attendance change who is range-ineligible; the nav badge no longer refetches per route.
    await queryClient.invalidateQueries({ queryKey: queryKeys.ineligibleSoldierCount() });
  };

  if (rangeEventQuery.isError) {
    return (
      <EventDetailModal open title={t("ranges.detail_title", "פרטי מטווח")} onClose={onClose}>
        <p role="alert" data-testid="range-detail-error" className="text-sm text-red-600 dark:text-red-400">
          {t("ranges.detail_load_error", "טעינת פרטי המטווח נכשלה")}
        </p>
      </EventDetailModal>
    );
  }

  if (!rangeEventQuery.data) return null;

  return (
    <EventDetailModal
      open
      title={rangeEventQuery.data.location}
      subtitle={`${RANGE_TYPE_LABELS[rangeEventQuery.data.range_type] ?? rangeEventQuery.data.range_type} · ${formatDate(rangeEventQuery.data.date)}`}
      onClose={onClose}
      metadata={[
        { label: "סטטוס", value: RANGE_EVENT_STATUS_LABELS[rangeEventQuery.data.status] ?? rangeEventQuery.data.status },
        { label: "שעות", value: `${rangeEventQuery.data.start_time ?? "—"}–${rangeEventQuery.data.end_time ?? "—"}` },
      ]}
    >
      {soldiersQuery.isError && (
        <div role="alert" className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
          {t("ranges.soldier_names_load_error")}
          <button
            type="button"
            onClick={() => void soldiersQuery.refetch()}
            className="mr-2 rounded border border-amber-500 px-2 py-0.5 font-medium hover:bg-amber-100 dark:hover:bg-amber-900"
          >
            {t("common.retry")}
          </button>
        </div>
      )}
      <RangeDetailContent
        event={rangeEventQuery.data}
        canManage={manage}
        canEditAttendance={rangeEventQuery.data.can_edit_attendance}
        userId={user?.id}
        soldierName={soldierName}
        excusalRequests={excusalQuery.data}
        onExcuse={async (id, reason) => {
          await excuseRangeAssignment(rangeEventQuery.data!.id, id, reason);
          await invalidate();
        }}
        onDecide={async (id, approve) => {
          await decideRangeExcusal(rangeEventQuery.data!.id, id, approve);
          await invalidate();
        }}
        onAttendance={() => { void invalidate(); }}
      />
    </EventDetailModal>
  );
}
