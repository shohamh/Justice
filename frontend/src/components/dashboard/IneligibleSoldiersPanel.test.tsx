import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SoldierModalProvider } from "../../contexts/SoldierModalContext";
import type { IneligibleSoldiersResponse } from "../../api/ineligibleSoldiers";
import { IneligibleSoldiersPanel } from "./IneligibleSoldiersPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string | number>) => ({
      "range_qualification.columns.unit": "יחידה",
      "range_qualification.columns.count": "חיילים",
      "range_qualification.columns.soldier": "חייל",
      "range_qualification.columns.qualification": "כשירות",
      "range_qualification.columns.context": "הקשר עתידי",
      "range_qualification.warning.normal": "אין כשירות מטווח בתוקף",
      "range_qualification.qualificationExpiry": `בתוקף עד ${options?.date}`,
      "range_qualification.explanation.noWeaponDuty": "טרם שובץ לתורנות שדורשת נשק",
      "range_qualification.explanation.uncoveredDuty": `מוצב לתורנות ${options?.dutyType} שדורשת לפחות מטווח מסוג ${options?.rangeType} בתאריך ${options?.date}`,
      "range_qualification.soldiersLoading": "טוען חיילים ללא הסמכה...",
      "range_qualification.soldiersError": "טעינת החיילים ללא הסמכה נכשלה",
      "range_qualification.soldiersEmpty": "אין חיילים ללא הסמכת מטווח",
      "range_qualification.soldiersCount": `${options?.count} חיילים ללא הסמכת מטווח`,
      "range_qualification.filterUnits": "סנן יחידות",
      "range_qualification.emptyUnits": "אין יחידות",
      "range_qualification.filterSoldiers": "סנן חיילים",
      "range_qualification.emptySoldiersInUnit": "אין חיילים ביחידה",
    }[key] ?? key),
  }),
}));

vi.mock("../../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({ levelTypes: [{ id: "company", key: "company", label: "פלוגה", rank: 1 }] }),
}));
vi.mock("../../api/ineligibleSoldiers", () => ({ getIneligibleSoldiers: vi.fn() }));

import { getIneligibleSoldiers } from "../../api/ineligibleSoldiers";

const commanderResponse: IneligibleSoldiersResponse = {
  count: 2,
  nodes: [
    { id: "root", name: "גדוד", level: "company", parent_id: null, path_ids: ["root"] },
    { id: "company", name: "פלוגה א", level: "company", parent_id: "root", path_ids: ["root", "company"] },
  ],
  soldiers: [
    {
      soldier_id: "soldier-1", soldier_name: "נועם כהן", personal_number: "12345",
      hierarchy_node_id: "company", hierarchy_node_name: "פלוגה א", hierarchy_path_ids: ["root", "company"],
      valid_qualifications: [], has_upcoming_weapon_duty: false, has_upcoming_matching_range: false,
      upcoming_weapon_duties: [], upcoming_matching_ranges: [],
    },
    {
      soldier_id: "soldier-2", soldier_name: "אורי פרץ", personal_number: "67890",
      hierarchy_node_id: "company", hierarchy_node_name: "פלוגה א", hierarchy_path_ids: ["root", "company"],
      valid_qualifications: [], has_upcoming_weapon_duty: true, has_upcoming_matching_range: false,
      upcoming_weapon_duties: [{
        assignment_id: "duty-1", duty_type_id: "weapon", duty_type_name: "סיור", start_date: "2026-08-12", end_date: "2026-08-12",
        required_range_type: "live", eligible: false, qualification_source: null, covered_by_range_date: null, projected_valid_until: null, reason: "weapon_qualification",
      }],
      upcoming_matching_ranges: [],
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SoldierModalProvider><IneligibleSoldiersPanel /></SoldierModalProvider>
    </QueryClientProvider>,
  );
}

describe("IneligibleSoldiersPanel", () => {
  it("renders the shared hierarchy table for commander data instead of per-soldier cards", async () => {
    vi.mocked(getIneligibleSoldiers).mockResolvedValue(commanderResponse);
    renderPanel();

    await waitFor(() => expect(getIneligibleSoldiers).toHaveBeenCalledWith("commander"));
    const table = await screen.findByTestId("ineligible-soldiers-table");
    expect(within(table).getByText("גדוד")).toBeInTheDocument();
    expect(within(table).getByText("פלוגה א")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("expands hierarchy rows into SoldierLink rows with shared explanations and sorting", async () => {
    vi.mocked(getIneligibleSoldiers).mockResolvedValue(commanderResponse);
    renderPanel();

    const companyRow = await screen.findByTestId("ineligible-node-company");
    await act(async () => {
      fireEvent.click(within(companyRow).getByRole("button", { name: "הרחב" }));
    });

    const soldierTable = screen.getByTestId("ineligible-soldiers-node-company");
    expect(within(soldierTable).getByRole("button", { name: "נועם כהן" })).toBeInTheDocument();
    expect(within(soldierTable).getByRole("button", { name: "אורי פרץ" })).toBeInTheDocument();
    expect(within(soldierTable).getByText("מוצב לתורנות סיור שדורשת לפחות מטווח מסוג מטווח חי בתאריך 12.08.2026")).toBeInTheDocument();

    const hierarchyTable = screen.getByTestId("ineligible-soldiers-table");
    await act(async () => {
      fireEvent.click(within(hierarchyTable).getByRole("columnheader", { name: "יחידה" }));
    });
    expect(screen.getAllByTestId(/^ineligible-node-/).map((row) => row.textContent)).toEqual([
      expect.stringContaining("גדוד"),
      expect.stringContaining("פלוגה א"),
    ]);
    expect(screen.queryByRole("button", { name: /שבץ|הסמך|עדכן/ })).not.toBeInTheDocument();
  });

  it("keeps clear loading, error, and empty states", async () => {
    let resolveQuery!: (value: IneligibleSoldiersResponse) => void;
    vi.mocked(getIneligibleSoldiers).mockReturnValueOnce(new Promise((resolve) => { resolveQuery = resolve; }));
    const { unmount } = renderPanel();
    expect(screen.getByRole("status")).toHaveTextContent("טוען חיילים ללא הסמכה...");

    resolveQuery({ count: 0, nodes: [], soldiers: [] });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("אין חיילים ללא הסמכת מטווח"));

    vi.mocked(getIneligibleSoldiers).mockRejectedValueOnce(new Error("boom"));
    unmount();
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("טעינת החיילים ללא הסמכה נכשלה");
  });
});
