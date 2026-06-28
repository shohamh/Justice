import { createContext, useCallback, useContext, useState } from "react";
import { markJobSeen as apiMarkJobSeen, markAllJobsSeen as apiMarkAllJobsSeen, JobSummaryOut } from "../api/algorithm";

interface AlgorithmSeenContextValue {
  seenIds: ReadonlySet<string>;
  /** Merge server-side seen flags into local state after a jobs list fetch. Never removes. */
  seedSeenIds: (items: Pick<JobSummaryOut, "id" | "seen">[]) => void;
  /** Mark a single job seen — calls backend and updates local state immediately. */
  markJobSeen: (jobId: string) => Promise<void>;
  /** Mark all provided job IDs as seen — calls backend and updates local state. */
  markAllSeen: (allJobIds: string[]) => Promise<void>;
}

const AlgorithmSeenContext = createContext<AlgorithmSeenContextValue | null>(null);

export function AlgorithmSeenProvider({ children }: { children: React.ReactNode }) {
  const [seenIds, setSeenIds] = useState<ReadonlySet<string>>(new Set());

  const seedSeenIds = useCallback((items: Pick<JobSummaryOut, "id" | "seen">[]) => {
    const newIds = items.filter((i) => i.seen).map((i) => i.id);
    if (newIds.length === 0) return;
    setSeenIds((prev) => {
      const merged = new Set(prev);
      for (const id of newIds) merged.add(id);
      return merged;
    });
  }, []);

  const markJobSeen = useCallback(async (jobId: string) => {
    await apiMarkJobSeen(jobId);
    setSeenIds((prev) => {
      if (prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.add(jobId);
      return next;
    });
  }, []);

  const markAllSeen = useCallback(async (allJobIds: string[]) => {
    await apiMarkAllJobsSeen();
    setSeenIds((prev) => {
      const next = new Set(prev);
      for (const id of allJobIds) next.add(id);
      return next;
    });
  }, []);

  return (
    <AlgorithmSeenContext.Provider value={{ seenIds, seedSeenIds, markJobSeen, markAllSeen }}>
      {children}
    </AlgorithmSeenContext.Provider>
  );
}

export function useSeenJobs(): AlgorithmSeenContextValue {
  const ctx = useContext(AlgorithmSeenContext);
  if (!ctx) throw new Error("useSeenJobs must be used inside AlgorithmSeenProvider");
  return ctx;
}
