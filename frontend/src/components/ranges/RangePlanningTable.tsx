import type { ReactNode } from "react";
import { PlanningTable, PlanningColumn } from "../planning";
import { RangeEvent } from "../../api/ranges";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../../utils/rangeLabels";
interface Props { rows: RangeEvent[]; onRowClick:(event:RangeEvent)=>void; rowActions:(event:RangeEvent)=>ReactNode; filters?:ReactNode; sort?:ReactNode; }
function filled(event: RangeEvent, reserve: boolean) { const reported = reserve ? event.reserve_filled : event.primary_filled; return reported ?? event.assignments.filter(a => a.is_reserve === reserve && !a.is_draft).length; }
export default function RangePlanningTable({rows,onRowClick,rowActions,filters,sort}:Props){ const columns:PlanningColumn<RangeEvent>[]=[{key:"date",label:"תאריך",sortValue:e=>e.date,render:e=><span dir="ltr">{e.date}</span>},{key:"type",label:"סוג",render:e=>RANGE_TYPE_LABELS[e.range_type] ?? e.range_type},{key:"location",label:"מיקום",render:e=><button type="button" aria-label={e.location} onClick={()=>onRowClick(e)} className="text-blue-600 dark:text-blue-400 underline hover:text-blue-800 dark:hover:text-blue-300 text-right">{e.location}</button>},{key:"primary",label:"ראשיים",render:e=>`${filled(e, false)}/${e.required_count}`},{key:"reserve",label:"רזרבה",render:e=>`${filled(e, true)}/${e.reserve_count}`},{key:"status",label:"סטטוס",render:e=>RANGE_EVENT_STATUS_LABELS[e.status] ?? e.status}]; return <PlanningTable columns={columns} rows={rows} getRowId={e=>e.id} getRowLabel={e=>e.location} onRowClick={onRowClick} rowActions={rowActions} actionsLabel="פעולות" filters={filters} sort={sort} filterPlaceholder="סנן..." emptyMessage="אין מטווחים" />; }





