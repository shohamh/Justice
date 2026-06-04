import { render, screen, fireEvent } from "@testing-library/react";
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
