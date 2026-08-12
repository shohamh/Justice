import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
    expect(screen.getByRole("button", { name: "פטור בדיקה (עד 01.05.2026)" })).toBeInTheDocument();
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

  it("opens the detail modal on click", async () => {
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
    // Wait for the modal's async detail fetch to resolve so its state update
    // happens inside act() — otherwise React logs a spurious act() warning
    // after this test function has already returned. Waiting on the category
    // badge (not the type name, which also matches the chip button behind it).
    await waitFor(() => expect(screen.getByText("גלובלי")).toBeInTheDocument());
  });
});
