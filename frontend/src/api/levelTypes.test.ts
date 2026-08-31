import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listLevelTypes } from "./levelTypes";

vi.mock("./client");

describe("hierarchy level type APIs", () => {
  it("returns an empty list when the endpoint returns a non-array payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listLevelTypes()).resolves.toEqual([]);
  });
});
