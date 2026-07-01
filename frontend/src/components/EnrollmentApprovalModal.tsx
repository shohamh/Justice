import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { EnrollmentRequestDTO, patchEnrollment, approveEnrollment, rejectEnrollment } from "../api/enrollment";
import Combobox from "./Combobox";

// Rank lists for the rank selector
const RANKS_ENLISTED = ["טוראי","רבט","סמל","סמר","רסל","רסר","רסמ","רסב","רנג","קמא","סגמ"];
const RANKS_OFFICER = ["סגן","קאב","סרן","רסן","סאל","אלמ","תאל","אלוף","רב אלוף"];

interface NodeItem {
  id: string;
  name: string;
}

interface ExemptionTypeItem {
  id: string;
  name: string;
}

interface Props {
  req: EnrollmentRequestDTO;
  nodes: NodeItem[];
  exemptionTypes: ExemptionTypeItem[];
  onClose: () => void;
  onDone: () => void;
}

export default function EnrollmentApprovalModal({ req, nodes, exemptionTypes, onClose, onDone }: Props) {
  const { t } = useTranslation();

  const [fullName, setFullName] = useState(req.soldier_name);
  const [personalNumber, setPersonalNumber] = useState(req.soldier_personal_number);
  const [requestedNodeId, setRequestedNodeId] = useState(req.requested_node_id);
  const [phone, setPhone] = useState(req.phone ?? "");
  const [email, setEmail] = useState(req.email ?? "");
  const [rank, setRank] = useState(req.rank ?? "");
  const [isOfficer, setIsOfficer] = useState(req.is_officer ?? false);
  const [isCareer, setIsCareer] = useState(req.is_career);
  const [gender, setGender] = useState(req.gender ?? "");
  const [enlistmentDate, setEnlistmentDate] = useState(req.enlistment_date ?? "");
  const [mandatoryEndDate, setMandatoryEndDate] = useState(req.mandatory_end_date ?? "");
  const [dischargeDate, setDischargeDate] = useState(req.discharge_date ?? "");
  const [lastMitvahimDate, setLastMitvahimDate] = useState(req.last_mitvahim_date ?? "");
  const [lastAlalDate, setLastAlalDate] = useState(req.last_alal_date ?? "");
  const [rejectNote, setRejectNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const typeById = Object.fromEntries(exemptionTypes.map(et => [et.id, et.name]));

  async function handleSaveAndApprove(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await patchEnrollment(req.id, {
        full_name: fullName,
        personal_number: personalNumber,
        requested_node_id: requestedNodeId,
        phone: phone || null,
        email: email || null,
        rank: rank || null,
        is_officer: isOfficer,
        is_career: isCareer,
        gender: gender || null,
        enlistment_date: enlistmentDate || null,
        mandatory_end_date: mandatoryEndDate || null,
        discharge_date: dischargeDate || null,
        last_mitvahim_date: lastMitvahimDate || null,
        last_alal_date: lastAlalDate || null,
      });
      await approveEnrollment(req.id);
      onDone();
    } catch {
      setError("שגיאה בשמירה");
    } finally {
      setSaving(false);
    }
  }

  async function handleReject() {
    if (!rejectNote.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await rejectEnrollment(req.id, rejectNote);
      onDone();
    } catch {
      setError("שגיאה בדחייה");
    } finally {
      setSaving(false);
    }
  }

  void t; // i18n hook reserved for future use

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90vh] overflow-y-auto"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold text-lg">אישור הצטרפות — {req.soldier_name}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>

        {error && <p className="text-red-600 text-sm mb-3">{error}</p>}

        <form onSubmit={handleSaveAndApprove} className="space-y-3 text-sm">
          <label className="block">
            <span className="text-xs text-gray-500">שם מלא</span>
            <input
              className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              required
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">מספר אישי</span>
            <input
              className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
              value={personalNumber}
              onChange={e => setPersonalNumber(e.target.value)}
              required
            />
          </label>
          <div className="block">
            <span className="text-xs text-gray-500">מסגרת מבוקשת</span>
            <Combobox
              items={nodes}
              value={requestedNodeId}
              onChange={setRequestedNodeId}
              placeholder="—"
            />
          </div>
          <div className="block">
            <span className="text-xs text-gray-500">דרגה</span>
            <Combobox
              items={[
                ...RANKS_ENLISTED.map(r => ({ id: r, name: r })),
                ...RANKS_OFFICER.map(r => ({ id: r, name: r })),
              ]}
              value={rank}
              onChange={v => {
                setRank(v);
                setIsOfficer(RANKS_OFFICER.includes(v));
              }}
              placeholder="בחר"
            />
          </div>
          <div className="flex gap-4">
            <label className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={isOfficer}
                onChange={e => setIsOfficer(e.target.checked)}
              />
              <span className="text-xs">קצין</span>
            </label>
            {!isOfficer && (
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={isCareer}
                  onChange={e => setIsCareer(e.target.checked)}
                />
                <span className="text-xs">קבע</span>
              </label>
            )}
          </div>
          <label className="block">
            <span className="text-xs text-gray-500">מגדר</span>
            <select
              className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
              value={gender}
              onChange={e => setGender(e.target.value)}
            >
              <option value="">—</option>
              <option value="male">זכר</option>
              <option value="female">נקבה</option>
              <option value="other">אחר</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">טלפון</span>
            <input
              type="tel"
              className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
              value={phone}
              onChange={e => setPhone(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">אימייל</span>
            <input
              type="email"
              className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
          </label>
          {[
            ["תאריך גיוס", enlistmentDate, setEnlistmentDate],
            ["סיום חובה", mandatoryEndDate, setMandatoryEndDate],
            ["שחרור", dischargeDate, setDischargeDate],
            ["מטווח אחרון", lastMitvahimDate, setLastMitvahimDate],
          ].map(([label, value, setter]) => (
            <label key={label as string} className="block">
              <span className="text-xs text-gray-500">{label as string}</span>
              <input
                type="date"
                lang="he"
                className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
                value={value as string}
                onChange={e => (setter as (v: string) => void)(e.target.value)}
              />
            </label>
          ))}
          {(isOfficer || isCareer) && (
            <label className="block">
              <span className="text-xs text-gray-500">אל"ל אחרון</span>
              <input
                type="date"
                lang="he"
                className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600"
                value={lastAlalDate}
                onChange={e => setLastAlalDate(e.target.value)}
              />
            </label>
          )}

          {req.exemption_requests.length > 0 && (
            <div className="border-t dark:border-gray-600 pt-2">
              <p className="text-xs font-medium text-gray-500 mb-1">
                פטורים מבוקשים (יטופלו ע"י אחראי תורנויות):
              </p>
              <ul className="space-y-1">
                {req.exemption_requests.map(er => (
                  <li
                    key={er.id}
                    className="text-xs bg-amber-50 dark:bg-amber-950 border border-amber-200 dark:border-amber-700 rounded px-2 py-1"
                  >
                    <span className="font-medium">
                      {er.exemption_type_id ? (typeById[er.exemption_type_id] ?? er.exemption_type_id) : "—"}
                    </span>
                    {" · "}{er.start_date}{er.end_date ? ` → ${er.end_date}` : " → ללא הגבלה"}
                    {er.reason && <span className="text-gray-500"> · {er.reason}</span>}
                    <span
                      className={`mr-2 px-1 rounded text-xs ${
                        er.status === "approved"
                          ? "bg-green-100 text-green-700"
                          : er.status === "rejected"
                          ? "bg-red-100 text-red-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {er.status === "pending" ? "ממתין" : er.status === "approved" ? "אושר" : "נדחה"}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-2 pt-2 border-t dark:border-gray-600">
            <button
              type="submit"
              disabled={saving}
              className="bg-green-600 text-white px-4 py-1.5 rounded text-sm disabled:opacity-50 hover:bg-green-700"
            >
              {saving ? "שומר..." : "שמור ואשר"}
            </button>
            <div className="flex gap-1 flex-1">
              <input
                className="border rounded p-1 text-sm flex-1 dark:bg-gray-700 dark:border-gray-600"
                placeholder="סיבת דחייה (חובה לדחייה)"
                value={rejectNote}
                onChange={e => setRejectNote(e.target.value)}
              />
              <button
                type="button"
                disabled={!rejectNote.trim() || saving}
                onClick={handleReject}
                className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50 hover:bg-red-700"
              >
                דחה
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
