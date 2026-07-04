import { useState } from "react";
import { useTranslation } from "react-i18next";
import { DutyType, ExemptionType, setExemptionDutyTypes, updateExemptionType } from "../api/dutyConfig";

interface Props {
  exemptionType: ExemptionType;
  mappedDutyTypeIds: string[];
  dutyTypes: DutyType[];
  canEdit: boolean;
  onClose: () => void;
  onSaved: (updated: ExemptionType, mappedDutyTypeIds: string[]) => void;
}

export default function ExemptionTypeViewModal({
  exemptionType, mappedDutyTypeIds, dutyTypes, canEdit, onClose, onSaved,
}: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(exemptionType.name);
  const [isGlobal, setIsGlobal] = useState(exemptionType.is_global ?? false);
  const [isMedical, setIsMedical] = useState(exemptionType.is_medical ?? false);
  const [isCommander, setIsCommander] = useState(exemptionType.is_commander_exemption ?? false);
  const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>(mappedDutyTypeIds);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mappedNames = dutyTypes.filter((d) => mappedDutyTypeIds.includes(d.id)).map((d) => d.name);

  function toggleDutyType(id: string) {
    setSelectedDutyTypeIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateExemptionType(exemptionType.id, {
        name, is_global: isGlobal, is_medical: isMedical, is_commander_exemption: isCommander,
      });
      const newMapping = isGlobal ? [] : await setExemptionDutyTypes(exemptionType.id, selectedDutyTypeIds);
      onSaved(updated, newMapping);
      setEditing(false);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4"
      onClick={onClose}
      data-testid="exemption-type-view-modal"
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-md"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base flex items-center gap-2">
            {editing ? (
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="border border-gray-300 dark:border-gray-600 rounded p-1 text-sm dark:bg-gray-700 dark:text-gray-100"
                data-testid="exemption-name-input"
              />
            ) : (
              <span>{exemptionType.name}</span>
            )}
            {canEdit && !editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="text-gray-400 hover:text-indigo-600"
                aria-label={t("duty_config.edit", "ערוך")}
                data-testid="exemption-edit-pencil"
              >
                ✏️
              </button>
            )}
          </h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {!editing && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-2 flex-wrap">
              {exemptionType.is_global && (
                <span className="text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-0.5 rounded">
                  {t("duty_config.global")}
                </span>
              )}
              {exemptionType.is_medical && (
                <span className="text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 px-2 py-0.5 rounded">
                  🏥 {t("duty_config.medical")}
                </span>
              )}
              {exemptionType.is_commander_exemption && (
                <span className="text-xs bg-purple-100 dark:bg-purple-900 text-purple-800 dark:text-purple-200 px-2 py-0.5 rounded">
                  🎖️ {t("duty_config.commander_exemption")}
                </span>
              )}
            </div>
            <div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{t("duty_config.exempts_from")}:</p>
              {exemptionType.is_global ? (
                <p className="text-gray-700 dark:text-gray-300">{t("duty_config.global_exempt_desc")}</p>
              ) : mappedNames.length > 0 ? (
                <p className="text-gray-700 dark:text-gray-300">{mappedNames.join(", ")}</p>
              ) : (
                <p className="text-gray-400 dark:text-gray-500">—</p>
              )}
            </div>
          </div>
        )}

        {editing && (
          <div className="space-y-3 text-sm">
            <div className="flex gap-4 flex-wrap">
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isGlobal} onChange={(e) => setIsGlobal(e.target.checked)} data-testid="exemption-edit-global" />
                {t("duty_config.global")}
              </label>
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isMedical} onChange={(e) => setIsMedical(e.target.checked)} data-testid="exemption-edit-medical" />
                🏥 {t("duty_config.medical")}
              </label>
              <label className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={isCommander} onChange={(e) => setIsCommander(e.target.checked)} data-testid="exemption-edit-commander" />
                🎖️ {t("duty_config.commander_exemption")}
              </label>
            </div>
            {!isGlobal && (
              <div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{t("duty_config.exempts_from")}:</p>
                <div className="flex flex-wrap gap-2">
                  {dutyTypes.map((d) => (
                    <label key={d.id} className="text-xs flex items-center gap-1">
                      <input
                        type="checkbox"
                        checked={selectedDutyTypeIds.includes(d.id)}
                        onChange={() => toggleDutyType(d.id)}
                        data-testid={`exemption-edit-dt-${d.name}`}
                      />
                      {d.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
            {error && <p className="text-red-500 text-xs">{error}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                disabled={saving}
                className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded disabled:opacity-50"
              >
                {t("duty_config.cancel", "ביטול")}
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                data-testid="exemption-edit-save"
              >
                {saving ? "..." : t("duty_config.save", "שמור")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
