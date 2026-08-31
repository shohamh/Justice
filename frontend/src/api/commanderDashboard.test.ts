import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import {
  getAlerts,
  getApprovals,
  getDashboardSoldiers,
  getFairnessExternal,
  getFairnessInternal,
  getPotential,
  getSummary,
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

describe("getSummary", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(getSummary()).rejects.toThrow("Invalid dashboard summary response");
  });

  it("rejects a payload with a non-numeric counter", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { approvals_pending: "3", upcoming_duties_7d: 1, unfilled_gaps: 0, alerts_count: 2 },
    });
    await expect(getSummary()).rejects.toThrow("Invalid dashboard summary response");
  });

  it("passes through a well-formed payload", async () => {
    const summary = { approvals_pending: 3, upcoming_duties_7d: 1, unfilled_gaps: 0, alerts_count: 2 };
    vi.mocked(api.get).mockResolvedValue({ data: summary });
    await expect(getSummary()).resolves.toEqual(summary);
  });
});

describe("getFairnessInternal", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "unexpected response" });
    await expect(getFairnessInternal()).rejects.toThrow("Invalid internal fairness response");
  });

  it("rejects a payload with a missing numeric field", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { mean: 1, median: 1, min: 0, max: 2, stddev: 0.5 } });
    await expect(getFairnessInternal()).rejects.toThrow("Invalid internal fairness response");
  });

  it("passes through a well-formed payload", async () => {
    const stats = { mean: 1, median: 1, min: 0, max: 2, stddev: 0.5, soldier_count: 10 };
    vi.mocked(api.get).mockResolvedValue({ data: stats });
    await expect(getFairnessInternal()).resolves.toEqual(stats);
  });
});
