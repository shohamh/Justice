import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listDutyTypes, listExemptionTypes, listLocations } from "./dutyConfig";

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

  it("returns an empty list when exemption types are not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(listExemptionTypes()).resolves.toEqual([]);
  });

  it("passes through a well-formed exemption types list", async () => {
    const types = [{ id: "e-1", name: "Medical", description: null, active: true }];
    vi.mocked(api.get).mockResolvedValue({ data: types });

    await expect(listExemptionTypes()).resolves.toEqual(types);
  });
});
