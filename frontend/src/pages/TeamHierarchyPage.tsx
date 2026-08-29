import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import { DataTable, type ColDef } from "../components/DataTable";
import Layout from "../components/Layout";
import HierarchyTree from "../components/HierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import { fetchTree } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import Combobox from "../components/Combobox";
import { SoldierDTO, listSoldiers, onboardSoldier, promoteSoldierToAdmin, resetSoldierPassword, softDeleteSoldier } from "../api/soldiers";
import { createTransferRequest } from "../api/hierarchyTransfers";
import TelegramBadge from "../components/TelegramBadge";
import { usePortfolioDialog } from "../hooks/usePortfolioDialog";
import { translateApiError } from "../utils/translateApiError";
import PasswordInput from "../components/PasswordInput";
import ConfirmDialog from "../components/ConfirmDialog";
import MessageDialog from "../components/MessageDialog";

export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { openSoldierModal } = useSoldierModal();
  const queryClient = useQueryClient();
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [resetTargetId, setResetTargetId] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [removeTargetId, setRemoveTargetId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [promotionTarget, setPromotionTarget] = useState<SoldierDTO | null>(null);
  const [promotionPassword, setPromotionPassword] = useState("");
  const [promotionAcknowledged, setPromotionAcknowledged] = useState(false);
  const [promotionError, setPromotionError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const isAdmin = user?.role === "admin";
  const canManageLevelTypes = user?.role === "admin" || (user?.is_duty_manager ?? false);
  const canDeleteSoldier = user?.can_delete_soldier ?? false;

  const nodesQuery = useQuery({ queryKey: queryKeys.hierarchyTreeVisible(), queryFn: fetchTree });
  const nodes = Array.isArray(nodesQuery.data) ? nodesQuery.data : [];

  const soldiersQuery = useQuery({ queryKey: queryKeys.soldiers(), queryFn: listSoldiers });
  const soldiers: SoldierDTO[] = Array.isArray(soldiersQuery.data) ? soldiersQuery.data : [];

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: queryKeys.hierarchyTreeVisible() });
    await queryClient.invalidateQueries({ queryKey: queryKeys.soldiers() });
  }

  const portfolioDialog = usePortfolioDialog(nodes, refresh);

  async function addSoldier(e: FormEvent) {
    e.preventDefault();
    const existing = soldiers.find((s) => s.personal_number === pn && !s.left_at);
    if (existing) {
      // Assigning an existing soldier to this node goes through the
      // hierarchy-transfer request flow (pending the destination's
      // approval), not a direct update — see HierarchyTree's handleQuickAdd
      // for the same pattern. No node selected means nothing to request.
      if (nodeId) await createTransferRequest(existing.id, nodeId);
      setPn(""); setName(""); setNodeId("");
    } else {
      try {
        const res = await onboardSoldier({ personal_number: pn, full_name: name, hierarchy_node_id: nodeId || null });
        setTempPw(res.temp_password);
        setPn(""); setName(""); setNodeId("");
      } catch {
        setMessage(t("errors.generic"));
      }
    }
    await refresh();
  }

  async function confirmReset() {
    if (!resetTargetId || resetting) return;
    const soldierId = resetTargetId;
    setResetting(true);
    setMessage(null);
    try {
      const r = await resetSoldierPassword(soldierId);
      setTempPw(r.temp_password);
      setResetTargetId(null);
    } catch {
      setMessage(t("errors.generic"));
    } finally {
      setResetting(false);
    }
  }

  function onRemove(id: string) {
    const commandedNode = nodes.find((n) => n.commander_id === id);
    if (commandedNode) {
      setMessage(`${t("team.cannot_delete_commander")} "${commandedNode.name}". ${t("team.reassign_commander_first")}`);
      return;
    }
    setRemoveTargetId(id);
  }

  async function confirmRemove() {
    if (!removeTargetId) return;
    const soldierId = removeTargetId;
    setRemoveTargetId(null);
    setRemoveError(null);
    try {
      await softDeleteSoldier(soldierId, new Date().toISOString().slice(0, 10));
      await refresh();
    } catch (err) {
      setRemoveError(translateApiError(err, t, "אין לך הרשאה למחוק חייל זה"));
    }
  }

  function openPromotion(soldier: SoldierDTO) {
    setPromotionTarget(soldier);
    setPromotionPassword("");
    setPromotionAcknowledged(false);
    setPromotionError(null);
  }

  function closePromotion() {
    if (!promoting) {
      setPromotionTarget(null);
      setPromotionPassword("");
      setPromotionAcknowledged(false);
      setPromotionError(null);
    }
  }

  async function confirmPromotion() {
    if (!promotionTarget || !promotionAcknowledged || !promotionPassword) return;
    setPromoting(true);
    setPromotionError(null);
    try {
      await promoteSoldierToAdmin(promotionTarget.id, promotionPassword);
      await refresh();
      setPromotionTarget(null);
      setPromotionPassword("");
      setPromotionAcknowledged(false);
    } catch (err) {
      setPromotionError(translateApiError(err, t));
    } finally {
      setPromoting(false);
    }
  }

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
        </div>
        <HierarchyTree nodes={nodes} soldiers={soldiers} onChanged={refresh} canManageLevelTypes={canManageLevelTypes} />

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
        {removeError && <div className="text-sm text-red-600" data-testid="remove-error">{removeError}</div>}

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
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {(isAdmin || (user?.is_commander ?? false)) && (
                      <button
                        onClick={() => portfolioDialog.open(s.id, s.full_name)}
                        className="text-indigo-600 dark:text-indigo-300"
                        data-testid={`dm-portfolio-${s.personal_number}`}
                      >
                        {t("team.manage_portfolio")}
                      </button>
                    )}
                    <button onClick={() => openSoldierModal(s.id, refresh)} className="text-indigo-600 dark:text-indigo-300" data-testid={`edit-${s.personal_number}`}>{t("team.edit")}</button>
                    <button onClick={() => setResetTargetId(s.id)} className="text-indigo-600 dark:text-indigo-300" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                    {isAdmin && s.role !== "admin" && (
                      <button onClick={() => openPromotion(s)} className="text-amber-700 dark:text-amber-300" data-testid={`promote-admin-${s.personal_number}`}>
                        {t("team.promote_admin")}
                      </button>
                    )}
                    {canDeleteSoldier && (
                      <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                    )}
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

        {portfolioDialog.dialog}
        <ConfirmDialog
          open={resetTargetId !== null}
          title={t("team.reset_password_title")}
          message={t("team.confirm_reset_password")}
          danger
          confirmDisabled={resetting}
          onConfirm={() => void confirmReset()}
          onClose={() => { if (!resetting) setResetTargetId(null); }}
        />
        <ConfirmDialog
          open={removeTargetId !== null}
          title={t("team.remove_soldier_title")}
          message={t("team.confirm_remove_soldier")}
          confirmLabel={t("team.remove")}
          danger
          onConfirm={() => void confirmRemove()}
          onClose={() => setRemoveTargetId(null)}
        />
        <MessageDialog
          open={message !== null}
          title={t("common.error")}
          message={message ?? ""}
          onClose={() => setMessage(null)}
        />
        {promotionTarget && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={closePromotion} data-testid="promote-admin-modal">
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-md w-full" dir="rtl" onClick={(event) => event.stopPropagation()}>
              <h3 className="font-bold text-lg mb-3">{t("team.promote_admin_title")}</h3>
              <p className="text-sm text-gray-700 dark:text-gray-300 mb-4">{t("team.promote_admin_warning", { name: promotionTarget.full_name })}</p>
              <label className="block text-sm mb-4">
                <span className="block mb-1">{t("team.current_password")}</span>
                <PasswordInput
                  value={promotionPassword}
                  onChange={(event) => setPromotionPassword(event.target.value)}
                  className="w-full border rounded p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  autoComplete="current-password"
                  dir="ltr"
                />
              </label>
              <label className="flex items-start gap-2 text-sm mb-4 cursor-pointer">
                <input type="checkbox" checked={promotionAcknowledged} onChange={(event) => setPromotionAcknowledged(event.target.checked)} data-testid="promote-admin-acknowledgement" />
                <span>{t("team.promote_admin_acknowledgement")}</span>
              </label>
              {promotionError && <p className="text-red-600 text-sm mb-3">{promotionError}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={closePromotion} disabled={promoting} className="border dark:border-gray-600 rounded px-3 py-1 dark:text-gray-200">{t("team.cancel")}</button>
                <button type="button" onClick={() => void confirmPromotion()} disabled={promoting || !promotionAcknowledged || !promotionPassword} className="bg-amber-700 text-white rounded px-3 py-1 disabled:opacity-50" data-testid="promote-admin-confirm">
                  {t("team.promote_admin_confirm")}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </Layout>
  );
}
