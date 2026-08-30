import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listPendingTransferRequests } from "./hierarchyTransfers";

vi.mock("./client");

describe("hierarchy transfer APIs", () => {
  it("returns an empty list when pending transfer requests are not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingTransferRequests()).resolves.toEqual([]);
  });
});
