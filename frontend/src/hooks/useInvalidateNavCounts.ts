import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";

/**
 * Returns a stable callback that marks every nav badge count (approvals,
 * incoming swaps, hakpaza) stale. Call it after a decision made outside the
 * pages that already invalidate, so the badges don't wait out the global
 * staleTime. Needs a QueryClientProvider ancestor.
 */
export function useInvalidateNavCounts(): () => void {
  const queryClient = useQueryClient();
  return useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.navCountsAll() });
  }, [queryClient]);
}
