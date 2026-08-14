import { useQuery } from "@tanstack/react-query";
import { getPublicRankLadder, getRankLadder, RankLadder } from "../api/rankAdvancement";
import { queryKeys } from "../queryKeys";

// Mirrors backend/app/services/eligibility.py ENLISTED_RANKS / OFFICER_RANKS.
// Kept as an internal, unexported list: it backs the static rank/track-
// compatibility table and the officer-rank/bahad1 helpers below, which are
// business rules out of scope for the rank-advancement API work — NOT the
// admin-editable rank *order*, which now lives server-side. Anything that
// needs the ordered ladder (e.g. to populate a rank picker) should use
// useRankLadder() below instead of hardcoding another copy of these lists.
// Keep these two lists in sync with the backend if ranks are ever added/removed.
const ENLISTED_RANKS = [
  "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
];

const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "קאם", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];

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
// סמ"ר is deliberately unrestricted (like סגן): it's held both by
// extended-חובה soldiers and by קבע soldiers, so it's excluded here.
const KEVA_ONLY_RANKS = [
  ...ENLISTED_RANKS.filter((r) => !CHOVAH_ONLY_RANKS.includes(r) && r !== "סמר"),
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

// ── Rank ladder (API-backed) ────────────────────────────────────────────────
// The ordered rank-advancement ladder — including each rank's admin-configured
// months_to_next — lives server-side (backend/app/services/rank_advancement.py)
// so it can be edited without a frontend deploy. This hook is the sole
// frontend source of rank order; consumers that previously read the
// ENLISTED_RANKS/OFFICER_RANKS constants (e.g. to build a rank picker) should
// use enlistedRanks/officerRanks/allRanks from this hook instead.
export function useRankLadder() {
  return withLadderFields(
    useQuery({ queryKey: queryKeys.rankLadder(), queryFn: getRankLadder }),
  );
}

// Same ladder, fetched from the unauthenticated /auth/rank-ladder endpoint —
// for PUBLIC routes (currently /register) where there is no access token, and
// the authenticated /soldiers/rank-ladder read would 401 and leave the rank
// picker empty. Kept under its own query key so the two never share a cache
// entry populated by the wrong fetcher.
export function usePublicRankLadder() {
  return withLadderFields(
    useQuery({ queryKey: queryKeys.publicRankLadder(), queryFn: getPublicRankLadder }),
  );
}

function withLadderFields<T extends { data?: RankLadder }>(query: T) {
  const enlistedRanks = query.data?.enlisted.map((e) => e.rank) ?? [];
  const officerRanks = query.data?.officer.map((e) => e.rank) ?? [];
  return {
    ...query,
    ladder: query.data,
    enlistedRanks,
    officerRanks,
    allRanks: [...enlistedRanks, ...officerRanks],
  };
}
