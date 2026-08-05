// Mirrors backend/app/services/eligibility.py ENLISTED_RANKS / OFFICER_RANKS.
// Keep these two lists in sync with the backend if ranks are ever added/removed.
export const ENLISTED_RANKS = [
  "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
];

export const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "קאם", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];

export const ALL_RANKS = [...ENLISTED_RANKS, ...OFFICER_RANKS];

const OFFICER_RANK_SET = new Set(OFFICER_RANKS);

export function isOfficerRank(rank: string): boolean {
  return OFFICER_RANK_SET.has(rank);
}

// Mirrors backend/app/services/eligibility.py RANK_TRACK_COMPATIBILITY.
// Keep this table in sync with the backend if the compatibility rules change.
const CHOVAH_ONLY_RANKS = ["טוראי", "רבט", "סמל", "סגמ", "קמא"];
const RASAN_AND_ABOVE = OFFICER_RANKS.slice(OFFICER_RANKS.indexOf("רסן"));
// קא"ב and סרן are קבע-only per product confirmation, but fall below רס"ן in
// OFFICER_RANKS so they must be added explicitly — not covered by RASAN_AND_ABOVE.
const KEVA_ONLY_RANKS = [
  ...ENLISTED_RANKS.filter((r) => !CHOVAH_ONLY_RANKS.includes(r)),
  ...RASAN_AND_ABOVE,
  "קאב",
  "סרן",
  "קאם",
];

const RANK_TRACK_COMPATIBILITY: Record<string, "חובה" | "קבע"> = {
  ...Object.fromEntries(CHOVAH_ONLY_RANKS.map((r) => [r, "חובה" as const])),
  ...Object.fromEntries(KEVA_ONLY_RANKS.map((r) => [r, "קבע" as const])),
};

export function isRankTrackCompatible(rank: string, isCareer: boolean): boolean {
  const required = RANK_TRACK_COMPATIBILITY[rank];
  if (!required) return true;
  return required === (isCareer ? "קבע" : "חובה");
}

const BAHAD1_EXCLUDED_OFFICER_RANKS = ["קמא", "קאב", "קאם"];

// Mirrors backend/app/services/eligibility.py derive_bahad1_graduate.
export function deriveBahad1Graduate(rank: string): boolean {
  if (!OFFICER_RANK_SET.has(rank)) return false;
  return !BAHAD1_EXCLUDED_OFFICER_RANKS.includes(rank);
}

// Mirrors backend/app/services/eligibility.py derive_is_career. Dates are ISO
// "YYYY-MM-DD" strings, compared lexicographically (safe for this format,
// avoids `Date` timezone-parsing pitfalls for a same-day comparison).
export function deriveIsCareer(
  rank: string,
  mandatoryEndDate: string,
  dischargeDate: string,
  todayIso: string = new Date().toISOString().slice(0, 10),
): boolean {
  if (CHOVAH_ONLY_RANKS.includes(rank)) return false;
  if (!mandatoryEndDate) return false;
  if (todayIso <= mandatoryEndDate) return false;
  return !dischargeDate || dischargeDate > mandatoryEndDate;
}
