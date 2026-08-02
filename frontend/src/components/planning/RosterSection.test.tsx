import { fireEvent, render, screen } from "@testing-library/react";
import { RosterSection } from "./RosterSection";

describe("RosterSection", () => {
  it("passes assignment actions to AssignmentRow without replacing the row", () => {
    const onAction = vi.fn();
    render(
      <RosterSection
        kind="reserve"
        assignments={[{ id: "a1", soldierName: "Ada", status: "Confirmed", isDraft: true }]}
        assignmentActionRenderer={() => <button type="button" onClick={onAction}>Remove</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "רזרבה" })).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("טיוטה")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});