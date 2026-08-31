import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listDmScope } from "./dmScope";

vi.mock("./client");

describe("listDmScope", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listDmScope("soldier-1")).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const entries = [{ id: "entry-1", duty_manager_id: "soldier-1", hierarchy_node_id: "node-1" }];
    vi.mocked(api.get).mockResolvedValue({ data: entries });

    await expect(listDmScope("soldier-1")).resolves.toEqual(entries);
  });
});
