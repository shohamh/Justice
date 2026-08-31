import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listPendingTransferRequests } from "./hierarchyTransfers";

vi.mock("./client");

describe("hierarchy transfer APIs", () => {
  it("rejects a malformed pending transfer requests payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingTransferRequests()).rejects.toThrow("Invalid pending hierarchy transfer requests response");
  });
});
