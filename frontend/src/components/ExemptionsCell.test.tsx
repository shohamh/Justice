import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import ExemptionsCell from "./ExemptionsCell";

vi.mock("../api/exemptions", async () => {
  const actual = await vi.importActual("../api/exemptions");
  return {
    ...actual,
    getExemptionDetail: vi.fn().mockResolvedValue({
      id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true,
      start_date: "2026-01-01", end_date: null, reason: null, granted_by_name: null,
    }),
  };
});

describe("ExemptionsCell", () => {
  it("renders the placeholder when not visible", () => {
    render(<ExemptionsCell exemptions={[]} visible={false} placeholder="חסוי" soldierId="s1" />);
    expect(screen.getByText("חסוי")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a dash when visible but empty", () => {
    render(<ExemptionsCell exemptions={[]} visible={true} placeholder="חסוי" soldierId="s1" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders a clickable chip with the end date suffix when present", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: "2026-05-01" }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    expect(screen.getByRole("button", { name: "פטור בדיקה (עד 01/05/2026)" })).toBeInTheDocument();
  });

  it("renders a chip without a date suffix when end_date is null", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: null }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    expect(screen.getByRole("button", { name: "פטור בדיקה" })).toBeInTheDocument();
  });

  it("opens the detail modal on click", () => {
    render(
      <ExemptionsCell
        exemptions={[{ id: "ex-1", exemption_type_name: "פטור בדיקה", is_global: true, start_date: "2026-01-01", end_date: null }]}
        visible={true}
        placeholder="חסוי"
        soldierId="s1"
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "פטור בדיקה" }));
    expect(screen.getByTestId("exemption-instance-modal")).toBeInTheDocument();
  });
});
