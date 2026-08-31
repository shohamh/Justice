import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listAdjustments } from "./scoreAdjustments";

vi.mock("./client");

describe("listAdjustments", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listAdjustments("soldier-1")).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const adjustments = [
      { id: "adj-1", soldier_id: "soldier-1", delta: "1.0", reason: "note", duty_type_id: null, created_at: "2026-08-30T00:00:00Z" },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: adjustments });

    await expect(listAdjustments("soldier-1")).resolves.toEqual(adjustments);
  });
});
