import { render, screen } from "@testing-library/react";
import { RosterSection } from "./RosterSection";

describe("RosterSection", () => {
  it("groups assignments by kind and renders status and draft badges", () => {
    render(<RosterSection kind="reserve" assignments={[{ id: "a1", soldierName: "Ada", status: "Confirmed", isDraft: true }]} />);
    expect(screen.getByRole("heading", { name: "Reserve" })).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });
});
