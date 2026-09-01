import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import PendingApprovalsWidget from "./PendingApprovalsWidget";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "command_dashboard.pending_approvals_scope_command": "אישורים ממתינים בפיקוד",
        "home.pending_approvals_scope_personal": "בקשות אישיות ממתינות",
        "command_dashboard.pending_enrollments": "בקשות הצטרפות",
        "command_dashboard.pending_swaps": "בקשות החלפה",
        "command_dashboard.pending_constraints": "בקשות אישי",
        "command_dashboard.pending_exemptions": "בקשות פטור",
        "command_dashboard.pending_field_updates": "עדכוני פרופיל",
        "command_dashboard.pending_transfers": "בקשות העברה",
      }[key] ?? key),
  }),
}));

const baseProps = {
  pendingEnrollments: [],
  pendingSwaps: [],
  pendingConstraints: 1,
  pendingExemptions: 0,
  pendingFieldUpdates: 0,
  pendingTransfers: [],
};

describe("PendingApprovalsWidget", () => {
  it("labels command-scope approvals explicitly without changing the command approvals link", () => {
    render(
      <MemoryRouter>
        <PendingApprovalsWidget {...baseProps} scope="command" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "אישורים ממתינים בפיקוד" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /בקשות אישי/ })).toHaveAttribute("href", "/approvals?tab=constraints");
  });

  it("can render personal wording when the parent explicitly passes personal scope", () => {
    render(
      <MemoryRouter>
        <PendingApprovalsWidget {...baseProps} scope="personal" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "בקשות אישיות ממתינות" })).toBeInTheDocument();
  });
});
