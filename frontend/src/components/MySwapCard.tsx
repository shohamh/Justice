// Shared swap-card building blocks, extracted from SwapsPage so other pages
// (MyRequestsPage) can render a soldier's own swap requests — with all the
// requester-side actions (cancel, soldier approve/reject, manage targets,
// shift detail) — without duplicating the markup or the invalidation logic.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import SwapApprovalColumns, {
  SwapApprovalColumn,
  requesterColumn,
  candidateColumn,
} from "./SwapApprovalColumns";
import AskSwapModal from "./AskSwapModal";
import ShiftDetailPanel from "./ShiftDetailPanel";
import SoldierLink from "./SoldierLink";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import {
  SwapRequest,
  cancelSwap,
  soldierApproveSwap,
  soldierRejectSwap,
  getSwapConfig,
} from "../api/swaps";
import type { CalendarShift } from "../api/calendar";
import { getCalendarShift } from "../api/calendar";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";

export const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  open: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  cancelled: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
};

export function statusKey(status: string) {
  const map: Record<string, string> = {
    open: "swaps.status_open",
    applied: "swaps.status_applied",
    rejected: "swaps.status_rejected",
    cancelled: "swaps.status_cancelled",
  };
  return map[status] ?? status;
}

/** Soldier-side accept/reject is independent of whether *manager* approval
 * is required — so the commander/duty-manager fields on a column are zeroed
 * out (hiding those specific bullets) only when the commander-approval
 * setting is off, while the soldier-side bullet always renders. */
export function gateManagerFields(
  column: SwapApprovalColumn,
  requireManagerApproval: boolean,
): SwapApprovalColumn {
  if (requireManagerApproval) return column;
  return { ...column, commanderApprovals: [], dutyManagerApprovals: [], showDutyManagerRow: false };
}

export function SwapDutyHeader({ swap, onShiftClick }: { swap: SwapRequest; onShiftClick?: () => void }) {
  const dutyEnd = swap.duty_end_date ? lastDutyDay(swap.duty_end_date) : swap.duty_end_date;
  const dateLabel = swap.duty_start_date && dutyEnd && swap.duty_start_date !== dutyEnd
    ? `${swap.duty_start_date} → ${dutyEnd}`
    : (swap.duty_start_date ?? swap.duty_date);

  const inner = (
    <>
      {swap.duty_type_name && (
        <span className="font-semibold dark:text-gray-100">{swap.duty_type_name}</span>
      )}
      {swap.duty_location_name && (
        <span className="text-gray-500 dark:text-gray-400 mr-1"> — {swap.duty_location_name}</span>
      )}
      <span className="text-xs text-gray-400 dark:text-gray-500 mr-2" dir="ltr">{dateLabel}</span>
    </>
  );

  if (onShiftClick) {
    return (
      <button
        type="button"
        onClick={onShiftClick}
        className="text-sm text-right hover:underline decoration-dotted underline-offset-2 cursor-pointer"
      >
        {inner}
      </button>
    );
  }
  return <div className="text-sm">{inner}</div>;
}

export function CandidateRow({ candidate, t }: {
  candidate: SwapRequest["candidates"][number];
  t: (k: string) => string;
}) {
  const sourceLabel = candidate.source === "marketplace" ? t("swaps.candidate_source_marketplace") : t("swaps.candidate_source_invited");
  return (
    <div className="border rounded p-2 text-xs space-y-1 dark:border-gray-600">
      <div className="flex items-center justify-between gap-2">
        {/* Always shown, even for a "live" candidate who also has their own
            SwapApprovalColumns column above — that column can silently clip
            off narrow (mobile) viewports since it doesn't scroll, which
            previously left the candidate's name visible nowhere at all. */}
        <SoldierLink id={candidate.soldier_id} name={candidate.soldier_name ?? candidate.soldier_id.slice(0, 8)} className="font-medium" />
        <span className="text-gray-400">{sourceLabel}</span>
      </div>
      {candidate.status === "declined" && <p className="text-red-500">{t("swaps.candidate_declined")}</p>}
      {candidate.status === "cancelled" && <p className="text-gray-400">{t("swaps.candidate_cancelled")}</p>}
      {candidate.status === "applied" && <p className="text-green-600">{t("swaps.candidate_applied")}</p>}
    </div>
  );
}

/**
 * A soldier's own swap request card, fully self-contained: renders the duty
 * header, approval columns, candidates, and every requester-side action.
 * Actions invalidate the swaps cache family (prefix match covers mine/
 * incoming/board/pending regardless of board filters) plus effective duties.
 */
export function MySwapCard({ swap }: { swap: SwapRequest }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [manageOpen, setManageOpen] = useState(false);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);

  // Fetched per-card but deduped by react-query across cards and pages.
  const configQuery = useQuery({
    queryKey: queryKeys.swapConfig(),
    queryFn: () =>
      getSwapConfig().catch(() => ({
        require_manager_approval: false,
        require_duty_manager_approval: true,
        max_specific_targets: 5,
      })),
  });
  const requireManagerApproval = configQuery.data?.require_manager_approval ?? false;
  const requireDutyManagerApproval = configQuery.data?.require_duty_manager_approval ?? true;

  async function refresh() {
    setActionError(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["swaps"] }),
      user ? queryClient.invalidateQueries({ queryKey: queryKeys.effectiveDuties(user.id) }) : Promise.resolve(),
    ]);
  }

  async function runAction(id: string, action: () => Promise<unknown>) {
    try {
      await action();
      setRejectNotes((prev) => {
        if (!(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await refresh();
    } catch (err: unknown) {
      setActionError(translateApiError(err, t, "שגיאה"));
    }
  }

  async function handleShiftClick(shiftId: string | null) {
    if (!shiftId) return;
    try {
      const shift = await getCalendarShift(shiftId);
      setSelectedShift(shift);
    } catch {
      // shift not found or no permission — silently ignore
    }
  }

  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  const columns: SwapApprovalColumn[] = liveCandidates.length > 0
    ? [
        gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, t("swaps.mine"), t), requireManagerApproval),
        ...liveCandidates.map((c) => gateManagerFields(candidateColumn(c, requireDutyManagerApproval, c.soldier_name ?? c.soldier_id.slice(0, 8), t), requireManagerApproval)),
      ]
    : [];

  return (
    <>
      <li data-testid={`swap-row-${swap.id}`} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
        {actionError && (
          <p className="text-red-500 text-xs" role="alert" data-testid="swap-action-error">{actionError}</p>
        )}
        <div className="flex items-start justify-between gap-2">
          <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
          <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
        {swap.reason && <p className="text-gray-500 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
        {swap.decision_note && (
          <p className="text-xs text-amber-600 dark:text-amber-400">{t("swaps.decision_note")}: {swap.decision_note}</p>
        )}
        {swap.status === "open" && swap.requester_side_approved !== true && liveCandidates.length > 0 && (
          <div className="flex gap-2 items-center">
            <button type="button" onClick={() => runAction(swap.id, () => soldierApproveSwap(swap.id))}
              className="bg-green-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.approve")}
            </button>
            <input
              placeholder={t("approvals.decision_note")}
              value={rejectNotes[swap.id] ?? ""}
              onChange={(e) => setRejectNotes((prev) => ({ ...prev, [swap.id]: e.target.value }))}
              className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <button type="button" onClick={() => runAction(swap.id, () => soldierRejectSwap(swap.id, rejectNotes[swap.id]))}
              className="bg-red-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.reject")}
            </button>
          </div>
        )}
        {swap.candidates.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({swap.candidates.length})</p>
            <div className="space-y-1">
              {swap.candidates.map((c) => (
                <CandidateRow key={c.id} candidate={c} t={t} />
              ))}
            </div>
          </div>
        )}
        {swap.status === "open" && (
          <div className="flex gap-3">
            <button type="button" onClick={() => setManageOpen(true)} className="text-indigo-600 text-xs hover:underline">
              {t("swaps.manage_button")}
            </button>
            <button type="button" onClick={() => runAction(swap.id, () => cancelSwap(swap.id))} className="text-red-600 text-xs hover:underline">
              {t("swaps.cancel")}
            </button>
          </div>
        )}
      </li>

      {manageOpen && (
        <AskSwapModal
          duty={{
            assignment_id: swap.duty_assignment_id,
            start_date: swap.duty_start_date ?? swap.duty_date,
            end_date: swap.duty_end_date ?? swap.duty_date,
          }}
          dutyTypeName={swap.duty_type_name ?? ""}
          editingSwap={{
            id: swap.id,
            open_to_marketplace: swap.open_to_marketplace,
            candidates: swap.candidates.map((c) => ({ soldier_id: c.soldier_id })),
          }}
          onClose={() => setManageOpen(false)}
          onCreated={async () => { setManageOpen(false); await refresh(); }}
        />
      )}

      {selectedShift && (
        <ShiftDetailPanel
          shift={selectedShift}
          onClose={() => setSelectedShift(null)}
          onRefreshNeeded={() => { setSelectedShift(null); void refresh(); }}
        />
      )}
    </>
  );
}
