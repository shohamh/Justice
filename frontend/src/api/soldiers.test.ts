import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getRanks, listFieldUpdates, listPendingFieldUpdates, listSoldiers } from "./soldiers";

vi.mock("./client");

describe("soldier collection APIs", () => {
  it.each([
    ["listSoldiers", () => listSoldiers()],
    ["listFieldUpdates", () => listFieldUpdates("soldier-1")],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });

  it("rejects a malformed pending field-updates payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listPendingFieldUpdates()).rejects.toThrow("Invalid pending field updates response");
  });

  it("rejects a malformed soldier ranks payload", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { enlisted: ["רב\"ט"], officers: { detail: "unexpected response" }, officer_academic: [] },
    });

    await expect(getRanks()).rejects.toThrow("Invalid soldier ranks response");
  });
});
