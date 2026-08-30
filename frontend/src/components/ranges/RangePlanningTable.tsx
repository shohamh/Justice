import { useEffect, useRef } from "react";
import type { MouseEvent, ReactNode } from "react";
import { PlanningTable, PlanningColumn } from "../planning";
import { RangeEvent } from "../../api/ranges";
import { RANGE_TYPE_LABELS, RANGE_EVENT_STATUS_LABELS } from "../../utils/rangeLabels";
import { formatDate } from "../../utils/formatDate";
import SoldierLink from "../SoldierLink";

interface Props {
  rows: RangeEvent[];
  onRowClick: (event: RangeEvent) => void;
  rowActions: (event: RangeEvent) => ReactNode;
  filters?: ReactNode;
  sort?: ReactNode;
  loading?: boolean;
  error?: ReactNode;
  selectedIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
  soldierName?: (id: string) => string;
}

function filled(event: RangeEvent, reserve: boolean) {
  const reported = reserve ? event.reserve_filled : event.primary_filled;
  return reported ?? event.assignments.filter(a => a.is_reserve === reserve && !a.is_draft).length;
}

function SelectAllCheckbox({ rows, selectedIds, onToggle }: {
  rows: RangeEvent[];
  selectedIds: Set<string>;
  onToggle: (select: boolean) => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);
  const selectableRows = rows.filter(row => row.can_manage !== false);
  const selectedCount = selectableRows.filter(row => selectedIds.has(row.id)).length;
  const allSelected = selectableRows.length > 0 && selectedCount === selectableRows.length;

  useEffect(() => {
    if (checkboxRef.current) checkboxRef.current.indeterminate = selectedCount > 0 && !allSelected;
  }, [allSelected, selectedCount]);

  return <input
    ref={checkboxRef}
    type="checkbox"
    data-testid="select-all-ranges"
    aria-label="בחר הכל"
    checked={allSelected}
    disabled={selectableRows.length === 0}
    onChange={() => onToggle(!allSelected)}
    onClick={(event: MouseEvent) => event.stopPropagation()}
  />;
}

function toggleRows(rows: RangeEvent[], selectedIds: Set<string>, onToggle: (id: string) => void, select: boolean) {
  rows.filter(row => row.can_manage !== false).forEach(row => {
    if (select !== selectedIds.has(row.id)) onToggle(row.id);
  });
}

export default function RangePlanningTable({ rows, onRowClick, rowActions, filters, sort, loading, error, selectedIds, onToggleSelect, soldierName }: Props) {
  const columns: PlanningColumn<RangeEvent>[] = [
    ...(onToggleSelect ? [{
      key: "select",
      label: <SelectAllCheckbox
        rows={rows}
        selectedIds={selectedIds ?? new Set()}
        onToggle={select => toggleRows(rows, selectedIds ?? new Set(), onToggleSelect, select)}
      />,
      render: (event: RangeEvent) => <input
        type="checkbox"
        data-testid={`select-range-${event.id}`}
        checked={selectedIds?.has(event.id) ?? false}
        disabled={event.can_manage === false}
        title={event.can_manage === false ? "אין הרשאה לניהול מטווח זה" : undefined}
        onChange={() => onToggleSelect(event.id)}
        onClick={(clickEvent: MouseEvent) => clickEvent.stopPropagation()}
      />,
    } as PlanningColumn<RangeEvent>] : []),
    { key: "date", label: "תאריך", sortValue: event => event.date, render: event => <span>{formatDate(event.date)}</span> },
    { key: "type", label: "סוג", render: event => RANGE_TYPE_LABELS[event.range_type] ?? event.range_type },
    { key: "location", label: "מיקום", render: event => <span>{event.location}</span> },
    { key: "responsible", label: "אחראי", render: event => event.responsible_duty_manager_id
      ? <SoldierLink id={event.responsible_duty_manager_id} name={soldierName ? soldierName(event.responsible_duty_manager_id) : event.responsible_duty_manager_id} />
      : <span className="text-gray-400">—</span> },
    { key: "primary", label: "ראשיים", render: event => `${filled(event, false)}/${event.required_count}` },
    { key: "reserve", label: "רזרבה", render: event => `${filled(event, true)}/${event.reserve_count}` },
    { key: "status", label: "סטטוס", render: event => RANGE_EVENT_STATUS_LABELS[event.status] ?? event.status },
  ];

  return <PlanningTable
    columns={columns}
    rows={rows}
    getRowId={event => event.id}
    getRowLabel={event => event.location}
    onRowClick={onRowClick}
    rowActions={rowActions}
    actionsLabel="פעולות"
    filters={filters}
    sort={sort}
    filterPlaceholder="סנן..."
    emptyMessage="אין מטווחים"
    loading={loading}
    error={error}
  />;
}
