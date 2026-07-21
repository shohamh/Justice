import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Layout from "../components/Layout";
import TabBar from "../components/TabBar";
import CoverOfferModal from "../components/CoverOfferModal";
import ShiftDetailPanel from "../components/ShiftDetailPanel";
import DirectCommanderApproval from "../components/DirectCommanderApproval";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import { useAuth } from "../auth/AuthContext";
import { queryKeys } from "../queryKeys";
import {
  SwapRequest, cancelSwap, createSwap, listBoard,
  listMySwaps, listIncomingSwaps, getSwapConfig, CreateSwapInput, BoardFilters,
  CoverEligibilityResult, checkCoverEligibility, soldierApproveSwap, soldierRejectSwap,
} from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes, type DutyType } from "../api/dutyConfig";
import { CalendarShift, getCalendarShift } from "../api/calendar";
import { fetchTree } from "../api/hierarchy";
import { SoldierDTO } from "../api/soldiers";
import { lastDutyDay } from "../utils/formatDate";

interface HierarchyNode {
  id: string;
  name: string;
}

const STATUS_COLORS: Record<string, string> = {
  applied: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  pending_approval: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  open: "bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300",
  rejected: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  cancelled: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400",
};

function statusKey(status: string) {
  const map: Record<string, string> = {
    open: "swaps.status_open",
    pending_approval: "swaps.status_pending_approval",
    applied: "swaps.status_applied",
    rejected: "swaps.status_rejected",
    cancelled: "swaps.status_cancelled",
  };
  return map[status] ?? status;
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined;
    if (first && typeof first.msg === "string") return first.msg;
  }
  return fallback;
}

function ApprovalDot({ value }: { value: boolean | null }) {
  if (value === true) return <span className="text-green-600 font-bold">✓</span>;
  if (value === false) return <span className="text-red-500 font-bold">✗</span>;
  return <span className="text-gray-400">—</span>;
}

function ApprovalBadge({ value, t }: { value: boolean | null; t: (k: string) => string }) {
  if (value === true)
    return <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300">{t("swaps.approval_approved")} ✓</span>;
  if (value === false)
    return <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-300">{t("swaps.approval_rejected")} ✗</span>;
  return <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">{t("swaps.approval_pending")}…</span>;
}

function PendingSide({
  label, name, commanderName, approved, showCommander, t,
}: {
  label: string; name: string | null | undefined; commanderName: string | null | undefined;
  approved: boolean | null; showCommander: boolean; t: (k: string) => string;
}) {
  return (
    <div className="flex-1 border rounded p-3 space-y-1.5 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/40 min-w-0">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400">{label}</p>
      <p className="text-sm font-medium dark:text-gray-100 truncate">{name ?? "—"}</p>
      {showCommander && commanderName && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t("swaps.commander_label")}: {commanderName}
        </p>
      )}
      <ApprovalBadge value={approved} t={t} />
    </div>
  );
}

function PendingApprovalCard({
  swap, requireManagerApproval, onShiftClick, t,
}: {
  swap: SwapRequest; requireManagerApproval: boolean; onShiftClick?: () => void; t: (k: string) => string;
}) {
  return (
    <li className="border rounded-lg p-4 space-y-3 dark:border-gray-600">
      <SwapDutyHeader swap={swap} onShiftClick={onShiftClick} />
      <div className="flex gap-3 items-stretch">
        <PendingSide
          label={t("swaps.side_requester")}
          name={swap.requesting_soldier_name}
          commanderName={swap.requesting_commander_name}
          approved={swap.requester_side_approved}
          showCommander={requireManagerApproval}
          t={t}
        />
        <div className="flex items-center text-gray-400 text-lg select-none">⇄</div>
        <PendingSide
          label={t("swaps.side_covering")}
          name={swap.covering_soldier_name}
          commanderName={swap.covering_commander_name}
          approved={swap.covering_side_approved}
          showCommander={requireManagerApproval}
          t={t}
        />
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

function ApprovalStatus({ swap, requireManagerApproval }: { swap: SwapRequest; requireManagerApproval: boolean }) {
  const { t } = useTranslation();
  if (!requireManagerApproval || swap.status !== "pending_approval") return null;
  return (
    <div className="text-xs text-gray-500 dark:text-gray-400 space-y-1 mt-1">
      <div className="flex flex-wrap gap-3">
        <span>{t("swaps.requester_approval")}: <ApprovalDot value={swap.requester_side_approved} /></span>
        <span>{t("swaps.covering_approval")}: <ApprovalDot value={swap.covering_side_approved} /></span>
      </div>
      <div className="flex flex-col gap-1">
        <span>{t("swaps.requester_managers")}: <DirectCommanderApproval approvals={swap.requester_manager_approvals} /></span>
        <span>{t("swaps.covering_managers")}: <DirectCommanderApproval approvals={swap.covering_manager_approvals} /></span>
      </div>
    </div>
  );
}

function AskSwapModal({
  duty, dutyTypeName, onClose, onCreated,
}: {
  duty: EffectiveDuty; dutyTypeName: string; onClose: () => void; onCreated: () => void;
}) {
  const { t } = useTranslation();
  const { enrollmentPending } = useAuth();
  const [mode, setMode] = useState<"open" | "soldier">("open");
  const [targetSoldier, setTargetSoldier] = useState<SoldierDTO | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const input: CreateSwapInput = {
        duty_assignment_id: duty.assignment_id,
        reason: reason || null,
        target_soldier_id: mode === "soldier" ? targetSoldier?.id ?? null : null,
      };
      await createSwap(input);
      onCreated();
    } catch (err: unknown) {
      setError(extractErrorMessage(err, "שגיאה"));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold dark:text-gray-100">{t("swaps.ask_swap")}: {dutyTypeName}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-3" dir="ltr">
          {(() => {
            const last = lastDutyDay(duty.end_date);
            return duty.start_date === last ? duty.start_date : `${duty.start_date} → ${last}`;
          })()}
        </p>
        {enrollmentPending && (
          <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
            בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
          </div>
        )}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
              <input type="radio" name="mode" checked={mode === "open"} onChange={() => setMode("open")} />
              {t("swaps.post_open")}
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer dark:text-gray-300">
              <input type="radio" name="mode" checked={mode === "soldier"} onChange={() => setMode("soldier")} />
              {t("swaps.send_to_soldier")}
            </label>
          </div>
          {mode === "soldier" && (
            <SoldierSearchAutocomplete
              onSelect={setTargetSoldier}
            />
          )}
          <textarea placeholder={t("swaps.personal_message")} value={reason}
            onChange={e => setReason(e.target.value)} rows={3}
            className="w-full border rounded px-2 py-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded dark:border-gray-600 dark:text-gray-300">{t("swaps.cancel")}</button>
            <button type="submit" disabled={enrollmentPending} className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{t("swaps.save")}</button>
          </div>
        </form>
      </div>
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
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);
  const [selectedShift, setSelectedShift] = useState<CalendarShift | null>(null);
  // Board filters
  const [boardFilters, setBoardFilters] = useState<BoardFilters>({});

  const queryClient = useQueryClient();

  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id).catch(() => [] as EffectiveDuty[]),
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
    queryFn: () => fetchTree().catch(() => [] as HierarchyNode[]),
  });
  const hierarchyNodes = hierarchyNodesQuery.data ?? [];

  const configQuery = useQuery({
    queryKey: queryKeys.swapConfig(),
    queryFn: () => getSwapConfig().catch(() => ({ require_manager_approval: false })),
  });
  const requireManagerApproval = configQuery.data?.require_manager_approval ?? false;

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
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }

  const [swapRejectNote, setSwapRejectNote] = useState<Record<string, string>>({});

  async function handleSoldierApprove(id: string) {
    try { await soldierApproveSwap(id); await refreshSwapData(); }
    catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }
  async function handleSoldierReject(id: string) {
    try {
      await soldierRejectSwap(id, swapRejectNote[id]);
      setSwapRejectNote((prev) => { const next = { ...prev }; delete next[id]; return next; });
      await refreshSwapData();
    } catch (err: unknown) {
      alert((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "שגיאה");
    }
  }

  const pendingApproval = [...mySwaps, ...incomingSwaps]
    .filter((s) => s.status === "pending_approval")
    .filter((s, i, arr) => arr.findIndex((x) => x.id === s.id) === i);

  const tabs = [t("swaps.tab_mine"), t("swaps.tab_board"), t("swaps.tab_incoming"), t("swaps.tab_pending")];

  const renderMySwapCard = (swap: SwapRequest) => (
    <li key={swap.id} className="border rounded p-3 text-sm space-y-1.5 dark:border-gray-600">
      <div className="flex items-start justify-between gap-2">
        <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
        <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
          {t(statusKey(swap.status))}
        </span>
      </div>
      <ApprovalStatus swap={swap} requireManagerApproval={requireManagerApproval} />
      {swap.status === "pending_approval" && swap.requester_side_approved !== true && (
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
      {swap.covering_soldier_id && swap.status === "pending_approval" && (
        <p className="text-xs text-indigo-600 dark:text-indigo-300">{t("swaps.has_cover_candidate")}</p>
      )}
      {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
      {swap.decision_note && (
        <p className="text-xs text-amber-600 dark:text-amber-400">{t("swaps.decision_note")}: {swap.decision_note}</p>
      )}
      {(swap.status === "open" || swap.status === "pending_approval") && (
        <button type="button" onClick={() => handleCancel(swap.id)} className="text-red-600 text-xs hover:underline">
          {t("swaps.cancel")}
        </button>
      )}
    </li>
  );

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
            {swap.requesting_soldier_name}
            {swap.requesting_soldier_node_name && (
              <span className="mr-1 text-gray-400 dark:text-gray-500"> · {swap.requesting_soldier_node_name}</span>
            )}
          </p>
        )}
        {swap.reason && <p className="text-gray-500 text-xs">{swap.reason}</p>}
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
    return (
      <li key={swap.id}
        className="border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950 rounded p-3 text-sm space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <SwapDutyHeader swap={swap} onShiftClick={swap.duty_shift_id ? () => handleShiftClick(swap.duty_shift_id) : undefined} />
          <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${STATUS_COLORS[swap.status] ?? ""}`}>
            {t(statusKey(swap.status))}
          </span>
        </div>
        <ApprovalStatus swap={swap} requireManagerApproval={requireManagerApproval} />
        {swap.status === "pending_approval" && swap.covering_side_approved !== true && (
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
        {swap.reason && <p className="text-gray-600 dark:text-gray-400 text-xs">{swap.reason}</p>}
        <button
          type="button"
          onClick={coverDisabled ? undefined : () => setCoverSwap(swap)}
          disabled={coverDisabled}
          title={coverDisabled ? (elig.reason ?? undefined) : undefined}
          className={`px-2 py-1 rounded text-xs ${coverDisabled ? "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed" : "bg-indigo-600 text-white hover:bg-indigo-700"}`}
        >
          {t("swaps.accept_cover")}
        </button>
      </li>
    );
  };

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6" dir="rtl" data-testid="swaps-page">
        <h2 className="text-xl font-semibold mb-4 dark:text-gray-100">{t("swaps.title")}</h2>
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
                  <input
                    type="date" lang="he"
                    value={boardFilters.dateFrom ?? ""}
                    onChange={e => applyFilters({ dateFrom: e.target.value || undefined })}
                    className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_date_to")}</label>
                  <input
                    type="date" lang="he"
                    value={boardFilters.dateTo ?? ""}
                    onChange={e => applyFilters({ dateTo: e.target.value || undefined })}
                    className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_duty_type")}</label>
                  <select
                    multiple
                    size={Math.min(4, dutyTypeList.length || 1)}
                    value={boardFilters.dutyTypeIds ?? []}
                    onChange={e => {
                      const sel = Array.from(e.target.selectedOptions).map(o => o.value);
                      applyFilters({ dutyTypeIds: sel.length > 0 ? sel : undefined });
                    }}
                    className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-[8rem]"
                  >
                    {dutyTypeList.map(dt => (
                      <option key={dt.id} value={dt.id}>{dt.name}</option>
                    ))}
                  </select>
                </div>
                {hierarchyNodes.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-gray-500 dark:text-gray-400">{t("swaps.filter_node")}</label>
                    <select
                      multiple
                      size={Math.min(4, hierarchyNodes.length)}
                      value={boardFilters.nodeIds ?? []}
                      onChange={e => {
                        const sel = Array.from(e.target.selectedOptions).map(o => o.value);
                        applyFilters({ nodeIds: sel.length > 0 ? sel : undefined });
                      }}
                      className="border rounded px-2 py-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 min-w-[8rem]"
                    >
                      {hierarchyNodes.map(n => (
                        <option key={n.id} value={n.id}>{n.name}</option>
                      ))}
                    </select>
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
    </Layout>
  );
}
