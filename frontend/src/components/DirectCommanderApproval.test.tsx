import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import "../i18n";
import DirectCommanderApproval from "./DirectCommanderApproval";

vi.mock("./SoldierLink", () => ({ default: ({ name }: { name: string }) => <span>{name}</span> }));

describe("DirectCommanderApproval empty state", () => {
  test("shows the commander-flavored text when no commander chain exists", () => {
    render(<DirectCommanderApproval approvals={[]} approverKind="commander" />);
    expect(screen.getByText("לא נדרש אישור מפקד")).toBeInTheDocument();
  });

  test("shows a distinct duty-manager-flavored text when no duty manager is scoped", () => {
    render(<DirectCommanderApproval approvals={[]} approverKind="duty_manager" />);
    expect(screen.getByText("אין אחראי תורנויות משויך למסגרת")).toBeInTheDocument();
    expect(screen.queryByText("לא נדרש אישור מפקד")).not.toBeInTheDocument();
  });

  test("defaults to the commander-flavored text when approverKind is omitted", () => {
    render(<DirectCommanderApproval approvals={[]} />);
    expect(screen.getByText("לא נדרש אישור מפקד")).toBeInTheDocument();
  });
});

describe("DirectCommanderApproval decisions", () => {
  test("shows the approving higher commander as the approver and exposes its approval time", () => {
    render(
      <DirectCommanderApproval
        approvals={[
          { commander_id: "near", commander_name: "המפקד הישיר", approved: false },
          {
            commander_id: "senior",
            commander_name: "המפקד הבכיר",
            approved: true,
            approved_by_name: "המפקד הבכיר",
            approved_at: "2026-08-28T17:31:00Z",
            decision_note: "אושר לאחר בדיקה",
          },
        ]}
      />,
    );

    expect(screen.getByText("המפקד הבכיר")).toBeInTheDocument();
    expect(screen.queryByText("המפקד הישיר")).not.toBeInTheDocument();
    const check = screen.getByTestId("approval-checkmark");
    expect(check).toHaveTextContent("✓");
    expect(check).toHaveAttribute("title", expect.stringContaining("המפקד הבכיר"));
    expect(check).toHaveAttribute("title", expect.stringContaining("2026"));
    fireEvent.click(check);
    expect(screen.getByTestId("approval-decision-details")).toHaveClass("max-w-[calc(100vw-1rem)]", "whitespace-normal", "break-words");
    expect(screen.getByTestId("approval-decision-details")).toHaveTextContent("אושר לאחר בדיקה");
  });

  test("opens rejection details when the x is tapped", () => {
    render(<DirectCommanderApproval approvals={[{
      commander_id: "near", commander_name: "המפקד הישיר", approved: false,
      rejected: true, rejected_by_name: "מפקד דוחה", rejected_at: "2026-08-28T18:00:00Z",
      decision_note: "חסר אישור רפואי",
    }]} />);

    fireEvent.click(screen.getByTestId("approval-rejection"));
    expect(screen.getByTestId("approval-decision-details")).toHaveTextContent("חסר אישור רפואי");
  });
});
