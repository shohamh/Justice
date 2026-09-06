import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarShift, CalendarShiftAssignee } from "../api/calendar";
import { SwapRequest, listSwapsForAssignment, checkCoverEligibility } from "../api/swaps";
import { EffectiveDuty, listEffectiveDuties } from "../api/assignments";
import { getShift, removeShiftAssignment } from "../api/shifts";
import type { DutyShift } from "../api/shifts";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import DismissalModal from "./DismissalModal";
import ReserveDismissalModal from "./ReserveDismissalModal";
import SoldierLink from "./SoldierLink";
import CoverOfferModal from "./CoverOfferModal";
import OfferSwapModal from "./OfferSwapModal";
import ShiftAssignModal from "./ShiftAssignModal";
import { useAuth } from "../auth/AuthContext";
import { canApprove } from "../auth/permissions";
import { getPublicSettings } from "../api/publicSettings";
import { formatDutyRange } from "../utils/formatDate";
import { formatRangeEligibilityExplanation } from "../utils/rangeEligibilityExplanation";
import { formatDutyRequirements } from "../utils/dutyRequirements";
import { EventDetailModal, RosterSection } from "./planning";
import HolidayBadge from "./HolidayBadge";
import Tooltip from "./Tooltip";

function SoldierAvatar({ url, name }: { url: string | null | undefined; name: string }) {
  const [imgError, setImgError] = useState(false);
  const initials = name.split(" ").map((w) => w[0]).filter(Boolean).slice(0, 2).join("");
  if (url && !imgError) {
    return (
      <img
        src={url}
        alt={name}
        className="w-7 h-7 rounded-full object-cover shrink-0 border border-gray-200 dark:border-gray-600"
        onError={() => setImgError(true)}
      />
    );
  }
  return (
    <div className="w-7 h-7 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0 text-indigo-700 dark:text-indigo-300 font-semibold text-xs">
      {initials}
    </div>
  );
}

function RangeEligibilityBadge({
  kind,
  label,
  explanation,
}: {
  kind: "warning" | "info";
  label: string;
  explanation: string;
}) {
  const colorCls =
    kind === "warning"
      ? "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300"
      : "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300";

  return (
    <Tooltip
      ariaLabel={label}
      title={explanation}
      label={label}
      content={explanation}
      className={`inline-flex items-center rounded px-1.5 py-0.5 ${colorCls}`}
    >
      {kind === "warning" ? "⚠️" : "ℹ️"}
    </Tooltip>
  );
}

interface Props {
  shift: CalendarShift;
  onClose: () => void;
  onRefreshNeeded: () => void;
}

export default function ShiftDetailPanel({ shift, onClose, onRefreshNeeded }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [dismissTarget, setDismissTarget] = useState<CalendarShiftAssignee | null>(null);
  const [reserveDismissTarget, setReserveDismissTarget] = useState<CalendarShiftAssignee | null>(null);
  const [swapsByAssignment, setSwapsByAssignment] = useState<Record<string, SwapRequest[]>>({});
  const [coverSwap, setCoverSwap] = useState<SwapRequest | null>(null);
  const [myDuties, setMyDuties] = useState<EffectiveDuty[]>([]);
  const [dutyTypeById, setDutyTypeById] = useState<Record<string, DutyType>>({});
  const [shiftDutyTypes, setShiftDutyTypes] = useState<Record<string, DutyType>>({});
  const [offerSwapTarget, setOfferSwapTarget] = useState<{
    soldierId: string;
    soldierName: string;
    assignmentId: string;
  } | null>(null);
  const [gimelimEnabled, setGimelimEnabled] = useState(true);
  const [gimelimDefaultRestDays, setGimelimDefaultRestDays] = useState(7);
  const [canOfferReplace, setCanOfferReplace] = useState(true);
  const [coverIneligibleReason, setCoverIneligibleReason] = useState<string | null>(null);
  const [replaceTarget, setReplaceTarget] = useState<DutyShift | null>(null);

  useEffect(() => {
    getPublicSettings().then((settings) => {
      const enabled = settings["gimalim.enabled"];
      setGimelimEnabled(enabled === true || enabled === undefined);
      const restDays = settings["gimalim.default_rest_days"];
      if (typeof restDays === "number") setGimelimDefaultRestDays(restDays);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    listDutyTypes().catch(() => []).then((dts) => {
      const byId = Object.fromEntries(dts.map((d) => [d.id, d]));
      setShiftDutyTypes(byId);
    });
  }, []);

  useEffect(() => {
    const primaryIds = shift.assignees
      .filter((a) => !a.is_reserve || a.called_up_from)
      .map((a) => a.assignment_id);
    if (primaryIds.length === 0) return;
    Promise.all(
      primaryIds.map((id) =>
        listSwapsForAssignment(id)
          .then((swaps) => ({ id, swaps }))
          .catch(() => ({ id, swaps: [] as SwapRequest[] }))
      )
    ).then((results) => {
      const map: Record<string, SwapRequest[]> = {};
      for (const { id, swaps } of results) {
        if (swaps.length > 0) map[id] = swaps;
      }
      setSwapsByAssignment(map);
    });
  }, [shift]);

  useEffect(() => {
    if (!user) return;
    const someAssignmentId = shift.assignees[0]?.assignment_id;
    if (!someAssignmentId) {
      setCanOfferReplace(true);
      return;
    }
    checkCoverEligibility(someAssignmentId)
      .then((result) => {
        setCanOfferReplace(result.eligible);
        setCoverIneligibleReason(result.eligible ? null : (result.reason ?? null));
      })
      .catch(() => { setCanOfferReplace(true); setCoverIneligibleReason(null); });
  }, [shift, user]);

  async function handleOpenCoverModal(swap: SwapRequest) {
    setCoverSwap(swap);
    if (user) {
      const [duties, dts] = await Promise.all([
        listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
        listDutyTypes().catch(() => []),
      ]);
      setMyDuties(duties);
      setDutyTypeById(Object.fromEntries(dts.map((d) => [d.id, d])));
    }
  }

  const dismissed = shift.assignees.filter((a) => (!a.is_reserve || a.called_up_from) && a.dismissals.length > 0);
  const primaries = shift.assignees.filter((a) => (!a.is_reserve || a.called_up_from) && a.dismissals.length === 0);
  const reserves = shift.assignees.filter((a) => a.is_reserve && !a.called_up_from);
  const dutyRequirements = formatDutyRequirements(
    shiftDutyTypes[shift.duty_type_id],
    shift.required_range_type
  );

  const problemLabels: Record<string, string> = {
    duty_exemption: "פטור מתורנות",
    gimelim: "גימלים",
    inability_to_attend: "אי-יכולת להתייצב",
    hakpaza_pikudit: "הקפצה פיקודית",
  };
  const problemAssignees = shift.assignees.filter((a) => a.problems.length > 0);
  const calledUpReserves = shift.assignees.filter((a) => a.is_reserve && a.called_up_from);

  const assigneeById = Object.fromEntries(
    shift.assignees.map((a) => [a.assignment_id, { soldierId: a.soldier_id, name: a.soldier_name }])
  );

  function soldierNode(id: string | null): React.ReactNode {
    if (!id) return "—";
    const a = assigneeById[id];
    if (!a) return "—";
    return <SoldierLink id={a.soldierId} name={a.name} />;
  }

  function rangeEligibilityIndicator(assignee: CalendarShiftAssignee): React.ReactNode {
    if (!shift.required_range_type) return null;
    const canSeeEligibility = canApprove(user);
    if (!canSeeEligibility) return null;
    if (!assignee.range_eligibility) {
      return (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {t("range_qualification.shiftDetail.unavailable")}
        </span>
      );
    }
    if (!assignee.range_eligibility.eligible) {
      return (
        <RangeEligibilityBadge
          kind="warning"
          label={t("range_qualification.shiftDetail.warning")}
          explanation={formatRangeEligibilityExplanation(assignee.range_eligibility, t)}
        />
      );
    }
    if (assignee.range_eligibility.qualification_source === "planned_range") {
      return (
        <RangeEligibilityBadge
          kind="info"
          label={t("range_qualification.shiftDetail.info")}
          explanation={formatRangeEligibilityExplanation(assignee.range_eligibility, t)}
        />
      );
    }
    return null;
  }

  return (
    <EventDetailModal
      open
      title={`${shift.duty_type_name} — ${shift.duty_location_name}`}
      subtitle={
        <span className="flex items-center gap-2 flex-wrap">
          {formatDutyRange(shift.start_date, shift.end_date)}
          <HolidayBadge holidays={shift.crossed_holidays} />
        </span>
      }
      onClose={onClose}
    >
        {dutyRequirements.length > 0 && (
          <div className="mb-4 rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700">
            <p className="font-medium text-gray-700 dark:text-gray-200">דרישות תפקיד</p>
            <ul className="mt-1 space-y-1 text-gray-600 dark:text-gray-300">
              {dutyRequirements.map((requirement) => <li key={requirement}>{requirement}</li>)}
            </ul>
          </div>
        )}
        {problemAssignees.length > 0 && (
          <section
            data-testid="shift-problem-panel"
            className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm dark:border-red-800 dark:bg-red-950/30"
            dir="rtl"
          >
            <h4 className="mb-2 font-semibold text-red-800 dark:text-red-200">{t("shift_problems.title", "בעיות בתורנות")}</h4>
            <div className="space-y-2">
              {problemAssignees.map((assignee) => (
                <div key={assignee.assignment_id} className="rounded border border-red-200 bg-white/70 p-2 dark:border-red-800 dark:bg-gray-800/60">
                  <div className="font-medium text-gray-800 dark:text-gray-100">
                    <SoldierLink id={assignee.soldier_id} name={assignee.soldier_name} />
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {assignee.problems.map((problem) => (
                      <span
                        key={`${problem.kind}-${problem.source_id}`}
                        data-testid={`problem-badge-${problem.kind}`}
                        className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800 dark:bg-red-900 dark:text-red-200"
                        title={problem.reason ?? undefined}
                      >
                        {t(`shift_problems.${problem.kind}`, problemLabels[problem.kind] ?? problem.kind)}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
        {calledUpReserves.some((a) => a.primary_assignment_ids.length > 0) && (
          <section data-testid="replacement-history" className="mb-4 rounded border border-blue-200 bg-blue-50 p-3 text-sm dark:border-blue-800 dark:bg-blue-950/30">
            <h4 className="mb-2 font-semibold text-blue-800 dark:text-blue-200">{t("shift_problems.replacement_history", "היסטוריית החלפות")}</h4>
            <div className="space-y-2">
              {calledUpReserves.filter((a) => a.primary_assignment_ids.length > 0).map((reserve) => (
                <div key={reserve.assignment_id} data-testid={`replacement-row-${reserve.assignment_id}`} className="flex flex-wrap items-center gap-2">
                  <SoldierLink id={reserve.soldier_id} name={reserve.soldier_name} />
                  <span className="text-xs text-blue-700 dark:text-blue-300">{t("shift_problems.active_reserve", "רזרבה פעילה")}</span>
                  <span className="text-xs text-gray-600 dark:text-gray-300">{t("shift_problems.replaces", "מחליף:")}</span>
                  {reserve.primary_assignment_ids.map((id) => <React.Fragment key={id}>{soldierNode(id)}</React.Fragment>)}
                </div>
              ))}
            </div>
          </section>
        )}
        {(() => {
          const dt = shiftDutyTypes[shift.duty_type_id];
          if (!dt) return null;
          const hasInfo = dt.contact_name || dt.contact_phone || dt.start_time || dt.end_time || dt.instructions;
          return (
            <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-700 rounded text-sm space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-xs px-1.5 py-0.5 rounded ${dt.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                  {dt.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                </span>
                {dt.start_time && dt.end_time && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {dt.start_time.slice(0, 5)} – {dt.end_time.slice(0, 5)}
                  </span>
                )}
              </div>
              {hasInfo && (
                <>
                  {(dt.contact_name || dt.contact_phone) && (
                    <p className="text-xs text-gray-600 dark:text-gray-300">
                      {t("duty_config.contact_name")}: {dt.contact_name ?? "—"}
                      {dt.contact_phone && <> | <a href={`tel:${dt.contact_phone}`} className="text-indigo-600 dark:text-indigo-300">{dt.contact_phone}</a></>}
                    </p>
                  )}
                  {dt.instructions && (
                    <p className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{dt.instructions}</p>
                  )}
                </>
              )}
            </div>
          );
        })()}

        <section className="mb-5">
          <h4 className="font-semibold text-sm text-gray-600 dark:text-gray-300 mb-2">
            {t("primary_soldiers")} ({primaries.length}/{shift.required_count})
            {shift.fill_status === "full" ? " ✅" : ""}
          </h4>
          <div className="space-y-2">
            {primaries.length === 0 && <p className="text-xs text-gray-400">{t("unit_calendar.none")}</p>}
            {primaries.map((a) => {
              const isCalledUp = a.is_reserve && a.called_up_from;
              const openSwaps = swapsByAssignment[a.assignment_id] ?? [];
              return (
                <div
                  key={a.assignment_id}
                  className={`border rounded p-2 text-sm flex flex-col gap-1 ${
                    isCalledUp ? "border-blue-200 dark:border-blue-700 bg-blue-50 dark:bg-blue-950" : "dark:border-gray-600"
                  }`}
                >
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-2">
                      <SoldierAvatar url={a.profile_picture_url} name={a.soldier_name} />
                      <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
                      {rangeEligibilityIndicator(a)}
                      {a.hierarchy_label && <span className="text-xs text-gray-400">({a.hierarchy_label})</span>}
                      {isCalledUp && (
                        <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300 px-1.5 py-0.5 rounded">
                          {a.called_up_from === a.called_up_to
                            ? `${t("reserve_called_up")} ${a.called_up_from}`
                            : `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}`}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1">
                      {!isCalledUp && (
                        <>
                          {a.soldier_id !== user?.id && canOfferReplace && (
                            <button
                              className="text-xs bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded hover:bg-indigo-200"
                              onClick={() => setOfferSwapTarget({ soldierId: a.soldier_id, soldierName: a.soldier_name, assignmentId: a.assignment_id })}
                            >
                              {t("swaps.offer_replace")}
                            </button>
                          )}
                          {(user?.role === "admin" || user?.is_duty_manager) && (
                            <button
                              data-testid={`shift-dismiss-assignment-${a.assignment_id}`}
                              className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
                              onClick={() => setDismissTarget(a)}
                            >
                              {t("dismiss_action")}
                            </button>
                          )}
                        </>
                      )}
                      {(user?.role === "admin" || user?.is_duty_manager) && a.weapon_ineligible && (
                        <button
                          className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
                          onClick={async () => {
                            await removeShiftAssignment(shift.id, a.assignment_id);
                            setReplaceTarget(await getShift(shift.id));
                            onRefreshNeeded();
                          }}
                        >
                          {t("weapon_ineligible.replace")}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {!isCalledUp && a.reserve_assignment_id && (
                      <span className="text-purple-600">
                        {t("reserve_standby")}: {soldierNode(a.reserve_assignment_id)}
                        {a.reserve_hierarchy_distance != null &&
                          ` (${t("distance_label", "מרחק")}: ${a.reserve_hierarchy_distance})`}
                      </span>
                    )}
                    {isCalledUp && a.primary_assignment_ids.length > 0 && (
                      <span className="text-blue-600 dark:text-blue-400">
                        {t("reserve_covers")}:{" "}
                        {a.primary_assignment_ids.map((id, i) => (
                          <span key={id}>{i > 0 && ", "}{soldierNode(id)}</span>
                        ))}
                      </span>
                    )}
                  </div>
                  {openSwaps.map((swap) => (
                    <div
                      key={swap.id}
                      className="flex items-center gap-2 mt-1 bg-orange-50 border border-orange-200 rounded px-2 py-1 text-xs"
                    >
                      <span className="text-orange-700 flex-1">
                        {t("unit_calendar.swap_requests_has")}
                        {swap.requesting_soldier_name && (
                          <span className="font-medium"> — {swap.requesting_soldier_name}</span>
                        )}
                        {swap.reason && (
                          <span className="text-orange-500 mr-1"> ({swap.reason})</span>
                        )}
                      </span>
                      <button
                        onClick={canOfferReplace ? () => void handleOpenCoverModal(swap) : undefined}
                        disabled={!canOfferReplace}
                        title={!canOfferReplace ? (coverIneligibleReason ?? undefined) : undefined}
                        className={`px-2 py-0.5 rounded text-xs ${!canOfferReplace ? "bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed" : "bg-orange-500 text-white hover:bg-orange-600"}`}
                      >
                        {t("swaps.cover")}
                      </button>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </section>

        {dismissed.length > 0 && (
          <RosterSection
            kind="primary"
            title={`${t("dismissed_soldiers")} (${dismissed.length})`}
            assignments={dismissed.map(a => ({
              id: a.assignment_id,
              soldierId: a.soldier_id,
              soldierName: a.soldier_name,
              profilePictureUrl: a.profile_picture_url,
              status: a.dismissals.map(d => t("dismissed_from_to", { from: d.dismissed_from, to: d.dismissed_to }) + (d.reason ? ` (${d.reason})` : "")).join(" · "),
            }))}
          />
        )}
        <section>
          <h4 className="font-semibold text-sm text-gray-600 dark:text-gray-300 mb-2">
            {t("reserve_soldiers")} ({reserves.length})
          </h4>
          <div className="space-y-2">
            {reserves.length === 0 && <p className="text-xs text-gray-400">{t("unit_calendar.none")}</p>}
            {reserves.map((a) => (
              <div
                key={a.assignment_id}
                className="border rounded p-2 text-sm border-purple-200 dark:border-purple-700 bg-purple-50 dark:bg-purple-950 flex flex-col gap-1"
              >
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <SoldierAvatar url={a.profile_picture_url} name={a.soldier_name} />
                    <SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
                    {rangeEligibilityIndicator(a)}
                    <span className="text-xs text-purple-500">({t("reserve_label")})</span>
                    {a.hierarchy_label && (
                      <span className="text-xs text-gray-400">({a.hierarchy_label})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    {a.soldier_id !== user?.id && canOfferReplace && (
                      <button
                        className="text-xs bg-indigo-100 text-indigo-800 px-2 py-0.5 rounded hover:bg-indigo-200"
                        onClick={() => setOfferSwapTarget({ soldierId: a.soldier_id, soldierName: a.soldier_name, assignmentId: a.assignment_id })}
                      >
                        {t("swaps.offer_replace")}
                      </button>
                    )}
                    {(user?.role === "admin" || user?.is_duty_manager) && (
                      <button
                        className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded hover:bg-amber-200"
                        onClick={() => setReserveDismissTarget(a)}
                      >
                        {t("dismiss_action")}
                      </button>
                    )}
                    {(user?.role === "admin" || user?.is_duty_manager) && a.weapon_ineligible && (
                      <button
                        className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
                        onClick={async () => {
                          await removeShiftAssignment(shift.id, a.assignment_id);
                          setReplaceTarget(await getShift(shift.id));
                          onRefreshNeeded();
                        }}
                      >
                        {t("weapon_ineligible.replace")}
                      </button>
                    )}
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${
                        a.called_up_from ? "bg-blue-100 text-blue-800" : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {a.called_up_from
                        ? `${t("reserve_called_up")} ${a.called_up_from}–${a.called_up_to}`
                        : t("reserve_standby")}
                    </span>
                  </div>
                </div>
                {a.primary_assignment_ids.length > 0 && (
                  <div className="text-xs text-gray-600">
                    {t("reserve_covers")}:{" "}
                    {a.primary_assignment_ids.map((id, i) => (
                      <span key={id}>{i > 0 && ", "}{soldierNode(id)}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        {dismissTarget && (
          <DismissalModal
            shift={shift}
            primary={dismissTarget}
            canGimelim={
              gimelimEnabled &&
              !dismissTarget.is_reserve &&
              (user?.role === "admin" || (user?.is_duty_manager ?? false))
            }
            defaultRestDays={gimelimDefaultRestDays}
            onClose={() => setDismissTarget(null)}
            onDone={() => { setDismissTarget(null); onRefreshNeeded(); }}
          />
        )}

        {reserveDismissTarget && (
          <ReserveDismissalModal
            shift={shift}
            reserve={reserveDismissTarget}
            onClose={() => setReserveDismissTarget(null)}
            onDone={() => { setReserveDismissTarget(null); onRefreshNeeded(); }}
          />
        )}

        {coverSwap && (
          <CoverOfferModal
            swap={coverSwap}
            myDuties={myDuties}
            dutyTypes={Object.fromEntries(Object.entries(dutyTypeById).map(([id, dt]) => [id, dt.name]))}
            onClose={() => setCoverSwap(null)}
            onDone={() => { setCoverSwap(null); onRefreshNeeded(); }}
          />
        )}

        {offerSwapTarget && (
          <OfferSwapModal
            targetSoldierId={offerSwapTarget.soldierId}
            targetSoldierName={offerSwapTarget.soldierName}
            targetAssignmentId={offerSwapTarget.assignmentId}
            targetDutyStart={shift.start_date}
            targetDutyEnd={shift.end_date}
            targetDutyTypeId={shift.duty_type_id}
            onClose={() => setOfferSwapTarget(null)}
            onDone={() => { setOfferSwapTarget(null); onRefreshNeeded(); }}
          />
        )}

        {replaceTarget && (
          <ShiftAssignModal
            shift={replaceTarget}
            dutyTypes={Object.values(shiftDutyTypes)}
            onSaved={() => { setReplaceTarget(null); onRefreshNeeded(); }}
            onClose={() => setReplaceTarget(null)}
          />
        )}
    </EventDetailModal>
  );
}
