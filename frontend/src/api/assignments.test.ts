import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listEffectiveDuties } from "./assignments";

vi.mock("./client");

describe("effective duties API", () => {
  it("returns an empty list when the response is not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listEffectiveDuties("soldier-1")).resolves.toEqual([]);
  });
});
