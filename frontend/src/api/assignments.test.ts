import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getShiftCandidates, listAssignments, listEffectiveDuties } from "./assignments";

vi.mock("./client");

describe("assignment list APIs", () => {
  it.each([
    ["listAssignments", () => listAssignments("soldier-1")],
    ["listEffectiveDuties", () => listEffectiveDuties("soldier-1")],
    ["getShiftCandidates", () => getShiftCandidates("shift-1")],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });
});
