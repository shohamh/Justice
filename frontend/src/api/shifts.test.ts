import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import {
  getAutoAssignResponsibilityPreview,
  getQuotaSplitPreview,
  getTwoLevelSplitPreview,
  listShifts,
} from "./shifts";

vi.mock("./client");

describe("listShifts", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listShifts()).resolves.toEqual([]);
  });

  it("normalizes a null response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await expect(listShifts()).resolves.toEqual([]);
  });

  it("passes through a well-formed shift list", async () => {
    const shifts = [{ id: "shift-1", fill_status: "empty" }];
    vi.mocked(api.get).mockResolvedValue({ data: shifts });

    await expect(listShifts()).resolves.toEqual(shifts);
  });
});

describe("preview endpoints returning a nested collection", () => {
  it("normalizes a malformed getQuotaSplitPreview entries field to []", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { entries: "not-an-array" } });

    await expect(getQuotaSplitPreview("node-1", 3)).resolves.toEqual([]);
  });

  it("normalizes a non-object getQuotaSplitPreview response to []", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await expect(getQuotaSplitPreview("node-1", 3)).resolves.toEqual([]);
  });

  it("normalizes a malformed getTwoLevelSplitPreview entries field to []", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { entries: null } });

    await expect(getTwoLevelSplitPreview("shift-1")).resolves.toEqual([]);
  });

  it("normalizes a malformed getAutoAssignResponsibilityPreview assignments field to []", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { assignments: "not-an-array" } });

    await expect(getAutoAssignResponsibilityPreview(["shift-1"])).resolves.toEqual([]);
  });
});
