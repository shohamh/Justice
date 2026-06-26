import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, createDutyType, updateDutyType, updateDutyTypeRequirements } from "../api/dutyConfig";
import { getRanks } from "../api/soldiers";
import SubHierarchySelector from "./SubHierarchySelector";

type Reqs = NonNullable<DutyType["requirements"]>;

interface Props {
  initial?: DutyType;
  onSaved: (dt: DutyType) => void;
  onClose: () => void;
}

export default function DutyTypeFormModal({ initial, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initial?.name ?? "");
  const [score, setScore] = useState(initial?.score_per_day ?? "1.00");
  const [reserveRatio, setReserveRatio] = useState(initial?.reserve_ratio ?? "0.000");
  const [reserveMin, setReserveMin] = useState(String(initial?.reserve_minimum ?? "0"));
  const [contactName, setContactName] = useState(initial?.contact_name ?? "");
  const [contactPhone, setContactPhone] = useState(initial?.contact_phone ?? "");
  const [startTime, setStartTime] = useState(initial?.start_time?.slice(0, 5) ?? "");
  const [endTime, setEndTime] = useState(initial?.end_time?.slice(0, 5) ?? "");
  const [instructions, setInstructions] = useState(initial?.instructions ?? "");
  const [isExternal, setIsExternal] = useState<"" | "true" | "false">(
    initial == null ? "" : initial.is_external ? "true" : "false"
  );
  const [reqs, setReqs] = useState<Reqs>(initial?.requirements ?? {});
  const [ranks, setRanks] = useState<{ enlisted: string[]; officers: string[] }>({ enlisted: [], officers: [] });
  const [eligOpen, setEligOpen] = useState(false);
  const [scopeNodeIds, setScopeNodeIds] = useState<string[]>(initial?.eligible_node_ids ?? []);
  const [showHelp, setShowHelp] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void getRanks().then(setRanks); }, []);

  function toggleArr(key: keyof Reqs, value: string) {
    const current = (reqs[key] as string[] | undefined) ?? [];
    const next = current.includes(value) ? current.filter(v => v !== value) : [...current, value];
    setReqs(prev => ({ ...prev, [key]: next }));
  }
  function toggleBool(key: keyof Reqs, checked: boolean) {
    setReqs(prev => ({ ...prev, [key]: checked }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError(t("duty_config.name") + " חובה");
      return;
    }
    if (isExternal === "") {
      setError("יש לבחור אם סוג התורנות פנימי או חיצוני");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name,
        score_per_day: score,
        reserve_ratio: reserveRatio,
        reserve_minimum: parseInt(reserveMin) || 0,
        contact_name: contactName || null,
        contact_phone: contactPhone || null,
        start_time: startTime || null,
        end_time: endTime || null,
        instructions: instructions || null,
        is_external: isExternal === "true",
        eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
      };
      let dt: DutyType;
      if (initial) {
        dt = await updateDutyType(initial.id, { ...payload, requirements: reqs });
      } else {
        dt = await createDutyType(payload);
        if (Object.keys(reqs).length > 0) {
          dt = await updateDutyTypeRequirements(dt.id, reqs);
        }
      }
      onSaved(dt);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSaving(false);
    }
  }

  const inputCls = "block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100";

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">
            {initial ? t("duty_config.edit", "עריכת סוג תורנות") : `${t("duty_config.add")} ${t("duty_config.duty_types")}`}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Basic fields */}
          <div>
            <div className="flex flex-wrap gap-2">
              <div className="flex-1 min-w-36">
                <label htmlFor="duty-type-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.name")} *</label>
                <input id="duty-type-name" required autoFocus value={name} onChange={e => setName(e.target.value)} className={inputCls} />
              </div>
              <div className="w-24">
                <label htmlFor="duty-type-score" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.score_per_day")}</label>
                <input id="duty-type-score" value={score} onChange={e => setScore(e.target.value)} className={inputCls} />
              </div>
              <div className="w-20">
                <label htmlFor="duty-type-reserve-ratio" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("reserve_ratio")}</label>
                <input id="duty-type-reserve-ratio" type="number" min="0" max="1" step="0.001" value={reserveRatio} onChange={e => setReserveRatio(e.target.value)} className={inputCls} />
              </div>
              <div className="w-16">
                <label htmlFor="duty-type-reserve-minimum" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("reserve_minimum")}</label>
                <input id="duty-type-reserve-minimum" type="number" min="0" step="1" value={reserveMin} onChange={e => setReserveMin(e.target.value)} className={inputCls} />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <div className="flex-1 min-w-36">
              <label htmlFor="duty-type-contact-name" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.contact_name")}</label>
              <input id="duty-type-contact-name" value={contactName} onChange={e => setContactName(e.target.value)} className={inputCls} />
            </div>
            <div className="w-36">
              <label htmlFor="duty-type-contact-phone" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.contact_phone")}</label>
              <input id="duty-type-contact-phone" value={contactPhone} onChange={e => setContactPhone(e.target.value)} className={inputCls} />
            </div>
            <div className="w-24">
              <label htmlFor="duty-type-start-time" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.start_time")}</label>
              <input id="duty-type-start-time" type="text" inputMode="numeric" placeholder="HH:MM" pattern="[0-2][0-9]:[0-5][0-9]" value={startTime} onChange={e => setStartTime(e.target.value)} className={inputCls} />
            </div>
            <div className="w-24">
              <label htmlFor="duty-type-end-time" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.end_time")}</label>
              <input id="duty-type-end-time" type="text" inputMode="numeric" placeholder="HH:MM" pattern="[0-2][0-9]:[0-5][0-9]" value={endTime} onChange={e => setEndTime(e.target.value)} className={inputCls} />
            </div>
          </div>

          <div>
            <div className="flex items-center gap-2 mb-1">
              <label htmlFor="is-external-select" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                {t("duty_config.is_external")}<span className="text-red-500"> *</span>
              </label>
              <button
                type="button"
                onClick={() => setShowHelp((v) => !v)}
                className="text-xs text-blue-500 hover:underline"
              >
                {t("duty_config.is_external_help_title")}
              </button>
            </div>
            {showHelp && (
              <div className="mb-2 text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-700 rounded p-2 border border-gray-200 dark:border-gray-600">
                {t("duty_config.is_external_help_text")}
              </div>
            )}
            <select
              id="is-external-select"
              required
              value={isExternal}
              onChange={e => setIsExternal(e.target.value as "" | "true" | "false")}
              className={inputCls}
            >
              <option value="" disabled>{t("duty_config.is_external_placeholder")}</option>
              <option value="false">{t("duty_config.is_external_internal")}</option>
              <option value="true">{t("duty_config.is_external_external")}</option>
            </select>
          </div>

          <div>
            <label htmlFor="duty-type-instructions" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t("duty_config.instructions")}</label>
            <textarea id="duty-type-instructions" value={instructions} onChange={e => setInstructions(e.target.value)} rows={2} className={inputCls} />
          </div>

          {/* Eligibility section */}
          <div className="border dark:border-gray-600 rounded">
            <button
              type="button"
              onClick={() => setEligOpen(o => !o)}
              className="flex w-full justify-between items-center px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700/50 rounded"
            >
              <span>{t("eligibility.title")}</span>
              <span className="text-gray-400 text-xs">{eligOpen ? "▲" : "▼"}</span>
            </button>

            {eligOpen && (
              <div className="px-3 pb-3 space-y-3 text-sm border-t dark:border-gray-600 pt-3">
                {/* Gender */}
                <div>
                  <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">{t("eligibility.allowed_genders")}</p>
                  <div className="flex gap-4">
                    {["male", "female"].map(g => (
                      <label key={g} className="flex items-center gap-1 text-xs">
                        <input type="checkbox"
                          checked={(reqs.allowed_genders ?? []).includes(g)}
                          onChange={() => toggleArr("allowed_genders", g)} />
                        {g === "male" ? t("soldier_profile.gender_male") : t("soldier_profile.gender_female")}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Service type */}
                <div>
                  <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">{t("eligibility.allowed_service_types")}</p>
                  <div className="flex gap-4">
                    {["חובה", "קבע"].map(s => (
                      <label key={s} className="flex items-center gap-1 text-xs">
                        <input type="checkbox"
                          checked={(reqs.allowed_service_types ?? []).includes(s)}
                          onChange={() => toggleArr("allowed_service_types", s)} />
                        {s}
                      </label>
                    ))}
                  </div>
                </div>

                {/* Ranks */}
                <div>
                  <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-1">{t("eligibility.allowed_ranks")}</p>
                  {ranks.enlisted.length > 0 && (
                    <>
                      <p className="text-xs text-gray-400 mb-0.5">{t("soldier_profile.enlisted")}</p>
                      <div className="flex flex-wrap gap-2 mb-1">
                        {ranks.enlisted.map(r => (
                          <label key={r} className="flex items-center gap-1 text-xs">
                            <input type="checkbox"
                              checked={(reqs.allowed_ranks ?? []).includes(r)}
                              onChange={() => toggleArr("allowed_ranks", r)} />
                            {r}
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                  {ranks.officers.length > 0 && (
                    <>
                      <p className="text-xs text-gray-400 mb-0.5">{t("soldier_profile.officers")}</p>
                      <div className="flex flex-wrap gap-2">
                        {ranks.officers.map(r => (
                          <label key={r} className="flex items-center gap-1 text-xs">
                            <input type="checkbox"
                              checked={(reqs.allowed_ranks ?? []).includes(r)}
                              onChange={() => toggleArr("allowed_ranks", r)} />
                            {r}
                          </label>
                        ))}
                      </div>
                    </>
                  )}
                </div>

                {/* Boolean flags */}
                <div className="space-y-1.5">
                  {([
                    { key: "officers_allowed", label: t("eligibility.officers_allowed"), def: true },
                    { key: "enlisted_allowed", label: t("eligibility.enlisted_allowed"), def: true },
                    { key: "requires_mitvahim", label: t("eligibility.requires_mitvahim"), def: false },
                    { key: "requires_alal", label: t("eligibility.requires_alal"), def: false },
                    { key: "requires_bahad1", label: t("eligibility.requires_bahad1"), def: false },
                  ] as { key: keyof Reqs; label: string; def: boolean }[]).map(({ key, label, def }) => (
                    <label key={key} className="flex items-center gap-2 text-xs">
                      <input type="checkbox"
                        checked={(reqs[key] as boolean | undefined) ?? def}
                        onChange={e => toggleBool(key, e.target.checked)} />
                      {label}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Hierarchy scope section */}
          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">{t("hierarchy_scope.title")}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{t("hierarchy_scope.help")}</p>
            <SubHierarchySelector value={scopeNodeIds} onChange={setScopeNodeIds} />
          </div>

          {error && <p className="text-red-500 text-xs">{error}</p>}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">
              {t("duty_config.cancel", "ביטול")}
            </button>
            <button type="submit" disabled={saving}
              className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              {initial ? t("duty_config.save", "שמור") : t("duty_config.add")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
