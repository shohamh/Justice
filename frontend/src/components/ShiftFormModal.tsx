import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { CreateShiftInput, DutyShift, createShift, updateShift, setShiftQuotas, getQuotaSplitPreview } from "../api/shifts";
import { DutyType, DutyLocation, createLocation } from "../api/dutyConfig";
import { NodeDTO, fetchTree } from "../api/hierarchy";
import { getPublicSettings } from "../api/publicSettings";
import { submitJob, getAlgorithmDefaults, SolverSettings } from "../api/algorithm";
import Combobox from "./Combobox";
import SubHierarchySelector from "./SubHierarchySelector";
import { lastDutyDay, toExclusiveEndDate } from "../utils/formatDate";

interface QuotaRow {
  hierarchy_node_id: string;
  count: number;
}

function flattenNodes(nodes: NodeDTO[]): { id: string; name: string; path_ids: string[] }[] {
  const result: { id: string; name: string; path_ids: string[] }[] = [];
  for (const n of nodes) {
    result.push({ id: n.id, name: n.name, path_ids: n.path_ids });
    if (n.children?.length) result.push(...flattenNodes(n.children));
  }
  return result;
}

function commonAncestorName(
  nodeIds: string[],
  nodeOptions: { id: string; name: string; path_ids: string[] }[]
): string | null {
  const paths = nodeIds
    .map((id) => nodeOptions.find((n) => n.id === id)?.path_ids)
    .filter((p): p is string[] => !!p && p.length > 0);
  if (paths.length < 2) return null;

  const minLen = Math.min(...paths.map((p) => p.length));
  let commonLength = 0;
  for (let i = 0; i < minLen; i++) {
    if (paths.every((p) => p[i] === paths[0][i])) {
      commonLength = i + 1;
    } else {
      break;
    }
  }
  if (commonLength === 0) return null;
  const ancestorId = paths[0][commonLength - 1];
  return nodeOptions.find((n) => n.id === ancestorId)?.name ?? null;
}

const DEFAULT_RERUN_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30, num_workers: 1,
  auto_relax_node_quotas: false,
};

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  existing?: DutyShift;
  onSaved: () => void | Promise<void>;
  onClose: () => void;
}

export default function ShiftFormModal({ dutyTypes, locations: initialLocations, existing, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [locations, setLocations] = useState<DutyLocation[]>(initialLocations);
  const [dtId, setDtId] = useState(existing?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(existing?.duty_location_id ?? initialLocations[0]?.id ?? "");
  const [startDate, setStartDate] = useState(existing?.start_date ?? "");
  // `endDate` here is the INCLUSIVE last duty day shown to the user; the backend's
  // DutyShift.end_date is exclusive (the first day NOT touched), converted at submit time.
  const [endDate, setEndDate] = useState(existing ? lastDutyDay(existing.end_date) : "");
  const [count, setCount] = useState(existing?.required_count ?? 1);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [reserveOverride, setReserveOverride] = useState(existing?.reserve_count_override?.toString() ?? "");
  const [scopeNodeIds, setScopeNodeIds] = useState<string[]>(
    existing?.eligible_node_ids ?? dutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []
  );
  const [error, setError] = useState<string | null>(null);
  const [quotaRows, setQuotaRows] = useState<QuotaRow[]>(
    (existing?.node_quotas ?? []).map((q) => ({ hierarchy_node_id: q.hierarchy_node_id, count: q.count }))
  );
  const [nodeOptions, setNodeOptions] = useState<{ id: string; name: string; path_ids: string[] }[]>([]);

  useEffect(() => {
    void fetchTree().then((nodes) => setNodeOptions(flattenNodes(nodes)));
  }, []);

  const quotaTotal = quotaRows.reduce((sum, r) => sum + (r.count || 0), 0);
  const quotaOverAllocated = quotaTotal > count;
  const commonAncestor = commonAncestorName(
    quotaRows.map((r) => r.hierarchy_node_id).filter(Boolean),
    nodeOptions
  );

  function addQuotaRow() {
    const firstAvailable = nodeOptions.find((n) => !quotaRows.some((r) => r.hierarchy_node_id === n.id));
    setQuotaRows((prev) => [...prev, { hierarchy_node_id: firstAvailable?.id ?? "", count: 1 }]);
  }

  function removeQuotaRow(index: number) {
    setQuotaRows((prev) => prev.filter((_, i) => i !== index));
  }

  function updateQuotaRow(index: number, patch: Partial<QuotaRow>) {
    setQuotaRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  const [splitting, setSplitting] = useState(false);
  const [autoSplitEnabled, setAutoSplitEnabled] = useState(false);
  const [autoSplitApplied, setAutoSplitApplied] = useState(false);

  const [rerunning, setRerunning] = useState(false);
  const [rerunResult, setRerunResult] = useState<string | null>(null);

  async function handleRerunAlgorithm() {
    if (!existing) return;
    setRerunning(true);
    setRerunResult(null);
    setError(null);
    try {
      const defaults = await getAlgorithmDefaults();
      const settings: SolverSettings = { ...DEFAULT_RERUN_SETTINGS, ...defaults };
      const resp = await submitJob({ shift_ids: [existing.id], mode: "shadow", settings });
      setRerunResult(t("shifts.rerun_algorithm_success", { id: resp.id }));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setRerunning(false);
    }
  }

  useEffect(() => {
    void getPublicSettings()
      .then((settings) => setAutoSplitEnabled(settings["shifts.auto_split_node_quotas"] === true))
      .catch(() => {});
  }, []);

  async function runSplit(): Promise<boolean> {
    if (scopeNodeIds.length !== 1 || count < 1) return false;
    setSplitting(true);
    setError(null);
    try {
      const entries = await getQuotaSplitPreview(scopeNodeIds[0], count);
      setQuotaRows(
        entries
          .filter((e) => e.count > 0)
          .map((e) => ({ hierarchy_node_id: e.hierarchy_node_id, count: e.count }))
      );
      return true;
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
      return false;
    } finally {
      setSplitting(false);
    }
  }

  async function handleSplitByPotential() {
    setAutoSplitApplied(false);
    await runSplit();
  }

  useEffect(() => {
    if (!autoSplitEnabled || scopeNodeIds.length !== 1 || count < 1) return;
    const timer = setTimeout(() => {
      void runSplit().then((ok) => setAutoSplitApplied(ok));
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSplitEnabled, scopeNodeIds, count]);

  useEffect(() => {
    if (!existing) {
      setScopeNodeIds(dutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtId]);
  const [addingLocation, setAddingLocation] = useState(false);
  const [newLocName, setNewLocName] = useState("");
  const [locSaving, setLocSaving] = useState(false);

  useEffect(() => {
    if (!existing) {
      setScopeNodeIds(dutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtId]);

  async function handleAddLocation(e: React.FormEvent) {
    e.preventDefault();
    if (!newLocName.trim()) return;
    setLocSaving(true);
    try {
      const created = await createLocation({ name: newLocName.trim() });
      setLocations(prev => [...prev, created]);
      setLocId(created.id);
      setNewLocName("");
      setAddingLocation(false);
    } finally {
      setLocSaving(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (quotaOverAllocated) {
      setError(t("shifts.quotas_over_allocated", { total: quotaTotal, required: count }));
      return;
    }
    try {
      const exclusiveEndDate = toExclusiveEndDate(endDate);
      let shiftId: string;
      if (existing) {
        await updateShift(existing.id, {
          start_date: startDate,
          end_date: exclusiveEndDate,
          required_count: count,
          notes: notes || null,
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
          eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        });
        shiftId = existing.id;
      } else {
        const input: CreateShiftInput = {
          duty_type_id: dtId,
          duty_location_id: locId,
          start_date: startDate,
          end_date: exclusiveEndDate,
          required_count: count,
          notes: notes || null,
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
          eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        };
        const created = await createShift(input);
        shiftId = created.id;
      }
      const validQuotaRows = quotaRows.filter((r) => r.hierarchy_node_id);
      if (validQuotaRows.length > 0) {
        await setShiftQuotas(shiftId, validQuotaRows);
      }
      await onSaved();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4 max-h-[90vh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{existing ? t("shifts.edit") : t("shifts.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          {!existing && (
            <>
              <div>
                <span className="text-sm block mb-0.5">{t("shifts.duty_type")}</span>
                <Combobox items={dutyTypes} value={dtId} onChange={setDtId} />
              </div>
              <div className="block text-sm">
                <div className="flex items-center justify-between mb-1">
                  <span>{t("shifts.location")}</span>
                  {!addingLocation && (
                    <button type="button" onClick={() => setAddingLocation(true)} className="text-xs text-blue-600 dark:text-blue-400 hover:underline">
                      + {t("shifts.add_location")}
                    </button>
                  )}
                </div>
                {addingLocation ? (
                  <form onSubmit={handleAddLocation} className="flex gap-1">
                    <input
                      autoFocus
                      type="text"
                      value={newLocName}
                      onChange={e => setNewLocName(e.target.value)}
                      placeholder={t("shifts.location_name")}
                      className="flex-1 border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    />
                    <button type="submit" disabled={locSaving || !newLocName.trim()} className="px-2 py-1 text-xs bg-blue-600 text-white rounded disabled:opacity-50">
                      {t("shifts.save")}
                    </button>
                    <button type="button" onClick={() => { setAddingLocation(false); setNewLocName(""); }} className="px-2 py-1 text-xs border dark:border-gray-600 dark:text-gray-300 rounded">
                      {t("shifts.dismiss")}
                    </button>
                  </form>
                ) : (
                  <Combobox items={locations} value={locId} onChange={setLocId} />
                )}
              </div>
            </>
          )}
          <label className="block text-sm">
            {t("shifts.start_date")}
            <input type="date" lang="he" value={startDate} onChange={e => setStartDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.end_date")}
            <input type="date" lang="he" value={endDate} onChange={e => setEndDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" required />
          </label>
          <label className="block text-sm">
            {t("shifts.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" rows={2} />
          </label>
          <label className="block text-sm">
            {t("reserve_count_override")}
            <input type="number" min="0" step="1" value={reserveOverride} onChange={e => setReserveOverride(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" placeholder={existing?.calculated_reserve_count?.toString() ?? ""} />
            {existing?.calculated_reserve_count != null && (
              <span className="text-xs text-gray-500">({t("reserve_calculated_count")}: {existing.calculated_reserve_count})</span>
            )}
          </label>
          <div className="border dark:border-gray-600 rounded p-2">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">{t("hierarchy_scope.title")}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{t("hierarchy_scope.help")}</p>
            <SubHierarchySelector value={scopeNodeIds} onChange={setScopeNodeIds} />
          </div>
          <div className="border dark:border-gray-600 rounded p-2">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-2">{t("shifts.quotas_title")}</p>
            {commonAncestor && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                {t("shifts.quotas_common_ancestor", { name: commonAncestor })}
              </p>
            )}
            <div className="space-y-1">
              {quotaRows.map((row, i) => (
                <div key={i} className="flex items-center gap-1">
                  <select
                    aria-label={t("shifts.quotas_select_node")}
                    value={row.hierarchy_node_id}
                    onChange={(e) => updateQuotaRow(i, { hierarchy_node_id: e.target.value })}
                    className="flex-1 border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  >
                    <option value="">{t("shifts.quotas_select_node")}</option>
                    {nodeOptions.map((n) => (
                      <option key={n.id} value={n.id}>{n.name}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={0}
                    value={row.count}
                    data-testid="quota-count-input"
                    onChange={(e) => updateQuotaRow(i, { count: parseInt(e.target.value) || 0 })}
                    className="w-16 border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                  <button
                    type="button"
                    onClick={() => removeQuotaRow(i)}
                    className="px-2 py-1 text-xs border dark:border-gray-600 dark:text-gray-300 rounded"
                  >
                    {t("shifts.quotas_remove")}
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-3">
              <button
                type="button"
                onClick={addQuotaRow}
                className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                + {t("shifts.quotas_add")}
              </button>
              {scopeNodeIds.length === 1 && (
                <button
                  type="button"
                  onClick={handleSplitByPotential}
                  disabled={splitting}
                  className="text-xs text-blue-600 dark:text-blue-400 hover:underline disabled:opacity-50"
                >
                  {t("shifts.quotas_split_by_potential")}
                </button>
              )}
            </div>
            {autoSplitApplied && (
              <p className="text-xs mt-2 text-gray-500 dark:text-gray-400">{t("shifts.quotas_auto_split_hint")}</p>
            )}
            <p className={`text-xs mt-2 ${quotaOverAllocated ? "text-red-500" : "text-gray-500 dark:text-gray-400"}`}>
              {t("shifts.quotas_total")}: {quotaTotal} / {count}
            </p>
            {quotaOverAllocated && (
              <p className="text-red-500 text-xs">
                {t("shifts.quotas_over_allocated", { total: quotaTotal, required: count })}
              </p>
            )}
          </div>
          {existing && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleRerunAlgorithm}
                disabled={rerunning}
                className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50"
              >
                {t("shifts.rerun_algorithm")}
              </button>
              {rerunResult && <span className="text-xs text-green-600 dark:text-green-400">{rerunResult}</span>}
            </div>
          )}
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">{t("shifts.cancel")}</button>
            <button type="submit" disabled={quotaOverAllocated} className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{t("shifts.save")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
