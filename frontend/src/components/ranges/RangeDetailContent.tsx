import { ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { FoodAssignmentSummary, RangeAssignment, RangeEvent, RangeExcusalRequest } from "../../api/ranges";
import { RosterSection } from "../planning";
import { RangeAttendanceRow } from "./RangeAttendanceRow";
import { ATTENDANCE_STATUS_LABELS } from "../../utils/rangeLabels";

interface Props {
  event: RangeEvent;
  canManage: boolean;
  canEditAttendance?: boolean;
  isDutyManager?: boolean;
  userId?: string;
  soldierName: (id: string) => string;
  excusalRequests?: RangeExcusalRequest[];
  onExcuse: (id: string, reason: string) => Promise<void>;
  onDecide: (id: string, approve: boolean) => Promise<void>;
  onAttendance: () => void;
  actions?: ReactNode;
}

export default function RangeDetailContent(p: Props) {
  const { t } = useTranslation();
  const text = (key: string, fallback: string) => {
    const translated = t(key);
    return translated === key ? fallback : translated;
  };
  const { event } = p;
  const [excuseId, setExcuseId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [rosterSearch, setRosterSearch] = useState("");
  const today = new Date().toISOString().slice(0, 10);
  const future = event.date > today;
  const selfAssignment = event.assignments.find(a => future && !a.is_draft && a.soldier_id === p.userId);
  const actionClass = "rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50";
  const attendanceEditable = !!p.canEditAttendance && event.date <= today;

  const foodTypes = ["regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin", "unspecified"];
  const foodTypeLabels: Record<string, string> = {
    regular: text("soldier_profile.food_type_regular", "רגיל"),
    vegetarian: text("soldier_profile.food_type_vegetarian", "צמחוני"),
    vegan: text("soldier_profile.food_type_vegan", "טבעוני"),
    gluten_free: text("soldier_profile.food_type_gluten_free", "ללא גלוטן"),
    kosher_le_mehadrin: text("soldier_profile.food_type_kosher_le_mehadrin", "כשר למהדרין"),
    unspecified: text("ranges.food_unspecified", "לא צוין"),
  };
  const foodSummary = p.isDutyManager ? event.food_summary : null;
  const foodGroup = (kind: "primary" | "reserve", summary: FoodAssignmentSummary) => (
    <section data-testid={`range-food-${kind}`} className="rounded border p-3 dark:border-gray-600">
      <h4 className="mb-2 text-sm font-semibold">{kind === "primary" ? text("ranges.food_primary", "שיבוצים ראשיים") : text("ranges.food_reserve", "רזרבה")}</h4>
      <div className="grid grid-cols-2 gap-1 text-sm sm:grid-cols-3">
        {foodTypes.map(type => <div key={type} className="flex justify-between gap-2"><span>{foodTypeLabels[type]}</span><strong>{summary.counts[type] ?? 0}</strong></div>)}
      </div>
      {summary.special_constraints.length > 0 && <table className="mt-3 w-full text-xs"><thead><tr className="border-b text-right dark:border-gray-600"><th className="p-1">{text("ranges.food_soldier", "חייל")}</th><th className="p-1">{text("ranges.food_type", "סוג מזון")}</th><th className="p-1">{text("ranges.food_constraint", "אילוץ מיוחד")}</th></tr></thead><tbody>{summary.special_constraints.map(row => <tr key={row.soldier_id} className="border-b last:border-0 dark:border-gray-700"><td className="p-1">{row.soldier_name}</td><td className="p-1">{foodTypeLabels[row.food_type] ?? row.food_type}</td><td className="p-1">{row.constraint}</td></tr>)}</tbody></table>}
    </section>
  );

  const query = rosterSearch.trim().toLowerCase();
  const matchesSearch = (a: RangeAssignment) => !query || p.soldierName(a.soldier_id).toLowerCase().includes(query);
  const primary = event.assignments.filter(a => !a.is_reserve && matchesSearch(a));
  const reserve = event.assignments.filter(a => a.is_reserve && matchesSearch(a));

  const row = (a: RangeAssignment) => ({ id: a.id, soldierId: a.soldier_id, soldierName: p.soldierName(a.soldier_id), isDraft: a.is_draft, status: ATTENDANCE_STATUS_LABELS[a.attendance_status] ?? a.attendance_status });
  const attendanceAction = (assignmentId: string) => {
    if (!attendanceEditable) return null;
    const assignment = event.assignments.find(a => a.id === assignmentId);
    if (!assignment || assignment.is_draft) return null;
    return <RangeAttendanceRow eventId={event.id} assignment={assignment} onMarked={p.onAttendance} />;
  };

  return <div className="space-y-4" data-testid="range-detail-content">
    {p.actions}
    {selfAssignment && <section className="flex flex-wrap items-center gap-2" data-testid="range-self-excusal-action"><button type="button" onClick={() => { setExcuseId(selfAssignment.id); setReason(""); }} className={`${actionClass} border-amber-300 text-amber-700`}>{text("ranges.self_excuse", "אני לא אוכל להגיע")}</button>{excuseId === selfAssignment.id && <span className="flex items-center gap-1"><input aria-label={text("ranges.self_excuse_reason", "סיבת היעדרות")} value={reason} onChange={e => setReason(e.target.value)} className="rounded border p-1 text-sm" /><button type="button" data-testid="submit-excuse-button" disabled={!reason.trim()} onClick={async () => { await p.onExcuse(selfAssignment.id, reason.trim()); setExcuseId(null); setReason(""); }} className={`${actionClass} border-blue-600 bg-blue-600 text-white`}>{text("ranges.send", "שלח")}</button></span>}</section>}
    <section data-testid="range-detail-information" className="rounded border bg-gray-50 p-4 text-sm text-gray-800 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"><h3 className="mb-2 text-sm font-semibold">מידע והנחיות</h3><div><b>הוראות הגעה:</b> {event.arrival_instructions || "—"}</div><div><b>איש קשר:</b> {event.contact_name || "—"} {event.contact_phone || ""}</div><div><b>הערות:</b> {event.notes || "—"}</div></section>
    {foodSummary && <section data-testid="range-food-summary" className="space-y-3 rounded border border-indigo-200 bg-indigo-50 p-4 dark:border-indigo-800 dark:bg-indigo-950"><h3 className="text-sm font-semibold">{text("ranges.food_summary_title", "סיכום הזמנת אוכל")}</h3>{foodGroup("primary", foodSummary.primary)}{foodGroup("reserve", foodSummary.reserve)}</section>}
    <section data-testid="range-detail-roster" className="space-y-3">
      <h3 className="text-sm font-semibold">רשימת שיבוצים</h3>
      <input
        type="text"
        data-testid="range-roster-search"
        value={rosterSearch}
        onChange={e => setRosterSearch(e.target.value)}
        placeholder="חיפוש חייל..."
        className="w-full rounded border p-1.5 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
      />
      <RosterSection kind="primary" assignments={primary.map(row)} count={event.required_count} assignmentActionRenderer={rowData => attendanceAction(rowData.id)} />
      <RosterSection kind="reserve" assignments={reserve.map(row)} count={event.reserve_count} assignmentActionRenderer={rowData => attendanceAction(rowData.id)} />
    </section>
    {p.excusalRequests && p.excusalRequests.length > 0 && <section data-testid="excusal-review-queue" className="space-y-2 rounded border p-4 dark:border-gray-600"><h3 className="text-sm font-semibold">בקשות היעדרות</h3>{p.excusalRequests.map(r => <div key={r.id} className="flex flex-wrap items-center gap-2 text-sm">{r.reason}{p.canManage && <><button type="button" data-testid={`approve-excusal-${r.id}`} onClick={() => p.onDecide(r.id, true)} className={`${actionClass} border-green-600 bg-green-600 text-white`}>אשר וקדם</button><button type="button" data-testid={`reject-excusal-${r.id}`} onClick={() => p.onDecide(r.id, false)} className={`${actionClass} border-red-200 text-red-700`}>דחה</button></>}</div>)}</section>}
  </div>;
}
