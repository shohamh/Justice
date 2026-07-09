import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { formatFieldUpdateValue } from "../utils/formatFieldUpdateValue";
import SoldierLink from "../components/SoldierLink";
import EnrollmentApprovalModal from "../components/EnrollmentApprovalModal";
import { listPublicExemptionTypes } from "../api/auth";
import { fetchFullTree, NodeDTO } from "../api/hierarchy";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";
import {
  ExemptionRequest,
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
  SwapRequest,
  approveSwapSide,
  listPendingSwaps,
  rejectSwap,
} from "../api/swaps";
import { EnrollmentRequestDTO, listPendingEnrollments, approveEnrollment, rejectEnrollment } from "../api/enrollment";

function describeError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  return "שגיאה בביצוע הפעולה";
}

function daysBetween(start: string, end: string | null | undefined): number | null {
  if (!end) return null;
  const a = new Date(start);
  const b = new Date(end);
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

function DaysBadge({ start, end }: { start: string; end: string | null | undefined }) {
  const days = daysBetween(start, end);
  if (days === null) return null;
  const cls =
    days > 90
      ? "text-red-600 dark:text-red-400"
      : days > 30
      ? "text-yellow-600 dark:text-yellow-400"
      : "text-gray-400 dark:text-gray-500";
  return <span className={`text-xs ${cls}`}>({days} ימים)</span>;
}

type Tab = "constraints" | "exemptions" | "field_updates" | "swaps" | "enrollment";

const VALID_TABS: Tab[] = ["constraints", "exemptions", "field_updates", "swaps", "enrollment"];

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab") as Tab | null;
  const tab: Tab = rawTab && VALID_TABS.includes(rawTab) ? rawTab : "constraints";

  function setTab(next: Tab) {
    setSearchParams((prev) => { prev.set("tab", next); return prev; }, { replace: true });
  }
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [erItems, setErItems] = useState<ExemptionRequest[]>([]);
  const [fuItems, setFuItems] = useState<FieldUpdateDTO[]>([]);
  const [swapItems, setSwapItems] = useState<SwapRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});
  const [fuNotes, setFuNotes] = useState<Record<string, string>>({});
  const [swapRejectNotes, setSwapRejectNotes] = useState<Record<string, string>>({});
  const [enrollItems, setEnrollItems] = useState<EnrollmentRequestDTO[]>([]);
  const [enrollRejectNotes, setEnrollRejectNotes] = useState<Record<string, string>>({});
  const [selectedEnrollment, setSelectedEnrollment] = useState<EnrollmentRequestDTO | null>(null);
  const [nodes, setNodes] = useState<{ id: string; name: string }[]>([]);
  const [exemptionTypes, setExemptionTypes] = useState<{ id: string; name: string }[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const [constraints, exemptionReqs, fieldUpdates, swaps, enrollments, tree, etypes] = await Promise.all([
        listPendingApprovals(),
        listPendingExemptionRequests(),
        listPendingFieldUpdates(),
        listPendingSwaps(),
        listPendingEnrollments(),
        fetchFullTree(),
        listPublicExemptionTypes(),
      ]);
      setItems(constraints);
      setErItems(exemptionReqs);
      setFuItems(fieldUpdates);
      setSwapItems(swaps);
      setEnrollItems(enrollments);
      // Flatten tree into id+name list
      const flatNodes: { id: string; name: string }[] = [];
      function flatten(nodes: NodeDTO[]) {
        for (const n of nodes) {
          flatNodes.push({ id: n.id, name: n.name });
          if (n.children) flatten(n.children);
        }
      }
      flatten(tree);
      setNodes(flatNodes);
      setExemptionTypes(etypes.map(et => ({ id: et.id, name: et.name })));
    })();
  }, []);

  const refresh = useCallback(async () => {
    const [constraints, exemptionReqs, fieldUpdates, swaps, enrollments] = await Promise.all([
      listPendingApprovals(),
      listPendingExemptionRequests(),
      listPendingFieldUpdates(),
      listPendingSwaps(),
      listPendingEnrollments(),
    ]);
    setItems(constraints);
    setErItems(exemptionReqs);
    setFuItems(fieldUpdates);
    setSwapItems(swaps);
    setEnrollItems(enrollments);
  }, []);

  async function onApprove(id: string) {
    try {
      await approveConstraint(id);
      await refresh();
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
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onErApproveCommander(id: string) {
    try {
      await approveExemptionRequestCommanderStep(id);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onErApproveDutyManager(id: string) {
    try {
      await approveExemptionRequestDutyManagerStep(id);
      await refresh();
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
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onFuApprove(item: FieldUpdateDTO) {
    try {
      await approveFieldUpdate(item.soldier_id, item.id, fuNotes[item.id]);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onFuReject(item: FieldUpdateDTO) {
    const note = fuNotes[item.id];
    if (!note) return;
    try {
      await rejectFieldUpdate(item.soldier_id, item.id, note);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onSwapApproveSide(id: string, side: "requester" | "covering") {
    try {
      await approveSwapSide(id, side);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }
  async function onSwapReject(id: string) {
    try {
      await rejectSwap(id, swapRejectNotes[id]);
      const next = { ...swapRejectNotes };
      delete next[id];
      setSwapRejectNotes(next);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  async function onEnrollApprove(id: string, soldierName: string, nodeName: string) {
    if (!window.confirm(t("enrollment.confirm_approve", { soldier: soldierName, node: nodeName }))) return;
    try {
      await approveEnrollment(id);
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
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
      await refresh();
    } catch (err) {
      setActionError(describeError(err));
    }
  }

  const total = items.length + erItems.length + fuItems.length + swapItems.length + enrollItems.length;

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}{total > 0 ? ` (${total})` : ""}</h2>

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
            {t("approvals.tab_exemptions")}{erItems.length > 0 ? ` (${erItems.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "field_updates" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("field_updates")}
            data-testid="approvals-tab-field-updates"
          >
            {t("soldier_profile.field_updates_tab")}{fuItems.length > 0 ? ` (${fuItems.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "swaps" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("swaps")}
            data-testid="approvals-tab-swaps"
          >
            {t("swaps.title")}{swapItems.length > 0 ? ` (${swapItems.length})` : ""}
          </button>
          <button
            className={`pb-2 text-sm ${tab === "enrollment" ? "font-semibold border-b-2 border-indigo-600" : "text-gray-500"}`}
            onClick={() => setTab("enrollment")}
            data-testid="approvals-tab-enrollment"
          >
            {t("enrollment.tab")}{enrollItems.length > 0 ? ` (${enrollItems.length})` : ""}
          </button>
        </div>

        {tab === "constraints" && (
          <>
            {items.length === 0 && <p className="text-sm text-gray-500">{t("approvals.none")}</p>}
            <ul className="space-y-3" data-testid="approvals-list">
              {items.map((c) => {
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
            {erItems.length === 0 && <p className="text-sm text-gray-500">{t("approvals.exemption_none")}</p>}
            <ul className="space-y-3" data-testid="er-approvals-list">
              {erItems.map((er) => {
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
                    <span>{er.start_date} → {er.end_date ?? t("exemptions.forever")}</span>
                    <DaysBadge start={er.start_date} end={er.end_date} />
                  </p>
                  <p className="text-xs text-gray-500 mb-2">{er.reason ?? "מידע פרטי"}</p>
                  {er.files.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {er.files.map(f => (
                        <a
                          key={f.id}
                          href={exemptionFileDownloadUrl(er.id, f.id)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-600 dark:text-blue-400 text-xs hover:underline flex items-center gap-1"
                        >
                          📎 {f.file_name}
                        </a>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    {er.status === "pending_commander" && (
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApproveCommander(er.id)} data-testid={`er-approve-${er.id}`}>
                        אשר (שלב מפקד)
                      </button>
                    )}
                    {er.status === "pending_duty_manager" && (
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
            {fuItems.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {fuItems.map(item => {
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
                <div className="flex gap-2 items-center">
                  <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">{t("approvals.approve")}</button>
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
            {swapItems.length === 0 && <p className="text-gray-500 text-sm">{t("approvals.none")}</p>}
            {swapItems.map(swap => {
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong>{t("swaps.requester")}:</strong>
                    <span><SoldierLink id={swap.requesting_soldier_id} name={swap.requesting_soldier_name || swap.requesting_soldier_id.slice(0, 8)} /></span>
                    {swap.requesting_soldier_node_name && <span className="text-xs text-gray-400">{swap.requesting_soldier_node_name}</span>}
                  </div>
                  {swap.covering_soldier_id && (
                    <div className="flex items-center gap-2">
                      <strong>{t("swaps.covering")}:</strong>
                      <span><SoldierLink id={swap.covering_soldier_id} name={swap.covering_soldier_name || swap.covering_soldier_id.slice(0, 8)} /></span>
                    </div>
                  )}
                  <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
                  <div className="flex gap-2 items-center flex-wrap">
                    <button
                      onClick={() => onSwapApproveSide(swap.id, "requester")}
                      disabled={!!swap.requester_side_approved}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                    >
                      {swap.requester_side_approved ? "✓ " : ""}{t("approvals.approve")} ({t("swaps.requester")})
                    </button>
                    <button
                      onClick={() => onSwapApproveSide(swap.id, "covering")}
                      disabled={!!swap.covering_side_approved}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs disabled:opacity-50"
                    >
                      {swap.covering_side_approved ? "✓ " : ""}{t("approvals.approve")} ({t("swaps.covering")})
                    </button>
                    <input
                      placeholder={t("approvals.decision_note")}
                      value={swapRejectNotes[swap.id] ?? ""}
                      onChange={e => setSwapRejectNotes(prev => ({ ...prev, [swap.id]: e.target.value }))}
                      className="border rounded p-1 text-xs w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button
                      onClick={() => onSwapReject(swap.id)}
                      className="bg-red-600 text-white px-2 py-1 rounded text-xs"
                    >
                      {t("approvals.reject")}
                    </button>
                  </div>
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
              return (
                <div key={req.id} className="border rounded p-3 text-sm space-y-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700" onClick={() => setSelectedEnrollment(req)}>
                  <div className="flex items-center gap-2">
                    <strong><SoldierLink id={req.soldier_id} name={req.soldier_name} /></strong>
                    <span className="text-xs text-gray-400">{t("enrollment.click_to_view_profile")}</span>
                  </div>
                  <p className="text-gray-500">{t("enrollment.requested_node")}: <strong>{nodeName}</strong></p>
                  <div className="flex gap-2 items-center" onClick={e => e.stopPropagation()}>
                    <button onClick={() => onEnrollApprove(req.id, req.soldier_name, nodeName)}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs">
                      {t("enrollment.approve")}
                    </button>
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
      </section>
      {selectedEnrollment && (
        <EnrollmentApprovalModal
          req={selectedEnrollment}
          nodes={nodes}
          exemptionTypes={exemptionTypes}
          onClose={() => setSelectedEnrollment(null)}
          onDone={async () => { setSelectedEnrollment(null); await refresh(); }}
        />
      )}
    </Layout>
  );
}
