import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import ExemptionsPanel from "../components/ExemptionsPanel";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { NodeDTO, createNode, fetchTree } from "../api/hierarchy";
import { SoldierDTO, listSoldiers, onboardSoldier, resetSoldierPassword, softDeleteSoldier } from "../api/soldiers";

export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [selected, setSelected] = useState<SoldierDTO | null>(null);
  const canManageExemptions = user?.role === "admin" || user?.role === "commander" || user?.role === "duty_manager";
  const isAdmin = user?.role === "admin";

  async function refresh() {
    setNodes(await fetchTree());
    setSoldiers(await listSoldiers());
  }
  useEffect(() => { void refresh(); }, []);

  async function addSoldier(e: FormEvent) {
    e.preventDefault();
    const res = await onboardSoldier({ personal_number: pn, full_name: name, hierarchy_node_id: nodeId || null });
    setTempPw(res.temp_password);
    setPn(""); setName(""); setNodeId("");
    await refresh();
  }

  async function onReset(id: string) {
    const r = await resetSoldierPassword(id);
    setTempPw(r.temp_password);
  }

  async function onRemove(id: string) {
    if (!confirm(t("team.remove") + "?")) return;
    await softDeleteSoldier(id);
    await refresh();
  }

  async function addRootNode() {
    const nm = prompt(t("team.node_name"));
    if (!nm) return;
    await createNode({ level: "division", name: nm, parent_id: null });
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
          {isAdmin && (
            <button onClick={addRootNode} className="text-sm text-indigo-600" data-testid="add-department">
              {t("team.add_node")}
            </button>
          )}
        </div>
        <HierarchyTree nodes={nodes} soldiers={soldiers} isAdmin={isAdmin} onChanged={refresh} />

        {isAdmin && (
          <form onSubmit={addSoldier} className="flex flex-wrap items-end gap-2" data-testid="onboard-form">
            <label className="block">
              <span className="text-xs">{t("team.personal_number")}</span>
              <input className="block border rounded p-1" value={pn} onChange={(e) => setPn(e.target.value)} required data-testid="onboard-pn" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.full_name")}</span>
              <input className="block border rounded p-1" value={name} onChange={(e) => setName(e.target.value)} required data-testid="onboard-name" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <select className="block border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="onboard-node">
                <option value="">—</option>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
              </select>
            </label>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="onboard-submit">
              {t("team.add_soldier")}
            </button>
          </form>
        )}

        {tempPw && <div className="text-sm text-green-600" data-testid="temp-password">{t("team.temp_password_is", { pw: tempPw })}</div>}

        <table className="w-full text-sm" data-testid="soldier-table">
          <thead>
            <tr className="text-right text-gray-500">
              <th className="py-1">{t("team.personal_number")}</th>
              <th>{t("team.full_name")}</th>
              <th>{t("team.role")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {soldiers.map((s) => (
              <tr key={s.id} className="border-t" data-testid={`soldier-row-${s.personal_number}`}>
                <td className="py-1">{s.personal_number}</td>
                <td>{s.full_name}</td>
                <td>{s.role}</td>
                <td className="space-x-2 space-x-reverse">
                  <button onClick={() => onReset(s.id)} className="text-indigo-600" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                  <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                  <button onClick={() => setSelected(s)} className="text-indigo-600" data-testid={`exemptions-${s.personal_number}`}>{t("exemptions.title")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {selected && canManageExemptions && (
          <div className="border-t pt-4" data-testid="manage-exemptions">
            <div className="text-sm text-gray-500">{selected.full_name} ({selected.personal_number})</div>
            <ExemptionsPanel soldierId={selected.id} canManage={true} />
          </div>
        )}
      </section>
    </Layout>
  );
}
