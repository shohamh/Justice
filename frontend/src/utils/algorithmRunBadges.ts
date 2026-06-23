export interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

interface RunBadgeJob {
  status: string;
  mode: string;
  error_message: string | null;
}

export function computeRunBadgeCounts(jobs: RunBadgeJob[]): RunBadgeCounts {
  return jobs.reduce<RunBadgeCounts>(
    (acc, job) => {
      if (job.status === "failed" && job.error_message === "cancelled_by_user") {
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
