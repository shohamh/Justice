import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CommandDashboardSection from "./CommandDashboardSection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: string | { defaultValue?: string }) =>
      (typeof options === "string" ? options : options?.defaultValue) ??
      {
        "command_dashboard.management_section_title": "ניהול היחידה",
        "command_dashboard.management_section_scope": "פיקוד פלוגה א",
      }[key] ??
      key,
  }),
}));

describe("CommandDashboardSection", () => {
  it("labels command content and applies highlighted treatment", () => {
    render(
      <CommandDashboardSection>
        <span>command content</span>
      </CommandDashboardSection>,
    );

    const region = screen.getByRole("region", { name: "ניהול היחידה" });
    expect(region).toBeInTheDocument();
    expect(region).toHaveAttribute("dir", "rtl");
    expect(region).toHaveClass("border-2", "border-indigo-400", "bg-indigo-50/50");
    expect(screen.getByText("command content")).toBeInTheDocument();
  });

  it("renders an optional scope label and test id", () => {
    render(
      <CommandDashboardSection
        scopeLabel="פיקוד פלוגה א"
        data-testid="command-dashboard-section"
      >
        <span>more command content</span>
      </CommandDashboardSection>,
    );

    expect(screen.getByTestId("command-dashboard-section")).toHaveAttribute("aria-labelledby");
    expect(screen.getByText("פיקוד פלוגה א")).toBeInTheDocument();
  });
});
