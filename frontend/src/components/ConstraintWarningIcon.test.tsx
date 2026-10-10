import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ConstraintWarningIcon from "./ConstraintWarningIcon";

// Instants straddling local/UTC midnight: 2026-10-09T21:30Z is already 2026-10-10
// in Asia/Jerusalem (UTC+3) but still 2026-10-09 in UTC.
// Expected days are hard-coded for the test timezone pinned to Asia/Jerusalem in vite.config.ts.
const DECIDED_AT_CASES: [string, string][] = [
  ["2026-10-09T21:30:00Z", "10.10.2026"],
  ["2026-10-09T12:00:00Z", "09.10.2026"],
  ["2026-10-10T00:00:00Z", "10.10.2026"],
];

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

  it.each(DECIDED_AT_CASES)("shows the decision date as the LOCAL calendar day (decided_at=%s -> %s)", (decidedAt, expected) => {
    render(<ConstraintWarningIcon warning={{ ...warning, decided_at: decidedAt }} />);
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText((text) => text.endsWith(` · ${expected}`))).toBeInTheDocument();
  });
});
