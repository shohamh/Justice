import { FormEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExemptionType, listExemptionTypes, getAllExemptionDutyTypeMaps, listDutyTypes } from "../api/dutyConfig";
import { Exemption, grantExemption, listExemptions, revokeExemption } from "../api/exemptions";

export default function ExemptionsPanel({ soldierId, canManage }: { soldierId: string; canManage: boolean }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<Exemption[]>([]);
  const [types, setTypes] = useState<ExemptionType[]>([]);
  const [dutyTypeMap, setDutyTypeMap] = useState<Record<string, string[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [typeId, setTypeId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [indefinite, setIndefinite] = useState(false);
  const [reason, setReason] = useState("");

  const refresh = useCallback(async () => {
    setItems(await listExemptions(soldierId));
  }, [soldierId]);
  useEffect(() => {
    void refresh();
    Promise.all([listExemptionTypes(), getAllExemptionDutyTypeMaps(), listDutyTypes()]).then(
      ([etypes, maps, dtypes]) => {
        setTypes(etypes);
        const nameById = Object.fromEntries(dtypes.map((d) => [d.id, d.name]));
        const named: Record<string, string[]> = {};
        for (const [etId, dtIds] of Object.entries(maps)) {
          named[etId] = dtIds.map((id) => nameById[id] ?? id);
        }
        setDutyTypeMap(named);
      }
    );
  }, [refresh]);

  const typeName = (id: string) => types.find((tp) => tp.id === id)?.name ?? id;

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  async function onGrant(e: FormEvent) {
    e.preventDefault();
    await grantExemption(soldierId, {
      exemption_type_id: typeId,
      start_date: start,
      end_date: end || null,
      reason: reason || null,
    });
    setTypeId(""); setStart(""); setEnd(""); setIndefinite(false); setReason("");
    await refresh();
  }

  async function onRevoke(id: string) {
    if (!confirm(t("exemptions.revoke") + "?")) return;
    await revokeExemption(soldierId, id);
    await refresh();
  }

  return (
    <div data-testid="exemptions-panel" className="space-y-3">
      <h3 className="font-medium">{t("exemptions.title")}</h3>
      {items.length === 0 && (
        <p className="text-sm text-gray-500" data-testid="exemptions-empty">{t("exemptions.none")}</p>
      )}
      <ul className="text-sm space-y-1" data-testid="exemptions-list">
        {items.map((ex) => {
          const names = dutyTypeMap[ex.exemption_type_id] ?? [];
          const isExpanded = expanded.has(ex.id);
          return (
            <li
              key={ex.id}
              className="border dark:border-gray-600 rounded p-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700"
              onClick={() => toggleExpand(ex.id)}
              data-testid={`exemption-row-${ex.id}`}
            >
              <div className="flex items-center gap-2">
                <span className="font-medium">{typeName(ex.exemption_type_id)}</span>
                <span className="text-gray-500 dark:text-gray-400 text-xs" dir="ltr">{ex.start_date} → {ex.end_date ?? t("exemptions.forever")}</span>
                {canManage && (
                  <button
                    className="text-red-500 text-xs mr-auto"
                    onClick={(e) => { e.stopPropagation(); void onRevoke(ex.id); }}
                    data-testid={`revoke-${ex.id}`}
                  >
                    {t("exemptions.revoke")}
                  </button>
                )}
              </div>
              {isExpanded && (
                <div className="mt-1.5 space-y-0.5">
                  {ex.reason && <p className="text-xs text-gray-500">{ex.reason}</p>}
                  {names.length > 0 && (
                    <p className="text-xs text-gray-500">
                      <span className="font-medium">{t("exemptions.exempts_from")}:</span>{" "}
                      {names.join("، ")}
                    </p>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {canManage && (
        <form onSubmit={onGrant} className="flex flex-wrap items-end gap-2" data-testid="grant-form">
          <select className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={typeId} onChange={(e) => setTypeId(e.target.value)} required data-testid="grant-type">
            <option value="">{t("exemptions.type")}</option>
            {types.map((tp) => <option key={tp.id} value={tp.id}>{tp.name}</option>)}
          </select>
          <input type="date" className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="grant-start" />
          <div className="flex items-center gap-2">
            <input
              type="date"
              className={`border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 ${indefinite ? "opacity-40 cursor-not-allowed" : ""}`}
              value={indefinite ? "" : end}
              onChange={(e) => setEnd(e.target.value)}
              disabled={indefinite}
              data-testid="grant-end"
            />
            <label className="flex items-center gap-1 text-sm whitespace-nowrap cursor-pointer">
              <input
                type="checkbox"
                checked={indefinite}
                onChange={(e) => {
                  setIndefinite(e.target.checked);
                  if (e.target.checked) setEnd("");
                }}
                data-testid="grant-indefinite"
              />
              ללא הגבלת זמן
            </label>
          </div>
          <input className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("exemptions.reason")} data-testid="grant-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="grant-submit">{t("exemptions.grant")}</button>
        </form>
      )}
    </div>
  );
}
