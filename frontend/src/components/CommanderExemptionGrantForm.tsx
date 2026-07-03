import { useState } from "react";
import { grantCommanderExemption } from "../api/exemptions";

interface Props {
  soldierId: string;
  commanderExemptionTypes: { id: string; name: string }[];
  onGranted: () => void;
}

export default function CommanderExemptionGrantForm({ soldierId, commanderExemptionTypes, onGranted }: Props) {
  const [typeId, setTypeId] = useState(commanderExemptionTypes[0]?.id ?? "");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!reason.trim()) {
      setError("נדרשת סיבה");
      return;
    }
    try {
      await grantCommanderExemption(soldierId, {
        exemption_type_id: typeId,
        start_date: startDate,
        end_date: endDate || null,
        reason,
      });
      setReason("");
      onGranted();
    } catch {
      setError("שגיאה במתן הפטור");
    }
  }

  return (
    <div className="space-y-2 border rounded p-3" dir="rtl" data-testid="commander-exemption-form">
      <h3 className="font-semibold">מתן פטור פיקודי</h3>
      <p className="text-sm text-gray-600">
        שימו לב: פטור פיקודי לא מפחית את הפוטנציאל של היחידה — עומס התורנות יתחלק על פחות חיילים. יש להשתמש בו בצמצום.
      </p>
      <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className="border rounded p-1 w-full" data-testid="commander-exemption-type">
        {commanderExemptionTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
      <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded p-1 w-full" data-testid="commander-exemption-start" />
      <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} placeholder="תאריך סיום (רשות)" className="border rounded p-1 w-full" data-testid="commander-exemption-end" />
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 w-full" data-testid="commander-exemption-reason" />
      {error && <p className="text-red-600 text-sm">{error}</p>}
      <button type="button" onClick={handleSubmit} className="bg-blue-600 text-white rounded px-3 py-1" data-testid="commander-exemption-submit">הענק פטור</button>
    </div>
  );
}
