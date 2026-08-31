import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { findCandidates } from "./hakpaza";

vi.mock("./client");

describe("findCandidates", () => {
  it("returns an empty list when the payload is not an array", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(findCandidates("assignment-1", "2026-08-30")).resolves.toEqual([]);
  });

  it("returns the candidates when the payload is a valid array", async () => {
    const payload = [
      {
        soldier_id: "soldier-1",
        full_name: "מפקד לדוגמה",
        hierarchy_node_name: "פלוגה א",
        hierarchy_distance: 1,
        current_score: 3,
        score_per_day: 0.5,
        days_remaining: 10,
        recent_forced_callups_decayed: 0,
      },
    ];
    vi.mocked(api.post).mockResolvedValue({ data: payload });

    await expect(findCandidates("assignment-1", "2026-08-30")).resolves.toEqual(payload);
  });
});
