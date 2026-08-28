import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { NodeDTO } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import { SoldierDTO, SoldierScoreDTO, updateSoldier, updateSoldierProfile, getRanks } from "../api/soldiers";
import { createTransferRequest } from "../api/hierarchyTransfers";
import { translateApiError } from "../utils/translateApiError";
import { PersonalConstraint, listSoldierConstraints, approveConstraint, rejectConstraint, cancelConstraintForManager } from "../api/constraints";
import Combobox from "./Combobox";
import ExemptionsPanel from "./ExemptionsPanel";
import DutyHistoryPanel from "./DutyHistoryPanel";
import DeputiesPanel from "./DeputiesPanel";
import SoldierLink from "./SoldierLink";
import DateInput from "../components/DateInput";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../utils/formatDate";
import { useModalBackClose } from "../hooks/useModalBackClose";
import { getSoldierRangeStatus } from "../api/rangeStatus";
import { formatRangeStatus } from "../utils/rangeEligibilityExplanation";
import { parseRankSelectionId, rankSelectionId, RankTrack } from "../constants/ranks";
import ReasonPromptModal from "./ReasonPromptModal";
import ApprovalStageIcons from "./ApprovalStageIcons";

function SoldierAvatar({ url, name, size = 10 }: { url?: string | null; name: string; size?: number }) {
  const initials = name.split(" ").map((w) => w[0]).filter(Boolean).slice(0, 2).join("");
  if (url) {
    return (
      <img
        src={url}
        alt={name}
        className={`w-${size} h-${size} rounded-full object-cover shrink-0 border border-gray-200 dark:border-gray-600`}
        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
      />
    );
  }
  return (
    <div className={`w-${size} h-${size} rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0 text-indigo-700 dark:text-indigo-300 font-semibold text-sm`}>
      {initials}
    </div>
  );
}

interface Props {
  soldier: SoldierDTO;
  score: SoldierScoreDTO | null;
  nodes: NodeDTO[];
  onClose: () => void;
  onRefresh: () => void;
  initialEditing?: boolean;
  initialTab?: TabKey;
  initialHistoryTypes?: string[];
}

const ALL_TABS = ["details", "profile", "exemptions", "constraints", "duty_history"] as const;
export type TabKey = (typeof ALL_TABS)[number];

export default function UnifiedSoldierModal({ soldier, score, nodes, onClose, onRefresh, initialEditing = false, initialTab, initialHistoryTypes }: Props) {
  useModalBackClose(onClose);
  const { t } = useTranslation();
  const { user } = useAuth();
  const isSelf = user?.personal_number === soldier.personal_number;
  const isAdmin = user?.role === "admin";
  const isDutyManager = user?.is_duty_manager ?? false;
  const isCommander = user?.is_commander ?? false;
  const canManage = isAdmin || isDutyManager;
  // Backend authorizes commanders to grant exemptions too (Action.EXEMPTION_GRANT
  // is in _COMMANDER_ACTIONS) — this is scoped to ExemptionsPanel only, not the
  // broader `canManage` used for soldier-detail editing and constraint approval.
  const canManageExemptions = isAdmin || isDutyManager || isCommander;
  const canViewAll = isAdmin || isDutyManager || isCommander;
  const TABS: TabKey[] = canViewAll
    ? ["details", "profile", "exemptions", "constraints", "duty_history"]
    : isSelf
      ? ["details", "profile", "duty_history"]
      : ["details", "duty_history"];

  const [soldierData, setSoldierData] = useState<SoldierDTO>(soldier);

  useEffect(() => { setSoldierData(soldier); }, [soldier]);

  const [tab, setTab] = useState<TabKey>(initialTab ?? "details");
  const { data: rangeStatus } = useQuery({
    queryKey: ["soldierRangeStatus", soldierData.id],
    queryFn: () => getSoldierRangeStatus(soldierData.id),
    enabled: tab === "profile",
  });
  const [editing, setEditing] = useState(initialEditing);
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");
  const [enrolledAt, setEnrolledAt] = useState(soldier.enrolled_at ?? "");
  const [constraints, setConstraints] = useState<PersonalConstraint[]>([]);
  const [cancellingConstraintId, setCancellingConstraintId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  // Profile fields
  const [profileGender, setProfileGender] = useState(soldier.gender ?? "");
  const [profileIsOfficer, setProfileIsOfficer] = useState(soldier.is_officer ?? false);
  const [profileRank, setProfileRank] = useState(soldier.rank ?? "");
  const [profileRankTrack, setProfileRankTrack] = useState<RankTrack>(soldier.rank_track ?? (soldier.is_officer ? "officer" : "enlisted"));
  const [profileEnlistment, setProfileEnlistment] = useState(soldier.enlistment_date ?? "");
  const [profileMandEnd, setProfileMandEnd] = useState(soldier.mandatory_end_date ?? "");
  const [profileDischarge, setProfileDischarge] = useState(soldier.discharge_date ?? "");
  const [profileMitvahim, setProfileMitvahim] = useState(soldier.last_mitvahim_date ?? "");
  const [profileAlal, setProfileAlal] = useState(soldier.last_alal_date ?? "");
  const [profileEmail, setProfileEmail] = useState(soldier.email ?? "");
  const [profilePictureUrl, setProfilePictureUrl] = useState(soldier.profile_picture_url ?? "");
  const [profileHasLicense, setProfileHasLicense] = useState(soldier.has_military_driving_license ?? false);
  const [profileLicenseExpiry, setProfileLicenseExpiry] = useState(soldier.military_driving_license_expiry ?? "");
  const [profileFoodType, setProfileFoodType] = useState(soldier.food_type ?? "");
  const [profileFoodConstraints, setProfileFoodConstraints] = useState(soldier.food_constraints ?? "");
  const [showFoodHelp, setShowFoodHelp] = useState(false);
  const [rankOptions, setRankOptions] = useState<{ enlisted: string[]; officers: string[]; officer_academic: string[] }>({ enlisted: [], officers: [], officer_academic: [] });
  // Narrow rank/next-rank-date correction flow, for commanders/duty managers who
  // are authorized to edit rank advancement fields but lack ordinary full-profile
  // edit authority (`canManage`). Kept separate from the full profile editor's
  // `editing` state so opening one never implicitly opens the other.
  const [rankEditing, setRankEditing] = useState(false);
  const [nextRankDate, setNextRankDate] = useState(soldier.next_rank_date ?? "");
  const canEditRankNarrow = soldierData.can_edit_rank_advancement && !canManage;
  // Second line of defense (finding 1 of the final-review fix wave): the
  // backend now compares rank/rank_track values, not key presence, but the
  // frontend still shouldn't send unchanged rank/next-rank-date fields on an
  // ordinary profile save — it's unnecessary and adds audit noise.
  const rankFieldsDirty =
    profileRank !== (soldierData.rank ?? "") ||
    profileRankTrack !== (soldierData.rank_track ?? (soldierData.is_officer ? "officer" : "enlisted"));
  const nextRankDateDirty = nextRankDate !== (soldierData.next_rank_date ?? "");
  const genderDirty = profileGender !== (soldierData.gender ?? "");
  const isOfficerDirty = profileIsOfficer !== (soldierData.is_officer ?? false);
  const enlistmentDirty = profileEnlistment !== (soldierData.enlistment_date ?? "");
  const mandEndDirty = profileMandEnd !== (soldierData.mandatory_end_date ?? "");
  const dischargeDirty = profileDischarge !== (soldierData.discharge_date ?? "");
  const mitvahimDirty = profileMitvahim !== (soldierData.last_mitvahim_date ?? "");
  const alalDirty = profileAlal !== (soldierData.last_alal_date ?? "");
  const emailDirty = profileEmail !== (soldierData.email ?? "");
  const pictureDirty = profilePictureUrl !== (soldierData.profile_picture_url ?? "");
  const licenseDirty =
    profileHasLicense !== (soldierData.has_military_driving_license ?? false) ||
    (profileHasLicense && profileLicenseExpiry !== (soldierData.military_driving_license_expiry ?? ""));
  const foodTypeDirty = profileFoodType !== (soldierData.food_type ?? "");
  const foodConstraintsDirty = profileFoodConstraints !== (soldierData.food_constraints ?? "");
  // Gates both the Save button and handleProfileSave: a click that changed
  // nothing (opened the editor and immediately saved, or edited a field then
  // reverted it) must not fire a PATCH — the backend writes an audit entry
  // unconditionally for whatever's in the payload, so a no-op save would
  // otherwise log a misleading "changed" entry for every field it sent.
  const profileDirty =
    genderDirty || isOfficerDirty || enlistmentDirty || mandEndDirty || dischargeDirty || mitvahimDirty || alalDirty ||
    emailDirty || pictureDirty || licenseDirty ||
    foodTypeDirty || foodConstraintsDirty ||
    (soldierData.can_edit_rank_advancement && (rankFieldsDirty || nextRankDateDirty));

  const mandatoryEndBeforeEnlistmentError = profileMandEnd && profileEnlistment && profileMandEnd < profileEnlistment
    ? t("register.mandatory_end_before_enlistment")
    : null;

  useEffect(() => {
    setFullName(soldierData.full_name);
    setPhone(soldierData.phone ?? "");
    setHierarchyNodeId(soldierData.hierarchy_node_id ?? "");
    setEnrolledAt(soldierData.enrolled_at ?? "");
    setProfileRank(soldierData.rank ?? "");
    setProfileIsOfficer(soldierData.is_officer ?? false);
    setProfileRankTrack(soldierData.rank_track ?? (soldierData.is_officer ? "officer" : "enlisted"));
    setNextRankDate(soldierData.next_rank_date ?? "");
  }, [soldierData]);

  useEffect(() => {
    void getRanks().then(setRankOptions);
  }, []);

  const refreshConstraints = useCallback(async () => {
    setConstraints(await listSoldierConstraints(soldierData.id));
  }, [soldierData.id]);

  useEffect(() => {
    if (tab === "constraints") void refreshConstraints();
  }, [tab, refreshConstraints]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const data: { full_name?: string; phone?: string | null; enrolled_at?: string | null } = {};
      if (fullName !== soldierData.full_name) data.full_name = fullName;
      if (phone !== (soldierData.phone ?? "")) data.phone = phone || null;
      if (enrolledAt !== (soldierData.enrolled_at ?? "")) data.enrolled_at = enrolledAt || null;
      if (Object.keys(data).length > 0) {
        const updated = await updateSoldier(soldierData.id, data);
        setSoldierData(updated);
      }
      // Moving to a different hierarchy node goes through the transfer-request
      // flow, not this ordinary profile PATCH: the destination commander/duty
      // manager must approve it (Action.HIERARCHY_TRANSFER), unlike full_name/
      // phone/enrolled_at which only need Action.SOLDIER_UPDATE on the source.
      if (hierarchyNodeId && hierarchyNodeId !== (soldierData.hierarchy_node_id ?? "")) {
        await createTransferRequest(soldierData.id, hierarchyNodeId);
      }
      setEditing(false);
      onRefresh();
    } finally {
      setSaving(false);
    }
  }

  async function handleProfileSave(e: FormEvent) {
    e.preventDefault();
    if (mandatoryEndBeforeEnlistmentError) return;
    if (!profileDirty) { setEditing(false); onClose(); return; }
    setSavingProfile(true);
    setProfileError(null);
    try {
      await updateSoldierProfile(soldierData.id, {
        ...(genderDirty ? { gender: profileGender || null } : {}),
        ...(soldierData.can_edit_rank_advancement && isOfficerDirty ? { is_officer: profileIsOfficer } : {}),
        // Rank-advancement fields are omitted entirely (not just left unchanged)
        // when the user isn't authorized to edit them — the backend authorizes
        // by which fields are present in the request body, so including them
        // unchanged would still require rank-advancement authority. They're
        // also omitted when unchanged even for an authorized actor, so an
        // ordinary edit (e.g. phone/email) never risks being mistaken for a
        // rank change (see UnifiedSoldierModal's rankFieldsDirty comment).
        ...(soldierData.can_edit_rank_advancement && rankFieldsDirty ? {
          rank: profileRank || null,
          rank_track: profileRank ? profileRankTrack : null,
          is_officer: profileIsOfficer,
        } : {}),
        ...(soldierData.can_edit_rank_advancement && nextRankDateDirty ? {
          next_rank_date: nextRankDate || null,
        } : {}),
        ...(enlistmentDirty ? { enlistment_date: profileEnlistment || null } : {}),
        ...(mandEndDirty ? { mandatory_end_date: profileMandEnd || null } : {}),
        ...(dischargeDirty ? { discharge_date: profileDischarge || null } : {}),
        ...(mitvahimDirty ? { last_mitvahim_date: profileMitvahim || null } : {}),
        ...(soldierData.is_officer && alalDirty ? { last_alal_date: profileAlal || null } : {}),
        ...(isAdmin && emailDirty ? { email: profileEmail || null } : {}),
        ...(pictureDirty ? { profile_picture_url: profilePictureUrl || null } : {}),
        ...(licenseDirty ? {
          has_military_driving_license: profileHasLicense,
          military_driving_license_expiry: profileHasLicense ? (profileLicenseExpiry || null) : null,
        } : {}),
        ...(foodTypeDirty ? { food_type: profileFoodType || null } : {}),
        ...(foodConstraintsDirty ? { food_constraints: profileFoodConstraints || null } : {}),
      });
      onRefresh();
      onClose();
    } catch (err: unknown) {
      setProfileError(translateApiError(err, t));
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleRankSave(e: FormEvent) {
    e.preventDefault();
    if (!rankFieldsDirty && !nextRankDateDirty) { setRankEditing(false); return; }
    setSavingProfile(true);
    setProfileError(null);
    try {
      // Only rank-advancement fields are sent — the backend authorizes this
      // narrow flow by `rank_advancement_edit_authorized` alone, precisely
      // because no ordinary (non-rank) field is present in the request.
      await updateSoldierProfile(soldierData.id, {
        rank: profileRank || null,
        rank_track: profileRank ? profileRankTrack : null,
        is_officer: profileRank ? profileRankTrack !== "enlisted" : null,
        next_rank_date: nextRankDate || null,
      });
      onRefresh();
      setRankEditing(false);
    } catch (err: unknown) {
      setProfileError(translateApiError(err, t));
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleApprove(id: string) {
    await approveConstraint(id);
    await refreshConstraints();
  }

  async function handleReject(id: string, note: string) {
    await rejectConstraint(id, note);
    await refreshConstraints();
  }

  async function handleCancelConstraint(reason?: string) {
    if (!cancellingConstraintId) return;
    await cancelConstraintForManager(cancellingConstraintId, reason);
    setCancellingConstraintId(null);
    await refreshConstraints();
  }

  async function handleCancelPendingConstraint(id: string) {
    await cancelConstraintForManager(id);
    await refreshConstraints();
  }

  const rankComboItems = [
    ...rankOptions.enlisted.map(r => ({ id: rankSelectionId("enlisted", r), name: r, group: t("soldier_profile.enlisted") })),
    ...rankOptions.officers.map(r => ({ id: rankSelectionId("officer", r), name: r, group: t("soldier_profile.officers") })),
    ...rankOptions.officer_academic.map(r => ({ id: rankSelectionId("officer_academic", r), name: r, group: "קצינים אקדמאים" })),
  ];

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-[32rem] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="unified-soldier-modal">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-3">
            <SoldierAvatar url={soldierData.profile_picture_url} name={soldierData.full_name} size={10} />
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">{soldierData.full_name}</h3>
                {canManage && !editing && (
                  <button
                    onClick={() => { setRankEditing(false); setEditing(true); }}
                    className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 text-sm leading-none"
                    title={t("team.edit")}
                    aria-label={t("team.edit")}
                    data-testid="modal-edit-toggle"
                  >
                    ✏️
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400">{soldierData.personal_number} · {t(`role.${soldierData.role}`)}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none -mt-1 -mr-1 p-1"
            aria-label="סגור"
            data-testid="modal-close"
          >
            ×
          </button>
        </div>

        <div className="flex gap-4 border-b dark:border-gray-600 mb-4">
          {TABS.map((tKey) => (
            <button
              key={tKey}
              className={`pb-1 text-sm ${tab === tKey ? "border-b-2 border-indigo-600 text-indigo-600 font-medium" : "text-gray-500 dark:text-gray-400"}`}
              onClick={() => setTab(tKey)}
              data-testid={`modal-tab-${tKey}`}
            >
              {t(`team.${tKey}`)}
            </button>
          ))}
        </div>

        {tab === "details" && (
          !editing ? (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">{t("team.full_name")}</span>
                <span className="font-medium">{soldierData.full_name}</span>
              </div>
              {soldierData.rank && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.rank")}</span>
                  <span>{soldierData.rank}</span>
                </div>
              )}
              {(() => {
                const nodeMap = new Map(nodes.map((n) => [n.id, n]));
                const soldierNode = soldierData.hierarchy_node_id ? nodeMap.get(soldierData.hierarchy_node_id) : null;
                const chain = soldierNode ? soldierNode.path_ids.map((id) => nodeMap.get(id)?.name ?? id) : null;
                return (
                  <div className="space-y-0.5">
                    <span className="text-gray-500 dark:text-gray-400">{t("team.hierarchy")}</span>
                    <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs mt-0.5">
                      {chain
                        ? chain.map((name, i) => (
                            <span key={i} className="flex items-center gap-x-1">
                              {i > 0 && <span className="text-gray-300 dark:text-gray-600">›</span>}
                              <span className={i === chain.length - 1 ? "font-medium text-gray-800 dark:text-gray-200" : "text-gray-500 dark:text-gray-400"}>
                                {name}
                              </span>
                            </span>
                          ))
                        : <span className="text-gray-400">—</span>
                      }
                    </div>
                  </div>
                );
              })()}
              {soldierData.phone && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("team.phone")}</span>
                  <span dir="ltr">{soldierData.phone}</span>
                </div>
              )}
              {soldierData.email && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("profile.email")}</span>
                  <span dir="ltr">{soldierData.email}</span>
                </div>
              )}
              {soldierData.enrolled_at && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("transparency.enrolled_at")}</span>
                  <span>{formatDate(soldierData.enrolled_at!)}</span>
                </div>
              )}
              {soldierData.direct_commander_id && soldierData.direct_commander_name && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.direct_commander")}</span>
                  <SoldierLink id={soldierData.direct_commander_id} name={soldierData.direct_commander_name} />
                </div>
              )}
              {soldierData.last_mitvahim_date && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_mitvahim_date")}</span>
                  <span>{formatDate(soldierData.last_mitvahim_date)}</span>
                </div>
              )}
              {soldierData.is_officer && soldierData.last_alal_date && (
                <div className="flex justify-between">
                  <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_alal_date")}</span>
                  <span>{formatDate(soldierData.last_alal_date)}</span>
                </div>
              )}
              {score && (
                <div className="border-t dark:border-gray-600 pt-3 space-y-1">
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">{t("transparency.active_days")}</span>
                    <span>{score.active_days}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500 dark:text-gray-400">{t("transparency.normalised")}</span>
                    <span>{Number(score.normalised_score).toFixed(3)}</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <form onSubmit={handleSave} className="space-y-3">
              <label className="block">
                <span className="text-xs">{t("team.full_name")}</span>
                <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="edit-soldier-name" />
              </label>
              <label className="block">
                <span className="text-xs">{t("team.phone")}</span>
                <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="edit-soldier-phone" />
              </label>
              <label className="block">
                <span className="text-xs">{t("team.title")}</span>
                <Combobox
                  items={sortNodesByTree(nodes).map(({ node, depth }) => ({ id: node.id, name: node.name, depth }))}
                  value={hierarchyNodeId}
                  onChange={setHierarchyNodeId}
                  placeholder="—"
                  testId="edit-soldier-node"
                />
                {hierarchyNodeId && hierarchyNodeId !== (soldierData.hierarchy_node_id ?? "") && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{t("team.move_requires_approval")}</p>
                )}
              </label>
              {(() => {
                const nodeMap = new Map(nodes.map((n) => [n.id, n]));
                const selectedNode = hierarchyNodeId ? nodeMap.get(hierarchyNodeId) : null;
                const chain = selectedNode
                  ? selectedNode.path_ids.map((id) => nodeMap.get(id)?.name).filter(Boolean) as string[]
                  : null;
                if (!chain || chain.length === 0) return null;
                return (
                  <div className="space-y-0.5">
                    <span className="text-xs text-gray-500 dark:text-gray-400">{t("team.hierarchy")}</span>
                    <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-xs">
                      {chain.map((name, i) => (
                        <span key={i} className="flex items-center gap-x-1">
                          {i > 0 && <span className="text-gray-300 dark:text-gray-600">›</span>}
                          <span className={i === chain.length - 1 ? "font-medium text-gray-800 dark:text-gray-200" : "text-gray-500 dark:text-gray-400"}>{name}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}
              {canManage && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    {t("transparency.enrolled_at")}
                  </label>
                  <DateInput
                    className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={enrolledAt}
                    onChange={setEnrolledAt}
                    data-testid="enrolled-at-input"
                  />
                </div>
              )}
              {soldierData.direct_commander_id && soldierData.direct_commander_name && (
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-xs text-gray-500">{t("soldier_profile.direct_commander")}:</span>
                  <SoldierLink id={soldierData.direct_commander_id} name={soldierData.direct_commander_name} />
                </div>
              )}
              <div className="flex justify-end gap-2">
                <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={() => setEditing(false)}>{t("team.cancel")}</button>
                <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" disabled={saving} data-testid="edit-soldier-submit">{t("duty_config.save")}</button>
              </div>
            </form>
          )
        )}

        {tab === "profile" && !editing && !rankEditing && (
          <div className="space-y-2 text-sm">
            {soldierData.gender && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.gender")}</span><span>{t(`soldier_profile.gender_${soldierData.gender}`)}</span></div>}
            {soldierData.rank && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.rank")}</span><span>{soldierData.rank}</span></div>}
            {soldierData.next_rank_date && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.next_rank_date")}</span>
                <span className="flex flex-col items-end">
                  <span>{formatDate(soldierData.next_rank_date)}</span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    {soldierData.next_rank_date_overridden ? t("soldier_profile.next_rank_date_manual") : t("soldier_profile.next_rank_date_automatic")}
                  </span>
                </span>
              </div>
            )}
            {soldierData.enlistment_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.enlistment_date")}</span><span>{formatDate(soldierData.enlistment_date)}</span></div>}
            {soldierData.mandatory_end_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.mandatory_end_date")}</span><span>{formatDate(soldierData.mandatory_end_date)}</span></div>}
            {soldierData.discharge_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.discharge_date")}</span><span>{formatDate(soldierData.discharge_date)}</span></div>}
            {soldierData.last_mitvahim_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_mitvahim_date")}</span><span>{formatDate(soldierData.last_mitvahim_date)}</span></div>}
            {soldierData.is_officer && soldierData.last_alal_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_alal_date")}</span><span>{formatDate(soldierData.last_alal_date)}</span></div>}
            {soldierData.food_type && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.food_type")}</span><span>{t(`soldier_profile.food_${soldierData.food_type}`)}</span></div>}
            {soldierData.food_constraints && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.food_constraints")}</span><span className="text-right">{soldierData.food_constraints}</span></div>}
            {rangeStatus && rangeStatus.statuses.length > 0 && (
              <div>
                <span className="text-gray-500 dark:text-gray-400">{t("range_qualification.status.sectionTitle")}</span>
                <ul className="mt-1 space-y-1">
                  {rangeStatus.statuses.map((s) => (
                    <li key={s.required_range_type} className="text-xs">
                      {formatRangeStatus(s, t)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.service_type")}</span>
              <span>{soldierData.is_career ? t("soldier_profile.career") : t("soldier_profile.mandatory")}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.has_driving_license")}</span>
              <span>{soldierData.has_military_driving_license ? t("common.yes") : t("common.no")}</span>
            </div>
            {soldierData.has_military_driving_license && soldierData.military_driving_license_expiry && (
              <div className="flex justify-between">
                <span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.driving_license_expiry")}</span>
                <span>{formatDate(soldierData.military_driving_license_expiry)}</span>
              </div>
            )}
            {canEditRankNarrow && (
              <div className="pt-2 border-t dark:border-gray-600">
                <button
                  type="button"
                  className="text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 text-xs"
                  onClick={() => setRankEditing(true)}
                  data-testid="rank-correction-toggle"
                >
                  {t("soldier_profile.rank_correction")}
                </button>
              </div>
            )}
          </div>
        )}

        {tab === "profile" && !editing && rankEditing && (
          <form onSubmit={handleRankSave} className="space-y-3" data-testid="rank-correction-form">
            <label className="block">
              <span className="text-xs">{t("soldier_profile.rank")}</span>
              <Combobox
                items={rankComboItems}
                value={profileRank ? rankSelectionId(profileRankTrack, profileRank) : ""}
                onChange={v => {
                  const selection = parseRankSelectionId(v);
                  if (!selection) return;
                  setProfileRank(selection.rank);
                  setProfileRankTrack(selection.rankTrack);
                }}
                placeholder="—"
              />
            </label>
            <label className="block">
              <span className="text-xs">{t("soldier_profile.next_rank_date")}</span>
              <DateInput
                className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                value={nextRankDate}
                onChange={setNextRankDate}
                data-testid="next-rank-date-input"
              />
            </label>
            {profileError && <p className="text-red-500 text-xs">{profileError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={() => { setProfileError(null); setRankEditing(false); }}>{t("team.cancel")}</button>
              <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={savingProfile || (!rankFieldsDirty && !nextRankDateDirty)} data-testid="rank-correction-submit">{t("duty_config.save")}</button>
            </div>
          </form>
        )}

        {tab === "profile" && editing && (
          <form onSubmit={handleProfileSave} className="space-y-3">
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs">{t("soldier_profile.gender")}</span>
                <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileGender} onChange={(e) => setProfileGender(e.target.value)}>
                  <option value="">—</option>
                  <option value="male">{t("soldier_profile.gender_male")}</option>
                  <option value="female">{t("soldier_profile.gender_female")}</option>
                  <option value="other">{t("soldier_profile.gender_other")}</option>
                </select>
              </label>
              {soldierData.can_edit_rank_advancement && (
                <label className="block">
                  <span className="text-xs">{t("soldier_profile.rank")}</span>
                  <Combobox
                    items={rankComboItems}
                    value={profileRank ? rankSelectionId(profileRankTrack, profileRank) : ""}
                    onChange={v => {
                      const selection = parseRankSelectionId(v);
                      if (!selection) return;
                      setProfileRank(selection.rank);
                      setProfileRankTrack(selection.rankTrack);
                      setProfileIsOfficer(selection.rankTrack !== "enlisted");
                    }}
                    placeholder="—"
                  />
                </label>
              )}
              {soldierData.can_edit_rank_advancement && (
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={profileIsOfficer} onChange={(e) => setProfileIsOfficer(e.target.checked)} />
                  <span className="text-xs">קצין</span>
                </label>
              )}
              {soldierData.can_edit_rank_advancement && (
                <label className="block">
                  <span className="text-xs">{t("soldier_profile.next_rank_date")}</span>
                  <DateInput
                    className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={nextRankDate}
                    onChange={setNextRankDate}
                    data-testid="next-rank-date-input"
                  />
                </label>
              )}
              <label className="block">
                <span className="text-xs">{t("soldier_profile.enlistment_date")}</span>
                <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileEnlistment} onChange={setProfileEnlistment} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.mandatory_end_date")}</span>
                <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileMandEnd} onChange={setProfileMandEnd} />
                {mandatoryEndBeforeEnlistmentError && <p className="text-red-600 text-xs mt-1">{mandatoryEndBeforeEnlistmentError}</p>}
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.discharge_date")}</span>
                <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileDischarge} onChange={setProfileDischarge} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.last_mitvahim_date")}</span>
                <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileMitvahim} onChange={setProfileMitvahim} />
              </label>
              {soldierData.is_officer && (
                <label className="block">
                  <span className="text-xs">{t("soldier_profile.last_alal_date")}</span>
                  <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileAlal} onChange={setProfileAlal} />
                </label>
              )}
              <label className="flex items-center gap-2 mt-1">
                <input type="checkbox" checked={profileHasLicense} onChange={(e) => setProfileHasLicense(e.target.checked)} />
                <span className="text-xs">{t("soldier_profile.has_driving_license")}</span>
              </label>
              {profileHasLicense && (
                <label className="block">
                  <span className="text-xs">{t("soldier_profile.driving_license_expiry")}</span>
                  <DateInput className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={profileLicenseExpiry} onChange={setProfileLicenseExpiry} />
                </label>
              )}
              <label className="block">
                <span className="text-xs flex items-center gap-1">
                  {t("soldier_profile.food_type")}
                  <button
                    type="button"
                    className="text-gray-400 hover:text-indigo-600 text-xs font-bold border rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0"
                    onClick={() => setShowFoodHelp(v => !v)}
                    title={t("soldier_profile.food_constraints_tooltip")}
                  >
                    ?
                  </button>
                </span>
                <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileFoodType} onChange={(e) => setProfileFoodType(e.target.value)}>
                  <option value="">—</option>
                  <option value="regular">{t("soldier_profile.food_regular")}</option>
                  <option value="vegetarian">{t("soldier_profile.food_vegetarian")}</option>
                  <option value="vegan">{t("soldier_profile.food_vegan")}</option>
                  <option value="gluten_free">{t("soldier_profile.food_gluten_free")}</option>
                  <option value="kosher_le_mehadrin">{t("soldier_profile.food_kosher_le_mehadrin")}</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.food_constraints")}</span>
                <textarea rows={2} maxLength={2000} className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileFoodConstraints} onChange={(e) => setProfileFoodConstraints(e.target.value)} />
              </label>
              {showFoodHelp && <p className="text-xs text-gray-500 dark:text-gray-400">{t("soldier_profile.food_constraints_tooltip")}</p>}
              {isAdmin && (
                <label className="block">
                  <span className="text-xs">{t("profile.email")}</span>
                  <input type="email" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileEmail} onChange={(e) => setProfileEmail(e.target.value)} placeholder="כתובת אימייל" />
                </label>
              )}
              <label className="block">
                <span className="text-xs">{t("soldier_profile.profile_picture_url")}</span>
                <input type="url" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profilePictureUrl} onChange={(e) => setProfilePictureUrl(e.target.value)} placeholder="https://..." dir="ltr" />
              </label>
            </div>
            {profileError && <p className="text-red-500 text-xs">{profileError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={() => { setProfileError(null); setEditing(false); }}>{t("team.cancel")}</button>
              <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded disabled:opacity-50" disabled={savingProfile || !profileDirty || !!mandatoryEndBeforeEnlistmentError}>{t("duty_config.save")}</button>
            </div>
          </form>
        )}

        {tab === "exemptions" && (
          <ExemptionsPanel soldierId={soldier.id} canManage={canManageExemptions} canApproveDutyManagerStep={canManage} />
        )}

        {tab === "constraints" && (
          <div className="space-y-3">
            {constraints.length === 0 && (
              <p className="text-sm text-gray-500">{t("team.no_constraints")}</p>
            )}
            {constraints.map((c) => (
              <div key={c.id} className="border dark:border-gray-600 rounded p-3 text-sm space-y-1" data-testid={`constraint-row-${c.id}`}>
                <div className="flex items-center gap-2">
                  <span className="text-gray-500">{formatDate(c.start_date)} → {formatDate(c.end_date)}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager" ? "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" : c.status === "approved" ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
                    {t(`my_requests.${c.status}`)}
                  </span>
                  <ApprovalStageIcons request={c} />
                </div>
                <p className="text-gray-700 dark:text-gray-300">
                  {c.reason ?? "מידע פרטי"}
                </p>
                {c.decision_note && <p className="text-gray-500 dark:text-gray-400 text-xs">{t("approvals.decision_note")}: {c.decision_note}</p>}
                {c.overrides.length > 0 && (
                  <ul className="mt-1 text-xs text-amber-600 dark:text-amber-400 space-y-0.5">
                    {c.overrides.map(o => (
                      <li key={o.id}>
                        נדרס ע&quot;י {o.overridden_by?.name ?? "?"} · {o.reason}
                      </li>
                    ))}
                  </ul>
                )}
                {(isAdmin || isDutyManager) && (c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager") && (
                  <div className="flex gap-2 mt-1">
                    <button className="text-xs text-green-600 hover:underline" onClick={() => handleApprove(c.id)} data-testid={`approve-constraint-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <button className="text-xs text-red-600 hover:underline" onClick={() => { const n = prompt(t("approvals.decision_note")); if (n !== null) handleReject(c.id, n || ""); }} data-testid={`reject-constraint-${c.id}`}>
                      {t("approvals.reject")}
                    </button>
                  </div>
                )}
                {c.can_cancel && (c.status === "pending" || c.status === "pending_commander" || c.status === "pending_duty_manager") && (
                  <button className="text-xs text-red-600 border border-red-300 dark:border-red-700 rounded px-2 py-0.5" onClick={() => void handleCancelPendingConstraint(c.id)} data-testid={`cancel-constraint-${c.id}`}>בטל</button>
                )}
                {c.can_cancel && c.status === "approved" && (
                  <button className="text-xs text-red-600 border border-red-300 dark:border-red-700 rounded px-2 py-0.5" onClick={() => setCancellingConstraintId(c.id)} data-testid={`cancel-constraint-${c.id}`}>בטל</button>
                )}
              </div>
            ))}
          </div>
        )}

        {cancellingConstraintId && <ReasonPromptModal title={t("team.cancel_constraint")} description={t("team.cancel_constraint_active_warning")} variant="warning" onConfirm={handleCancelConstraint} onClose={() => setCancellingConstraintId(null)} />}

        {tab === "duty_history" && (
          <DutyHistoryPanel
            soldierId={soldier.id}
            soldierName={soldier.full_name}
            canManage={canManage}
            isActive={tab === "duty_history"}
            initialTypes={initialHistoryTypes}
          />
        )}

        {tab === "details" && user?.role === "admin" && (soldierData.role === "commander" || soldierData.role === "duty_manager") && (
          <div className="mt-4 pt-4 border-t dark:border-gray-600">
            <DeputiesPanel
              principalId={soldierData.id}
              principalRoles={{
                isCommander: soldierData.role === "commander",
                isDutyManager: soldierData.role === "duty_manager",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
