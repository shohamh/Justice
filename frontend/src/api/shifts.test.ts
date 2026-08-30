import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listShifts } from "./shifts";

vi.mock("./client");

describe("shift list API", () => {
  it("returns an empty list when the response is not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listShifts()).resolves.toEqual([]);
  });
});
