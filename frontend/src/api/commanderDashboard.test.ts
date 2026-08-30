import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  getAlerts,
  getApprovals,
  getDashboardSoldiers,
  getFairnessExternal,
  getPotential,
  getUpcoming,
} from "./commanderDashboard";

vi.mock("./client");

describe("commander dashboard collection APIs", () => {
  it.each([
    ["getDashboardSoldiers", () => getDashboardSoldiers()],
    ["getFairnessExternal", () => getFairnessExternal()],
    ["getPotential", () => getPotential()],
    ["getUpcoming", () => getUpcoming()],
    ["getAlerts", () => getAlerts()],
    ["getApprovals", () => getApprovals()],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });
});
