export interface InterruptedInfo {
  reason: string;
}

// A job interrupted by infrastructure (server restart mid-solve, or the
// watchdog timeout with nothing left to salvage) is not a scheduling failure —
// showing the generic "couldn't find a solution" panel for it is misleading.
// Distinguishes that case from a real INFEASIBLE/solver failure so the UI can
// show an accurate message instead.
export function parseInterrupted(errorMessage: string | null): InterruptedInfo | null {
  if (!errorMessage) return null;
  try {
    const data = JSON.parse(errorMessage) as { status?: string; reason?: string };
    if (data.status === "INTERRUPTED" && typeof data.reason === "string") {
      return { reason: data.reason };
    }
    return null;
  } catch {
    // Legacy bare-string error messages predate the structured INTERRUPTED format.
    if (errorMessage === "orphaned_on_restart") return { reason: "server_restarted" };
    if (errorMessage === "timed_out") return { reason: "timed_out" };
    return null;
  }
}
