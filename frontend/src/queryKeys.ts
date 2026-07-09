// frontend/src/queryKeys.ts
//
// Central registry of react-query cache keys. Add a new entry here whenever a
// page starts fetching a new piece of server data — this keeps invalidation
// call sites (in mutations) and read sites (in useQuery calls) referring to
// the exact same key shape instead of hand-typed arrays that can drift apart.

export const queryKeys = {
  effectiveDuties: (soldierId: string, params?: Record<string, unknown>) =>
    ["effectiveDuties", soldierId, params ?? {}] as const,
  dutyTypes: () => ["dutyTypes"] as const,
  dutyLocations: () => ["dutyLocations"] as const,
  mySwaps: () => ["swaps", "mine"] as const,
  incomingSwaps: () => ["swaps", "incoming"] as const,
  pendingSwaps: () => ["swaps", "pending"] as const,
  swapBoard: (filters?: Record<string, unknown>) => ["swaps", "board", filters ?? {}] as const,
  pendingEnrollments: () => ["enrollment", "pending"] as const,
  systemSettings: () => ["systemSettings"] as const,
  transparency: () => ["scoring", "transparency"] as const,
  breakdown: (soldierId: string) => ["scoring", "breakdown", soldierId] as const,
  reserveStats: () => ["soldiers", "reserveStats"] as const,
  pendingConstraintsCount: () => ["constraints", "pendingCount"] as const,
  pendingExemptionsCount: () => ["exemptions", "pendingCount"] as const,
  pendingFieldUpdatesCount: () => ["soldiers", "pendingFieldUpdatesCount"] as const,
  myConstraints: () => ["constraints", "mine"] as const,
  myExemptionRequests: () => ["exemptionRequests", "mine"] as const,
  pendingConstraints: () => ["constraints", "pending"] as const,
  pendingExemptionRequests: () => ["exemptionRequests", "pending"] as const,
  pendingFieldUpdates: () => ["soldiers", "pendingFieldUpdates"] as const,
  hierarchyTree: () => ["hierarchy", "tree"] as const,
  publicExemptionTypes: () => ["exemptionTypes", "public"] as const,
  swapConfig: () => ["swaps", "config"] as const,
  swapCoverEligibility: (ids: string[]) => ["swaps", "coverEligibility", ids] as const,
  exemptionTypes: () => ["exemptionTypes"] as const,
  exemptionDutyTypeMap: () => ["exemptionTypes", "dutyTypeMap"] as const,
  myExemptions: (soldierId: string) => ["exemptions", "mine", soldierId] as const,
  fieldUpdates: (soldierId: string) => ["soldiers", "fieldUpdates", soldierId] as const,
  ranks: () => ["soldiers", "ranks"] as const,
  telegramStatus: () => ["telegram", "status"] as const,
  notificationPreferences: () => ["notifications", "preferences"] as const,
  commanderScopes: () => ["notifications", "commanderScopes"] as const,
  hierarchyTreeVisible: () => ["hierarchy", "tree", "visible"] as const,
  notificationsList: () => ["notifications", "list"] as const,
  notifications: (filter: string, offset: number) => ["notifications", "list", filter, offset] as const,
};
