import type { QueryClient } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";

/**
 * Marks every cached data family stale that `POST /import/sessions/{id}/confirm`
 * can write to (see `confirm_session` in backend/app/services/import_sessions.py):
 * soldiers (and their rank/telegram/profile fields), hierarchy nodes, duty types,
 * duty locations, shift templates, shifts and assignments, exemption types,
 * soldier exemptions/exemption requests, personal constraints, field updates,
 * enrollment requests, swap requests, range locations/events/assignments/
 * qualifications/excusals, system settings, bug reports and rank-advancement
 * intervals. Derived reads (scoring, potential, command dashboard, nav badge
 * counts) follow from those writes. Level types, algorithm jobs and
 * notifications are not written by the import and are left alone.
 *
 * Fire-and-forget: inactive queries are only marked stale, active ones refetch in
 * the background; the caller does not wait for that.
 */
export function invalidateImportedData(queryClient: QueryClient): void {
  const families: readonly (readonly unknown[])[] = [
    queryKeys.soldiersAll(),
    queryKeys.soldierRangeStatusAll(),
    queryKeys.hierarchyAll(),
    queryKeys.dutyTypes(),
    queryKeys.dutyLocations(),
    queryKeys.shiftTemplates(),
    queryKeys.shiftsAll(),
    queryKeys.assignmentsAll(),
    queryKeys.effectiveDutiesAll(),
    queryKeys.exemptionTypes(),
    queryKeys.exemptionsAll(),
    queryKeys.exemptionRequestsAll(),
    queryKeys.constraintsAll(),
    queryKeys.enrollmentAll(),
    queryKeys.swapsAll(),
    queryKeys.requestsAll(),
    queryKeys.ranges(),
    queryKeys.rangeLocations(),
    queryKeys.systemSettings(),
    queryKeys.bugReportsAll(),
    queryKeys.rankAdvancementAll(),
    queryKeys.scoringAll(),
    queryKeys.potentialAll(),
    queryKeys.commandDashboardAll(),
    queryKeys.navCountsAll(),
  ];
  for (const queryKey of families) {
    void queryClient.invalidateQueries({ queryKey });
  }
}
