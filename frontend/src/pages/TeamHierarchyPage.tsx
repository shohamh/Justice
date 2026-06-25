import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable, type ColDef } from "../components/DataTable";
import Layout from "../components/Layout";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "../components/Combobox";
import { SoldierDTO, listSoldiers, onboardSoldier, updateSoldier, resetSoldierPassword, softDeleteSoldier } from "../api/soldiers";
import TelegramBadge from "../components/TelegramBadge";

export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { openSoldierModal } = useSoldierModal();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const isAdmin = user?.role === "admin";
  const canManageLevelTypes = user?.role === "admin" || (user?.is_duty_manager ?? false);

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
    if (!window.confirm(t("team.confirm_reset_password", "לאפס סיסמה לחייל זה?"))) return;
    const r = await resetSoldierPassword(id);
    setTempPw(r.temp_password);
  }

  async function onRemove(id: string) {
    const commandedNode = nodes.find((n) => n.commander_id === id);
    if (commandedNode) {
      alert(`${t("team.cannot_delete_commander")} "${commandedNode.name}". ${t("team.reassign_commander_first")}`);
      return;
    }
    if (!confirm(t("team.remove") + "?")) return;
    await softDeleteSoldier(id);
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
        </div>
        <HierarchyTree nodes={nodes} soldiers={soldiers} isAdmin={isAdmin} onChanged={refresh} canManageLevelTypes={canManageLevelTypes} />

        {isAdmin && (
          <form onSubmit={addSoldier} className="flex flex-wrap items-end gap-2" data-testid="onboard-form">
            <label className="block">
              <span className="text-xs">{t("team.personal_number")}</span>
              <input className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={pn} onChange={(e) => setPn(e.target.value)} required data-testid="onboard-pn" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.full_name")}</span>
              <input className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} required data-testid="onboard-name" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <Combobox
                items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                value={nodeId}
                onChange={setNodeId}
                placeholder="—"
                testId="onboard-node"
              />
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
                id: "telegram",
                header: t("team.telegram"),
                cell: (s) => <TelegramBadge linked={s.telegram_linked} />,
                sortValue: (s) => (s.telegram_linked ? 0 : 1),
              },
              {
                id: "node",
                header: t("team.node"),
                cell: (s) => {
                  if (!s.hierarchy_node_id) return <span className="text-gray-400">—</span>;
                  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
                  const soldierNode = nodeMap.get(s.hierarchy_node_id);
                  if (!soldierNode) return <span className="text-gray-400">—</span>;
                  const chain = soldierNode.path_ids.map((id) => nodeMap.get(id)?.name).filter(Boolean) as string[];
                  if (chain.length === 0) return <span>{soldierNode.name}</span>;
                  return (
                    <span className="text-xs">
                      {chain.map((name, i) => (
                        <span key={i}>
                          {i > 0 && <span className="text-gray-300 dark:text-gray-600 mx-0.5">›</span>}
                          <span className={i === chain.length - 1 ? "font-medium" : "text-gray-500 dark:text-gray-400"}>{name}</span>
                        </span>
                      ))}
                    </span>
                  );
                },
                sortValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
                filterValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
              },
              {
                id: "actions",
                header: "",
                cell: (s) => (
                  <span className="space-x-2 space-x-reverse">
                    <button onClick={() => openSoldierModal(s.id, refresh)} className="text-indigo-600 dark:text-indigo-300" data-testid={`edit-${s.personal_number}`}>{t("team.edit")}</button>
                    <button onClick={() => onReset(s.id)} className="text-indigo-600 dark:text-indigo-300" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
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
                testId="soldier-table"
                rowTestId={(s) => `soldier-row-${s.personal_number}`}
              />
            );
          })()}
        </div>
      </section>



    </Layout>
  );
}
