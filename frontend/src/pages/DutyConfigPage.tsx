import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import DutyTypeRequirementsEditor from "../components/DutyTypeRequirementsEditor";
import DutyTypeFormModal from "../components/DutyTypeFormModal";
import ReasonPromptModal from "../components/ReasonPromptModal";
import { DataTable, type ColDef } from "../components/DataTable";
import { type DutyType as DutyTypeT } from "../api/dutyConfig";

type Reqs = NonNullable<DutyTypeT["requirements"]>;
type RankLists = { enlisted: string[]; officers: string[] };

function rankRange(selected: string[], ordered: string[]): string | null {
  const indexed = selected
    .map(r => ({ rank: r, idx: ordered.indexOf(r) }))
    .filter(x => x.idx !== -1)
    .sort((a, b) => a.idx - b.idx);
  if (indexed.length === 0) return null;
  if (indexed.length === 1) return indexed[0].rank;
  const isContiguous = indexed.every((x, i) => i === 0 || x.idx === indexed[i - 1].idx + 1);
  if (isContiguous) return `${indexed[0].rank}–${indexed[indexed.length - 1].rank}`;
  return indexed.map(x => x.rank).join(", ");
}

function summarizeReqs(r: Reqs | undefined, rankLists: RankLists): string {
  if (!r || Object.keys(r).length === 0) return "ללא הגבלה";
  const parts: string[] = [];

  const genders = r.allowed_genders ?? [];
  if (genders.length === 1) parts.push(genders[0] === "male" ? "גברים" : "נשים");

  const svc = r.allowed_service_types ?? [];
  if (svc.length === 1) parts.push(svc[0]);

  if (r.requires_mitvahim) parts.push('מטווחים');
  if (r.requires_alal) parts.push('אל"ל');
  if (r.requires_bahad1) parts.push('בה"ד 1');

  if (r.officers_allowed === false) parts.push("חוגרים");
  else if (r.enlisted_allowed === false) parts.push("קצינים");

  const selectedRanks = r.allowed_ranks ?? [];
  if (selectedRanks.length > 0 && rankLists.enlisted.length > 0) {
    const eRange = rankRange(selectedRanks, rankLists.enlisted);
    const oRange = rankRange(selectedRanks, rankLists.officers);
    if (eRange) parts.push(eRange);
    if (oRange) parts.push(oRange);
  }

  return parts.length > 0 ? parts.join(" | ") : "ללא הגבלה";
}
import {
  DutyLocation,
  DutyType,
  ExemptionType,
  createExemptionType,
  createLocation,
  DutyTypeUsage,
  deleteDutyType,
  deleteExemptionType,
  disableExemptionType,
  getAllExemptionDutyTypeMaps,
  getDutyTypeUsage,
  listDutyTypes,
  listExemptionTypes,
  listLocations,
  setExemptionDutyTypes,
  updateDutyType,
  updateExemptionType,
} from "../api/dutyConfig";
import { getRanks } from "../api/soldiers";

export function DutyConfigContent() {
  const { t } = useTranslation();
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [exTypes, setExTypes] = useState<ExemptionType[]>([]);
  const [locName, setLocName] = useState("");
  const [exName, setExName] = useState("");
  const [exGlobal, setExGlobal] = useState(false);
  const [exMedical, setExMedical] = useState(false);
  const [exCommanderExemption, setExCommanderExemption] = useState(false);
  const [mapSel, setMapSel] = useState<Record<string, string[]>>({});
  const [dtModal, setDtModal] = useState<{ initial?: DutyType } | null>(null);
  const [eligModal, setEligModal] = useState<DutyType | null>(null);
  const [deleteModal, setDeleteModal] = useState<{ dt: DutyType; usage: DutyTypeUsage | null; loading: boolean; error: string | null } | null>(null);
  const [etDisableModal, setEtDisableModal] = useState<{ et: ExemptionType } | null>(null);
  const [etDeleteError, setEtDeleteError] = useState<string | null>(null);
  const [rankLists, setRankLists] = useState<RankLists>({ enlisted: [], officers: [] });

  useEffect(() => { void getRanks().then(setRankLists).catch(() => {}); }, []);

  async function refresh() {
    const [dts, locs, ets, sel] = await Promise.all([
      listDutyTypes(),
      listLocations(),
      listExemptionTypes(),
      getAllExemptionDutyTypeMaps(),
    ]);
    setDutyTypes(dts);
    setLocations(locs);
    setExTypes(ets);
    setMapSel(sel);
  }
  useEffect(() => { void refresh(); }, []);

  async function openDeleteModal(dt: DutyType) {
    setDeleteModal({ dt, usage: null, loading: true, error: null });
    try {
      const usage = await getDutyTypeUsage(dt.id);
      setDeleteModal({ dt, usage, loading: false, error: null });
    } catch (err: unknown) {
      console.error("getDutyTypeUsage failed:", err);
      const resp = (err as { response?: { data?: unknown; status?: number } })?.response;
      const status = resp?.status;
      let msg = status === 403 ? "אין הרשאה" : status === 404 ? "נתיב לא נמצא (אולי השרת לא עודכן)" : `שגיאה בטעינת נתונים (${status ?? "network"})`;
      const detail = (resp?.data as { detail?: unknown } | undefined)?.detail;
      if (typeof detail === "string" && detail) msg = detail;
      else if (Array.isArray(detail) && detail.length > 0) msg = JSON.stringify(detail[0]);
      setDeleteModal({ dt, usage: null, loading: false, error: msg });
    }
  }

  async function handleConfirmDelete() {
    if (!deleteModal) return;
    setDeleteModal(prev => prev ? { ...prev, loading: true, error: null } : null);
    try {
      await deleteDutyType(deleteModal.dt.id);
      setDeleteModal(null);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setDeleteModal(prev => prev ? { ...prev, loading: false, error: detail ?? "שגיאה במחיקה" } : null);
    }
  }

  async function handleDisableDutyType() {
    if (!deleteModal) return;
    setDeleteModal(prev => prev ? { ...prev, loading: true, error: null } : null);
    try {
      await updateDutyType(deleteModal.dt.id, { active: false });
      setDeleteModal(null);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setDeleteModal(prev => prev ? { ...prev, loading: false, error: detail ?? "שגיאה בהשבתה" } : null);
    }
  }
  async function handleDeleteExemptionType(et: ExemptionType) {
    setEtDeleteError(null);
    try {
      await deleteExemptionType(et.id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string }; status?: number } })?.response;
      if (detail?.status === 409) {
        setEtDisableModal({ et });
      } else {
        setEtDeleteError(detail?.data?.detail ?? "שגיאה במחיקה");
      }
    }
  }

  async function handleDisableExemptionType(reason: string) {
    if (!etDisableModal) return;
    await disableExemptionType(etDisableModal.et.id, reason);
    setEtDisableModal(null);
    await refresh();
  }
  async function addLocation(e: FormEvent) {
    e.preventDefault();
    await createLocation({ name: locName });
    setLocName("");
    await refresh();
  }
  async function addExType(e: FormEvent) {
    e.preventDefault();
    await createExemptionType({ name: exName, is_global: exGlobal, is_medical: exMedical, is_commander_exemption: exCommanderExemption });
    setExName(""); setExGlobal(false); setExMedical(false); setExCommanderExemption(false);
    await refresh();
  }
  async function toggleMap(etId: string, dtId: string) {
    const current = mapSel[etId] ?? [];
    const next = current.includes(dtId) ? current.filter((x) => x !== dtId) : [...current, dtId];
    await setExemptionDutyTypes(etId, next);
    setMapSel({ ...mapSel, [etId]: next });
  }

  return (
    <>
    {dtModal && (
      <DutyTypeFormModal
        initial={dtModal.initial}
        onSaved={async () => { setDtModal(null); await refresh(); }}
        onClose={() => setDtModal(null)}
      />
    )}
    {eligModal && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={() => setEligModal(null)}>
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-semibold text-base">{t("eligibility.title")} — {eligModal.name}</h3>
            <button type="button" onClick={() => setEligModal(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          <DutyTypeRequirementsEditor
            dutyType={eligModal}
            onSaved={async () => { setEligModal(null); await refresh(); }}
          />
        </div>
      </div>
    )}
    {deleteModal && (() => {
      const u = deleteModal.usage;
      const hasFuture = !!u && (u.future_count > 0 || u.template_count > 0 || u.shift_count > 0);
      const hasPast = !!u && u.past_count > 0;
      const canDelete = !!u && !hasFuture && !hasPast;
      const pastOnly = hasPast && !hasFuture;
      const futureParts: string[] = [];
      if (u && u.future_count > 0) futureParts.push(`${u.future_count} תורנויות עתידיות`);
      if (u && u.shift_count > 0) futureParts.push(`${u.shift_count} משמרות`);
      if (u && u.template_count > 0) futureParts.push(`${u.template_count} תבניות`);
      const exemptionNote = u && u.exemption_map_count > 0
        ? ` (${u.exemption_map_count} מיפויי פטורים יימחקו גם כן)`
        : "";

      return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={() => !deleteModal.loading && setDeleteModal(null)}>
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-sm" dir="rtl" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-semibold text-base">מחיקת סוג תורנות</h3>
              <button type="button" onClick={() => setDeleteModal(null)} disabled={deleteModal.loading} className="text-gray-400 hover:text-gray-600 disabled:opacity-50">✕</button>
            </div>
            <p className="text-sm font-medium text-gray-800 dark:text-gray-100 mb-4">&quot;{deleteModal.dt.name}&quot;</p>

            {deleteModal.loading && !u ? (
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">טוען נתונים...</p>
            ) : u ? (
              <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
                {canDelete && `לא נמצאו תורנויות, משמרות או תבניות עם סוג זה.${exemptionNote} מחיקה תהיה לצמיתות.`}
                {pastOnly && <>נמצאו <span className="font-medium">{u.past_count}</span> תורנויות עבר. מחיקה עלולה לפגוע בהיסטוריית הניקוד — מומלץ להשבית במקום.</>}
                {hasFuture && <>נמצאו {futureParts.join(', ')} עם סוג זה. לא ניתן למחוק. ניתן להשבית את הסוג במקום.</>}
              </p>
            ) : null}

            {deleteModal.error && <p className="text-red-500 text-xs mb-3">{deleteModal.error}</p>}

            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setDeleteModal(null)} disabled={deleteModal.loading} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50">
                ביטול
              </button>
              {canDelete && (
                <button type="button" onClick={handleConfirmDelete} disabled={deleteModal.loading} className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50">
                  {deleteModal.loading ? "מוחק..." : "מחק"}
                </button>
              )}
              {(pastOnly || hasFuture) && (
                <button type="button" onClick={handleDisableDutyType} disabled={deleteModal.loading} className="px-3 py-1 text-sm bg-yellow-600 text-white rounded hover:bg-yellow-700 disabled:opacity-50">
                  {deleteModal.loading ? "מעדכן..." : "השבת"}
                </button>
              )}
            </div>
          </div>
        </div>
      );
    })()}
    <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-8" data-testid="duty-config-page">
      <h2 className="text-xl font-semibold">{t("duty_config.title")}</h2>

      <div data-testid="duty-types-section">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">{t("duty_config.duty_types")}</h3>
          <button
            type="button"
            onClick={() => setDtModal({})}
            className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700"
            data-testid="dt-add-btn"
          >
            + {t("duty_config.add")} {t("duty_config.duty_types")}
          </button>
        </div>
        <DataTable<DutyType>
          data={dutyTypes}
          testId="duty-type-list"
          filterPlaceholder={t("duty_config.name")}
          emptyMessage="אין סוגי תורנות"
          columns={[
            {
              id: "name",
              header: t("duty_config.name"),
              cell: d => <span className="font-medium">{d.name}</span>,
              sortValue: d => d.name,
              filterValue: d => d.name,
            },
            {
              id: "score",
              header: t("duty_config.score_per_day"),
              cell: d => d.score_per_day,
              sortValue: d => parseFloat(d.score_per_day),
            },
            {
              id: "times",
              header: t("duty_config.start_time"),
              cell: d => (d.start_time || d.end_time)
                ? `${d.start_time?.slice(0, 5) ?? "—"} – ${d.end_time?.slice(0, 5) ?? "—"}`
                : "—",
            },
            {
              id: "type",
              header: t("duty_config.is_external"),
              cell: d => (
                <span className={`text-xs px-1.5 py-0.5 rounded ${d.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                  {d.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                </span>
              ),
              columnFilter: true,
              filterValue: d => d.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal"),
            },
            {
              id: "active",
              header: t("duty_config.active"),
              cell: d => (
                <button
                  className="text-xs text-indigo-600 dark:text-indigo-300 underline"
                  onClick={() => updateDutyType(d.id, { active: !d.active }).then(refresh)}
                  data-testid={`dt-toggle-${d.name}`}
                >
                  {d.active ? t("duty_config.active") : "לא פעיל"}
                </button>
              ),
            },
            {
              id: "eligibility",
              header: t("eligibility.title"),
              cell: d => {
                const summary = summarizeReqs(d.requirements, rankLists);
                const hasReqs = summary !== "ללא הגבלה";
                return (
                  <button
                    type="button"
                    onClick={() => setEligModal(d)}
                    className={`text-xs underline text-right ${hasReqs ? "text-blue-600 dark:text-blue-400" : "text-gray-400 dark:text-gray-500"}`}
                  >
                    {summary}
                  </button>
                );
              },
              filterValue: d => summarizeReqs(d.requirements, rankLists),
            },
            {
              id: "actions",
              header: "",
              cell: d => (
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => setDtModal({ initial: d })}
                    className="text-xs text-gray-600 dark:text-gray-300 border border-gray-300 dark:border-gray-600 rounded px-2 py-0.5 hover:bg-gray-50 dark:hover:bg-gray-700"
                    data-testid={`dt-edit-${d.name}`}
                  >
                    {t("duty_config.edit", "ערוך")}
                  </button>
                  <button
                    type="button"
                    onClick={() => openDeleteModal(d)}
                    className="text-xs text-red-600 dark:text-red-400 border border-red-300 dark:border-red-700 rounded px-2 py-0.5 hover:bg-red-50 dark:hover:bg-red-900/30"
                    data-testid={`dt-delete-${d.name}`}
                  >
                    {t("duty_config.delete", "מחק")}
                  </button>
                </div>
              ),
            },
          ] satisfies ColDef<DutyType>[]}
          rowTestId={d => `dt-row-${d.name}`}
        />
      </div>

      <div data-testid="locations-section">
        <h3 className="font-medium mb-2">{t("duty_config.locations")}</h3>
        <form onSubmit={addLocation} className="flex items-end gap-2 mb-2" data-testid="location-form">
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={locName} onChange={(e) => setLocName(e.target.value)} required data-testid="loc-name" placeholder={t("duty_config.name")} />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="loc-submit">{t("duty_config.add")}</button>
        </form>
        <ul className="text-sm" data-testid="location-list">
          {locations.map((l) => <li key={l.id} data-testid={`loc-row-${l.name}`}>{l.name}</li>)}
        </ul>
      </div>

      <div data-testid="exemption-types-section">
        <h3 className="font-medium mb-2">{t("duty_config.exemption_types")}</h3>
        <form onSubmit={addExType} className="flex items-end gap-2 mb-2 flex-wrap" data-testid="exemption-type-form">
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={exName} onChange={(e) => setExName(e.target.value)} required data-testid="et-name" placeholder={t("duty_config.name")} />
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input type="checkbox" checked={exGlobal} onChange={(e) => setExGlobal(e.target.checked)} data-testid="et-global" />
            {t("duty_config.global")}
          </label>
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input type="checkbox" checked={exMedical} onChange={(e) => setExMedical(e.target.checked)} data-testid="et-medical" />
            🏥 {t("duty_config.medical")}
          </label>
          <label className="flex items-center gap-1 text-xs cursor-pointer">
            <input type="checkbox" checked={exCommanderExemption} onChange={(e) => setExCommanderExemption(e.target.checked)} data-testid="et-commander-exemption" />
            🎖️ פטור פיקודי
          </label>
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="et-submit">{t("duty_config.add")}</button>
        </form>
        <ul className="text-sm space-y-2" data-testid="exemption-type-list">
          {exTypes.map((et) => (
            <li key={et.id} data-testid={`et-row-${et.name}`} className="border dark:border-gray-600 rounded p-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span>{et.name}</span>
                {et.is_global && <span className="text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">{t("duty_config.global")}</span>}
                {et.is_medical && <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">🏥 {t("duty_config.medical")}</span>}
                {et.is_commander_exemption && <span className="text-xs bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">🎖️ פטור פיקודי</span>}
                <button
                  type="button"
                  onClick={() => { void handleDeleteExemptionType(et); }}
                  className="text-xs text-red-600 dark:text-red-400 hover:underline"
                  data-testid={`et-delete-${et.name}`}
                >
                  מחק
                </button>
                {!et.active && (
                  <>
                    <span className="text-xs bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-2 py-0.5 rounded">מושבת</span>
                    <button
                      type="button"
                      onClick={async () => {
                        await updateExemptionType(et.id, { active: true });
                        await refresh();
                      }}
                      className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
                      data-testid={`et-enable-${et.name}`}
                    >
                      הפעל מחדש
                    </button>
                  </>
                )}
                <label className="flex items-center gap-1 text-xs cursor-pointer text-gray-500 dark:text-gray-400 mr-auto">
                  <input
                    type="checkbox"
                    checked={et.is_medical ?? false}
                    onChange={async (e) => {
                      await updateExemptionType(et.id, { is_medical: e.target.checked });
                      await refresh();
                    }}
                    data-testid={`et-medical-toggle-${et.name}`}
                  />
                  🏥 {t("duty_config.medical")}
                </label>
                <label className="flex items-center gap-1 text-xs cursor-pointer text-gray-500 dark:text-gray-400">
                  <input
                    type="checkbox"
                    checked={et.is_commander_exemption ?? false}
                    onChange={async (e) => {
                      await updateExemptionType(et.id, { is_commander_exemption: e.target.checked });
                      await refresh();
                    }}
                    data-testid={`et-commander-exemption-toggle-${et.name}`}
                  />
                  🎖️ פטור פיקודי
                </label>
              </div>
              {et.is_global ? (
                <div className="text-xs text-gray-500 mt-1">{t("duty_config.global_exempt_desc")}</div>
              ) : (
                <>
                  <div className="text-xs text-gray-500 mt-1">{t("duty_config.exempts_from")}:</div>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {dutyTypes.map((d) => (
                      <label key={d.id} className="text-xs flex items-center gap-1">
                        <input type="checkbox" checked={(mapSel[et.id] ?? []).includes(d.id)}
                               onChange={() => toggleMap(et.id, d.id)}
                               data-testid={`map-${et.name}-${d.name}`} />
                        {d.name}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
        {etDeleteError && <p className="text-red-500 text-xs mt-2">{etDeleteError}</p>}
      </div>
    </section>
    {etDisableModal && (
      <ReasonPromptModal
        title={`השבתת "${etDisableModal.et.name}"`}
        description="סוג פטור זה נמצא בשימוש. השבתה תבטל את הפטור אצל כל החיילים המחזיקים בו כעת, עם הסיבה שתוזן כאן."
        confirmLabel="השבת ובטל"
        onConfirm={handleDisableExemptionType}
        onClose={() => setEtDisableModal(null)}
      />
    )}
    </>
  );
}

export default function DutyConfigPage() {
  return <Layout><DutyConfigContent /></Layout>;
}
