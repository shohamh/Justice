import { api } from "./client";
import { optionalArrayResponse, requiredObjectResponse } from "./responseGuards";

export interface SoldierRef {
  id: string;
  name: string;
  rank: string | null;
}

export interface ShiftRef {
  shift_id: string;
  duty_type_name: string;
  duty_location_name: string;
  start_date: string;
  end_date: string;
}

export interface FutureAssignmentPreview {
  shift: ShiftRef;
  soldier_demoted: SoldierRef;
  demoted_assignment_id: string;
  c_existing_reserve_assignment_id: string | null;
  c_existing_reserve_soldier: SoldierRef | null;
}

export interface GimelimPreview {
  preview_token: string;
  preview_token_expires_at: string;
  current_shift: ShiftRef;
  soldier_a: SoldierRef;
  primary_assignment_id: string;
  reserve_assignment_id: string;
  reserve_soldier: SoldierRef;
  future_assignment: FutureAssignmentPreview | null;
  warnings: string[];
}

export interface GimelimCommitResult {
  dismissal_id: string;
  call_up_assignment_id: string;
  future_primary_assignment_id: string | null;
  future_demoted_assignment_id: string | null;
  notifications_queued: number;
}

export async function previewGimelim(
  shiftId: string,
  body: { primary_assignment_id: string; rest_days: number; reason?: string; from_date: string }
): Promise<GimelimPreview> {
  const r = await api.post<unknown>(`/shifts/${shiftId}/gimelim/preview`, body);
  const data = requiredObjectResponse(r.data, "Invalid gimelim preview response");
  if (typeof data.preview_token !== "string") {
    throw new Error("Invalid gimelim preview response");
  }
  return {
    ...(data as unknown as GimelimPreview),
    warnings: optionalArrayResponse<string>(data.warnings),
  };
}

export async function commitGimelim(
  shiftId: string,
  previewToken: string
): Promise<GimelimCommitResult> {
  return (await api.post<GimelimCommitResult>(`/shifts/${shiftId}/gimelim/commit`, {
    preview_token: previewToken,
  })).data;
}

export interface GimelimAttachmentResult {
  id: string;
  file_name: string;
  content_type: string;
  created_at: string;
}

export async function uploadGimelimAttachment(
  dismissalId: string,
  file: File
): Promise<GimelimAttachmentResult> {
  const form = new FormData();
  form.append("file", file);
  return (
    await api.post<GimelimAttachmentResult>(
      `/gimelim/${dismissalId}/attachments`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } }
    )
  ).data;
}
