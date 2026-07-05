import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../i18n";
import ExemptionInstanceModal from "./ExemptionInstanceModal";
import * as exemptionsApi from "../api/exemptions";

describe("ExemptionInstanceModal", () => {
  it("renders type name, category, dates, reason, and granted-by on success", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockResolvedValue({
      id: "ex-1", exemption_type_name: "פטור רפואי", is_global: true,
      start_date: "2026-01-01", end_date: "2026-05-01", reason: "בעיה רפואית",
      granted_by_name: "יוסי כהן",
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-1" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("פטור רפואי")).toBeInTheDocument());
    expect(screen.getByText("01/01/2026")).toBeInTheDocument();
    expect(screen.getByText("01/05/2026")).toBeInTheDocument();
    expect(screen.getByText("בעיה רפואית")).toBeInTheDocument();
    expect(screen.getByText("יוסי כהן")).toBeInTheDocument();
  });

  it("shows 'forever' when end_date is null", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockResolvedValue({
      id: "ex-2", exemption_type_name: "פטור קבוע", is_global: false,
      start_date: "2026-01-01", end_date: null, reason: null, granted_by_name: null,
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-2" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("ללא הגבלה")).toBeInTheDocument());
  });

  it("shows a no-permission message on 403 without crashing", async () => {
    vi.spyOn(exemptionsApi, "getExemptionDetail").mockRejectedValue({
      response: { status: 403 },
    });
    render(<ExemptionInstanceModal soldierId="s1" exemptionId="ex-3" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("אין הרשאה לצפות בפרטים")).toBeInTheDocument());
  });
});
