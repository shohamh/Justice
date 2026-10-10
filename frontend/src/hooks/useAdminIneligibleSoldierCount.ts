import { useQuery } from "@tanstack/react-query";
import { getIneligibleSoldierCount } from "../api/ineligibleSoldiers";
import { queryKeys } from "../queryKeys";

interface Options {
  actorId: string | null;
  authorizationScope: string | null;
  enabled: boolean;
}

/** Share the identical all-organization count between Home and navigation for admins. */
export function useAdminIneligibleSoldierCount({ actorId, authorizationScope, enabled }: Options) {
  return useQuery({
    queryKey: queryKeys.adminIneligibleSoldierCount(actorId, authorizationScope),
    queryFn: () => getIneligibleSoldierCount("commander"),
    enabled: enabled && actorId !== null && authorizationScope !== null,
    staleTime: 60_000,
    retry: false,
  });
}
