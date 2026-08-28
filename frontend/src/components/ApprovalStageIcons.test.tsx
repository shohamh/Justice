import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../i18n";
import ApprovalStageIcons from "./ApprovalStageIcons";

describe("ApprovalStageIcons", () => {
  it("shows who approved and when on the commander checkmark", () => {
    render(
      <ApprovalStageIcons
        request={{
          status: "pending_duty_manager",
          commander_approved_by: { soldier_id: "cmd-1", name: "מפקד בכיר" },
          commander_approved_at: "2026-08-28T17:31:00Z",
          commander_approval_note: "נבדק ואושר",
        }}
      />,
    );

    const check = screen.getByTestId("commander-approval-checkmark");
    expect(check).toHaveAttribute("title", expect.stringContaining("מפקד בכיר"));
    expect(check).toHaveAttribute("title", expect.stringContaining("2026"));
    fireEvent.click(check);
    expect(screen.getByTestId("approval-decision-details")).toHaveClass("max-w-[calc(100vw-1rem)]", "whitespace-normal", "break-words");
    expect(screen.getByTestId("approval-decision-details")).toHaveTextContent("נבדק ואושר");
  });
});
