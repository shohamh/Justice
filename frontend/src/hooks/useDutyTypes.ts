import { useQuery } from "@tanstack/react-query";
import { listDutyTypes } from "../api/dutyConfig";
import { queryKeys } from "../queryKeys";

/** Duty types change only on the duty-config page, which invalidates this key. */
export const DUTY_TYPES_STALE_TIME_MS = 300_000;

/**
 * `GET /api/duty-config/duty-types` through the shared `queryKeys.dutyTypes()`
 * cache entry, so components on one page (Home and its calendar) share a request.
 */
export function useDutyTypes() {
  return useQuery({
    queryKey: queryKeys.dutyTypes(),
    queryFn: listDutyTypes,
    staleTime: DUTY_TYPES_STALE_TIME_MS,
  });
}
