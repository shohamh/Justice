// Wrappers for the soldier-facing "all my requests" endpoints that back
// MyRequestsPage's existing-requests tab and its unseen-decision badge.
import { api } from "./client";

export interface MyHierarchyTransfer {
  id: string;
  status: string;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  from_node: { id: string; name: string } | null;
  to_node: { id: string; name: string } | null;
}

export async function listMyHierarchyTransfers(): Promise<MyHierarchyTransfer[]> {
  return (await api.get<MyHierarchyTransfer[]>("/me/hierarchy-transfers")).data;
}

export interface MyEnrollmentRequest {
  id: string;
  status: string;
  requested_node_id: string;
  requested_node_name: string;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export async function getMyEnrollment(): Promise<{ request: MyEnrollmentRequest | null }> {
  return (await api.get<{ request: MyEnrollmentRequest | null }>("/me/enrollment")).data;
}

export interface MyRangeExcusalRequest {
  id: string;
  status: "pending" | "approved" | "rejected";
  reason: string;
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
  range_date: string;
  range_type: string;
  range_location_name: string | null;
}

export async function listMyRangeExcusalRequests(): Promise<MyRangeExcusalRequest[]> {
  return (await api.get<MyRangeExcusalRequest[]>("/me/range-excusal-requests")).data;
}

/** Number of the soldier's requests whose status changed to a DECISION since
 * the last time they opened the existing-requests tab (see markRequestsSeen). */
export async function getRequestsUnseenCount(): Promise<{ count: number }> {
  return (await api.get<{ count: number }>("/me/requests/unseen-count")).data;
}

export async function markRequestsSeen(): Promise<void> {
  await api.post("/me/requests/mark-seen");
}
