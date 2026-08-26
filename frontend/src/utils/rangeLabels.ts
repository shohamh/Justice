import type { RangeType } from "../api/ranges";

export const RANGE_TYPE_LABELS: Record<string, string> = {
  laser: "מטווח לייזר",
  live: "מטווח חי",
  alal: 'אל"ל',
};

export const RANGE_TYPE_OPTIONS: Array<{ id: RangeType; name: string }> = (Object.keys(RANGE_TYPE_LABELS) as RangeType[]).map(id => ({
  id,
  name: RANGE_TYPE_LABELS[id],
}));

export const RANGE_EVENT_STATUS_LABELS: Record<string, string> = {
  planned: "מתוכנן",
  completed: "הושלם",
  cancelled: "בוטל",
};

export const ATTENDANCE_STATUS_LABELS: Record<string, string> = {
  pending: "ממתין",
  present: "נכח",
  no_show: "לא הגיע",
};
