import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HelpCircle } from "lucide-react";
import Layout from "../components/Layout";
import TabBar from "../components/TabBar";
import CoverOfferModal from "../components/CoverOfferModal";
import ShiftDetailPanel from "../components/ShiftDetailPanel";
import SwapApprovalColumns, { SwapApprovalColumn, requesterColumn, candidateColumn } from "../components/SwapApprovalColumns";
import AskSwapModal from "../components/AskSwapModal";
import SoldierLink from "../components/SoldierLink";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import {
  SwapRequest, cancelSwap, listBoard,
  listMySwaps, listIncomingSwaps, getSwapConfig, BoardFilters,
  CoverEligibilityResult, checkCoverEligibility, soldierApproveSwap, soldierRejectSwap,
} from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, type DutyType } from "../api/dutyConfig";
import { CalendarShift, getCalendarShift } from "../api/calendar";
import { fetchTree, type NodeDTO } from "../api/hierarchy";
import { lastDutyDay } from "../utils/formatDate";
import { translateApiError } from "../utils/translateApiError";
import DateInput from "../components/DateInput";
import HierarchyTreeDropdown from "../components/HierarchyTreeDropdown";
import CheckboxListDropdown from "../components/CheckboxListDropdown";

const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  open: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  cancelled: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
};

function statusKey(status: string) {
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
function gateManagerFields(column: SwapApprovalColumn, requireManagerApproval: boolean): SwapApprovalColumn {
  if (requireManagerApproval) return column;
  return { ...column, commanderApprovals: [], dutyManagerApprovals: [], showDutyManagerRow: false };
}

function PendingApprovalCard({
  swap, requireManagerApproval, requireDutyManagerApproval, onShiftClick, t,
}: {
  swap: SwapRequest; requireManagerApproval: boolean; requireDutyManagerApproval: boolean;
  onShiftClick?: () => void; t: (k: string) => string;
}) {
  const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
  const columns: SwapApprovalColumn[] = [
    gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, swap.requesting_soldier_name ?? t("swaps.requester"), t), requireManagerApproval),
    ...liveCandidates.map((c) => gateManagerFields(candidateColumn(c, requireDutyManagerApproval, c.soldier_name ?? c.soldier_id.slice(0, 8), t), requireManagerApproval)),
  ];
  return (
    <li className="border rounded-lg p-4 space-y-3 dark:border-gray-600">
      <SwapDutyHeader swap={swap} onShiftClick={onShiftClick} />
      {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
      <div className="flex flex-wrap gap-3">
        {liveCandidates.map((c) => (
          <div key={c.id} className="flex-1 min-w-[140px]">
            <CandidateRow candidate={c} t={t} />
          </div>
        ))}
      </div>
    </li>
  );
}

function SwapDutyHeader({ swap, onShiftClick }: { swap: SwapRequest; onShiftClick?: () => void }) {
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

function CandidateRow({ candidate, t }: {
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

export default function SwapsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  const TAB_KEYS = ["mine", "board", "incoming", "pending"] as const;
  type TabKey = typeof TAB_KEYS[number];
  const rawKey = searchParams.get("tab") as TabKey | null;
  const tab = TAB_KEYS.includes(rawKey as TabKey) ? TAB_KEYS.indexOf(rawKey as TabKey) : 0;

  function setTab(next: number) {
    setSearchParams((prev) => { prev.set("tab", TAB_KEYS[next] ?? "mine"); return prev; }, { replace: true });
  }
  const [askSwapDuty, setAskSwapDuty] = useState<EffectiveDuty | null>(null);
  const [manageSwap, setManageSwap] = useState<SwapRequest | null>(null);
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  // Board filters
  const [boardFilters, setBoardFilters] = useState<BoardFilters>({});

  const queryClient = useQueryClient();

  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id, { for_swap: true }) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { for_swap: true }).catch(() => [] as EffectiveDuty[]),
    enabled: !!user,
  });
  const myDuties = dutiesQuery.data ?? [];

  const dutyTypesQuery = useQuery({
    queryKey: queryKeys.dutyTypes(),
    queryFn: () => listDutyTypes().catch(() => [] as DutyType[]),
  });
  const dutyTypeList = useMemo(() => dutyTypesQuery.data ?? [], [dutyTypesQuery.data]);
  const dutyTypes = useMemo(
    () => Object.fromEntries(dutyTypeList.map(d => [d.id, d.name])),
    [dutyTypeList],
  );

  const hierarchyNodesQuery = useQuery({
    queryKey: queryKeys.hierarchyTreeVisible(),
    queryFn: () => fetchTree().catch(() => [] as NodeDTO[]),
  });
  const hierarchyNodes = hierarchyNodesQuery.data ?? [];

  const configQuery = useQuery({
    queryKey: queryKeys.swapConfig(),
    queryFn: () => getSwapConfig().catch(() => ({ require_manager_approval: false, require_duty_manager_approval: true, max_specific_targets: 5 })),
  });
  const requireManagerApproval = configQuery.data?.require_manager_approval ?? false;
  const requireDutyManagerApproval = configQuery.data?.require_duty_manager_approval ?? true;

  const mySwapsQuery = useQuery({ queryKey: queryKeys.mySwaps(), queryFn: listMySwaps });
  const mySwaps = mySwapsQuery.data ?? [];

  const boardQuery = useQuery({
    queryKey: queryKeys.swapBoard(boardFilters as Record<string, unknown>),
    queryFn: () => listBoard(boardFilters),
  });
  const boardSwaps = useMemo(() => boardQuery.data ?? [], [boardQuery.data]);
  const boardLoading = boardQuery.isFetching;

  const incomingQuery = useQuery({ queryKey: queryKeys.incomingSwaps(), queryFn: listIncomingSwaps });
  const incomingSwaps = useMemo(() => incomingQuery.data ?? [], [incomingQuery.data]);

  const eligibilityIds = useMemo(() => {
    const ids = new Set<string>();
    for (const s of [...boardSwaps, ...incomingSwaps]) ids.add(s.duty_assignment_id);
    return Array.from(ids).sort();
  }, [boardSwaps, incomingSwaps]);

  const eligibilityQuery = useQuery({
    queryKey: queryKeys.swapCoverEligibility(eligibilityIds),
    queryFn: async () => {
      const results = await Promise.all(
        eligibilityIds.map((id) =>
          checkCoverEligibility(id)
            .then((r) => [id, r] as const)
            .catch(() => [id, { eligible: true, reason: null }] as const)
        )
      );
      return Object.fromEntries(results) as Record<string, CoverEligibilityResult>;
    },
    enabled: eligibilityIds.length > 0,
  });
  const coverEligibility = eligibilityQuery.data ?? {};

  const loadError = (mySwapsQuery.error || boardQuery.error || incomingQuery.error)
    ? "שגיאה בטעינת נתוני ההחלפות"
    : null;

  async function handleShiftClick(shiftId: string | null) {
    if (!shiftId) return;
    try {
      const shift = await getCalendarShift(shiftId);
      setSelectedShift(shift);
    } catch {
      // shift not found or no permission — silently ignore
    }
  }

  async function refreshSwapData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.swapBoard(boardFilters as Record<string, unknown>) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() }),
      user ? queryClient.invalidateQueries({ queryKey: queryKeys.effectiveDuties(user.id) }) : Promise.resolve(),
    ]);
  }

  function applyFilters(updates: Partial<BoardFilters>) {
    setBoardFilters(prev => ({ ...prev, ...updates }));
  }

  function clearFilters() {
    setBoardFilters({});
  }

  const hasActiveFilters = !!(boardFilters.dateFrom || boardFilters.dateTo || boardFilters.dutyTypeIds?.length || boardFilters.nodeIds?.length || boardFilters.eligibleOnly);

  async function handleCancel(id: string) {
    try { await cancelSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }

  const [swapRejectNote, setSwapRejectNote] = useState<Record<string, string>>({});

  async function handleSoldierApprove(id: string) {
    try { await soldierApproveSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }
  async function handleSoldierReject(id: string) {
    try {
      await soldierRejectSwap(id, swapRejectNote[id]);
      setSwapRejectNote((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refreshSwapData();
    } catch (err: unknown) {
      alert(translateApiError(err, t, "שגיאה"));
    }
  }

  const pendingApproval = [...mySwaps, ...incomingSwaps]
    .filter((s) => s.status === "open" && s.candidates.some((c) => c.status === "accepted"))
    .filter((s, i, arr) => arr.findIndex((x) => x.id === s.id) === i);

  const tabs = [t("swaps.tab_mine"), t("swaps.tab_board"), t("swaps.tab_incoming"), t("swaps.tab_pending")];

  const renderMySwapCard = (swap: SwapRequest) => {
    const liveCandidates = swap.candidates.filter((c) => c.status === "pending" || c.status === "accepted");
    const columns: SwapApprovalColumn[] = liveCandidates.length > 0
      ? [
          gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, t("swaps.mine"), t), requireManagerApproval),
          ...liveCandidates.map((c) => gateManagerFields(candidateColumn(c, requireDutyManagerApproval, c.soldier_name ?? c.soldier_id.slice(0, 8), t), requireManagerApproval)),
        ]
      : [];
    return (
    <li key={swap.id} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
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
      {swap.status === "open" && swap.requester_side_approved !== true && (
        <div className="flex gap-2 items-center">
          <button type="button" onClick={() => handleSoldierApprove(swap.id)}
            className="bg-green-600 text-white px-2 py-1 rounded text-xs">
            {t("approvals.approve")}
          </button>
          <input
            placeholder={t("approvals.decision_note")}
            value={swapRejectNote[swap.id] ?? ""}
            onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
            className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
          />
          <button type="button" onClick={() => handleSoldierReject(swap.id)}
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
          <button type="button" onClick={() => setManageSwap(swap)} className="text-indigo-600 text-xs hover:underline">
            {t("swaps.manage_button")}
          </button>
          <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
            {t("swaps.cancel")}
          </button>
        </div>
      )}
    </li>
    );
  };

  const renderBoardCard = (swap: SwapRequest) => {
    const elig = coverEligibility[swap.duty_assignment_id];
    const coverDisabled = elig != null && !elig.eligible;
    return (
      <li key={swap.id} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
        <div className="flex items-start justify-between gap-2">
          <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
          <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        {swap.requesting_soldier_name && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            <SoldierLink id={swap.requesting_soldier_id} name={swap.requesting_soldier_name} />
            {swap.requesting_soldier_node_name && (
              <span className="mr-1 text-gray-400 dark:text-gray-500"> · {swap.requesting_soldier_node_name}</span>
            )}
          </p>
        )}
        {swap.reason && <p className="text-gray-500 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
        {swap.status === "open" && (
          <button
            type="button"
            onClick={coverDisabled ? undefined : () => setCoverSwap(swap)}
            disabled={coverDisabled}
            title={coverDisabled ? (elig.reason ?? undefined) : undefined}
            className={`px-2 py-1 rounded text-xs ${coverDisabled ? "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}
          >
            {t("swaps.cover")}
          </button>
        )}
      </li>
    );
  };

  const renderIncomingCard = (swap: SwapRequest) => {
    const elig = coverEligibility[swap.duty_assignment_id];
    const coverDisabled = elig != null && !elig.eligible;
    const myCandidate = swap.candidates.find((c) => c.soldier_id === user?.id);
    const columns: SwapApprovalColumn[] = [
      ...(myCandidate ? [gateManagerFields(candidateColumn(myCandidate, requireDutyManagerApproval, t("swaps.covering"), t), requireManagerApproval)] : []),
      gateManagerFields(requesterColumn(swap, requireDutyManagerApproval, swap.requesting_soldier_name ?? t("swaps.requester"), t), requireManagerApproval),
    ];
    return (
      <li key={swap.id}
        // Just the border carries the "incoming — needs your attention" signal;
        // a full indigo background wash used to sit *underneath* each approval
        // column's own translucent status tint (amber/green/red), muddying both
        // colors together. The columns already communicate status on their own.
        className="border border-indigo-200 dark:border-indigo-800 bg-white dark:bg-gray-800 rounded p-3 text-sm space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
          <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        {columns.length > 0 && <SwapApprovalColumns columns={columns} />}
        {myCandidate && myCandidate.status === "pending" && (
          <div className="flex gap-2 items-center">
            <button type="button" onClick={() => handleSoldierApprove(swap.id)}
              className="bg-green-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.approve")}
            </button>
            <input
              placeholder={t("approvals.decision_note")}
              value={swapRejectNote[swap.id] ?? ""}
              onChange={(e) => setSwapRejectNote((prev) => ({ ...prev, [swap.id]: e.target.value }))}
              className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            />
            <button type="button" onClick={() => handleSoldierReject(swap.id)}
              className="bg-red-600 text-white px-2 py-1 rounded text-xs">
              {t("approvals.reject")}
            </button>
          </div>
        )}
        {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{t("swaps.reason")}: {swap.reason}</p>}
        {/* Marketplace-claim action — only for a viewer who ISN'T already an
            invited candidate on this request. An invited candidate has their
            own approve/reject controls above; showing this too would offer
            two overlapping ways to respond to the same invite. */}
        {!myCandidate && (
          <button
            type="button"
            onClick={coverDisabled ? undefined : () => setCoverSwap(swap)}
            disabled={coverDisabled}
            title={coverDisabled ? (elig.reason ?? undefined) : undefined}
            className={`px-2 py-1 rounded text-xs ${coverDisabled ? "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}
          >
            {t("swaps.accept_cover")}
          </button>
        )}
      </li>
    );
  };

  return (
    <Layout>
      {(openHelp) => (
      <>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6" dir="rtl" data-testid="swaps-page">
        <div className="flex items-center gap-2 mb-4">
          <h2 className="text-xl font-semibold dark:text-gray-100">{t("swaps.title")}</h2>
          <button
            type="button"
            onClick={() => openHelp("swaps")}
            aria-label={t("swaps.help_aria")}
            className="text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-300"
          >
            <HelpCircle size={16} />
          </button>
        </div>
        {loadError && (
          <p className="text-red-500 text-sm mb-3">{loadError}</p>
        )}
        <TabBar tabs={tabs} active={tab} onChange={setTab} />

        {tab === 0 && (
          <div className="space-y-4">
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{t("swaps.my_upcoming_duties")}</h3>
              {myDuties.length === 0 && <p className="text-sm text-gray-500">{t("swaps.no_duties")}</p>}
              <ul className="space-y-2">
                {myDuties.map(d => (
                  <li key={d.assignment_id} className="border rounded p-3 text-sm flex items-center justify-between gap-2 dark:border-gray-600">
                    <button
                      type="button"
                      onClick={d.shift_id ? () => handleShiftClick(d.shift_id!) : undefined}
                      className={`text-right flex-1 min-w-0 ${d.shift_id ? "hover:underline decoration-dotted underline-offset-2 cursor-pointer" : "cursor-default"}`}
                    >
                      <span className="font-medium dark:text-gray-100">{d.duty_type_name}</span>
                      <span className="text-gray-500 mr-2 text-xs" dir="ltr">
                        {(() => {
                          const last = lastDutyDay(d.end_date);
                          return d.start_date === last ? d.start_date : `${d.start_date} → ${last}`;
                        })()}
                      </span>
                    </button>
                    <button type="button" onClick={() => setAskSwapDuty(d)}
                      className="text-xs bg-indigo-600 text-white px-2 py-1 rounded hover:bg-indigo-700 shrink-0">
                      {t("swaps.ask_swap")}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            {mySwaps.length > 0 && (
              <div className="border-t pt-4 space-y-2 dark:border-gray-600">
                <h3 className="text-sm font-medium text-gray-600 dark:text-gray-400">{t("swaps.mine")}</h3>
                <ul className="space-y-2">{mySwaps.map(renderMySwapCard)}</ul>
              </div>
            )}
          </div>
        )}

        {tab === 1 && (
          <div className="space-y-3">
            {/* Filter panel */}
            <div className="bg-gray-50 dark:bg-gray-700/40 rounded-lg p-3 space-y-2 border dark:border-gray-600">
              <div className="flex flex-wrap gap-2 items-end">
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_date_from")}</label>
                  <DateInput
                    value={boardFilters.dateFrom ?? ""}
                    onChange={iso => applyFilters({
                      dateFrom: iso || undefined,
                      ...(iso && boardFilters.dateTo && iso > boardFilters.dateTo ? { dateTo: iso } : {}),
                    })}
                    max={boardFilters.dateTo || undefined}
                    className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_date_to")}</label>
                  <DateInput
                    value={boardFilters.dateTo ?? ""}
                    onChange={iso => applyFilters({
                      dateTo: iso || undefined,
                      ...(iso && boardFilters.dateFrom && iso < boardFilters.dateFrom ? { dateFrom: iso } : {}),
                    })}
                    min={boardFilters.dateFrom || undefined}
                    className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_duty_type")}</label>
                  <CheckboxListDropdown
                    items={dutyTypeList.map((dt) => ({ id: dt.id, label: dt.name }))}
                    selected={boardFilters.dutyTypeIds ?? []}
                    onChange={(ids) => applyFilters({ dutyTypeIds: ids.length > 0 ? ids : undefined })}
                    triggerLabel={t("swaps.filter_duty_type")}
                  />
                </div>
                {hierarchyNodes.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_node")}</label>
                    <HierarchyTreeDropdown
                      nodes={hierarchyNodes}
                      selected={boardFilters.nodeIds ?? []}
                      onChange={(ids) => applyFilters({ nodeIds: ids.length > 0 ? ids : undefined })}
                      triggerLabel={t("swaps.filter_node")}
                    />
                  </div>
                )}
              </div>
              <div className="flex items-center justify-between">
                <label className="flex items-center gap-2 text-xs cursor-pointer dark:text-gray-300">
                  <input
                    type="checkbox"
                    checked={boardFilters.eligibleOnly ?? false}
                    onChange={e => applyFilters({ eligibleOnly: e.target.checked || undefined })}
                  />
                  {t("swaps.filter_eligible_only")}
                </label>
                {hasActiveFilters && (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="text-xs text-indigo-600 dark:text-indigo-300 hover:underline"
                  >
                    {t("swaps.filter_clear")}
                  </button>
                )}
              </div>
            </div>

            {boardLoading ? (
              <p className="text-sm text-gray-400">{t("app.loading")}</p>
            ) : boardSwaps.length === 0 ? (
              <p className="text-sm text-gray-500">{t("swaps.none_board")}</p>
            ) : (
              <ul className="space-y-2">{boardSwaps.map(renderBoardCard)}</ul>
            )}
          </div>
        )}

        {tab === 2 && (
          <div className="space-y-2">
            {incomingSwaps.length === 0 && <p className="text-sm text-gray-500">{t("swaps.none_incoming")}</p>}
            <ul className="space-y-2">{incomingSwaps.map(renderIncomingCard)}</ul>
          </div>
        )}

        {tab === 3 && (
          <div className="space-y-2">
            {pendingApproval.length === 0 && (
              <p className="text-sm text-gray-500">{t("swaps.none_pending")}</p>
            )}
            <ul className="space-y-3">
              {pendingApproval.map((swap) => (
                <PendingApprovalCard
                  key={swap.id}
                  swap={swap}
                  requireManagerApproval={requireManagerApproval}
                  requireDutyManagerApproval={requireDutyManagerApproval}
                  onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined}
                  t={t}
                />
              ))}
            </ul>
          </div>
        )}
      </section>

      {askSwapDuty && (
        <AskSwapModal
          duty={askSwapDuty}
          dutyTypeName={askSwapDuty.duty_type_name}
          onClose={() => setAskSwapDuty(null)}
          onCreated={async () => { setAskSwapDuty(null); await refreshSwapData(); }}
        />
      )}

      {manageSwap && (
        <AskSwapModal
          duty={{
            assignment_id: manageSwap.duty_assignment_id,
            start_date: manageSwap.duty_start_date ?? manageSwap.duty_date,
            end_date: manageSwap.duty_end_date ?? manageSwap.duty_date,
          }}
          dutyTypeName={manageSwap.duty_type_name ?? ""}
          editingSwap={{
            id: manageSwap.id,
            open_to_marketplace: manageSwap.open_to_marketplace,
            candidates: manageSwap.candidates.map((c) => ({ soldier_id: c.soldier_id })),
          }}
          onClose={() => setManageSwap(null)}
          onCreated={async () => { setManageSwap(null); await refreshSwapData(); }}
        />
      )}

      {coverSwap && (
        <CoverOfferModal
          swap={coverSwap}
          myDuties={myDuties}
          dutyTypes={dutyTypes}
          onClose={() => setCoverSwap(null)}
          onDone={async () => { setCoverSwap(null); await refreshSwapData(); }}
        />
      )}

      {selectedShift && (
        <ShiftDetailPanel
          shift={selectedShift}
          onClose={() => setSelectedShift(null)}
          onRefreshNeeded={() => { setSelectedShift(null); void refreshSwapData(); }}
        />
      )}
      </>
      )}
    </Layout>
  );
}
