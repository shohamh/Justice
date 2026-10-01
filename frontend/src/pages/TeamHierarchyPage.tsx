import { FormEvent, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../queryKeys";
import { type ColDef } from "../components/DataTable";
import CursorPagedTable from "../components/CursorPagedTable";
import Layout from "../components/Layout";
import LazyHierarchyTree from "../components/LazyHierarchyTree";
import { useAuth } from "../auth/AuthContext";
import { useSoldierModal } from "../contexts/SoldierModalContext";
import { fetchTree, NodeDTO } from "../api/hierarchy";
import {
  SoldierDTO,
  SoldierRosterItemDTO,
  SoldierRosterSort,
  isStaleSoldierRosterCursorError,
  lookupSoldierByPersonalNumber,
  listSoldierRosterPage,
  onboardSoldier,
  promoteSoldierToAdmin,
  resetSoldierPassword,
  softDeleteSoldier,
} from "../api/soldiers";
import { createTransferRequest } from "../api/hierarchyTransfers";
import TelegramBadge from "../components/TelegramBadge";
import { usePortfolioDialog } from "../hooks/usePortfolioDialog";
import { translateApiError } from "../utils/translateApiError";
import PasswordInput from "../components/PasswordInput";
import ConfirmDialog from "../components/ConfirmDialog";
import MessageDialog from "../components/MessageDialog";
import { todayIso } from "../utils/formatDate";

export default function TeamHierarchyPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { openSoldierModal } = useSoldierModal();
  const queryClient = useQueryClient();
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [selectedNodeName, setSelectedNodeName] = useState("");
  const [portfolioNodes, setPortfolioNodes] = useState<NodeDTO[]>([]);
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const [resetTargetId, setResetTargetId] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [removeTargetId, setRemoveTargetId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [promotionTarget, setPromotionTarget] = useState<Pick<SoldierDTO, "id" | "full_name" | "role"> | null>(null);
  const [promotionPassword, setPromotionPassword] = useState("");
  const [promotionAcknowledged, setPromotionAcknowledged] = useState(false);
  const [promotionError, setPromotionError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const isAdmin = user?.role === "admin";
  const canManageLevelTypes = user?.role === "admin" || (user?.is_duty_manager ?? false);
  const canDeleteSoldier = user?.can_delete_soldier ?? false;
  const roleOrder = useMemo(
    () =>
      ([...(["admin", "commander", "duty_manager", "soldier"] as const)]).sort((left, right) =>
        t(`role.${left}`).localeCompare(t(`role.${right}`), "he"),
      ),
    [t, i18n.language],
  );
  const rosterScopeKey = JSON.stringify({
    id: user?.id,
    role: user?.role,
    hierarchyNodeId: user?.hierarchy_node_id,
    isCommander: user?.is_commander,
    isDutyManager: user?.is_duty_manager,
    deputyGrants: user?.active_deputy_grants,
  });
  const rosterRowId = useCallback((soldier: SoldierRosterItemDTO) => soldier.id, []);

  async function refresh() {
    await Promise.all([
      queryClient.resetQueries({ queryKey: queryKeys.hierarchyBranches(rosterScopeKey) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.hierarchySearches(rosterScopeKey) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.hierarchyTreeVisible() }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.soldiers(),
        exact: true,
      }),
      queryClient.resetQueries({ queryKey: queryKeys.soldierRoster() }),
    ]);
  }

  const portfolioDialog = usePortfolioDialog(portfolioNodes, refresh);

  async function openPortfolio(soldierId: string, soldierName: string) {
    try {
      const nodes = await fetchTree();
      setPortfolioNodes(nodes);
      portfolioDialog.open(soldierId, soldierName);
    } catch {
      setMessage(t("team.roster_load_failed"));
    }
  }

  async function addSoldier(e: FormEvent) {
    e.preventDefault();
    try {
      const existing = await lookupSoldierByPersonalNumber(pn);
      if (existing) {
        // Existing soldiers still enter the destination's approval flow.
        if (nodeId) await createTransferRequest(existing.id, nodeId);
        setPn(""); setName(""); setNodeId(""); setSelectedNodeName("");
      } else {
        const res = await onboardSoldier({ personal_number: pn, full_name: name, hierarchy_node_id: nodeId || null });
        setTempPw(res.temp_password);
        setPn(""); setName(""); setNodeId(""); setSelectedNodeName("");
      }
    } catch {
      setMessage(t("team.roster_load_failed"));
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
      setMessage("שגיאה באיפוס סיסמת החייל");
    } finally {
      setResetting(false);
    }
  }

  function onRemove(soldier: SoldierRosterItemDTO) {
    if (soldier.is_commander) {
      const nodeName = soldier.commander_node_name ?? soldier.full_name;
      setMessage(`${t("team.cannot_delete_commander")} "${nodeName}". ${t("team.reassign_commander_first")}`);
      return;
    }
    setRemoveTargetId(soldier.id);
  }

  async function confirmRemove() {
    if (!removeTargetId) return;
    const soldierId = removeTargetId;
    setRemoveTargetId(null);
    setRemoveError(null);
    try {
      await softDeleteSoldier(soldierId, todayIso());
      await refresh();
    } catch (err) {
      setRemoveError(translateApiError(err, t, "אין לך הרשאה למחוק חייל זה"));
    }
  }

  function openPromotion(soldier: Pick<SoldierDTO, "id" | "full_name" | "role">) {
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
      setPromotionError(translateApiError(err, t, "שגיאה בהפיכת החייל למנהל מערכת"));
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
        <LazyHierarchyTree
          scopeKey={rosterScopeKey}
          roleOrder={[...roleOrder]}
          onChanged={refresh}
          canManageLevelTypes={canManageLevelTypes}
          onSelectedNodeChange={(node) => {
            setNodeId(node?.id ?? "");
            setSelectedNodeName(node?.name ?? "");
          }}
          onOpenPortfolio={(soldierId, soldierName) => void openPortfolio(soldierId, soldierName)}
        />

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
              <button
                type="button"
                className="block max-w-64 truncate border rounded p-1 text-right dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                onClick={() => document.querySelector<HTMLElement>('[data-testid="node-tree"]')?.focus()}
                data-testid="onboard-node"
                title={selectedNodeName || t("team.select_node_from_tree")}
              >
                {selectedNodeName || t("team.select_node_from_tree")}
              </button>
            </label>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="onboard-submit">
              {t("team.add_soldier")}
            </button>
          </form>
        )}

        {tempPw && <div className="text-sm text-green-600" data-testid="temp-password">{t("team.temp_password_is", { pw: tempPw })}</div>}
        {removeError && <div className="text-sm text-red-600" data-testid="remove-error">{removeError}</div>}

        {(() => {
            const soldierCols: ColDef<SoldierRosterItemDTO>[] = [
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
                  const chain = s.hierarchy_path;
                  if (chain.length === 0) return <span className="text-gray-400">—</span>;
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
                sortValue: (s) => s.hierarchy_path.at(-1) ?? "",
                filterValue: (s) => s.hierarchy_path.join(" "),
              },
              {
                id: "actions",
                header: "",
                cell: (s) => (
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    {(isAdmin || (user?.is_commander ?? false)) && (
                      <button
                        onClick={() => void openPortfolio(s.id, s.full_name)}
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
                      <button onClick={() => onRemove(s)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                    )}
                  </span>
                ),
              },
            ];
            return (
              <CursorPagedTable
                columns={soldierCols}
                queryKey={queryKeys.soldierRoster()}
                scopeKey={rosterScopeKey}
                filterKey={{ active_only: true }}
                roleOrder={[...roleOrder]}
                fetchPage={({ cursor, search, sort, descending, roleOrder: localizedRoleOrder, pageSize, signal }) =>
                  listSoldierRosterPage({
                    cursor,
                    search,
                    sort: sort as SoldierRosterSort,
                    descending,
                    role_order: localizedRoleOrder,
                    page_size: pageSize,
                    active_only: true,
                    signal,
                  })
                }
                getRowId={rosterRowId}
                tableLabel={t("team.title")}
                labels={{
                  searchLabel: t("team.roster_search_label"),
                  searchPlaceholder: t("team.roster_search_placeholder"),
                  loading: t("team.roster_loading"),
                  loadingMore: t("team.roster_loading_more"),
                  loadMore: t("team.roster_load_more"),
                  retry: t("team.roster_retry"),
                  loadFailed: t("team.roster_load_failed"),
                  emptyMessage: t("team.no_soldiers"),
                  loaded: (count) => t("team.roster_loaded", { count }),
                  allLoaded: (count) => t("team.roster_all_loaded", { count }),
                  keyboardHint: t("team.roster_keyboard_hint"),
                }}
                isCursorStaleError={isStaleSoldierRosterCursorError}
                pageSize={100}
                initialSort="full_name"
                testId="soldier-table"
                rowTestId={(s) => `soldier-row-${s.personal_number}`}
              />
            );
          })()}

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
