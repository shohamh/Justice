import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO } from "../api/hierarchy";
import { SoldierDTO, updateSoldier, updateSoldierProfile, getRanks } from "../api/soldiers";
import { PersonalConstraint, listSoldierConstraints, approveConstraint, rejectConstraint } from "../api/constraints";
import ExemptionsPanel from "./ExemptionsPanel";

const TABS = ["details", "profile", "exemptions", "constraints"] as const;

interface Props {
  soldier: SoldierDTO;
  user: { role: string; id: string } | null;
  nodes: NodeDTO[];
  onClose: () => void;
  onRefresh: () => void;
}

export default function UnifiedSoldierModal({ soldier, user, nodes, onClose, onRefresh }: Props) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<(typeof TABS)[number]>("details");
  const [fullName, setFullName] = useState(soldier.full_name);
  const [phone, setPhone] = useState(soldier.phone ?? "");
  const [hierarchyNodeId, setHierarchyNodeId] = useState(soldier.hierarchy_node_id ?? "");
  const [constraints, setConstraints] = useState<PersonalConstraint[]>([]);
  const [saving, setSaving] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  // Profile fields
  const [profileGender, setProfileGender] = useState(soldier.gender ?? "");
  const [profileIsOfficer, setProfileIsOfficer] = useState(soldier.is_officer ?? false);
  const [profileRank, setProfileRank] = useState(soldier.rank ?? "");
  const [profileBahad1, setProfileBahad1] = useState(soldier.bahad1_graduate);
  const [profileEnlistment, setProfileEnlistment] = useState(soldier.enlistment_date ?? "");
  const [profileMandEnd, setProfileMandEnd] = useState(soldier.mandatory_end_date ?? "");
  const [profileDischarge, setProfileDischarge] = useState(soldier.discharge_date ?? "");
  const [profileMitvahim, setProfileMitvahim] = useState(soldier.last_mitvahim_date ?? "");
  const [profileAlal, setProfileAlal] = useState(soldier.last_alal_date ?? "");
  const [rankOptions, setRankOptions] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });

  const isAdmin = user?.role === "admin";
  const isDutyManager = user?.role === "duty_manager";
  const canManage = isAdmin || isDutyManager || user?.role === "commander";

  useEffect(() => {
    void getRanks().then(setRankOptions);
  }, []);

  const refreshConstraints = useCallback(async () => {
    setConstraints(await listSoldierConstraints(soldier.id));
  }, [soldier.id]);

  useEffect(() => {
    if (tab === "constraints") void refreshConstraints();
  }, [tab, refreshConstraints]);

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    const data: { full_name?: string; phone?: string | null; hierarchy_node_id?: string | null } = {};
    if (fullName !== soldier.full_name) data.full_name = fullName;
    if (phone !== (soldier.phone ?? "")) data.phone = phone || null;
    if (hierarchyNodeId !== (soldier.hierarchy_node_id ?? "")) data.hierarchy_node_id = hierarchyNodeId || null;
    if (Object.keys(data).length > 0) {
      await updateSoldier(soldier.id, data);
    }
    setSaving(false);
    onRefresh();
    onClose();
  }

  async function handleProfileSave(e: FormEvent) {
    e.preventDefault();
    setSavingProfile(true);
    await updateSoldierProfile(soldier.id, {
      gender: profileGender || null,
      is_officer: profileIsOfficer,
      rank: profileRank || null,
      bahad1_graduate: profileBahad1,
      enlistment_date: profileEnlistment || null,
      mandatory_end_date: profileMandEnd || null,
      discharge_date: profileDischarge || null,
      last_mitvahim_date: profileMitvahim || null,
      last_alal_date: profileAlal || null,
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

  const statusBadge: Record<string, string> = {
    pending: "bg-yellow-100 text-yellow-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
  };

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 w-[32rem] max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="unified-soldier-modal">
        <h3 className="font-semibold mb-2">{t("team.edit_soldier")}: {soldier.full_name}</h3>
        <p className="text-xs text-gray-400 mb-4">{soldier.personal_number} · {t(`role.${soldier.role}`)}</p>

        <div className="flex gap-4 border-b mb-4">
          {TABS.map((tKey) => (
            <button
              key={tKey}
              className={`pb-1 text-sm ${tab === tKey ? "border-b-2 border-indigo-600 text-indigo-600 font-medium" : "text-gray-500"}`}
              onClick={() => setTab(tKey)}
              data-testid={`modal-tab-${tKey}`}
            >
              {t(`team.${tKey}`)}
            </button>
          ))}
        </div>

        {tab === "details" && (
          <form onSubmit={handleSave} className="space-y-3">
            <label className="block">
              <span className="text-xs">{t("team.full_name")}</span>
              <input className="border rounded p-1 w-full" value={fullName} onChange={(e) => setFullName(e.target.value)} required data-testid="edit-soldier-name" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.phone")}</span>
              <input className="border rounded p-1 w-full" value={phone} onChange={(e) => setPhone(e.target.value)} data-testid="edit-soldier-phone" />
            </label>
            <label className="block">
              <span className="text-xs">{t("team.title")}</span>
              <select className="border rounded p-1 w-full" value={hierarchyNodeId} onChange={(e) => setHierarchyNodeId(e.target.value)} data-testid="edit-soldier-node">
                <option value="">—</option>
                {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
              </select>
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("team.cancel")}</button>
              <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" disabled={saving} data-testid="edit-soldier-submit">{t("duty_config.save")}</button>
            </div>
          </form>
        )}

        {tab === "profile" && (
          <form onSubmit={handleProfileSave} className="space-y-3">
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <label className="block">
                <span className="text-xs">{t("soldier_profile.gender")}</span>
                <select className="border rounded p-1 w-full" value={profileGender} onChange={(e) => setProfileGender(e.target.value)}>
                  <option value="">—</option>
                  <option value="male">{t("soldier_profile.gender_male")}</option>
                  <option value="female">{t("soldier_profile.gender_female")}</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.is_officer")}</span>
                <input type="checkbox" className="ml-2" checked={profileIsOfficer} onChange={(e) => setProfileIsOfficer(e.target.checked)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.rank")}</span>
                <select className="border rounded p-1 w-full" value={profileRank} onChange={(e) => setProfileRank(e.target.value)}>
                  <option value="">—</option>
                  {rankOptions.enlisted.length > 0 && (
                    <optgroup label={t("soldier_profile.enlisted")}>
                      {rankOptions.enlisted.map((r) => <option key={r} value={r}>{r}</option>)}
                    </optgroup>
                  )}
                  {rankOptions.officers.length > 0 && (
                    <optgroup label={t("soldier_profile.officers")}>
                      {rankOptions.officers.map((r) => <option key={r} value={r}>{r}</option>)}
                    </optgroup>
                  )}
                </select>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.bahad1_graduate")}</span>
                <input type="checkbox" className="ml-2" checked={profileBahad1} onChange={(e) => setProfileBahad1(e.target.checked)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.enlistment_date")}</span>
                <input type="date" className="border rounded p-1 w-full" value={profileEnlistment} onChange={(e) => setProfileEnlistment(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.mandatory_end_date")}</span>
                <input type="date" className="border rounded p-1 w-full" value={profileMandEnd} onChange={(e) => setProfileMandEnd(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.discharge_date")}</span>
                <div className="flex gap-1 items-center">
                  <input type="date" className="border rounded p-1 flex-1" value={profileDischarge} onChange={(e) => setProfileDischarge(e.target.value)} />
                  {profileDischarge && (
                    <button type="button" className="text-xs text-red-500 hover:underline" onClick={() => setProfileDischarge("")}>{t("soldier_profile.clear")}</button>
                  )}
                </div>
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.last_mitvahim_date")}</span>
                <input type="date" className="border rounded p-1 w-full" value={profileMitvahim} onChange={(e) => setProfileMitvahim(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-xs">{t("soldier_profile.last_alal_date")}</span>
                <input type="date" className="border rounded p-1 w-full" value={profileAlal} onChange={(e) => setProfileAlal(e.target.value)} />
              </label>
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className="border rounded px-3 py-1" onClick={onClose}>{t("team.cancel")}</button>
              <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" disabled={savingProfile}>{t("team.edit")}</button>
            </div>
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
              <div key={c.id} className="border rounded p-3 text-sm space-y-1" data-testid={`constraint-row-${c.id}`}>
                <div className="flex items-center gap-2">
                  <span className="text-gray-500" dir="ltr">{c.start_date} → {c.end_date}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${statusBadge[c.status] ?? ""}`}>
                    {t(`my_requests.${c.status}`)}
                  </span>
                </div>
                {c.reason && <p className="text-gray-600">{c.reason}</p>}
                {c.decision_note && <p className="text-gray-400 text-xs">{t("approvals.decision_note")}: {c.decision_note}</p>}
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
      </div>
    </div>
  );
}
