import type { ReactNode } from "react";
import { PlanningTable, PlanningColumn } from "../planning";
import { RangeEvent } from "../../api/ranges";
interface Props { rows: RangeEvent[]; onRowClick:(event:RangeEvent)=>void; rowActions:(event:RangeEvent)=>ReactNode; filters?:ReactNode; sort?:ReactNode; }
export default function RangePlanningTable({rows,onRowClick,rowActions,filters,sort}:Props){ const columns:PlanningColumn<RangeEvent>[]=[{key:"date",label:"תאריך",sortValue:e=>e.date,render:e=><span dir="ltr">{e.date}</span>},{key:"type",label:"סוג",render:e=>e.range_type},{key:"location",label:"מיקום",render:e=><button type="button" onClick={()=>onRowClick(e)} className="text-indigo-600 hover:underline">{e.location}</button>},{key:"primary",label:"ראשיים",render:e=>`${e.assignments.filter(a=>!a.is_reserve).length}/${e.required_count}`},{key:"reserve",label:"רזרבה",render:e=>`${e.assignments.filter(a=>a.is_reserve).length}/${e.reserve_count}`},{key:"status",label:"סטטוס",render:e=>e.status}]; return <PlanningTable columns={columns} rows={rows} getRowId={e=>e.id} getRowLabel={e=>e.location} onRowClick={onRowClick} rowActions={rowActions} filters={filters} sort={sort} />; }





