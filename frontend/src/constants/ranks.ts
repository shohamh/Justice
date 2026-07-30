// Mirrors backend/app/services/eligibility.py ENLISTED_RANKS / OFFICER_RANKS.
// Keep these two lists in sync with the backend if ranks are ever added/removed.
export const ENLISTED_RANKS = [
  "טוראי", "רבט", "סמל", "סמר", "רסל", "רסר", "רסמ", "רסב", "רנג",
];

export const OFFICER_RANKS = [
  "קמא", "סגמ", "סגן", "קאב", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף",
];

export const ALL_RANKS = [...ENLISTED_RANKS, ...OFFICER_RANKS];

const OFFICER_RANK_SET = new Set(OFFICER_RANKS);

export function isOfficerRank(rank: string): boolean {
  return OFFICER_RANK_SET.has(rank);
}
