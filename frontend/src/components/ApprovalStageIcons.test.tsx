import { render, screen } from "@testing-library/react";
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
        }}
      />,
    );

    const check = screen.getByTestId("commander-approval-checkmark");
    expect(check).toHaveAttribute("title", expect.stringContaining("מפקד בכיר"));
    expect(check).toHaveAttribute("title", expect.stringContaining("2026"));
  });
});
