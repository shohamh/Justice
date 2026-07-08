import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ImportRowFieldsModal from "./ImportRowFieldsModal";

vi.mock("./SubHierarchySelector", () => ({
  default: ({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) => (
    <button onClick={() => onChange([...value, "node-x"])}>toggle-node</button>
  ),
}));

describe("ImportRowFieldsModal", () => {
  it("renders the duty-type multi-select and reports changes", () => {
    const onChange = vi.fn();
    render(
      <ImportRowFieldsModal
        onClose={() => {}}
        dutyTypeMultiSelect={{
          label: "חל על סוגי תורנות",
          options: [{ id: "dt-1", name: "שמירה" }, { id: "dt-2", name: "ליווי" }],
          value: ["dt-1"],
          onChange,
        }}
      />,
    );

    expect(screen.getByText("שמירה")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("ליווי"));
    expect(onChange).toHaveBeenCalledWith(["dt-1", "dt-2"]);
  });

  it("renders eligible units via SubHierarchySelector when provided", () => {
    const onChange = vi.fn();
    render(
      <ImportRowFieldsModal
        onClose={() => {}}
        eligibleUnits={{ value: ["node-1"], onChange }}
      />,
    );
    fireEvent.click(screen.getByText("toggle-node"));
    expect(onChange).toHaveBeenCalledWith(["node-1", "node-x"]);
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<ImportRowFieldsModal onClose={onClose} />);
    fireEvent.click(screen.getByText("✕"));
    expect(onClose).toHaveBeenCalled();
  });
});
