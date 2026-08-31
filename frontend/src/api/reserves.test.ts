import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getReserveCandidates } from "./reserves";

vi.mock("./client");

describe("getReserveCandidates", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(getReserveCandidates("shift-1", "assignment-1")).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const candidates = [
      { assignment_id: "a-1", soldier_id: "soldier-1", distance: 1, called_up_from: null, called_up_to: null },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: candidates });

    await expect(getReserveCandidates("shift-1", "assignment-1")).resolves.toEqual(candidates);
  });
});
