import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import SoldierLink from "../components/SoldierLink";
import {
  PersonalConstraint,
  approveConstraint,
  listPendingApprovals,
  rejectConstraint,
} from "../api/constraints";
import {
  ExemptionFile,
  ExemptionRequest,
  approveExemptionRequest,
  exemptionFileDownloadUrl,
  listExemptionFiles,
  listPendingExemptionRequests,
  rejectExemptionRequest,
} from "../api/exemptions";
import {
  FieldUpdateDTO,
  approveFieldUpdate,
  listSoldiers,
  rejectFieldUpdate,
  listPendingFieldUpdates,
  SoldierDTO,
} from "../api/soldiers";
import { fetchTree, NodeDTO } from "../api/hierarchy";
import {
  SwapRequest,
  approveSwapSide,
  listPendingSwaps,
  rejectSwap,
} from "../api/swaps";
import { EnrollmentRequestDTO, listPendingEnrollments, approveEnrollment, rejectEnrollment } from "../api/enrollment";

type Tab = "constraints" | "exemptions" | "field_updates" | "swaps" | "enrollment";

function flattenTree(nodes: NodeDTO[]): Map<string, NodeDTO> {
  const map = new Map<string, NodeDTO>();
  function walk(list: NodeDTO[]) {
    for (const n of list) {
      map.set(n.id, n);
      if ((n as unknown as { children?: NodeDTO[] }).children) {
        walk((n as unknown as { children: NodeDTO[] }).children);
      }
    }
  }
  walk(nodes);
  return map;
}

export default function ApprovalsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("constraints");
  const [items, setItems] = useState<PersonalConstraint[]>([]);
  const [erItems, setErItems] = useState<ExemptionRequest[]>([]);
  const [fuItems, setFuItems] = useState<FieldUpdateDTO[]>([]);
  const [swapItems, setSwapItems] = useState<SwapRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});
  const [fuNotes, setFuNotes] = useState<Record<string, string>>({});
  const [swapRejectNotes, setSwapRejectNotes] = useState<Record<string, string>>({});
  const [enrollItems, setEnrollItems] = useState<EnrollmentRequestDTO[]>([]);
  const [enrollRejectNotes, setEnrollRejectNotes] = useState<Record<string, string>>({});
  const [soldierMap, setSoldierMap] = useState<Map<string, SoldierDTO>>(new Map());
  const [nodeMap, setNodeMap] = useState<Map<string, NodeDTO>>(new Map());
  const [requestFiles, setRequestFiles] = useState<Record<string, ExemptionFile[]>>({});

  useEffect(() => {
    void (async () => {
      const [soldiers, tree] = await Promise.all([listSoldiers(), fetchTree()]);
      setSoldierMap(new Map(soldiers.map(s => [s.id, s])));
      setNodeMap(flattenTree(tree));
    })();
  }, []);

  const refresh = useCallback(async () => {
    setItems(await listPendingApprovals());
    const exemptionReqs = await listPendingExemptionRequests();
    setErItems(exemptionReqs);
    setFuItems(await listPendingFieldUpdates());
    setSwapItems(await listPendingSwaps());
    setEnrollItems(await listPendingEnrollments());
    // Load files for all exemption requests
    for (const req of exemptionReqs) {
      listExemptionFiles(req.id)
        .then(files => { if (files.length > 0) setRequestFiles(prev => ({ ...prev, [req.id]: files })); })
        .catch(() => {});
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onApprove(id: string) {
    await approveConstraint(id);
    await refresh();
  }
  async function onReject(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectConstraint(id, note);
    const next = { ...rejectNotes };
    delete next[id];
    setRejectNotes(next);
    await refresh();
  }

  async function onErApprove(id: string) {
    await approveExemptionRequest(id);
    await refresh();
  }
  async function onErReject(id: string) {
    const note = rejectNotes[`er-${id}`];
    if (!note) return;
    await rejectExemptionRequest(id, note);
    const next = { ...rejectNotes };
    delete next[`er-${id}`];
    setRejectNotes(next);
    await refresh();
  }

  async function onFuApprove(item: FieldUpdateDTO) {
    await approveFieldUpdate(item.soldier_id, item.id, fuNotes[item.id]);
    await refresh();
  }
  async function onFuReject(item: FieldUpdateDTO) {
    const note = fuNotes[item.id];
    if (!note) return;
    await rejectFieldUpdate(item.soldier_id, item.id, note);
    await refresh();
  }

  function soldierDisplay(id: string): { name: string; node: string } {
    const s = soldierMap.get(id);
    const nodeName = s && nodeMap.get(s.hierarchy_node_id ?? "")?.name;
    return {
      name: s?.full_name ?? id.slice(0, 8),
      node: nodeName ?? "",
    };
  }

  async function onSwapApproveSide(id: string, side: "requester" | "covering") {
    await approveSwapSide(id, side);
    await refresh();
  }
  async function onSwapReject(id: string) {
    await rejectSwap(id, swapRejectNotes[id]);
    const next = { ...swapRejectNotes };
    delete next[id];
    setSwapRejectNotes(next);
    await refresh();
  }

  async function onEnrollApprove(id: string) {
    await approveEnrollment(id);
    await refresh();
  }
  async function onEnrollReject(id: string) {
    const note = enrollRejectNotes[id];
    if (!note) return;
    await rejectEnrollment(id, note);
    const next = { ...enrollRejectNotes };
    delete next[id];
    setEnrollRejectNotes(next);
    await refresh();
  }

  const total = items.length + erItems.length + fuItems.length + swapItems.length + enrollItems.length;

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-xl font-semibold">{t("approvals.title")}{total > 0 ? ` (${total})` : ""}</h2>

        <div className="flex gap-4 border-b">
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
                const sd = soldierDisplay(c.soldier_id);
                return (
                <li key={c.id} className="border rounded p-3" data-testid={`approval-row-${c.id}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <strong className="text-sm"><SoldierLink id={c.soldier_id} name={sd.name} /></strong>
                    {sd.node && <span className="text-xs text-gray-400">{sd.node}</span>}
                  </div>
                  <p className="text-sm" dir="ltr">{c.start_date} → {c.end_date}</p>
                  <p className="text-xs text-gray-500 mb-2">{c.reason}</p>
                  <div className="flex items-center gap-2">
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onApprove(c.id)} data-testid={`approve-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28"
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
                      {t("approvals.reject")}
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
                const sd = soldierDisplay(er.soldier_id);
                return (
                <li key={er.id} className="border rounded p-3" data-testid={`er-approval-row-${er.id}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <strong className="text-sm"><SoldierLink id={er.soldier_id} name={sd.name} /></strong>
                    {sd.node && <span className="text-xs text-gray-400">{sd.node}</span>}
                  </div>
                  <p className="text-sm" dir="ltr">{er.start_date} → {er.end_date ?? t("exemptions.forever")}</p>
                  <p className="text-xs text-gray-500 mb-2">{er.reason}</p>
                  {(requestFiles[er.id] ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2">
                      {(requestFiles[er.id] ?? []).map(f => (
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
                    <button className="bg-green-600 text-white px-3 py-1 rounded text-sm" onClick={() => onErApprove(er.id)} data-testid={`er-approve-${er.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <input
                      className="border rounded p-1 text-sm w-28"
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
              const sd = soldierDisplay(item.soldier_id);
              return (
              <div key={item.id} className="border rounded p-3 text-sm space-y-2">
                <div className="flex items-center gap-2">
                  <strong><SoldierLink id={item.soldier_id} name={sd.name} /></strong>
                  {sd.node && <span className="text-xs text-gray-400">{sd.node}</span>}
                  <span className="text-gray-400">—</span>
                  <span>{t(`soldier_profile.${item.field_name}`)}</span>
                </div>
                <div className="text-gray-500">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.previous_value ? (item.field_name === "gender" ? t(`soldier_profile.gender_${item.previous_value}`) : item.previous_value) : "—"}</span></div>
                <div className="text-gray-600">{t("approvals.field_update_new_value")}<strong>{item.field_name === "gender" ? t(`soldier_profile.gender_${item.new_value}`) : item.new_value}</strong></div>
                <div className="flex gap-2 items-center">
                  <button onClick={() => onFuApprove(item)} className="bg-green-600 text-white px-2 py-1 rounded text-xs">{t("approvals.approve")}</button>
                  <input
                    placeholder={t("approvals.decision_note")}
                    value={fuNotes[item.id] ?? ""}
                    onChange={e => setFuNotes(prev => ({ ...prev, [item.id]: e.target.value }))}
                    className="border rounded p-1 text-xs flex-1"
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
              const requesterSd = soldierDisplay(swap.requesting_soldier_id);
              const coveringSd = swap.covering_soldier_id ? soldierDisplay(swap.covering_soldier_id) : null;
              return (
                <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong>{t("swaps.requester")}:</strong>
                    <span><SoldierLink id={swap.requesting_soldier_id} name={requesterSd.name} /></span>
                    {requesterSd.node && <span className="text-xs text-gray-400">{requesterSd.node}</span>}
                  </div>
                  {coveringSd && (
                    <div className="flex items-center gap-2">
                      <strong>{t("swaps.covering")}:</strong>
                      <span><SoldierLink id={swap.covering_soldier_id!} name={coveringSd.name} /></span>
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
                      className="border rounded p-1 text-xs w-28"
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
              const sd = soldierDisplay(req.soldier_id);
              const nodeName = nodeMap.get(req.requested_node_id)?.name ?? req.requested_node_id.slice(0, 8);
              return (
                <div key={req.id} className="border rounded p-3 text-sm space-y-2">
                  <div className="flex items-center gap-2">
                    <strong><SoldierLink id={req.soldier_id} name={sd.name} /></strong>
                    {sd.node && <span className="text-xs text-gray-400">{sd.node}</span>}
                  </div>
                  <p className="text-gray-500">{t("enrollment.requested_node")}: <strong>{nodeName}</strong></p>
                  <div className="flex gap-2 items-center">
                    <button onClick={() => onEnrollApprove(req.id)}
                      className="bg-green-600 text-white px-2 py-1 rounded text-xs">
                      {t("enrollment.approve")}
                    </button>
                    <input
                      placeholder={t("enrollment.decision_note_placeholder")}
                      value={enrollRejectNotes[req.id] ?? ""}
                      onChange={e => setEnrollRejectNotes(prev => ({ ...prev, [req.id]: e.target.value }))}
                      className="border rounded p-1 text-xs flex-1"
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
    </Layout>
  );
}
