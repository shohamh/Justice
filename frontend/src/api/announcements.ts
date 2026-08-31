import { api as client } from "./client";
import { optionalArrayResponse, requiredArrayResponse, requiredObjectResponse, requiredNumberField } from "./responseGuards";

export interface ScopeNode {
  id: string;
  name: string;
  level: string;
  parent_id: string | null;
}

export interface AnnounceResult {
  id: string;
  sent: number;
}

export interface AnnouncementDTO {
  id: string;
  title: string;
  body: string | null;
  type: string;
  hierarchy_node_ids: string[] | null;
  recipient_count: number;
  read_count: number;
  created_at: string;
}

export interface PaginatedAnnouncements {
  items: AnnouncementDTO[];
  total: number;
}

export interface AnnouncementRecipient {
  soldier_id: string;
  full_name: string;
  is_read: boolean;
  read_at: string | null;
}

export interface PaginatedAnnouncementRecipients {
  items: AnnouncementRecipient[];
  total: number;
}

export function getAnnounceScope(): Promise<ScopeNode[]> {
  return client
    .get<unknown>("/notifications/announce/scope")
    .then((r) => optionalArrayResponse<ScopeNode>(r.data));
}

export function postAnnouncement(payload: {
  title: string;
  body?: string;
  hierarchy_node_ids?: string[];
}): Promise<AnnounceResult> {
  return client.post("/notifications/announce", payload).then((r) => r.data);
}

export function listAnnouncements(params?: { offset?: number; limit?: number }): Promise<PaginatedAnnouncements> {
  return client.get<unknown>("/notifications/announcements", { params }).then((r) => {
    const data = requiredObjectResponse(r.data, "Invalid announcements response");
    return {
      ...data,
      items: requiredArrayResponse<AnnouncementDTO>(data.items, "Invalid announcements response"),
      total: requiredNumberField(data.total, "Invalid announcements response"),
    } as PaginatedAnnouncements;
  });
}

export function getAnnouncementRecipients(
  id: string,
  params?: { offset?: number; limit?: number }
): Promise<PaginatedAnnouncementRecipients> {
  return client.get<unknown>(`/notifications/announcements/${id}/recipients`, { params }).then((r) => {
    const data = requiredObjectResponse(r.data, "Invalid announcement recipients response");
    return {
      ...data,
      items: requiredArrayResponse<AnnouncementRecipient>(data.items, "Invalid announcement recipients response"),
      total: requiredNumberField(data.total, "Invalid announcement recipients response"),
    } as PaginatedAnnouncementRecipients;
  });
}
