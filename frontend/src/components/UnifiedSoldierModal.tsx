import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { sortNodesByTree } from "../utils/sortNodesByTree";
import { SoldierDTO, SoldierScoreDTO, updateSoldier, updateSoldierProfile, getRanks } from "../api/soldiers";
import { PersonalConstraint, listSoldierConstraints, approveConstraint, rejectConstraint } from "../api/constraints";
import Combobox from "./Combobox";
import ExemptionsPanel from "./ExemptionsPanel";
import DutyHistoryPanel from "./DutyHistoryPanel";
import SoldierLink from "./SoldierLink";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../utils/formatDate";

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
}

const ALL_TABS = ["details", "profile", "exemptions", "constraints", "duty_history"] as const;
type TabKey = (typeof ALL_TABS)[number];

export default function UnifiedSoldierModal({ soldier, score, nodes, onClose, onRefresh, initialEditing = false }: Props) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const isSelf = user?.personal_number === soldier.personal_number;
  const isAdmin = user?.role === "admin";
  const isDutyManager = user?.is_duty_manager ?? false;
  const isCommander = user?.is_commander ?? false;
  const canManage = isAdmin || isDutyManager;
  const canViewAll = isAdmin || isDutyManager || isCommander;
  const TABS: TabKey[] = canViewAll
    ? ["details", "profile", "exemptions", "constraints", "duty_history"]
    : isSelf
      ? ["details", "profile", "duty_history"]
      : ["details", "duty_history"];

  const [soldierData, setSoldierData] = useState<SoldierDTO>(soldier);

  useEffect(() => { setSoldierData(soldier); }, [soldier]);

  const [tab, setTab] = useState<TabKey>("details");
  const [editing, setEditing] = useState(initialEditing);
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");
  const [enrolledAt, setEnrolledAt] = useState(soldier.enrolled_at ?? "");
  const [constraints, setConstraints] = useState<PersonalConstraint[]>([]);
  const [saving, setSaving] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  // Profile fields
  const [profileGender, setProfileGender] = useState(soldier.gender ?? "");
  const [profileRank, setProfileRank] = useState(soldier.rank ?? "");
  const [profileEnlistment, setProfileEnlistment] = useState(soldier.enlistment_date ?? "");
  const [profileMandEnd, setProfileMandEnd] = useState(soldier.mandatory_end_date ?? "");
  const [profileDischarge, setProfileDischarge] = useState(soldier.discharge_date ?? "");
  const [profileMitvahim, setProfileMitvahim] = useState(soldier.last_mitvahim_date ?? "");
  const [profileAlal, setProfileAlal] = useState(soldier.last_alal_date ?? "");
  const [profileEmail, setProfileEmail] = useState(soldier.email ?? "");
  const [profilePictureUrl, setProfilePictureUrl] = useState(soldier.profile_picture_url ?? "");
  const [rankOptions, setRankOptions] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });

  useEffect(() => {
    setFullName(soldierData.full_name);
    setPhone(soldierData.phone ?? "");
    setHierarchyNodeId(soldierData.hierarchy_node_id ?? "");
    setEnrolledAt(soldierData.enrolled_at ?? "");
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
      const data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null; enrolled_at?: string | null } = {};
      if (fullName !== soldierData.full_name) data.full_name = fullName;
      if (phone !== (soldierData.phone ?? "")) data.phone = phone || null;
      if (hierarchyNodeId !== (soldierData.hierarchy_node_id ?? "")) data.hierarchy_node_id = hierarchyNodeId || null;
      if (enrolledAt !== (soldierData.enrolled_at ?? "")) data.enrolled_at = enrolledAt || null;
      if (Object.keys(data).length > 0) {
        const updated = await updateSoldier(soldierData.id, data);
        setSoldierData(updated);
      }
      setEditing(false);
      onRefresh();
    } finally {
      setSaving(false);
    }
  }

  async function handleProfileSave(e: FormEvent) {
    e.preventDefault();
    if (isCommander) return;  // UI hides button, but guard against keyboard submit
    setSavingProfile(true);
    await updateSoldierProfile(soldierData.id, {
      gender: profileGender || null,
      rank: profileRank || null,
      enlistment_date: profileEnlistment || null,
      mandatory_end_date: profileMandEnd || null,
      discharge_date: profileDischarge || null,
      last_mitvahim_date: profileMitvahim || null,
      ...(soldierData.is_officer ? { last_alal_date: profileAlal || null } : {}),
      ...(isAdmin ? { email: profileEmail || null } : {}),
      profile_picture_url: profilePictureUrl || null,
    });
    setSavingProfile(false);
    onRefresh();
    onClose();
  }

  async function handleApprove(id: string) {
    await approveConstraint(id);
    await refreshConstraints();
  }

  async function handleReject(id: string, note: string) {
    await rejectConstraint(id, note);
    await refreshConstraints();
  }


  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-[32rem] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="unified-soldier-modal">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-3">
            <SoldierAvatar url={soldierData.profile_picture_url} name={soldierData.full_name} size={10} />
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">{soldierData.full_name}</h3>
                {(canManage || isSelf) && !editing && (
                  <button
                    onClick={() => setEditing(true)}
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
            aria-label="close"
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
                  <input
                    type="date" lang="he"
                    className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={enrolledAt}
                    onChange={(e) => setEnrolledAt(e.target.value)}
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

        {tab === "profile" && !editing && (
          <div className="space-y-2 text-sm">
            {soldierData.gender && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.gender")}</span><span>{t(`soldier_profile.gender_${soldierData.gender}`)}</span></div>}
            {soldierData.rank && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.rank")}</span><span>{soldierData.rank}</span></div>}
            {soldierData.enlistment_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.enlistment_date")}</span><span>{formatDate(soldierData.enlistment_date)}</span></div>}
            {soldierData.mandatory_end_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.mandatory_end_date")}</span><span>{formatDate(soldierData.mandatory_end_date)}</span></div>}
            {soldierData.discharge_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.discharge_date")}</span><span>{formatDate(soldierData.discharge_date)}</span></div>}
            {soldierData.last_mitvahim_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_mitvahim_date")}</span><span>{formatDate(soldierData.last_mitvahim_date)}</span></div>}
            {soldierData.is_officer && soldierData.last_alal_date && <div className="flex justify-between"><span className="text-gray-500 dark:text-gray-400">{t("soldier_profile.last_alal_date")}</span><span>{formatDate(soldierData.last_alal_date)}</span></div>}
          </div>
        )}

        {tab === "profile" && editing && (
          <form onSubmit={handleProfileSave} className="space-y-3">
            <div className="grid grid-cols-1 gap-x-4 gap-y-3">
              <label className="block">
                <span className="text-xs">{t("soldier_profile.gender")}</span>
                <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileGender} onChange={(e) => setProfileGender(e.target.value)}>
                  <option value="">—</option>
                  <option value="male">{t("soldier_profile.gender_male")}</option>
                  <option value="female">{t("soldier_profile.gender_female")}</option>
                  <option value="other">{t("soldier_profile.gender_other")}</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.rank")}</span>
                <Combobox
                  items={[
                    ...rankOptions.enlisted.map(r => ({ id: r, name: r, group: t("soldier_profile.enlisted") })),
                    ...rankOptions.officers.map(r => ({ id: r, name: r, group: t("soldier_profile.officers") })),
                  ]}
                  value={profileRank}
                  onChange={setProfileRank}
                  placeholder="—"
                />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.enlistment_date")}</span>
                <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileEnlistment} onChange={(e) => setProfileEnlistment(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.mandatory_end_date")}</span>
                <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileMandEnd} onChange={(e) => setProfileMandEnd(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.discharge_date")}</span>
                <div className="flex gap-1 items-center">
                  <input type="date" lang="he" className="border rounded p-1 flex-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileDischarge} onChange={(e) => setProfileDischarge(e.target.value)} />
                  {profileDischarge && (
                    <button type="button" className="text-xs text-red-500 hover:underline" onClick={() => setProfileDischarge("")}>{t("soldier_profile.clear")}</button>
                  )}
                </div>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.last_mitvahim_date")}</span>
                <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileMitvahim} onChange={(e) => setProfileMitvahim(e.target.value)} />
              </label>
              {soldierData.is_officer && (
                <label className="block">
                  <span className="text-xs">{t("soldier_profile.last_alal_date")}</span>
                  <input type="date" lang="he" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileAlal} onChange={(e) => setProfileAlal(e.target.value)} />
                </label>
              )}
              {isAdmin && (
                <label className="block col-span-2">
                  <span className="text-xs">{t("profile.email")}</span>
                  <input type="email" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profileEmail} onChange={(e) => setProfileEmail(e.target.value)} placeholder="כתובת אימייל" />
                </label>
              )}
              <label className="block col-span-2">
                <span className="text-xs">{t("soldier_profile.profile_picture_url")}</span>
                <input type="url" className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={profilePictureUrl} onChange={(e) => setProfilePictureUrl(e.target.value)} placeholder="https://..." dir="ltr" />
              </label>
            </div>
            {!isCommander && (
              <div className="flex justify-end gap-2">
                <button type="button" className="border dark:border-gray-600 dark:text-gray-300 rounded px-3 py-1" onClick={() => setEditing(false)}>{t("team.cancel")}</button>
                <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" disabled={savingProfile}>{t("duty_config.save")}</button>
              </div>
            )}
          </form>
        )}

        {tab === "exemptions" && (
          <ExemptionsPanel soldierId={soldier.id} canManage={canManage} />
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
                  <span className={`text-xs px-1.5 py-0.5 rounded ${c.status === "pending" ? "bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200" : c.status === "approved" ? "bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200" : "bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200"}`}>
                    {t(`my_requests.${c.status}`)}
                  </span>
                </div>
                <p className="text-gray-700 dark:text-gray-300">
                  {c.reason ?? "מידע פרטי"}
                </p>
                {c.decision_note && <p className="text-gray-500 dark:text-gray-400 text-xs">{t("approvals.decision_note")}: {c.decision_note}</p>}
                {(isAdmin || isDutyManager) && c.status === "pending" && (
                  <div className="flex gap-2 mt-1">
                    <button className="text-xs text-green-600 hover:underline" onClick={() => handleApprove(c.id)} data-testid={`approve-constraint-${c.id}`}>
                      {t("approvals.approve")}
                    </button>
                    <button className="text-xs text-red-600 hover:underline" onClick={() => { const n = prompt(t("approvals.decision_note")); if (n !== null) handleReject(c.id, n || ""); }} data-testid={`reject-constraint-${c.id}`}>
                      {t("approvals.reject")}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === "duty_history" && (
          <DutyHistoryPanel
            soldierId={soldier.id}
            soldierName={soldier.full_name}
            canManage={canManage}
            isActive={tab === "duty_history"}
          />
        )}
      </div>
    </div>
  );
}
