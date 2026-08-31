import { api } from "./client";
import { requiredArrayResponse, requiredObjectResponse } from "./responseGuards";

export type RankTrack = "enlisted" | "officer" | "officer_academic";

export interface RankLadderEntry {
  rank: string;
  months_to_next: number | null;
  advance_on_career_entry: boolean;
}

export interface RankLadder {
  enlisted: RankLadderEntry[];
  officer: RankLadderEntry[];
  officer_academic: RankLadderEntry[];
}

export interface RankIntervalUpdate {
  track: RankTrack;
  rank: string;
  months_to_next: number | null;
  advance_on_career_entry: boolean;
}

function toRankLadder(data: unknown): RankLadder {
  const record = requiredObjectResponse(data, "Invalid rank ladder response");
  return {
    ...record,
    enlisted: requiredArrayResponse<RankLadderEntry>(record.enlisted, "Invalid rank ladder response"),
    officer: requiredArrayResponse<RankLadderEntry>(record.officer, "Invalid rank ladder response"),
    officer_academic: requiredArrayResponse<RankLadderEntry>(record.officer_academic, "Invalid rank ladder response"),
  } as RankLadder;
}

export async function getRankLadder(): Promise<RankLadder> {
  return toRankLadder((await api.get<unknown>("/soldiers/rank-ladder")).data);
}

// Unauthenticated variant, for public routes (e.g. /register) that need the
// rank list but have no access token — /soldiers/rank-ladder is gated behind
// require_password_changed and would 401 (and spuriously trip the token-refresh
// interceptor) for an anonymous visitor.
export async function getPublicRankLadder(): Promise<RankLadder> {
  return toRankLadder((await api.get<unknown>("/auth/rank-ladder")).data);
}

export async function updateRankAdvancementIntervals(
  intervals: RankIntervalUpdate[],
): Promise<RankLadder> {
  return toRankLadder(
    (await api.put<unknown>("/soldiers/rank-advancement-intervals", intervals)).data,
  );
}
