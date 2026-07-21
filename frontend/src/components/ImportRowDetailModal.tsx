export interface DetailField {
  key: string;
  label: string;
  value: unknown;
  editable?: {
    type: "text" | "number" | "date" | "checkbox" | "textarea";
    onChange: (value: unknown) => void;
  };
}

interface Props {
  title: string;
  fields: DetailField[];
  onClose: () => void;
}

function formatReadOnly(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "כן" : "לא";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ImportRowDetailModal({ title, fields, onClose }: Props) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto space-y-3"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="font-semibold text-base">{title}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <div className="grid grid-cols-1 gap-2">
          {fields.map((f) => (
            <div key={f.key} className="flex flex-col gap-1">
              <span className="text-xs font-medium text-gray-500">{f.label}</span>
              {!f.editable ? (
                <span className="text-sm">{formatReadOnly(f.value)}</span>
              ) : f.editable.type === "checkbox" ? (
                <input
                  type="checkbox"
                  checked={Boolean(f.value)}
                  onChange={(e) => f.editable!.onChange(e.target.checked)}
                />
              ) : f.editable.type === "textarea" ? (
                <textarea
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                  defaultValue={typeof f.value === "string" ? f.value : ""}
                  onBlur={(e) => f.editable!.onChange(e.target.value || null)}
                />
              ) : (
                <input
                  type={f.editable.type}
                  className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600"
                  defaultValue={
                    f.value === null || f.value === undefined
                      ? ""
                      : (f.value as string | number)
                  }
                  onBlur={(e) =>
                    f.editable!.onChange(
                      f.editable!.type === "number"
                        ? (e.target.value === "" ? null : Number(e.target.value))
                        : (e.target.value || null),
                    )
                  }
                />
              )}
            </div>
          ))}
        </div>

        <div className="flex justify-end">
          <button type="button" onClick={onClose} className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
            סגור
          </button>
        </div>
      </div>
    </div>
  );
}
