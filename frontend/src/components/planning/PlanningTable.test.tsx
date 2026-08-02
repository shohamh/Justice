import { fireEvent, render, screen } from "@testing-library/react";
import { PlanningTable } from "./PlanningTable";

type Row = { id: string; name: string };

const columns = [
  { key: "name", label: "Name", render: (row: Row) => row.name },
];

describe("PlanningTable", () => {
  it("renders loading, error, and empty states", () => {
    const { rerender } = render(<PlanningTable<Row> columns={columns} rows={[]} getRowId={row => row.id} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");

    rerender(<PlanningTable<Row> columns={columns} rows={[]} getRowId={row => row.id} error="Could not load" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load");

    rerender(<PlanningTable<Row> columns={columns} rows={[]} getRowId={row => row.id} emptyMessage="Nothing here" />);
    expect(screen.getByRole("status")).toHaveTextContent("Nothing here");
  });

  it("renders deterministic headers and row actions", () => {
    render(
      <PlanningTable<Row>
        columns={columns}
        rows={[{ id: "r1", name: "Alpha" }]}
        getRowId={row => row.id}
        rowActions={row => <button type="button">Edit {row.name}</button>}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit Alpha" })).toBeInTheDocument();
  });

  it("opens rows without treating an action click as a row click", () => {
    const onRowClick = vi.fn();
    render(
      <PlanningTable<Row>
        columns={columns}
        rows={[{ id: "r1", name: "Alpha" }]}
        getRowId={row => row.id}
        onRowClick={onRowClick}
        rowActions={() => <button type="button">Edit</button>}
      />,
    );
    fireEvent.click(screen.getByText("Alpha"));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onRowClick).toHaveBeenCalledTimes(1);
  });
});
