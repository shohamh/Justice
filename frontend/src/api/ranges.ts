import { api } from "./client";
export type RangeType = "laser" | "live" | "alal";
export type RangeEventStatus = "planned" | "completed" | "cancelled";
export type RangeAttendanceStatus = "pending" | "present" | "no_show";
export interface RangeAssignment { id:string; soldier_id:string; is_reserve:boolean; is_draft:boolean; attendance_status:RangeAttendanceStatus; note:string|null; assignment_reason_code:string|null; assignment_reason_text:string|null; }
export interface RangeEvent { id:string; hierarchy_node_id:string; range_type:RangeType; date:string; location:string; required_count:number; reserve_count:number; status:RangeEventStatus; assignments:RangeAssignment[]; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; cancellation_reason?:string|null; primary_filled?:number; reserve_filled?:number; assigned_to_me?:boolean; can_edit_attendance?:boolean; }
export interface CreateRangeEventBody { hierarchy_node_id:string; range_type:RangeType; date:string; location:string; required_count:number; reserve_count?:number; start_time?:string|null; end_time?:string|null; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; }
export interface UpdateRangeEventBody { hierarchy_node_id?:string; range_type?:RangeType; date?:string; start_time?:string|null; end_time?:string|null; location?:string; required_count?:number; reserve_count?:number; arrival_instructions?:string|null; contact_name?:string|null; contact_phone?:string|null; notes?:string|null; force_schedule_change?:boolean; cancel?:boolean; cancellation_reason?:string; }
export function getRanges(nodeId:string,dateFrom?:string,dateTo?:string):Promise<RangeEvent[]>{const params=new URLSearchParams({node_id:nodeId});if(dateFrom)params.set("date_from",dateFrom);if(dateTo)params.set("date_to",dateTo);return api.get(`/ranges?${params.toString()}`).then(r=>r.data);}
export function getRangeEvent(id:string):Promise<RangeEvent>{return api.get(`/ranges/${id}`).then(r=>r.data);}
export function createRangeEvent(body:CreateRangeEventBody):Promise<RangeEvent>{return api.post("/ranges",body).then(r=>r.data);}
export function updateRangeEvent(id:string,body:UpdateRangeEventBody):Promise<RangeEvent>{return api.patch(`/ranges/${id}`,body).then(r=>r.data);}
export function deleteRangeEvent(id:string):Promise<void>{return api.delete(`/ranges/${id}`).then(()=>undefined);}
export function cancelRangeEvent(id:string,reason:string):Promise<RangeEvent>{return updateRangeEvent(id,{cancel:true,cancellation_reason:reason});}
export function addRangeAssignment(eventId:string,soldierId:string,isReserve:boolean):Promise<RangeAssignment>{return api.post(`/ranges/${eventId}/assignments`,{soldier_id:soldierId,is_reserve:isReserve}).then(r=>r.data);}
export function removeRangeAssignment(eventId:string,assignmentId:string):Promise<void>{return api.delete(`/ranges/${eventId}/assignments/${assignmentId}`).then(()=>undefined);}
export function updateRangeAssignmentReason(eventId:string,assignmentId:string,assignment_reason_code:string,assignment_reason_text:string|null):Promise<RangeAssignment>{return api.patch(`/ranges/${eventId}/assignments/${assignmentId}/reason`,{assignment_reason_code,assignment_reason_text}).then(r=>r.data);}
export function markRangeAttendance(eventId:string,assignmentId:string,status:RangeAttendanceStatus,note?:string):Promise<RangeAssignment>{return api.patch(`/ranges/${eventId}/assignments/${assignmentId}/attendance`,{status,note}).then(r=>r.data);}
export interface AutoAssignResult { created:RangeAssignment[]; shortfall:number; }
export function autoAssignRange(eventId:string):Promise<AutoAssignResult>{return api.post(`/ranges/${eventId}/auto-assign`).then(r=>r.data);}
export function confirmDraftAssignment(eventId:string,assignmentId:string):Promise<RangeAssignment>{return api.post(`/ranges/${eventId}/assignments/${assignmentId}/confirm`).then(r=>r.data);}
export function confirmAllDrafts(eventId:string):Promise<RangeAssignment[]>{return api.post(`/ranges/${eventId}/assignments/confirm-all`).then(r=>r.data);}
export interface RangeExcusalRequest { id:string; range_assignment_id:string; requested_by:string|null; reason:string; status:"pending"|"approved"|"rejected"; decided_by:string|null; decided_at:string|null; decision_note:string|null; promoted_assignment_id:string|null; }
export function excuseRangeAssignment(eventId:string,assignmentId:string,reason:string):Promise<RangeExcusalRequest>{return api.post(`/ranges/${eventId}/assignments/${assignmentId}/excuse`,{reason}).then(r=>r.data);}
export function getRangeExcusalRequests(eventId:string):Promise<RangeExcusalRequest[]>{return api.get(`/ranges/${eventId}/excusal-requests`).then(r=>r.data);}
export function decideRangeExcusal(eventId:string,requestId:string,approve:boolean,note?:string):Promise<RangeExcusalRequest>{return api.post(`/ranges/${eventId}/excusal-requests/${requestId}/decide`,{approve,note}).then(r=>r.data);}
