import { render, screen, fireEvent } from "@testing-library/react";
import { useState } from "react";
import { test, expect, vi } from "vitest";
import { DataTable, type ColDef } from "./DataTable";

interface Row { name: string; score: number; }

const cols: ColDef<Row>[] = [
  {
    id: "name",
    header: "Name",
    cell: (r) => r.name,
    sortValue: (r) => r.name,
    filterValue: (r) => r.name,
  },
  {
    id: "score",
    header: "Score",
    cell: (r) => String(r.score),
    sortValue: (r) => r.score,
  },
];

const filterableCols: ColDef<Row>[] = [
  {
    id: "name",
    header: "Name",
    cell: (r) => r.name,
    sortValue: (r) => r.name,
    filterValue: (r) => r.name,
    columnFilter: true,
  },
  {
    id: "score",
    header: "Score",
    cell: (r) => String(r.score),
    sortValue: (r) => r.score,
  },
];

const data: Row[] = [
  { name: "Alice", score: 3 },
  { name: "Bob", score: 1 },
  { name: "Charlie", score: 2 },
];

test("renders all rows", () => {
  render(<DataTable columns={cols} data={data} />);
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.getByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("Charlie")).toBeInTheDocument();
});

test("filters rows by global filter text", () => {
  render(<DataTable columns={cols} data={data} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Alice" } });
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.queryByText("Bob")).not.toBeInTheDocument();
  expect(screen.queryByText("Charlie")).not.toBeInTheDocument();
});

test("sorts ascending on header click", () => {
  const { container } = render(<DataTable columns={cols} data={data} />);
  fireEvent.click(screen.getByText("Score"));
  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].textContent).toContain("Bob");   // score 1
  expect(rows[1].textContent).toContain("Charlie"); // score 2
  expect(rows[2].textContent).toContain("Alice");   // score 3
});

test("sorts descending on second header click", () => {
  const { container } = render(<DataTable columns={cols} data={data} />);
  fireEvent.click(screen.getByText("Score"));
  fireEvent.click(screen.getByText("Score"));
  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].textContent).toContain("Alice");  // score 3
});

test("sorts descending on first header click when sortDescFirst is set on the column", () => {
  const descFirstCols: ColDef<Row>[] = [
    cols[0],
    { ...cols[1], sortDescFirst: true },
  ];
  const { container } = render(<DataTable columns={descFirstCols} data={data} />);
  fireEvent.click(screen.getByText("Score"));
  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].textContent).toContain("Alice"); // score 3 (descending first)
  expect(rows[1].textContent).toContain("Charlie"); // score 2
  expect(rows[2].textContent).toContain("Bob"); // score 1
});

test("non-sortable column header does not show arrow", () => {
  render(<DataTable columns={[{ id: "x", header: "NoSort", cell: () => "—" }]} data={[]} />);
  const header = screen.getByText("NoSort");
  expect(header.className).not.toContain("cursor-pointer");
});

test("shows empty message when no rows match filter", () => {
  render(<DataTable columns={cols} data={data} emptyMessage="nothing" />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "zzz" } });
  expect(screen.getByText("nothing")).toBeInTheDocument();
});

test("onVisibleRowsChange fires with full data on initial render", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  expect(spy).toHaveBeenCalledWith(data);
});

test("onVisibleRowsChange fires with filtered rows after search box input", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Alice" } });
  expect(spy).toHaveBeenLastCalledWith([data[0]]);
});

test("onVisibleRowsChange fires with sorted rows after header click", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  fireEvent.click(screen.getByText("Score"));
  expect(spy).toHaveBeenLastCalledWith([data[1], data[2], data[0]]); // Bob(1), Charlie(2), Alice(3)
});

test("onVisibleRowsChange does not fire again when parent re-renders without data/columns changing (no infinite loop)", () => {
  const spy = vi.fn();

  // Wrapper that re-renders DataTable on a state change unrelated to data/columns,
  // simulating what happens when onVisibleRowsChange is wired to setState in a parent.
  function Wrapper() {
    const [, setTick] = useState(0);
    return (
      <div>
        <button onClick={() => setTick((t) => t + 1)}>bump</button>
        <DataTable columns={cols} data={data} onVisibleRowsChange={spy} />
      </div>
    );
  }

  render(<Wrapper />);
  expect(spy).toHaveBeenCalledTimes(1);
  const firstRows = spy.mock.calls[0][0];

  // Force a parent re-render with no actual change to filtering/sorting/data.
  fireEvent.click(screen.getByText("bump"));
  fireEvent.click(screen.getByText("bump"));

  // visibleRows must be referentially stable across re-renders with unchanged
  // row model, so the effect must not fire again (this would infinite-loop if
  // onVisibleRowsChange were wired to setState, per Task 4).
  expect(spy).toHaveBeenCalledTimes(1);
  expect(spy.mock.calls[0][0]).toBe(firstRows);
});

test("column filter trigger shows no numeric badge in the unfiltered default state", () => {
  const { container } = render(<DataTable columns={filterableCols} data={data} />);
  // Distinct values for "name" is 3 (Alice, Bob, Charlie); if the badge were
  // wired to raw selected-count instead of isFiltered, the trigger button
  // would show a "3" badge here even though nothing is actually filtered.
  const trigger = screen.getByText("▼");
  const badge = trigger.parentElement?.querySelector("span.bg-blue-600");
  expect(badge).toBeNull();
  expect(container).toBeTruthy();
});

test("column filter trigger still shows no numeric badge once a filter is applied (dot indicator only)", () => {
  render(<DataTable columns={filterableCols} data={data} />);
  fireEvent.click(screen.getByText("▼"));
  fireEvent.click(screen.getByLabelText("Alice"));
  // DataTable's column filter never showed a numeric count badge, only the
  // "▼●" dot indicator on the trigger itself.
  const trigger = screen.getByText("▼●");
  const badge = trigger.parentElement?.querySelector("span.bg-blue-600");
  expect(badge).toBeNull();
});

test("expandable without expandOnRowClick: clicking a row does not expand it (existing consumers unaffected)", () => {
  const onToggle = vi.fn();
  const { container } = render(
    <DataTable
      columns={cols}
      data={data}
      expandable={{
        isExpanded: () => false,
        onToggle,
        content: () => <div>details</div>,
      }}
    />
  );
  const row = container.querySelectorAll("tbody tr")[0];
  fireEvent.click(row);
  expect(onToggle).not.toHaveBeenCalled();
});

test("expandable with expandOnRowClick: clicking anywhere on the row toggles expansion", () => {
  const onToggle = vi.fn();
  const { container } = render(
    <DataTable
      columns={cols}
      data={data}
      expandable={{
        isExpanded: () => false,
        onToggle,
        content: () => <div>details</div>,
        expandOnRowClick: true,
      }}
    />
  );
  const row = container.querySelectorAll("tbody tr")[0];
  fireEvent.click(row);
  expect(onToggle).toHaveBeenCalledWith(data[0]);
});

test("expandable with expandOnRowClick: the dedicated toggle button still works and does not double-toggle", () => {
  const onToggle = vi.fn();
  render(
    <DataTable
      columns={cols}
      data={data}
      expandable={{
        isExpanded: () => false,
        onToggle,
        content: () => <div>details</div>,
        expandOnRowClick: true,
      }}
    />
  );
  fireEvent.click(screen.getAllByRole("button", { name: "הרחב" })[0]);
  expect(onToggle).toHaveBeenCalledTimes(1);
  expect(onToggle).toHaveBeenCalledWith(data[0]);
});
