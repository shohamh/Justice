import { computeRunBadgeCounts } from "./algorithmRunBadges";

function job(status: string, mode: string, error_message: string | null = null, id = "job-1") {
  return { id, status, mode, error_message };
}

describe("computeRunBadgeCounts", () => {
  test("returns all zeros for an empty list", () => {
    expect(computeRunBadgeCounts([])).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });

  test("groups pending/running jobs as running regardless of mode", () => {
    const counts = computeRunBadgeCounts([
      job("pending", "shadow"),
      job("running", "dm_reviewed"),
    ]);
    expect(counts).toEqual({ running: 2, draft: 0, done: 0, failed: 0 });
  });

  test("splits done jobs into draft (shadow) and done (dm_reviewed)", () => {
    const counts = computeRunBadgeCounts([
      job("done", "shadow"),
      job("done", "shadow"),
      job("done", "dm_reviewed"),
    ]);
    expect(counts).toEqual({ running: 0, draft: 2, done: 1, failed: 0 });
  });

  test("counts a genuine failure as failed", () => {
    const counts = computeRunBadgeCounts([job("failed", "shadow", "solver_timeout")]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 1 });
  });

  test("excludes a cancelled job from every bucket", () => {
    const counts = computeRunBadgeCounts([
      job("failed", "shadow", "cancelled_by_user"),
      job("failed", "dm_reviewed", "solver_timeout"),
    ]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 1 });
  });

  test("a published job (status not in pending/running/done/failed) counts nowhere", () => {
    const counts = computeRunBadgeCounts([job("published", "dm_reviewed")]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });

  test("excludes a seen done job from its bucket", () => {
    const counts = computeRunBadgeCounts(
      [job("done", "shadow", null, "job-1")],
      new Set(["job-1"]),
    );
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });

  test("excludes a seen failed job from its bucket", () => {
    const counts = computeRunBadgeCounts(
      [job("failed", "shadow", "solver_timeout", "job-1")],
      new Set(["job-1"]),
    );
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });

  test("a seen job still counts while pending or running", () => {
    const counts = computeRunBadgeCounts(
      [job("running", "shadow", null, "job-1"), job("pending", "shadow", null, "job-2")],
      new Set(["job-1", "job-2"]),
    );
    expect(counts).toEqual({ running: 2, draft: 0, done: 0, failed: 0 });
  });

  test("seeing one job doesn't suppress an unseen job in the same bucket", () => {
    const counts = computeRunBadgeCounts(
      [job("done", "shadow", null, "job-1"), job("done", "shadow", null, "job-2")],
      new Set(["job-1"]),
    );
    expect(counts).toEqual({ running: 0, draft: 1, done: 0, failed: 0 });
  });
});
