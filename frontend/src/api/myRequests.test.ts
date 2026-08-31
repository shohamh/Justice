import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listMyHierarchyTransfers, listMyRangeExcusalRequests } from "./myRequests";

vi.mock("./client");

describe("listMyHierarchyTransfers", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listMyHierarchyTransfers()).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const transfers = [{ id: "t-1", status: "pending" }];
    vi.mocked(api.get).mockResolvedValue({ data: transfers });

    await expect(listMyHierarchyTransfers()).resolves.toEqual(transfers);
  });
});

describe("listMyRangeExcusalRequests", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await expect(listMyRangeExcusalRequests()).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const excusals = [{ id: "e-1", status: "pending" }];
    vi.mocked(api.get).mockResolvedValue({ data: excusals });

    await expect(listMyRangeExcusalRequests()).resolves.toEqual(excusals);
  });
});
