import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AlertsPanel from "./AlertsPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      ({
        "command_dashboard.alerts_scope_command": "התראות בפיקוד",
        "home.alerts_scope_personal": "התראות אישיות",
        "command_dashboard.no_alerts": "אין התראות",
      }[key] ?? key),
  }),
}));

vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

describe("AlertsPanel", () => {
  it("labels command alerts with command scope", () => {
    render(
      <AlertsPanel
        scope="command"
        data={[{ severity: "warning", soldier_id: "s1", soldier_name: "דני", message: "חסר שיבוץ" }]}
      />,
    );

    expect(screen.getByText("התראות בפיקוד")).toBeInTheDocument();
    expect(screen.getByTestId("alerts-panel")).toHaveTextContent("חסר שיבוץ");
  });

  it("keeps personal wording available only when explicitly passed", () => {
    render(<AlertsPanel scope="personal" data={[]} />);

    expect(screen.getByText("התראות אישיות")).toBeInTheDocument();
    expect(screen.getByText("אין התראות")).toBeInTheDocument();
  });
});
