// frontend/src/components/DutyHistoryPanel.tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { TimelineEvent, getSoldierDutyHistory } from "../api/dutyHistory";
import { approveExemptionRequest, rejectExemptionRequest } from "../api/exemptions";
import { approveConstraint, rejectConstraint } from "../api/constraints";
import { acceptProposalDirect, rejectProposalDirect } from "../api/algorithm";
import { SwapRequest, listSwapsForAssignment } from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import CoverOfferModal from "./CoverOfferModal";
import OfferSwapModal from "./OfferSwapModal";
import { useAuth } from "../auth/AuthContext";

type FilterType =
  | "all"
  | "assignment"
  | "algorithm_draft"
  | "cancellation"
  | "call_up"
  | "dismissal"
  | "exemption"
  | "exemption_request"
  | "personal_constraint";

type StatusFilter = "all" | "published" | "draft" | "reserve" | "official";

const FILTER_KEYS: { type: FilterType; i18nKey: string }[] = [
  { type: "all", i18nKey: "duty_history.filter_all" },
  { type: "assignment", i18nKey: "duty_history.filter_assignments" },
  { type: "algorithm_draft", i18nKey: "duty_history.filter_drafts" },
  { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
  { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
  { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
  { type: "exemption", i18nKey: "duty_history.filter_exemptions" },
  { type: "exemption_request", i18nKey: "duty_history.filter_exemption_requests" },
  { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
];

const TYPE_COLORS: Record<string, string> = {
  assignment: "border-indigo-500 bg-indigo-50 dark:bg-indigo-950",
  cancellation: "border-red-400 bg-red-50 dark:bg-red-950",
  call_up: "border-orange-400 bg-orange-50 dark:bg-orange-950",
  dismissal: "border-yellow-400 bg-yellow-50 dark:bg-yellow-950",
  exemption: "border-teal-400 bg-teal-50 dark:bg-teal-950",
  exemption_request: "border-blue-400 bg-blue-50 dark:bg-blue-950",
  personal_constraint: "border-purple-400 bg-purple-50 dark:bg-purple-950",
};

const DOT_COLORS: Record<string, string> = {
  assignment: "bg-indigo-500",
  cancellation: "bg-red-400",
  call_up: "bg-orange-400",
  dismissal: "bg-yellow-400",
  exemption: "bg-teal-400",
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

interface ScoreSegment {
  days: number;
  spd: string;
  mult: string;
  type: "regular" | "reserve_standby" | "reserve_called_up" | "forced_call_up" | "dismissed";
}

const SEGMENT_CHIP_COLORS: Record<ScoreSegment["type"], string> = {
  regular: "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200",
  reserve_standby: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  reserve_called_up: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200",
  forced_call_up: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  dismissed: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
};

const SEGMENT_LABELS: Record<ScoreSegment["type"], string> = {
  regular: "רגיל",
  reserve_standby: "רזרבה",
  reserve_called_up: "הוקפץ מרזרבה",
  forced_call_up: "הקפצה פיקודית",
  dismissed: "שוחרר",
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
  onAcceptDraft,
  onRejectDraft,
  dutyType,
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
  onAcceptDraft?: (id: string) => void;
  onRejectDraft?: (id: string) => void;
  dutyType?: DutyType | null;
  t: (key: string) => string;
}) {
  const colorClass = TYPE_COLORS[e.event_type] ?? "border-gray-300 bg-gray-50 dark:bg-gray-800";
  const dotColor = DOT_COLORS[e.event_type] ?? "bg-gray-400";
  const badgeClass = e.status ? (STATUS_BADGE[e.status] ?? "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300") : null;
  const scoreSegments: ScoreSegment[] | null = (() => {
    try {
      const raw = e.metadata.score_segments;
      if (!raw) return null;
      return JSON.parse(raw) as ScoreSegment[];
    } catch {
      return null;
    }
  })();

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
          <div className="flex flex-col items-end gap-1 shrink-0">
            {e.status === "algorithm_draft" && (
              <span className="text-xs px-1.5 py-0.5 rounded whitespace-nowrap bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 font-medium">
                {t("duty_history.draft_badge")}
              </span>
            )}
            {badgeClass && e.status !== "algorithm_draft" && (
              <span className={`text-xs px-1.5 py-0.5 rounded whitespace-nowrap ${badgeClass}`}>
                {t(`my_requests.${e.status}`)}
              </span>
            )}
            {e.metadata.score_total != null && (
              <span
                className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 whitespace-nowrap"
                data-testid={`score-badge-${e.id}`}
              >
                {e.metadata.score_total} ניקוד
              </span>
            )}
          </div>
        </div>

        {e.event_type === "assignment" && e.status !== "algorithm_draft" && onOfferSwap && (
          <div className="mt-1.5" onClick={(ev) => ev.stopPropagation()}>
            <button
              onClick={(ev) => { ev.stopPropagation(); onOfferSwap(e); }}
              className="text-xs bg-indigo-100 dark:bg-indigo-900 text-indigo-800 dark:text-indigo-200 px-2 py-0.5 rounded hover:bg-indigo-200 dark:hover:bg-indigo-800"
            >
              {t("swaps.offer_replace")}
            </button>
          </div>
        )}

        {e.event_type === "assignment" && e.status !== "algorithm_draft" && openSwaps && openSwaps.filter((s) => s.status === "open").map((swap) => (
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
            {(e.event_type === "exemption_request" || e.event_type === "exemption") && (() => {
              const raw = e.metadata.exempted_duty_types;
              if (!raw) return null;
              let names: string[] = [];
              try { names = JSON.parse(raw) as string[]; } catch { return null; }
              if (names.length === 0) return null;
              return (
                <div className="text-xs text-gray-500 dark:text-gray-400 border-t border-gray-200 dark:border-gray-600 pt-1 mt-1">
                  <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                  <span>{names.join("، ")}</span>
                </div>
              );
            })()}
            {dutyType && (() => {
              const hasInfo = dutyType.start_time || dutyType.end_time || dutyType.contact_name || dutyType.contact_phone || dutyType.instructions;
              if (!hasInfo && !dutyType) return null;
              return (
                <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5 border-t border-gray-200 dark:border-gray-600 pt-1 mt-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${dutyType.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                      {dutyType.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                    </span>
                    {(dutyType.start_time || dutyType.end_time) && (
                      <span dir="ltr">{dutyType.start_time?.slice(0, 5) ?? "?"}–{dutyType.end_time?.slice(0, 5) ?? "?"}</span>
                    )}
                    {dutyType.contact_name && <span>{dutyType.contact_name}</span>}
                    {dutyType.contact_phone && (
                      <a href={`tel:${dutyType.contact_phone}`} className="text-indigo-600 dark:text-indigo-300" onClick={(ev) => ev.stopPropagation()}>{dutyType.contact_phone}</a>
                    )}
                  </div>
                  {dutyType.instructions && (
                    <p className="mt-0.5 whitespace-pre-wrap">{dutyType.instructions}</p>
                  )}
                </div>
              );
            })()}
            {e.metadata.score_total != null && (
              <div data-testid={`score-formula-${e.id}`}>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  ניקוד:{" "}
                  {e.metadata.score_formula
                    ? `${e.metadata.score_formula} = ${e.metadata.score_total}`
                    : e.metadata.score_total}
                </p>
                {scoreSegments && scoreSegments.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {scoreSegments.map((seg, i) => (
                      <span
                        key={i}
                        className={`text-xs px-1.5 py-0.5 rounded ${SEGMENT_CHIP_COLORS[seg.type]}`}
                      >
                        {SEGMENT_LABELS[seg.type]} ×{seg.mult}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
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
            {canManage && e.status === "algorithm_draft" && (
              <div className="flex gap-2 mt-2">
                <button
                  className="text-xs text-green-600 hover:underline"
                  onClick={(ev) => { ev.stopPropagation(); onAcceptDraft?.(e.id); }}
                  data-testid={`accept-draft-${e.id}`}
                >
                  {t("approvals.approve")}
                </button>
                <button
                  className="text-xs text-red-600 hover:underline"
                  onClick={(ev) => { ev.stopPropagation(); onRejectDraft?.(e.id); }}
                  data-testid={`reject-draft-${e.id}`}
                >
                  {t("approvals.reject")}
                </button>
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
  onAcceptDraft,
  onRejectDraft,
  dutyTypeById,
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
  onAcceptDraft?: (id: string) => void;
  onRejectDraft?: (id: string) => void;
  dutyTypeById: Record<string, DutyType>;
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
            onAcceptDraft={onAcceptDraft}
            onRejectDraft={onRejectDraft}
            dutyType={e.metadata.duty_type_id ? (dutyTypeById[e.metadata.duty_type_id] ?? null) : null}
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
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [swapsByAssignment, setSwapsByAssignment] = useState<Record<string, SwapRequest[]>>({});
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypeNames, setDutyTypeNames] = useState<Record<string, string>>({});
  const [dutyTypeById, setDutyTypeById] = useState<Record<string, DutyType>>({});
  const [offerSwapEvent, setOfferSwapEvent] = useState<TimelineEvent | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await getSoldierDutyHistory(soldierId, canManage);
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
  }, [soldierId, canManage, t]);

  useEffect(() => {
    if (!isActive) return;
    setExpanded(new Set());
    setSwapsByAssignment({});
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [isActive, soldierId, load]);

  useEffect(() => {
    if (!isActive) return;
    listDutyTypes()
      .then((dts) => setDutyTypeById(Object.fromEntries(dts.map((d) => [d.id, d]))))
      .catch(() => {/* non-critical */});
  }, [isActive]);

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

  async function handleAcceptDraft(id: string) {
    try {
      await acceptProposalDirect(id);
      await load();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } })?.response?.status;
      if (httpStatus === 409) {
        await load();
      } else {
        alert("שגיאה בביצוע הפעולה");
      }
    }
  }

  async function handleRejectDraft(id: string) {
    try {
      await rejectProposalDirect(id);
      await load();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } })?.response?.status;
      if (httpStatus === 409) {
        await load();
      } else {
        alert("שגיאה בביצוע הפעולה");
      }
    }
  }

  if (loading) {
    return <p className="text-sm text-gray-400">{t("app.loading")}</p>;
  }

  if (loadError) {
    return <p className="text-sm text-red-500">{loadError}</p>;
  }

  const today = new Date().toISOString().slice(0, 10);
  const typeFiltered =
    filter === "all"
      ? events
      : filter === "algorithm_draft"
        ? events.filter((e) => e.status === "algorithm_draft")
        : events.filter((e) => e.event_type === filter);

  const filtered = (() => {
    switch (statusFilter) {
      case "published":
        return typeFiltered.filter(
          (e) =>
            (e.status === "published" || e.status === "active" || e.status === "approved") &&
            e.metadata.is_reserve !== "true"
        );
      case "draft":
        return typeFiltered.filter((e) => e.status === "algorithm_draft");
      case "reserve":
        return typeFiltered.filter((e) => e.metadata.is_reserve === "true");
      case "official":
        return typeFiltered.filter(
          (e) => e.status === "cancelled" || e.event_type === "cancellation"
        );
      default:
        return typeFiltered;
    }
  })();

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
    onAcceptDraft: handleAcceptDraft,
    onRejectDraft: handleRejectDraft,
    dutyTypeById,
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

      {/* Status filter row */}
      <div className="flex flex-wrap gap-1 mb-4">
        {(
          [
            { status: "all" as StatusFilter, label: t("duty_history.filter_all") },
            { status: "published" as StatusFilter, label: t("duty_history.filter_published") },
            ...(canManage
              ? [{ status: "draft" as StatusFilter, label: t("duty_history.filter_draft") }]
              : []),
            { status: "reserve" as StatusFilter, label: t("duty_history.filter_reserve") },
            { status: "official" as StatusFilter, label: t("duty_history.filter_official") },
          ] as { status: StatusFilter; label: string }[]
        ).map(({ status, label }) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`text-xs px-2 py-1 rounded-full border ${
              statusFilter === status
                ? "bg-indigo-600 text-white border-indigo-600"
                : "border-gray-300 text-gray-600 hover:border-indigo-400"
            }`}
            data-testid={`history-status-filter-${status}`}
          >
            {label}
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
