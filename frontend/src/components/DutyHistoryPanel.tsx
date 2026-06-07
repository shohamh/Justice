// frontend/src/components/DutyHistoryPanel.tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { TimelineEvent, getSoldierDutyHistory } from "../api/dutyHistory";
import { approveExemptionRequest, rejectExemptionRequest } from "../api/exemptions";
import { approveConstraint, rejectConstraint } from "../api/constraints";
import { SwapRequest, listSwapsForAssignment } from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { listDutyTypes } from "../api/dutyConfig";
import CoverOfferModal from "./CoverOfferModal";
import OfferSwapModal from "./OfferSwapModal";
import { useAuth } from "../auth/AuthContext";

type FilterType =
  | "all"
  | "assignment"
  | "cancellation"
  | "call_up"
  | "dismissal"
  | "exemption_request"
  | "personal_constraint";

const FILTER_KEYS: { type: FilterType; i18nKey: string }[] = [
  { type: "all", i18nKey: "duty_history.filter_all" },
  { type: "assignment", i18nKey: "duty_history.filter_assignments" },
  { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
  { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
  { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
  { type: "exemption_request", i18nKey: "duty_history.filter_exemption_requests" },
  { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
];

const TYPE_COLORS: Record<string, string> = {
  assignment: "border-indigo-500 bg-indigo-50 dark:bg-indigo-950",
  cancellation: "border-red-400 bg-red-50 dark:bg-red-950",
  call_up: "border-orange-400 bg-orange-50 dark:bg-orange-950",
  dismissal: "border-yellow-400 bg-yellow-50",
  exemption_request: "border-blue-400 bg-blue-50",
  personal_constraint: "border-purple-400 bg-purple-50",
};

const DOT_COLORS: Record<string, string> = {
  assignment: "bg-indigo-500",
  cancellation: "bg-red-400",
  call_up: "bg-orange-400",
  dismissal: "bg-yellow-400",
  exemption_request: "bg-blue-400",
  personal_constraint: "bg-purple-400",
};

const STATUS_BADGE: Record<string, string> = {
  published: "bg-green-100 text-green-800",
  active: "bg-green-100 text-green-800",
  approved: "bg-green-100 text-green-800",
  pending: "bg-yellow-100 text-yellow-800",
  proposed: "bg-blue-100 text-blue-800",
  algorithm_draft: "bg-blue-100 text-blue-800",
  cancelled: "bg-red-100 text-red-800",
  rejected: "bg-red-100 text-red-800",
  algorithm_rejected: "bg-red-100 text-red-800",
};

interface Props {
  soldierId: string;
  soldierName?: string;
  canManage: boolean;
  isActive: boolean;
}

function EventCard({
  e,
  isExpanded,
  onToggle,
  canManage,
  onApproveExemption,
  onRejectExemption,
  onApproveConstraint,
  onRejectConstraint,
  openSwaps,
  onCover,
  onOfferSwap,
  t,
}: {
  e: TimelineEvent;
  isExpanded: boolean;
  onToggle: (id: string) => void;
  canManage: boolean;
  onApproveExemption: (id: string) => void;
  onRejectExemption: (id: string) => void;
  onApproveConstraint: (id: string) => void;
  onRejectConstraint: (id: string) => void;
  openSwaps?: SwapRequest[];
  onCover?: (swap: SwapRequest) => void;
  onOfferSwap?: (e: TimelineEvent) => void;
  t: (key: string) => string;
}) {
  const colorClass = TYPE_COLORS[e.event_type] ?? "border-gray-300 bg-gray-50 dark:bg-gray-800";
  const dotColor = DOT_COLORS[e.event_type] ?? "bg-gray-400";
  const badgeClass = e.status ? (STATUS_BADGE[e.status] ?? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300") : null;

  return (
    <div
      key={`${e.event_type}-${e.id}`}
      className="relative flex items-start gap-3 pr-6"
      data-testid={`history-event-${e.event_type}`}
    >
      <div className={`absolute right-1 mt-2 w-4 h-4 rounded-full border-2 border-white ${dotColor}`} />
      <div
        className={`flex-1 border-r-4 rounded p-3 text-sm cursor-pointer ${colorClass}`}
        onClick={() => onToggle(e.id)}
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="font-medium">{e.title}</p>
            <p className="text-xs text-gray-500" dir="ltr">
              {e.date}{e.end_date && e.end_date !== e.date ? ` → ${e.end_date}` : ""}
            </p>
            <div className="flex gap-1 mt-1 flex-wrap">
              {e.metadata.is_reserve === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                  {t("duty_history.reserve")}
                </span>
              )}
              {e.metadata.called_up === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-orange-100 text-orange-800">
                  {t("duty_history.called_up")}
                </span>
              )}
            </div>
          </div>
          {badgeClass && (
            <span className={`text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${badgeClass}`}>
              {t(`my_requests.${e.status}`)}
            </span>
          )}
        </div>

        {e.event_type === "assignment" && onOfferSwap && (
          <div className="mt-1.5" onClick={(ev) => ev.stopPropagation()}>
            <button
              onClick={(ev) => { ev.stopPropagation(); onOfferSwap(e); }}
              className="text-xs bg-indigo-100 dark:bg-indigo-900 text-indigo-800 dark:text-indigo-200 px-2 py-0.5 rounded hover:bg-indigo-200 dark:hover:bg-indigo-800"
            >
              {t("swaps.offer_replace")}
            </button>
          </div>
        )}

        {e.event_type === "assignment" && openSwaps && openSwaps.filter((s) => s.status === "open").map((swap) => (
          <div
            key={swap.id}
            className="flex items-center gap-2 mt-1 bg-orange-50 border border-orange-200 rounded px-2 py-1 text-xs"
            onClick={(ev) => ev.stopPropagation()}
          >
            <span className="text-orange-700 flex-1">{t("unit_calendar.swap_requests_has")}</span>
            <button
              onClick={(ev) => { ev.stopPropagation(); onCover?.(swap); }}
              className="bg-orange-500 text-white px-2 py-0.5 rounded hover:bg-orange-600"
            >
              {t("swaps.cover")}
            </button>
          </div>
        ))}

        {isExpanded && (
          <div className="mt-2 space-y-1">
            {e.description && <p className="text-gray-600">{e.description}</p>}
            {e.metadata.decision_note && (
              <p className="text-gray-400 text-xs">
                {t("approvals.decision_note")}: {e.metadata.decision_note}
              </p>
            )}
            {canManage && e.status === "pending" && (
              <div className="flex gap-2 mt-2">
                {e.event_type === "exemption_request" && (
                  <>
                    <button
                      className="text-xs text-green-600 hover:underline"
                      onClick={(ev) => { ev.stopPropagation(); onApproveExemption(e.id); }}
                      data-testid={`approve-exemption-${e.id}`}
                    >
                      {t("approvals.approve")}
                    </button>
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={(ev) => { ev.stopPropagation(); onRejectExemption(e.id); }}
                      data-testid={`reject-exemption-${e.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </>
                )}
                {e.event_type === "personal_constraint" && (
                  <>
                    <button
                      className="text-xs text-green-600 hover:underline"
                      onClick={(ev) => { ev.stopPropagation(); onApproveConstraint(e.id); }}
                      data-testid={`approve-constraint-hist-${e.id}`}
                    >
                      {t("approvals.approve")}
                    </button>
                    <button
                      className="text-xs text-red-600 hover:underline"
                      onClick={(ev) => { ev.stopPropagation(); onRejectConstraint(e.id); }}
                      data-testid={`reject-constraint-hist-${e.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Timeline({
  events,
  expanded,
  onToggle,
  canManage,
  onApproveExemption,
  onRejectExemption,
  onApproveConstraint,
  onRejectConstraint,
  swapsByAssignment,
  onCover,
  onOfferSwap,
  t,
}: {
  events: TimelineEvent[];
  expanded: Set<string>;
  onToggle: (id: string) => void;
  canManage: boolean;
  onApproveExemption: (id: string) => void;
  onRejectExemption: (id: string) => void;
  onApproveConstraint: (id: string) => void;
  onRejectConstraint: (id: string) => void;
  swapsByAssignment?: Record<string, SwapRequest[]>;
  onCover?: (swap: SwapRequest) => void;
  onOfferSwap?: (e: TimelineEvent) => void;
  t: (key: string) => string;
}) {
  return (
    <div className="relative">
      <div className="absolute right-3 top-0 bottom-0 w-px bg-gray-200" />
      <div className="space-y-3">
        {events.map((e) => (
          <EventCard
            key={`${e.event_type}-${e.id}`}
            e={e}
            isExpanded={expanded.has(e.id)}
            onToggle={onToggle}
            canManage={canManage}
            onApproveExemption={onApproveExemption}
            onRejectExemption={onRejectExemption}
            onApproveConstraint={onApproveConstraint}
            onRejectConstraint={onRejectConstraint}
            openSwaps={swapsByAssignment?.[e.id]}
            onCover={onCover}
            onOfferSwap={onOfferSwap}
            t={t}
          />
        ))}
      </div>
    </div>
  );
}

export default function DutyHistoryPanel({ soldierId, soldierName, canManage, isActive }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [swapsByAssignment, setSwapsByAssignment] = useState<Record<string, SwapRequest[]>>({});
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypeNames, setDutyTypeNames] = useState<Record<string, string>>({});
  const [offerSwapEvent, setOfferSwapEvent] = useState<TimelineEvent | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await getSoldierDutyHistory(soldierId);
      if (!signal?.aborted) setEvents(data);
    } catch (err: unknown) {
      if (signal?.aborted) return;
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        setLoadError(t("common.no_permission"));
      } else {
        setLoadError(`שגיאה בטעינת ההיסטוריה (${status ?? "network"})`);
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [soldierId, t]);

  useEffect(() => {
    if (!isActive) return;
    setExpanded(new Set());
    setSwapsByAssignment({});
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [isActive, soldierId, load]);

  useEffect(() => {
    if (!isActive || soldierId === user?.id) return;
    const today = new Date().toISOString().slice(0, 10);
    const upcomingAssignments = events.filter(
      (e) => e.event_type === "assignment" && e.date >= today
    );
    if (upcomingAssignments.length === 0) return;
    Promise.all(
      upcomingAssignments.map((e) =>
        listSwapsForAssignment(e.id)
          .then((swaps) => ({ id: e.id, swaps }))
          .catch(() => ({ id: e.id, swaps: [] as SwapRequest[] }))
      )
    ).then((results) => {
      const map: Record<string, SwapRequest[]> = {};
      for (const { id, swaps } of results) {
        if (swaps.length > 0) map[id] = swaps;
      }
      setSwapsByAssignment(map);
    });
  }, [events, isActive, soldierId, user?.id]);

  async function handleOpenCoverModal(swap: SwapRequest) {
    setCoverSwap(swap);
    if (user) {
      const [duties, dts] = await Promise.all([
        listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
        listDutyTypes().catch(() => []),
      ]);
      setMyDuties(duties);
      setDutyTypeNames(Object.fromEntries(dts.map((d) => [d.id, d.name])));
    }
  }

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function handleApproveExemption(id: string) {
    try {
      await approveExemptionRequest(id);
      await load();
    } catch {
      alert("שגיאה בביצוע הפעולה");
    }
  }

  async function handleRejectExemption(id: string) {
    try {
      const note = prompt(t("approvals.decision_note"));
      if (note === null) return;
      await rejectExemptionRequest(id, note || "");
      await load();
    } catch {
      alert("שגיאה בביצוע הפעולה");
    }
  }

  async function handleApproveConstraint(id: string) {
    try {
      await approveConstraint(id);
      await load();
    } catch {
      alert("שגיאה בביצוע הפעולה");
    }
  }

  async function handleRejectConstraint(id: string) {
    try {
      const note = prompt(t("approvals.decision_note"));
      if (note === null) return;
      await rejectConstraint(id, note || "");
      await load();
    } catch {
      alert("שגיאה בביצוע הפעולה");
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-400">{t("app.loading")}</p>;
  }

  if (loadError) {
    return <p className="text-sm text-red-500">{loadError}</p>;
  }

  const today = new Date().toISOString().slice(0, 10);
  const filtered = filter === "all" ? events : events.filter((e) => e.event_type === filter);

  // upcoming: date >= today, sorted ascending (soonest first)
  const upcoming = filtered
    .filter((e) => e.date >= today)
    .sort((a, b) => a.date.localeCompare(b.date) || a.created_at.localeCompare(b.created_at));

  // past: date < today, sorted descending (most recent first)
  const past = filtered
    .filter((e) => e.date < today)
    .sort((a, b) => b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at));

  const isOtherSoldier = soldierId !== user?.id;

  const cardProps = {
    expanded,
    onToggle: toggleExpand,
    canManage,
    onApproveExemption: handleApproveExemption,
    onRejectExemption: handleRejectExemption,
    onApproveConstraint: handleApproveConstraint,
    onRejectConstraint: handleRejectConstraint,
    swapsByAssignment,
    onCover: handleOpenCoverModal,
    onOfferSwap: isOtherSoldier ? setOfferSwapEvent : undefined,
    t,
  };

  return (
    <>
    <div>
      {/* Filter chips */}
      <div className="flex flex-wrap gap-1 mb-4">
        {FILTER_KEYS.map(({ type, i18nKey }) => (
          <button
            key={type}
            onClick={() => setFilter(type)}
            className={`text-xs px-2 py-1 rounded-full border ${
              filter === type
                ? "bg-indigo-600 text-white border-indigo-600"
                : "border-gray-300 text-gray-600 hover:border-indigo-400"
            }`}
            data-testid={`history-filter-${type}`}
          >
            {t(i18nKey)}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-gray-500">{t("duty_history.empty")}</p>
      ) : (
        <div className="space-y-4">
          {/* Upcoming section */}
          <div>
            <h4 className="text-xs font-semibold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide mb-2">
              {t("duty_history.upcoming")}
            </h4>
            {upcoming.length === 0 ? (
              <p className="text-xs text-gray-400 mb-1">{t("duty_history.no_upcoming")}</p>
            ) : (
              <Timeline events={upcoming} {...cardProps} />
            )}
          </div>

          {/* Divider */}
          <div className="flex items-center gap-2 py-1">
            <div className="flex-1 h-px bg-gray-200" />
            <span className="text-xs text-gray-400">{today}</span>
            <div className="flex-1 h-px bg-gray-200" />
          </div>

          {/* Past section */}
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              {t("duty_history.past")}
            </h4>
            {past.length === 0 ? (
              <p className="text-xs text-gray-400">{t("duty_history.no_past")}</p>
            ) : (
              <Timeline events={past} {...cardProps} />
            )}
          </div>
        </div>
      )}
    </div>
    {coverSwap && (
      <CoverOfferModal
        swap={coverSwap}
        myDuties={myDuties}
        dutyTypes={dutyTypeNames}
        onClose={() => setCoverSwap(null)}
        onDone={() => setCoverSwap(null)}
      />
    )}
    {offerSwapEvent && (
      <OfferSwapModal
        targetSoldierId={soldierId}
        targetSoldierName={soldierName ?? soldierId}
        targetAssignmentId={offerSwapEvent.id}
        targetDutyStart={offerSwapEvent.date}
        targetDutyEnd={offerSwapEvent.end_date ?? offerSwapEvent.date}
        targetDutyTypeId={offerSwapEvent.metadata.duty_type_id ?? undefined}
        onClose={() => setOfferSwapEvent(null)}
        onDone={() => setOfferSwapEvent(null)}
      />
    )}
    </>
  );
}
