import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import { getAlgorithmDefaults, listJobs, pollJob } from "./algorithm";

vi.mock("./client");

describe("listJobs", () => {
  it("normalizes a malformed items payload to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { items: { detail: "unexpected response" }, total: 3 } });

    await expect(listJobs()).resolves.toEqual({ items: [], total: 3 });
  });

  it("normalizes a wholly malformed job-list payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "unexpected response" });

    await expect(listJobs()).resolves.toEqual({ items: [], total: 0 });
  });

  it("passes through a well-formed job list", async () => {
    const items = [{ id: "job-1", status: "done" }];
    vi.mocked(api.get).mockResolvedValue({ data: { items, total: 1 } });

    await expect(listJobs()).resolves.toEqual({ items, total: 1 });
  });
});

describe("pollJob", () => {
  it("rejects a malformed job payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(pollJob("job-1")).rejects.toThrow("Invalid algorithm job response");
  });

  it("rejects a non-object job payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await expect(pollJob("job-1")).rejects.toThrow("Invalid algorithm job response");
  });

  it("normalizes malformed proposals/batch_results on an otherwise-valid job to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        id: "job-1",
        status: "done",
        proposals: { detail: "unexpected response" },
        batch_results: "unexpected response",
      },
    });

    const job = await pollJob("job-1");
    expect(job.proposals).toEqual([]);
    expect(job.batch_results).toEqual([]);
    expect(job.id).toBe("job-1");
  });

  it("keeps a legitimately empty proposals/batch_results job as empty, not an error", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { id: "job-1", status: "done", proposals: [], batch_results: [] },
    });

    await expect(pollJob("job-1")).resolves.toEqual(
      expect.objectContaining({ id: "job-1", status: "done", proposals: [], batch_results: [] }),
    );
  });
});

describe("getAlgorithmDefaults", () => {
  it("rejects a malformed defaults payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { T: "8", Wt: 14, R: 15, Wr: 28 } });

    await expect(getAlgorithmDefaults()).rejects.toThrow("Invalid algorithm defaults response");
  });

  it("rejects a non-object defaults payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });

    await expect(getAlgorithmDefaults()).rejects.toThrow("Invalid algorithm defaults response");
  });

  it("returns a well-formed defaults payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { T: 8, Wt: 14, R: 15, Wr: 28 } });

    await expect(getAlgorithmDefaults()).resolves.toEqual({ T: 8, Wt: 14, R: 15, Wr: 28 });
  });
});
