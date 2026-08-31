import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { fetchFullTree, fetchTree } from "./hierarchy";

vi.mock("./client");

describe("hierarchy tree APIs", () => {
  it.each([
    ["fetchTree", () => fetchTree()],
    ["fetchFullTree", () => fetchFullTree()],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });
});
