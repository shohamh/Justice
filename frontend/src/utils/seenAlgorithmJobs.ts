const STORAGE_KEY = "algorithm_seen_job_ids";

function readSeenIds(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

export function getSeenJobIds(): Set<string> {
  return readSeenIds();
}

export function markJobSeen(jobId: string): void {
  const ids = readSeenIds();
  if (ids.has(jobId)) return;
  ids.add(jobId);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids]));
  } catch { /* storage unavailable — badge just won't stay dismissed across reloads */ }
}
