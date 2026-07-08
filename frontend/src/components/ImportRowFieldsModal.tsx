import DutyTypeRequirementsEditor from "./DutyTypeRequirementsEditor";
import SubHierarchySelector from "./SubHierarchySelector";

interface DutyTypeMultiSelect {
  label: string;
  options: { id: string; name: string }[];
  value: string[];
  onChange: (next: string[]) => void;
}

interface EligibleUnits {
  value: string[];
  onChange: (next: string[]) => void;
}

interface Requirements {
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

interface Props {
  onClose: () => void;
  eligibleUnits?: EligibleUnits;
  requirements?: Requirements;
  dutyTypeMultiSelect?: DutyTypeMultiSelect;
}

export default function ImportRowFieldsModal({
  onClose,
  eligibleUnits,
  requirements,
  dutyTypeMultiSelect,
}: Props) {
  function toggleDutyType(id: string) {
    if (!dutyTypeMultiSelect) return;
    const { value, onChange } = dutyTypeMultiSelect;
    onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id]);
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto space-y-4"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="font-semibold text-base">עריכת שדה</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {eligibleUnits && (
          <div>
            <p className="text-sm font-medium mb-2">יחידות זכאיות</p>
            <SubHierarchySelector value={eligibleUnits.value} onChange={eligibleUnits.onChange} />
          </div>
        )}

        {requirements && (
          <div>
            <p className="text-sm font-medium mb-2">דרישות</p>
            <DutyTypeRequirementsEditor value={requirements.value} onChange={requirements.onChange} />
          </div>
        )}

        {dutyTypeMultiSelect && (
          <div>
            <p className="text-sm font-medium mb-2">{dutyTypeMultiSelect.label}</p>
            <div className="border rounded p-2 max-h-60 overflow-y-auto dark:border-gray-600 space-y-1">
              {dutyTypeMultiSelect.options.map((opt) => (
                <label key={opt.id} className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={dutyTypeMultiSelect.value.includes(opt.id)}
                    onChange={() => toggleDutyType(opt.id)}
                  />
                  {opt.name}
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="flex justify-end">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
            סגור
          </button>
        </div>
      </div>
    </div>
  );
}
