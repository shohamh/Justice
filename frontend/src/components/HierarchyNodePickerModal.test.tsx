import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect } from "vitest";
import HierarchyNodePickerModal from "./HierarchyNodePickerModal";
import * as hierarchyApi from "../api/hierarchy";

vi.mock("../api/hierarchy");

function makeTree() {
  return [
    {
      id: "corps-1", level: "corps" as const, name: "אוגדה", parent_id: null,
      commander_id: null, commander_name: null, path_ids: ["corps-1"], duty_managers: [], dm_manageable: false, can_edit: true,
      children: [
        {
          id: "unit-1", level: "unit" as const, name: "יחידה א", parent_id: "corps-1",
          commander_id: null, commander_name: null, path_ids: ["corps-1", "unit-1"], duty_managers: [], dm_manageable: false, can_edit: true,
          children: [],
        },
      ],
    },
  ];
}

describe("HierarchyNodePickerModal", () => {
  it("renders parent/child structure with indentation, expandable nodes", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree());
    const onPicked = vi.fn();
    render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={onPicked} />);

    await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
    // the root is expanded by default; its child should already be visible
    expect(screen.getByText("יחידה א")).toBeInTheDocument();

    const selectButtons = screen.getAllByText("בחר");
    fireEvent.click(selectButtons[1]);
    expect(onPicked).toHaveBeenCalledWith("unit-1", "יחידה א");
  });

  it("still supports search, falling back to a flat filtered list", async () => {
    vi.mocked(hierarchyApi.fetchFullTree).mockResolvedValue(makeTree());
    render(<HierarchyNodePickerModal onClose={vi.fn()} onPicked={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("אוגדה")).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText("חיפוש..."), { target: { value: "יחידה א" } });

    expect(screen.queryByText("אוגדה")).not.toBeInTheDocument();
    expect(screen.getByText("יחידה א")).toBeInTheDocument();
  });
});
