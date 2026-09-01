import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DutyPotentialPanel from "./DutyPotentialPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "command_dashboard.potential_scope_command": "פוטנציאל תורנויות בפיקוד",
        "home.potential_scope_personal": "פוטנציאל אישי",
        "command_dashboard.no_potential_data": "אין נתוני פוטנציאל",
      }[key] ?? key),
  }),
}));

describe("DutyPotentialPanel", () => {
  it("labels command-scope potential explicitly", () => {
    render(<DutyPotentialPanel scope="command" data={[{ label: "שמירה", count: 3, unit_total: 5 }]} />);

    expect(screen.getByText("פוטנציאל תורנויות בפיקוד")).toBeInTheDocument();
    expect(screen.getByTestId("duty-potential")).toHaveTextContent("שמירה");
  });

  it("keeps personal wording only when explicitly passed", () => {
    render(<DutyPotentialPanel scope="personal" data={[]} />);

    expect(screen.getByText("פוטנציאל אישי")).toBeInTheDocument();
    expect(screen.getByText("אין נתוני פוטנציאל")).toBeInTheDocument();
  });
});
