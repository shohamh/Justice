import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import { listShifts } from "./shifts";

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
