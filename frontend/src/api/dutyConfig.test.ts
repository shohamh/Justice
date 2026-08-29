import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listDutyTypes, listLocations } from "./dutyConfig";

vi.mock("./client");

describe("duty configuration list APIs", () => {
  it("returns an empty list when duty types are not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listDutyTypes()).resolves.toEqual([]);
  });

  it("returns an empty list when locations are not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listLocations()).resolves.toEqual([]);
  });
});
