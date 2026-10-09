import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LevelTypeDTO, listLevelTypes } from "../api/levelTypes";
import { queryKeys } from "../queryKeys";

/** Level types change only through the hierarchy editor, which calls `refresh`. */
export const LEVEL_TYPES_STALE_TIME_MS = 300_000;

const NO_LEVEL_TYPES: LevelTypeDTO[] = [];

/**
 * The hierarchy level types, shared through the query cache so every consumer on
 * a page (Home renders several) reads one `GET /api/hierarchy/level-types`.
 */
export function useLevelTypes() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.levelTypes(),
    queryFn: listLevelTypes,
    staleTime: LEVEL_TYPES_STALE_TIME_MS,
  });

  // Refetches now (after create/delete/reorder) and updates every consumer.
  // Rejects on failure so callers can surface it.
  const refresh = useCallback(async () => {
    await queryClient.fetchQuery({ queryKey: queryKeys.levelTypes(), queryFn: listLevelTypes, staleTime: 0 });
  }, [queryClient]);

  return { levelTypes: query.data ?? NO_LEVEL_TYPES, loading: query.isPending, refresh };
}
