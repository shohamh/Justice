import { EffectiveDuty } from "../../api/assignments";

interface Props {
  duty: EffectiveDuty | null;
  typeNames: Record<string, string>;
  locationNames: Record<string, string>;
  onClose: () => void;
  onRequestSwap: (duty: EffectiveDuty) => void;
}

export default function DutyDetailModal({ duty, typeNames, locationNames, onClose, onRequestSwap }: Props) {
  if (!duty) return null;
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 max-w-sm w-full mx-4 space-y-3"
        dir="rtl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-center">
          <h3 className="text-lg font-semibold">פרטי תורנות</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <dl className="text-sm space-y-1">
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">סוג</dt>
            <dd>{typeNames[duty.duty_type_id] ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">מיקום</dt>
            <dd>{locationNames[duty.duty_location_id] ?? "—"}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-gray-500 w-20 shrink-0">תאריכים</dt>
            <dd dir="ltr">{duty.start_date === duty.end_date ? duty.start_date : `${duty.start_date} – ${duty.end_date}`}</dd>
          </div>
        </dl>
        <button
          className="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded text-sm font-medium"
          onClick={() => onRequestSwap(duty)}
        >
          בקש החלפה
        </button>
      </div>
    </div>
  );
}
