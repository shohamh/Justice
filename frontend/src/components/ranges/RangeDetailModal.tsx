import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../auth/AuthContext";
import { canPlan } from "../../auth/permissions";
import { queryKeys } from "../../queryKeys";
import { getRangeEvent, getRangeExcusalRequests, excuseRangeAssignment, decideRangeExcusal } from "../../api/ranges";
import { listSoldiers } from "../../api/soldiers";
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
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const manage = canPlan(user);
  const rangeEventQuery = useQuery({
    queryKey: queryKeys.rangeEvent(rangeId),
    queryFn: () => getRangeEvent(rangeId),
  });
  const soldiersQuery = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const excusalQuery = useQuery({
    queryKey: queryKeys.rangeExcusalRequests(rangeId),
    queryFn: () => getRangeExcusalRequests(rangeId),
    enabled: !!user?.is_duty_manager,
  });
  const soldierName = (id: string) => soldiersQuery.data?.find(s => s.id === id)?.full_name ?? id;
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(rangeId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.rangeExcusalRequests(rangeId) });
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
