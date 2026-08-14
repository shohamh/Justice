import { api } from "./client";

export type RankTrack = "enlisted" | "officer";

export interface RankLadderEntry {
  rank: string;
  months_to_next: number | null;
}

export interface RankLadder {
  enlisted: RankLadderEntry[];
  officer: RankLadderEntry[];
}

export interface RankIntervalUpdate {
  track: RankTrack;
  rank: string;
  months_to_next: number | null;
}

export async function getRankLadder(): Promise<RankLadder> {
  return (await api.get<RankLadder>("/soldiers/rank-ladder")).data;
}

// Unauthenticated variant, for public routes (e.g. /register) that need the
// rank list but have no access token — /soldiers/rank-ladder is gated behind
// require_password_changed and would 401 (and spuriously trip the token-refresh
// interceptor) for an anonymous visitor.
export async function getPublicRankLadder(): Promise<RankLadder> {
  return (await api.get<RankLadder>("/auth/rank-ladder")).data;
}

export async function updateRankAdvancementIntervals(
  intervals: RankIntervalUpdate[],
): Promise<RankLadder> {
  return (await api.put<RankLadder>("/soldiers/rank-advancement-intervals", intervals)).data;
}
