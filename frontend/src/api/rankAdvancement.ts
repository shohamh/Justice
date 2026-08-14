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

export async function updateRankAdvancementIntervals(
  intervals: RankIntervalUpdate[],
): Promise<RankLadder> {
  return (await api.put<RankLadder>("/soldiers/rank-advancement-intervals", intervals)).data;
}
