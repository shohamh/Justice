import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ConstraintWarningIcon from "./ConstraintWarningIcon";

const warning = {
  reason: "בקשה אישית",
  start_date: "2026-09-01",
  end_date: "2026-09-05",
  decided_by: "רב\"ט כהן",
  decided_at: "2026-08-20T10:00:00Z",
};

describe("ConstraintWarningIcon", () => {
  it("shows a popover with reason and approver on click", () => {
    render(<ConstraintWarningIcon warning={warning} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("בקשה אישית")).toBeInTheDocument();
    expect(screen.getByText(/רב"ט כהן/)).toBeInTheDocument();
  });
});
