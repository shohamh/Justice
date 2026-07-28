import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import "../i18n";
import DirectCommanderApproval from "./DirectCommanderApproval";

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
