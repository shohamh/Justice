import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable, type ColDef } from "../components/DataTable";
import Layout from "../components/Layout";
import HierarchyTree from "../components/HierarchyTree";
import AddRootNodeDialog from "../components/AddRootNodeDialog";
import UnifiedSoldierModal from "../components/UnifiedSoldierModal";
import { useAuth } from "../auth/AuthContext";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { SoldierDTO, listSoldiers, onboardSoldier, updateSoldier, resetSoldierPassword, softDeleteSoldier } from "../api/soldiers";

export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [showAddRoot, setShowAddRoot] = useState(false);
  const [editSoldier, setEditSoldier] = useState<SoldierDTO | null>(null);
  const isAdmin = user?.role === "admin";

  async function refresh() {
    setNodes(await fetchTree());
    setSoldiers(await listSoldiers());
  }
  useEffect(() => { void refresh(); }, []);

  async function addSoldier(e: FormEvent) {
    e.preventDefault();
    const existing = soldiers.find((s) => s.personal_number === pn && !s.left_at);
    if (existing) {
      await updateSoldier(existing.id, { hierarchy_node_id: nodeId || null });
      setPn(""); setName(""); setNodeId("");
    } else {
      try {
        const res = await onboardSoldier({ personal_number: pn, full_name: name, hierarchy_node_id: nodeId || null });
        setTempPw(res.temp_password);
        setPn(""); setName(""); setNodeId("");
      } catch {
        alert(t("errors.generic"));
      }
    }
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

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
          {isAdmin && (
            <button onClick={() => setShowAddRoot(true)} className="text-sm text-indigo-600" data-testid="add-department">
              {t("team.add_node")}
            </button>
          )}
        </div>
        <HierarchyTree nodes={nodes} soldiers={soldiers} isAdmin={isAdmin} onChanged={refresh} user={user} />

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

        <div className="overflow-x-auto">
          {(() => {
            const soldierCols: ColDef<SoldierDTO>[] = [
              {
                id: "personal_number",
                header: t("team.personal_number"),
                cell: (s) => s.personal_number,
                sortValue: (s) => s.personal_number,
                filterValue: (s) => s.personal_number,
              },
              {
                id: "full_name",
                header: t("team.full_name"),
                cell: (s) => s.full_name,
                sortValue: (s) => s.full_name,
                filterValue: (s) => s.full_name,
              },
              {
                id: "role",
                header: t("team.role"),
                cell: (s) => t(`role.${s.role}`),
                sortValue: (s) => t(`role.${s.role}`),
              },
              {
                id: "node",
                header: t("team.node"),
                cell: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "—",
                sortValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
                filterValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
              },
              {
                id: "actions",
                header: "",
                cell: (s) => (
                  <span className="space-x-2 space-x-reverse">
                    <button onClick={() => setEditSoldier(s)} className="text-indigo-600" data-testid={`edit-${s.personal_number}`}>{t("team.edit")}</button>
                    <button onClick={() => onReset(s.id)} className="text-indigo-600" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                    <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                  </span>
                ),
              },
            ];
            const activeSoldiers = soldiers.filter((s) => !s.left_at);
            return (
              <DataTable
                columns={soldierCols}
                data={activeSoldiers}
                filterPlaceholder={t("team.search_placeholder")}
                emptyMessage={t("team.no_soldiers")}
              />
            );
          })()}
        </div>
      </section>

      {showAddRoot && (
        <AddRootNodeDialog onClose={() => setShowAddRoot(false)} onCreated={refresh} />
      )}

      {editSoldier && (
        <UnifiedSoldierModal
          soldier={editSoldier}
          score={null}
          nodes={nodes}
          onClose={() => setEditSoldier(null)}
          onRefresh={refresh}
        />
      )}
    </Layout>
  );
}
