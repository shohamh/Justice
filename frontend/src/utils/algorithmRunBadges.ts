export interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

export interface RunBadgeJob {
  id: string;
  status: string;
  mode: string;
  error_message: string | null;
}

// Excludes jobs cancelled by the user (status "failed" with error_message "cancelled_by_user") from every
// bucket; "done" jobs split into "draft" (shadow mode) vs "done" (dm_reviewed mode). Jobs the user has already
// opened (seenIds) are excluded too, unless they're still pending/running — a job that's actively running stays
// in the badge even after being opened, since opening it didn't resolve anything.
export function computeRunBadgeCounts(jobs: RunBadgeJob[], seenIds: ReadonlySet<string> = new Set()): RunBadgeCounts {
  return jobs.reduce<RunBadgeCounts>(
    (acc, job) => {
      if (job.status === "failed" && job.error_message === "cancelled_by_user") {
        return acc;
      }
      if (job.status !== "pending" && job.status !== "running" && seenIds.has(job.id)) {
        return acc;
      }
      if (job.status === "pending" || job.status === "running") {
        acc.running += 1;
      } else if (job.status === "done" && job.mode === "shadow") {
        acc.draft += 1;
      } else if (job.status === "done" && job.mode === "dm_reviewed") {
        acc.done += 1;
      } else if (job.status === "failed") {
        acc.failed += 1;
      }
      return acc;
    },
    { running: 0, draft: 0, done: 0, failed: 0 }
  );
}
