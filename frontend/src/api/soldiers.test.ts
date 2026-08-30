import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getRanks, getSoldier, listFieldUpdates, listPendingFieldUpdates, listSoldiers } from "./soldiers";

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

describe("getSoldier", () => {
  it("returns the soldier when required fields are present", async () => {
    const soldier = { id: "s1", personal_number: "1234567", full_name: "ישראל ישראלי" };
    vi.mocked(api.get).mockResolvedValue({ data: soldier });

    await expect(getSoldier("s1")).resolves.toEqual(soldier);
  });

  it.each([
    ["a non-object payload", ["unexpected", "response"]],
    ["a payload missing id", { personal_number: "1234567", full_name: "ישראל ישראלי" }],
    ["a payload missing personal_number", { id: "s1", full_name: "ישראל ישראלי" }],
    ["a payload missing full_name", { id: "s1", personal_number: "1234567" }],
    ["a payload with a non-string id", { id: 1, personal_number: "1234567", full_name: "ישראל ישראלי" }],
  ])("rejects %s", async (_desc, data) => {
    vi.mocked(api.get).mockResolvedValue({ data });

    await expect(getSoldier("s1")).rejects.toThrow("Invalid soldier response");
  });
});
