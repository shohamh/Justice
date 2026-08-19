import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import { api, getAccessToken } from "../api/client";
import Layout from "../components/Layout";
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
import SoldierLink from "../components/SoldierLink";
import EnrollmentApprovalModal from "../components/EnrollmentApprovalModal";
import DocumentPreviewModal from "../components/DocumentPreviewModal";
import DirectCommanderApproval, { DirectCommanderApprovalRow, groupByKind, isSideSatisfied } from "../components/DirectCommanderApproval";
import SwapApprovalColumns, { requesterColumn, candidateColumn } from "../components/SwapApprovalColumns";
import { useAuth } from "../auth/AuthContext";
import { listPublicExemptionTypes } from "../api/auth";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import {
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";
import {
  approveExemptionRequestCommanderStep,
  approveExemptionRequestDutyManagerStep,
  exemptionFileDownloadUrl,
  listPendingExemptionRequests,
  rejectExemptionRequest,
} from "../api/exemptions";
import {
  FieldUpdateDTO,
  approveFieldUpdate,
  rejectFieldUpdate,
  listPendingFieldUpdates,
} from "../api/soldiers";
import {
  managerApproveSwap,
  listPendingSwaps,
  managerRejectSwap,
  getSwapConfig,
  SwapRequest,
} from "../api/swaps";
import { EnrollmentRequestDTO, listPendingEnrollments, rejectEnrollment } from "../api/enrollment";
import {
  TransferRequest,
  listPendingTransferRequests,
  approveTransferRequest,
  rejectTransferRequest,
} from "../api/hierarchyTransfers";
import { DaysBadge } from "../components/DaysBadge";
import i18n from "../i18n";
import { translateApiError } from "../utils/translateApiError";

async function handleExportApprovals() {
  const resp = await fetch("/api/approvals/export", {
    headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` },
  });
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "approvals_export.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

function describeError(err: unknown): string {
  const fallback = "שגיאה בביצוע הפעולה";
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    const detail = resp?.data?.detail;
    if (detail?.startsWith("cover_blocked:")) {
      const reason = detail.slice("cover_blocked:".length);
      return i18n.t(`cover_blocked.${reason}`, { defaultValue: translateApiError(err, i18n.t.bind(i18n), fallback) });
    }
  }
  return translateApiError(err, i18n.t.bind(i18n), fallback);
}

/** One approval-kind row (commander or duty-manager) for one swap side. Shows
 * status for everyone, but only shows the actionable button to a viewer who
 * is actually eligible for this specific kind — a commander with no
 * authority over the duty-manager step (or vice versa) sees status only. */
function SwapKindApproval({
  approvals, label, canAct, onApprove, t,
}: {
  approvals: DirectCommanderApprovalRow[];
  label: string;
  canAct: boolean;
  onApprove: () => void;
  t: (k: string) => string;
}) {
  if (approvals.length === 0) return null;
  const done = isSideSatisfied(approvals);
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span>{label}:</span>
      <DirectCommanderApproval approvals={approvals} />
      {!done && canAct && (
        <button
          onClick={onApprove}
          className="bg-green-600 text-white px-2 py-0.5 rounded text-xs"
        >
          {t("approvals.approve")}
        </button>
      )}
    </div>
  );
}

/**
 * Whether a commander can ever decide a field update for `fieldName` — mirrors
 * backend/app/auth/authz.py: `Action.SOLDIER_UPDATE` (used for every editable
 * field except military_driving_license) is only in `_DM_ACTIONS`, never
 * `_COMMANDER_ACTIONS`, so a commander can never approve those regardless of
 * scope. Only `military_driving_license` goes through the rank-gated
 * `MILITARY_LICENSE_DECIDE` branch, which commanders can satisfy. Used to
 * avoid showing a commander as a decider for a field they structurally can't
 * approve — keep in sync with authz.py if that ever changes.
 */
function fieldAllowsCommanderApproval(fieldName: string): boolean {
  return fieldName === "military_driving_license";
}

/**
 * Adapts the live-computed `nearest_commander`/`nearest_duty_manager` fields
 * (constraints/exemption-requests/field-updates/enrollment-requests) into the
 * row shape `DirectCommanderApproval`/`groupByKind` expect. Unlike swaps,
 * these 4 types only ever need a single decision total, so both rows share
 * the same overall `status` — this is purely a display adapter, not a second
 * independent approval gate.
 */
function nearestApproversToRows(
  nearestCommander: { id: string; name: string } | null,
  nearestDutyManager: { id: string; name: string } | null,
  status: "pending" | "pending_commander" | "pending_duty_manager" | "approved" | "rejected" | "cancelled",
): DirectCommanderApprovalRow[] {
  const rows: DirectCommanderApprovalRow[] = [];
  if (nearestCommander) {
    rows.push({
      commander_id: nearestCommander.id, commander_name: nearestCommander.name,
      approved: status === "approved", rejected: status === "rejected", approver_kind: "commander",
    });
  }
  if (nearestDutyManager) {
    rows.push({
      commander_id: nearestDutyManager.id, commander_name: nearestDutyManager.name,
      approved: status === "approved", rejected: status === "rejected", approver_kind: "duty_manager",
    });
  }
  return rows;
}

type Tab = "constraints" | "exemptions" | "field_updates" | "swaps" | "enrollment" | "transfers" | "waiting";

const VALID_TABS: Tab[] = ["constraints", "exemptions", "field_updates", "swaps", "enrollment", "transfers", "waiting"];

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") as Tab | null;
  const tab: Tab = rawTab && VALID_TABS.includes(rawTab) ? rawTab : "constraints";

  function setTab(next: Tab) {
    setSearchParams((prev) => { prev.set("tab", next); return prev; }, { replace: true });
  }
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});
  const [fuNotes, setFuNotes] = useState<Record<string, string>>({});
  const [swapRejectNotes, setSwapRejectNotes] = useState<Record<string, string>>({});
  const [enrollRejectNotes, setEnrollRejectNotes] = useState<Record<string, string>>({});
  const [transferRejectNotes, setTransferRejectNotes] = useState<Record<string, string>>({});
  const [selectedEnrollment, setSelectedEnrollment] = useState<EnrollmentRequestDTO | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [previewFile, setPreviewFile] = useState<{ url: string; name: string; contentType: string } | null>(null);

  const queryClient = useQueryClient();

  const constraintsQuery = useQuery({ queryKey: queryKeys.pendingConstraints(), queryFn: listPendingApprovals });
  const items = constraintsQuery.data ?? [];

  const erQuery = useQuery({ queryKey: queryKeys.pendingExemptionRequests(), queryFn: listPendingExemptionRequests });
  const erItems = erQuery.data ?? [];

  const fuQuery = useQuery({ queryKey: queryKeys.pendingFieldUpdates(), queryFn: listPendingFieldUpdates });
  const fuItems = fuQuery.data ?? [];

  const swapsQuery = useQuery({ queryKey: queryKeys.pendingSwaps(), queryFn: listPendingSwaps });
  const swapItems = swapsQuery.data ?? [];

  const isAdmin = user?.role === "admin";
  const canActCommander = (approvals: DirectCommanderApprovalRow[]) =>
    isAdmin || approvals.some(a => a.commander_id === user?.id);
  const canActDutyManager = (approvals: DirectCommanderApprovalRow[]) =>
    isAdmin || approvals.some(a => a.commander_id === user?.id);

  // A commander/duty-manager sees every card in their scope (broad read
  // visibility) but structurally can't act on most of them — e.g. a plain
  // commander has no authority over most field updates (duty-manager-only)
  // or a two-step exemption's duty-manager stage. Showing those cards
  // alongside ones the viewer can actually decide made the "for approval"
  // tabs cluttered with dead ends; splitting them into actionable vs.
  // waiting-for-someone-else keeps the main tabs to cards with a real action.
  function exemptionIsActionable(er: { status: string; can_approve_commander_step: boolean; can_approve_duty_manager_step: boolean }): boolean {
    return (
      (er.status === "pending_commander" && er.can_approve_commander_step) ||
      (er.status === "pending_duty_manager" && er.can_approve_duty_manager_step)
    );
  }
  function swapIsActionable(swap: SwapRequest): boolean {
    const reqGroups = groupByKind(swap.requester_manager_approvals);
    if (canActCommander(reqGroups.commander) || canActDutyManager(reqGroups.duty_manager)) return true;
    const liveCandidates = swap.candidates.filter(c => c.status === "pending" || c.status === "accepted");
    return liveCandidates.some(candidate => {
      const covGroups = groupByKind(candidate.manager_approvals);
      return canActCommander(covGroups.commander) || canActDutyManager(covGroups.duty_manager);
    });
  }
  const erActionable = erItems.filter(exemptionIsActionable);
  const erWaiting = erItems.filter(er => !exemptionIsActionable(er));
  const fuActionable = fuItems.filter(i => i.can_approve);
  const fuWaiting = fuItems.filter(i => !i.can_approve);
  const swapsActionable = swapItems.filter(swapIsActionable);
  const swapsWaiting = swapItems.filter(s => !swapIsActionable(s));
  const waitingCount = erWaiting.length + fuWaiting.length + swapsWaiting.length;

  const swapConfigQuery = useQuery({
    queryKey: queryKeys.swapConfig(),
    queryFn: () => getSwapConfig().catch(() => ({ require_manager_approval: false, require_duty_manager_approval: true, max_specific_targets: 5 })),
  });
  const requireDutyManagerApproval = swapConfigQuery.data?.require_duty_manager_approval ?? true;

  const enrollQuery = useQuery({ queryKey: queryKeys.pendingEnrollments(), queryFn: listPendingEnrollments });
  const enrollItems = enrollQuery.data ?? [];

  const transfersQuery = useQuery({ queryKey: queryKeys.pendingHierarchyTransfers(), queryFn: listPendingTransferRequests });
  const transferItems = transfersQuery.data ?? [];

  const treeQuery = useQuery({ queryKey: queryKeys.hierarchyTree(), queryFn: fetchFullTree });
  const nodes = useMemo(() => {
    const flatNodes: { id: string; name: string }[] = [];
    function flatten(nodes: NodeDTO[]) {
      for (const n of nodes) {
        flatNodes.push({ id: n.id, name: n.name });
        if (n.children) flatten(n.children);
      }
    }
    flatten(treeQuery.data ?? []);
    return flatNodes;
  }, [treeQuery.data]);

  const exemptionTypesQuery = useQuery({ queryKey: queryKeys.publicExemptionTypes(), queryFn: listPublicExemptionTypes });
  const exemptionTypes = useMemo(
    () => (exemptionTypesQuery.data ?? []).map(et => ({ id: et.id, name: et.name })),
    [exemptionTypesQuery.data],
  );

  async function onApprove(id: string) {
    try {
      await approveConstraint(id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraints() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraintsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    try {
      await rejectConstraint(id, note);
      const next = { ...rejectNotes };
      delete next[id];
      setRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraints() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingConstraintsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onErApproveCommander(id: string) {
    try {
      await approveExemptionRequestCommanderStep(id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionRequests() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onErApproveDutyManager(id: string) {
    try {
      await approveExemptionRequestDutyManagerStep(id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionRequests() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onErReject(id: string) {
    const note = rejectNotes[`er-${id}`];
    if (!note) return;
    try {
      await rejectExemptionRequest(id, note);
      const next = { ...rejectNotes };
      delete next[`er-${id}`];
      setRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionRequests() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingExemptionsCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function openExemptionFile(erId: string, fileId: string, fileName: string) {
    try {
      const resp = await api.get(exemptionFileDownloadUrl(erId, fileId), { responseType: "blob" });
      const blob = resp.data as Blob;
      const url = URL.createObjectURL(blob);
      setPreviewFile({ url, name: fileName, contentType: blob.type || "application/octet-stream" });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onFuApprove(item: FieldUpdateDTO) {
    try {
      await approveFieldUpdate(item.soldier_id, item.id, fuNotes[item.id]);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingFieldUpdates() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingFieldUpdatesCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onFuReject(item: FieldUpdateDTO) {
    const note = fuNotes[item.id];
    if (!note) return;
    try {
      await rejectFieldUpdate(item.soldier_id, item.id, note);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingFieldUpdates() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingFieldUpdatesCount() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onSwapManagerApprove(id: string, side: "requester" | "covering", candidateId?: string) {
    try {
      await managerApproveSwap(id, side, candidateId);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    } catch (err) {
      setActionError(describeError(err));
      // Another approver may have already finalized/rejected this request
      // (e.g. lost a finalize race) — refresh so the resolved card disappears
      // instead of sitting there with a now-stale action button.
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    }
  }
  async function onSwapManagerReject(id: string, candidateId?: string) {
    const noteKey = candidateId ? `${id}:${candidateId}` : id;
    try {
      await managerRejectSwap(id, swapRejectNotes[noteKey], candidateId);
      const next = { ...swapRejectNotes };
      delete next[noteKey];
      setSwapRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    } catch (err) {
      setActionError(describeError(err));
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingSwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.mySwaps() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.incomingSwaps() });
    }
  }

  async function onEnrollReject(id: string) {
    const note = enrollRejectNotes[id];
    if (!note) return;
    try {
      await rejectEnrollment(id, note);
      const next = { ...enrollRejectNotes };
      delete next[id];
      setEnrollRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingEnrollments() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onTransferApprove(id: string) {
    try {
      await approveTransferRequest(id);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingHierarchyTransfers() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onTransferReject(id: string) {
    const note = transferRejectNotes[id];
    if (!note) return;
    try {
      await rejectTransferRequest(id, note);
      const next = { ...transferRejectNotes };
      delete next[id];
      setTransferRejectNotes(next);
      await queryClient.invalidateQueries({ queryKey: queryKeys.pendingHierarchyTransfers() });
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  const total = items.length + erActionable.length + fuActionable.length + swapsActionable.length + enrollItems.length + transferItems.length;

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">{t("approvals.title")}{total > 0 ? ` (${total})` : ""}</h2>
          <button
            type="button"
            className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm font-medium hover:bg-indigo-700"
            onClick={() => void handleExportApprovals()}
          >
            ייצוא
          </button>
        </div>

        {actionError && (
          <div className="bg-red-50 dark:bg-red-950 border border-red-300 dark:border-red-800 text-red-700 dark:text-red-300 text-sm rounded p-2 flex items-center justify-between" dir="rtl">
            <span>{actionError}</span>
            <button className="text-red-500 hover:text-red-700" onClick={() => setActionError(null)}>✕</button>
          </div>
        )}

        <div className="flex flex-wrap gap-x-4 border-b dark:border-gray-600">
          <button
            className={`pb-2 text-sm ${tab === "constraints" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("constraints")}
            data-testid="approvals-tab-constraints"
          >
            {t("approvals.tab_constraints")}{items.length > 0 ? ` (${items.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "exemptions" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("exemptions")}
            data-testid="approvals-tab-exemptions"
          >
            {t("approvals.tab_exemptions")}{erActionable.length > 0 ? ` (${erActionable.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "field_updates" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("field_updates")}
            data-testid="approvals-tab-field-updates"
          >
            {t("soldier_profile.field_updates_tab")}{fuActionable.length > 0 ? ` (${fuActionable.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "swaps" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("swaps")}
            data-testid="approvals-tab-swaps"
          >
            {t("swaps.title")}{swapsActionable.length > 0 ? ` (${swapsActionable.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "enrollment" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("enrollment")}
            data-testid="approvals-tab-enrollment"
          >
            {t("enrollment.tab")}{enrollItems.length > 0 ? ` (${enrollItems.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "transfers" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("transfers")}
            data-testid="approvals-tab-transfers"
          >
            {t("approvals.tab_transfers")}{transferItems.length > 0 ? ` (${transferItems.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "waiting" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("waiting")}
            data-testid="approvals-tab-waiting"
          >
            {t("approvals.tab_waiting")}{waitingCount > 0 ? ` (${waitingCount})` : ""}
          </button>
        </div>

        {tab === "constraints" && (
          <>
            {items.length === 0 && <p className="text-sm text-gray-500">{t("approvals.none")}</p>}
            <ul className="space-y-3" data-testid="approvals-list">
              {items.map((c) => {
                const grouped = groupByKind(nearestApproversToRows(c.nearest_commander, c.nearest_duty_manager, c.status) as (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]);
                return (
                <li key={c.id} className="border dark:border-gray-600 rounded p-3" data-testid={`approval-row-${c.id}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <strong className="text-sm"><SoldierLink id={c.soldier_id} name={c.soldier_name || c.soldier_id.slice(0, 8)} /></strong>
                    {c.node_name && <span className="text-xs text-gray-400">{c.node_name}</span>}
                  </div>
                  <p className="text-sm flex items-center gap-2" dir="ltr">
                    <span>{c.start_date} → {c.end_date ?? "—"}</span>
                    <DaysBadge start={c.start_date} end={c.end_date} />
                  </p>
                  <p className="text-xs text-gray-500 mb-2">{c.reason ?? "מידע פרטי"}</p>
                  <div className="text-xs text-gray-500 flex items-center gap-3 flex-wrap mb-2">
                    {grouped.commander.length > 0 && <span>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={grouped.commander} /></span>}
                    {grouped.duty_manager.length > 0 && <span>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={grouped.duty_manager} /></span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      value={rejectNotes[c.id] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [c.id]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`reject-note-${c.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[c.id]}
                      onClick={() => onReject(c.id)}
                      data-testid={`reject-${c.id}`}
                    >
                      {t("approvals.reject_constraint")}
                    </button>
                  </div>
                </li>
                );
              })}
            </ul>
          </>
        )}

        {tab === "exemptions" && (
          <>
            {erActionable.length === 0 && <p className="text-sm text-gray-500">{t("approvals.exemption_none")}</p>}
            <ul className="space-y-3" data-testid="er-approvals-list">
              {erActionable.map((er) => {
                const erGrouped = groupByKind(nearestApproversToRows(
                  er.nearest_commander, er.nearest_duty_manager,
                  er.status === "approved" ? "approved" : er.status === "rejected" ? "rejected" : "pending",
                ) as (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]);
                return (
                <li key={er.id} className="border dark:border-gray-600 rounded p-3" data-testid={`er-approval-row-${er.id}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <strong className="text-sm"><SoldierLink id={er.soldier_id} name={er.soldier_name || er.soldier_id.slice(0, 8)} /></strong>
                    {er.node_name && <span className="text-xs text-gray-400">{er.node_name}</span>}
                  </div>
                  <p className="text-sm font-medium mb-1">
                    {exemptionTypes.find(et => et.id === er.exemption_type_id)?.name ?? t("exemptions.unknown_type")}
                  </p>
                  <p className="text-xs text-gray-500 mb-1" data-testid={`er-stage-${er.id}`}>
                    {er.status === "pending_commander"
                      ? "ממתין לאישור מפקד"
                      : er.status === "pending_duty_manager"
                      ? 'ממתין לאישור קצין אג"ם/מרכז ומעלה'
                      : null}
                  </p>
                  <p className="text-sm flex items-center gap-2" dir="ltr">
                    <span>{er.start_date ?? t("exemption_requests.start_date_pending_approval")} → {er.end_date ?? t("exemptions.forever")}</span>
                    {er.start_date && <DaysBadge start={er.start_date} end={er.end_date} />}
                  </p>
                  <p className="text-xs text-gray-500 mb-2">{er.reason ?? "מידע פרטי"}</p>
                  <div className="text-xs text-gray-500 flex items-center gap-3 flex-wrap mb-2">
                    {erGrouped.commander.length > 0 && <span>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={erGrouped.commander} /></span>}
                    {erGrouped.duty_manager.length > 0 && <span>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={erGrouped.duty_manager} /></span>}
                  </div>
                  {er.files.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {er.files.map(f => (
                        <button
                          key={f.id}
                          type="button"
                          onClick={() => openExemptionFile(er.id, f.id, f.file_name)}
                          className="text-blue-600 dark:text-blue-400 text-xs hover:underline flex items-center gap-1"
                        >
                          📎 {f.file_name}
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    {er.status === "pending_commander" && er.can_approve_commander_step && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveCommander(er.id)} data-testid={`er-approve-${er.id}`}>
                        אשר (שלב מפקד)
                      </button>
                    )}
                    {er.status === "pending_duty_manager" && er.can_approve_duty_manager_step && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveDutyManager(er.id)} data-testid={`er-approve-${er.id}`}>
                        אשר (שלב סופי)
                      </button>
                    )}
                    <input
                      className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      value={rejectNotes[`er-${er.id}`] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [`er-${er.id}`]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`er-reject-note-${er.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[`er-${er.id}`]}
                      onClick={() => onErReject(er.id)}
                      data-testid={`er-reject-${er.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </li>
                );
              })}
            </ul>
          </>
        )}

        {tab === "field_updates" && (
          <div className="space-y-3" dir="rtl">
            {fuActionable.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {fuActionable.map(item => {
              const fuGrouped = groupByKind(nearestApproversToRows(item.nearest_commander, item.nearest_duty_manager, item.status) as (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]);
              // A commander can never decide most field updates (see
              // fieldAllowsCommanderApproval) — showing their name as if they
              // were a decider here is what made this confusing, so hide that
              // row entirely for fields where it's never true.
              const showCommanderRow = fieldAllowsCommanderApproval(item.field_name) && fuGrouped.commander.length > 0;
              const showDutyManagerRow = fuGrouped.duty_manager.length > 0;
              return (
              <div key={item.id} className="border dark:border-gray-600 rounded p-3 text-sm space-y-2">
                <div className="flex items-center gap-2">
                  <strong><SoldierLink id={item.soldier_id} name={item.soldier_name || item.soldier_id.slice(0, 8)} /></strong>
                  {item.node_name && <span className="text-xs text-gray-400">{item.node_name}</span>}
                  <span className="text-gray-400">—</span>
                  <span>{t(`soldier_profile.${item.field_name}`)}</span>
                </div>
                <div className="text-gray-500 dark:text-gray-400">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.previous_value, t)}</span></div>
                <div className="text-gray-600 dark:text-gray-300">{t("approvals.field_update_new_value")}<strong>{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.new_value, t)}</strong></div>
                <div className="text-xs text-gray-500 flex items-center gap-3 flex-wrap">
                  {showCommanderRow && <span>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={fuGrouped.commander} /></span>}
                  {showDutyManagerRow && <span>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={fuGrouped.duty_manager} /></span>}
                  {showCommanderRow && showDutyManagerRow && (
                    <span className="italic">({t("approvals.field_update_either_approver_suffices")})</span>
                  )}
                </div>
                <div className="flex gap-2 items-center">
                  {item.can_approve && (
                    <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">{t("approvals.approve")}</button>
                  )}
                  <input
                    placeholder={t("approvals.decision_note")}
                    value={fuNotes[item.id] ?? ""}
                    onChange={e => setFuNotes(prev => ({ ...prev, [item.id]: e.target.value }))}
                    className="border rounded p-1 text-xs flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                  <button onClick={() => onFuReject(item)} disabled={!fuNotes[item.id]} className="bg-red-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50">{t("approvals.reject")}</button>
                </div>
              </div>
              );
            })}
          </div>
        )}

        {tab === "swaps" && (
          <div className="space-y-3" dir="rtl">
            {swapsActionable.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {swapsActionable.map(swap => {
              const reqGroups = groupByKind(swap.requester_manager_approvals);
              const liveCandidates = swap.candidates.filter(c => c.status === "pending" || c.status === "accepted");
              const statusColumns = [
                requesterColumn(
                  swap,
                  requireDutyManagerApproval,
                  `${t("swaps.requester")}: ${swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)}`,
                  t,
                ),
                ...liveCandidates.map(candidate => {
                  return candidateColumn(
                    candidate,
                    requireDutyManagerApproval,
                    candidate.soldier_name || candidate.soldier_id.slice(0, 8),
                    t,
                  );
                }),
              ];
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div>
                    {[swap.duty_type_name, swap.duty_location_name].filter(Boolean).join(" — ") && (
                      <p className="font-medium">{[swap.duty_type_name, swap.duty_location_name].filter(Boolean).join(" — ")}</p>
                    )}
                    <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                    {swap.reason && <p className="text-xs text-gray-400 mt-0.5">{swap.reason}</p>}
                  </div>
                  <SwapApprovalColumns columns={statusColumns} />
                  <div className="text-xs text-gray-500 space-y-1">
                    <SwapKindApproval
                      approvals={reqGroups.commander}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_commander")})`}
                      canAct={canActCommander(reqGroups.commander)}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                    <SwapKindApproval
                      approvals={reqGroups.duty_manager}
                      label={`${t("swaps.requester_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                      canAct={canActDutyManager(reqGroups.duty_manager)}
                      onApprove={() => onSwapManagerApprove(swap.id, "requester")}
                      t={t}
                    />
                  </div>
                  {/* Whole-request reject: a requester-side manager rejection kills the
                      ask entirely (backend: reject_manager_row -> reject_request), independent
                      of any per-candidate rejection below. Kept separate from the per-candidate
                      controls so a reviewer doesn't lose this previously-existing action.
                      Gated the same way the approve buttons above are — only shown to an
                      actor actually authorized on the requester side — so it doesn't dangle
                      a clickable-looking action for a viewer with no real authority here. */}
                  {(canActCommander(reqGroups.commander) || canActDutyManager(reqGroups.duty_manager)) && (
                    <div className="flex gap-2 items-center flex-wrap">
                      <input
                        placeholder={t("approvals.decision_note")}
                        value={swapRejectNotes[swap.id] ?? ""}
                        onChange={e => setSwapRejectNotes(prev => ({ ...prev, [swap.id]: e.target.value }))}
                        className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      />
                      <button
                        onClick={() => onSwapManagerReject(swap.id)}
                        className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                      >
                        {t("approvals.reject")}
                      </button>
                    </div>
                  )}
                  {liveCandidates.length > 0 && (
                    <div className="space-y-2 border-t pt-2 dark:border-gray-700">
                      <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{t("swaps.candidates_title")} ({liveCandidates.length})</p>
                      {liveCandidates.map(candidate => {
                        const covGroups = groupByKind(candidate.manager_approvals);
                        return (
                          <div key={candidate.id} className="border rounded p-2 space-y-1">
                            <strong className="text-sm">
                              <SoldierLink id={candidate.soldier_id} name={candidate.soldier_name || candidate.soldier_id.slice(0, 8)} />
                            </strong>
                            <div className="text-xs text-gray-500 space-y-1">
                              <SwapKindApproval
                                approvals={covGroups.commander}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_commander")})`}
                                canAct={canActCommander(covGroups.commander)}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                              <SwapKindApproval
                                approvals={covGroups.duty_manager}
                                label={`${t("swaps.covering_managers")} (${t("swaps.approver_kind_duty_manager")})`}
                                canAct={canActDutyManager(covGroups.duty_manager)}
                                onApprove={() => onSwapManagerApprove(swap.id, "covering", candidate.id)}
                                t={t}
                              />
                            </div>
                            {(canActCommander(covGroups.commander) || canActDutyManager(covGroups.duty_manager)) && (
                              <div className="flex gap-2 items-center flex-wrap">
                                <input
                                  placeholder={t("approvals.decision_note")}
                                  value={swapRejectNotes[`${swap.id}:${candidate.id}`] ?? ""}
                                  onChange={e => setSwapRejectNotes(prev => ({ ...prev, [`${swap.id}:${candidate.id}`]: e.target.value }))}
                                  className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                                />
                                <button
                                  onClick={() => onSwapManagerReject(swap.id, candidate.id)}
                                  className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                                >
                                  {t("approvals.reject")}
                                </button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {tab === "enrollment" && (
          <div className="space-y-3" dir="rtl">
            {enrollItems.length === 0 && <p className="text-gray-500 text-sm">{t("enrollment.none")}</p>}
            {enrollItems.map(req => {
              const nodeName = req.requested_node_name ?? req.requested_node_id.slice(0, 8);
              const enrollGrouped = groupByKind(nearestApproversToRows(
                req.nearest_commander, req.nearest_duty_manager,
                req.status === "approved" ? "approved" : req.status === "rejected" ? "rejected" : "pending",
              ) as (DirectCommanderApprovalRow & { approver_kind: "commander" | "duty_manager" })[]);
              return (
                <div key={req.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong><SoldierLink id={req.soldier_id} name={req.soldier_name} /></strong>
                  </div>
                  <p className="text-gray-500">{t("enrollment.requested_node")}: <strong>{nodeName}</strong></p>
                  <div className="text-xs text-gray-500 flex items-center gap-3 flex-wrap">
                    {enrollGrouped.commander.length > 0 && <span>{t("swaps.approver_kind_commander")}: <DirectCommanderApproval approvals={enrollGrouped.commander} /></span>}
                    {enrollGrouped.duty_manager.length > 0 && <span>{t("swaps.approver_kind_duty_manager")}: <DirectCommanderApproval approvals={enrollGrouped.duty_manager} /></span>}
                  </div>
                  <button
                    onClick={() => setSelectedEnrollment(req)}
                    className="w-full bg-indigo-600 text-white px-3 py-2 rounded text-sm font-medium hover:bg-indigo-700"
                    data-testid={`enrollment-view-${req.id}`}
                  >
                    {t("enrollment.view_request")}
                  </button>
                  <div className="flex gap-2 items-center">
                    <input
                      placeholder={t("enrollment.decision_note_placeholder")}
                      value={enrollRejectNotes[req.id] ?? ""}
                      onChange={e => setEnrollRejectNotes(prev => ({ ...prev, [req.id]: e.target.value }))}
                      className="border rounded p-1 text-xs flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button onClick={() => onEnrollReject(req.id)}
                      disabled={!enrollRejectNotes[req.id]}
                      className="bg-red-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50">
                      {t("enrollment.reject")}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {tab === "transfers" && (
          <div className="space-y-3" dir="rtl">
            {transferItems.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.transfers_none")}</p>}
            {transferItems.map((req: TransferRequest) => {
              const fromNodeName = req.from_node_id ? nodes.find(n => n.id === req.from_node_id)?.name ?? req.from_node_id.slice(0, 8) : "—";
              const toNodeName = nodes.find(n => n.id === req.to_node_id)?.name ?? req.to_node_id.slice(0, 8);
              return (
                <div key={req.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong><SoldierLink id={req.soldier_id} name={req.soldier_id.slice(0, 8)} /></strong>
                  </div>
                  <p className="text-gray-500">{t("approvals.transfer_from")}: <strong>{fromNodeName}</strong> ← {t("approvals.transfer_to")}: <strong>{toNodeName}</strong></p>
                  <div className="flex gap-2 items-center flex-wrap">
                    <button
                      onClick={() => onTransferApprove(req.id)}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs"
                      data-testid={`transfer-approve-${req.id}`}
                    >
                      {t("approvals.approve")}
                    </button>
                    <input
                      placeholder={t("approvals.decision_note")}
                      value={transferRejectNotes[req.id] ?? ""}
                      onChange={e => setTransferRejectNotes(prev => ({ ...prev, [req.id]: e.target.value }))}
                      className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      data-testid={`transfer-reject-note-${req.id}`}
                    />
                    <button
                      onClick={() => onTransferReject(req.id)}
                      disabled={!transferRejectNotes[req.id]}
                      className="bg-red-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                      data-testid={`transfer-reject-${req.id}`}
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {tab === "waiting" && (
          <div className="space-y-3" dir="rtl">
            {waitingCount === 0 && <p className="text-gray-500 text-sm">{t("approvals.waiting_none")}</p>}
            {fuWaiting.map(item => {
              const isRankField = ["rank", "rank_track", "is_officer", "next_rank_date"].includes(item.field_name);
              const waitingForName = isRankField
                ? t("approvals.waiting_for_rank_authority")
                : fieldAllowsCommanderApproval(item.field_name)
                ? (item.nearest_duty_manager?.name ?? item.nearest_commander?.name ?? "—")
                : (item.nearest_duty_manager?.name ?? "—");
              return (
                <div key={item.id} className="border dark:border-gray-600 rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong><SoldierLink id={item.soldier_id} name={item.soldier_name || item.soldier_id.slice(0, 8)} /></strong>
                    {item.node_name && <span className="text-xs text-gray-400">{item.node_name}</span>}
                    <span className="text-gray-400">—</span>
                    <span>{t(`soldier_profile.${item.field_name}`)}</span>
                  </div>
                  <div className="text-gray-500 dark:text-gray-400">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.previous_value, t)}</span></div>
                  <div className="text-gray-600 dark:text-gray-300">{t("approvals.field_update_new_value")}<strong>{item.new_value === null ? "מידע פרטי" : formatFieldUpdateValue(item.field_name, item.new_value, t)}</strong></div>
                  <p className="text-xs text-amber-700 dark:text-amber-400">{t("approvals.waiting_for")}: {waitingForName}</p>
                </div>
              );
            })}
            {erWaiting.map(er => {
              const waitingForName = er.status === "pending_commander"
                ? (er.nearest_commander?.name ?? "—")
                : (er.nearest_duty_manager?.name ?? "—");
              return (
                <div key={er.id} className="border dark:border-gray-600 rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2 mb-1">
                    <strong><SoldierLink id={er.soldier_id} name={er.soldier_name || er.soldier_id.slice(0, 8)} /></strong>
                    {er.node_name && <span className="text-xs text-gray-400">{er.node_name}</span>}
                  </div>
                  <p className="text-sm font-medium mb-1">
                    {exemptionTypes.find(et => et.id === er.exemption_type_id)?.name ?? t("exemptions.unknown_type")}
                  </p>
                  <p className="text-xs text-gray-500" dir="ltr">
                    {er.start_date ?? t("exemption_requests.start_date_pending_approval")} → {er.end_date ?? t("exemptions.forever")}
                  </p>
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    {t("approvals.waiting_for")}: {er.status === "pending_commander" ? t("swaps.approver_kind_commander") : t("swaps.approver_kind_duty_manager")} {waitingForName}
                  </p>
                </div>
              );
            })}
            {swapsWaiting.map(swap => {
              const reqGroups = groupByKind(swap.requester_manager_approvals);
              const liveCandidates = swap.candidates.filter(c => c.status === "pending" || c.status === "accepted");
              const statusColumns = [
                requesterColumn(
                  swap,
                  requireDutyManagerApproval,
                  `${t("swaps.requester")}: ${swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)}`,
                  t,
                ),
                ...liveCandidates.map(candidate =>
                  candidateColumn(candidate, requireDutyManagerApproval, candidate.soldier_name || candidate.soldier_id.slice(0, 8), t),
                ),
              ];
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div>
                    {[swap.duty_type_name, swap.duty_location_name].filter(Boolean).join(" — ") && (
                      <p className="font-medium">{[swap.duty_type_name, swap.duty_location_name].filter(Boolean).join(" — ")}</p>
                    )}
                    <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                  </div>
                  <SwapApprovalColumns columns={statusColumns} />
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    {t("approvals.waiting_for")}: {[
                      reqGroups.commander.length > 0 && !isSideSatisfied(reqGroups.commander) ? reqGroups.commander[0]?.commander_name : null,
                      reqGroups.duty_manager.length > 0 && !isSideSatisfied(reqGroups.duty_manager) ? reqGroups.duty_manager[0]?.commander_name : null,
                    ].filter(Boolean).join(", ") || t("swaps.requester")}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </section>
      {selectedEnrollment && (
        <EnrollmentApprovalModal
          req={selectedEnrollment}
          nodes={nodes}
          exemptionTypes={exemptionTypes}
          onClose={() => setSelectedEnrollment(null)}
          onDone={async () => {
            setSelectedEnrollment(null);
            await queryClient.invalidateQueries({ queryKey: queryKeys.pendingEnrollments() });
          }}
        />
      )}
      {previewFile && (
        <DocumentPreviewModal
          fileUrl={previewFile.url}
          fileName={previewFile.name}
          contentType={previewFile.contentType}
          onClose={() => {
            URL.revokeObjectURL(previewFile.url);
            setPreviewFile(null);
          }}
        />
      )}
    </Layout>
  );
}
