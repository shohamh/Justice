import { useState } from "react";
import { escalateCommanderExemption, grantCommanderExemption } from "../api/exemptions";
import DateInput from "../components/DateInput";

interface Props {
  soldierId: string;
  commanderExemptionTypes: { id: string; name: string }[];
  officialExemptionTypes: { id: string; name: string }[];
  onGranted: () => void;
}

export default function CommanderExemptionGrantForm({
  soldierId, commanderExemptionTypes, officialExemptionTypes, onGranted,
}: Props) {
  const [typeId, setTypeId] = useState(commanderExemptionTypes[0]?.id ?? "");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [escalate, setEscalate] = useState(false);
  const [officialTypeId, setOfficialTypeId] = useState(officialExemptionTypes[0]?.id ?? "");
  const [applyImmediately, setApplyImmediately] = useState(false);

  const [showConfirm, setShowConfirm] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  function openConfirm() {
    if (!reason.trim()) {
      setError("נדרשת סיבה");
      return;
    }
    if (escalate && !officialTypeId) {
      setError("יש לבחור סוג פטור רשמי לבקשה");
      return;
    }
    setError(null);
    setAcknowledged(false);
    setShowConfirm(true);
  }

  async function handleConfirm() {
    try {
      if (escalate) {
        await escalateCommanderExemption(soldierId, {
          official_exemption_type_id: officialTypeId,
          commander_exemption_type_id: applyImmediately ? typeId : undefined,
          start_date: startDate,
          end_date: endDate || null,
          reason,
          apply_immediately: applyImmediately,
        });
      } else {
        await grantCommanderExemption(soldierId, {
          exemption_type_id: typeId,
          start_date: startDate,
          end_date: endDate || null,
          reason,
        });
      }
      setReason("");
      setShowConfirm(false);
      onGranted();
    } catch {
      setError("שגיאה במתן הפטור");
      setShowConfirm(false);
    }
  }

  return (
    <div className="space-y-2 border rounded p-3" dir="rtl" data-testid="commander-exemption-form">
      <h3 className="font-semibold">צור פטור פיקודי</h3>
      <p className="text-sm text-gray-600">
        שימו לב: פטור פיקודי לא מפחית את הפוטנציאל של היחידה — עומס התורנות יתחלק על פחות חיילים. יש להשתמש בו בצמצום.
      </p>
      <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className="border rounded p-1 w-full" data-testid="commander-exemption-type">
        {commanderExemptionTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
      <DateInput value={startDate} onChange={v => setStartDate(v)} className="border rounded p-1 w-full" data-testid="commander-exemption-start" />
      <DateInput value={endDate} onChange={v => setEndDate(v)} className="border rounded p-1 w-full" data-testid="commander-exemption-end" />
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 w-full" data-testid="commander-exemption-reason" />

      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={escalate}
          onChange={(e) => setEscalate(e.target.checked)}
          data-testid="commander-exemption-escalate-checkbox"
        />
        העלה לאישור מפקד תורנויות כפטור רשמי
      </label>

      {escalate && (
        <div className="space-y-2 pr-4 border-r-2 border-indigo-200">
          <select
            value={officialTypeId}
            onChange={(e) => setOfficialTypeId(e.target.value)}
            className="border rounded p-1 w-full"
            data-testid="commander-exemption-official-type"
          >
            {officialExemptionTypes.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={applyImmediately}
              onChange={(e) => setApplyImmediately(e.target.checked)}
              data-testid="commander-exemption-apply-immediately-checkbox"
            />
            החל את הפטור הפיקודי מיידית (בנוסף לבקשה)
          </label>
        </div>
      )}

      {error && <p className="text-red-600 text-sm">{error}</p>}
      <button type="button" onClick={openConfirm} className="bg-blue-600 text-white rounded px-3 py-1" data-testid="commander-exemption-submit">
        צור פטור פיקודי
      </button>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowConfirm(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <h4 className="font-bold text-lg mb-3">אישור מתן פטור פיקודי</h4>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
              פטור פיקודי לא נספר בחישובי הפוטנציאל — היחידה תישא בעומס במקום החייל. יש להשתמש בכלי זה בצמצום.
            </p>
            <label className="flex items-center gap-2 text-sm cursor-pointer mb-4">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                data-testid="commander-exemption-ack-checkbox"
              />
              אני מבין/ה
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300"
              >
                ביטול
              </button>
              <button
                onClick={() => void handleConfirm()}
                disabled={!acknowledged}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-40"
                data-testid="commander-exemption-confirm"
              >
                אשר
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
