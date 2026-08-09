import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import { SoldierModalProvider } from "../../contexts/SoldierModalContext";
import type { IneligibleSoldiersResponse } from "../../api/ineligibleSoldiers";
import { IneligibleSoldiersTable } from "./IneligibleSoldiersTable";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { date?: string }) => ({
      "range_qualification.warning.normal": "אין כשירות מטווח בתוקף",
      "range_qualification.warning.urgent": "תורנות נשק קרובה ללא מטווח תואם",
      "range_qualification.qualificationExpiry": `בתוקף עד ${options?.date}`,
      "range_qualification.columns.unit": "יחידה",
      "range_qualification.columns.soldier": "חייל",
      "range_qualification.columns.qualification": "כשירות",
      "range_qualification.columns.context": "הקשר עתידי",
      "range_qualification.explanation.noCurrentQualification": "אין מטווחים בתוקף",
      "range_qualification.explanation.noWeaponDuty": "טרם שובץ לתורנות שדורשת נשק",
      "range_qualification.explanation.uncoveredDuty": `משובץ לתורנות ${options?.dutyType} שדורשת לפחות מטווח מסוג ${options?.rangeType} בתאריך ${options?.date}`,
      "range_qualification.explanation.plannedRangeCoverage": `מטווח מתוכנן מסוג ${options?.rangeType} בתאריך ${options?.rangeDate} מכסה את התורנות; הכשירות צפויה בתוקף עד ${options?.projectedValidUntil}`,
      "range_qualification.soldiersLoading": "טוען חיילים ללא הסמכה...",
      "range_qualification.soldiersError": "טעינת החיילים ללא הסמכה נכשלה",
      "range_qualification.soldiersEmpty": "אין חיילים ללא הסמכת מטווח",
    }[key] ?? key),
  }),
}));

vi.mock("../../hooks/useLevelTypes", () => ({
  useLevelTypes: () => ({
    levelTypes: [
      { id: "level-corps", key: "corps", label: "פיקוד", rank: 1 },
      { id: "level-unit", key: "unit", label: "פלוגה", rank: 2 },
      { id: "level-team", key: "team", label: "מחלקה", rank: 3 },
    ],
  }),
}));

const planningResponse: IneligibleSoldiersResponse = {
  count: 3,
  nodes: [
    { id: "platoon", name: "מחלקה 1", level: "team", parent_id: "company", path_ids: ["command", "company", "platoon"] },
    { id: "command", name: "פיקוד עליון", level: "corps", parent_id: null, path_ids: ["command"] },
    { id: "company", name: "פלוגה א", level: "unit", parent_id: "command", path_ids: ["command", "company"] },
  ],
  soldiers: [
    {
      soldier_id: "soldier-1", soldier_name: "נועם כהן", personal_number: "12345",
      hierarchy_node_id: "platoon", hierarchy_node_name: "מחלקה 1", hierarchy_path_ids: ["command", "company", "platoon"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-12-31" }],
      has_upcoming_weapon_duty: true, has_upcoming_matching_range: true,
      upcoming_weapon_duties: [{ assignment_id: "duty-1", duty_type_id: "weapon", duty_type_name: "שמירה", start_date: "2026-09-02", end_date: "2026-09-03", required_range_type: "laser", eligible: true, qualification_source: "planned_range", covered_by_range_date: "2026-08-20", projected_valid_until: "2027-02-20", reason: null }],
      upcoming_matching_ranges: [{ event_id: "range-1", range_type: "laser", date: "2026-08-20" }],
    },
    {
      soldier_id: "soldier-1", soldier_name: "נועם כהן", personal_number: "12345",
      hierarchy_node_id: "platoon", hierarchy_node_name: "מחלקה 1", hierarchy_path_ids: ["command", "company", "platoon"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-12-31" }],
      has_upcoming_weapon_duty: true, has_upcoming_matching_range: true,
      upcoming_weapon_duties: [{ assignment_id: "duty-1", duty_type_id: "weapon", duty_type_name: "שמירה", start_date: "2026-09-02", end_date: "2026-09-03", required_range_type: "laser", eligible: true, qualification_source: "planned_range", covered_by_range_date: "2026-08-20", projected_valid_until: "2027-02-20", reason: null }],
      upcoming_matching_ranges: [{ event_id: "range-1", range_type: "laser", date: "2026-08-20" }],
    },
    {
      soldier_id: "soldier-2", soldier_name: "מאיה לוי", personal_number: "67890",
      hierarchy_node_id: "company", hierarchy_node_name: "פלוגה א", hierarchy_path_ids: ["command", "company"],
      valid_qualifications: [], has_upcoming_weapon_duty: false, has_upcoming_matching_range: false,
      upcoming_weapon_duties: [], upcoming_matching_ranges: [],
    },
    {
      soldier_id: "soldier-3", soldier_name: "אורי פרץ", personal_number: "24680",
      hierarchy_node_id: "company", hierarchy_node_name: "פלוגה א", hierarchy_path_ids: ["command", "company"],
      valid_qualifications: [], has_upcoming_weapon_duty: true, has_upcoming_matching_range: false,
      upcoming_weapon_duties: [{ assignment_id: "duty-3", duty_type_id: "weapon", duty_type_name: "סיור", start_date: "2026-08-12", end_date: "2026-08-12", required_range_type: "live", eligible: false, qualification_source: null, covered_by_range_date: null, projected_valid_until: null, reason: "weapon_qualification" }],
      upcoming_matching_ranges: [],
    },
  ],
};

function renderTable(response = planningResponse, audience?: "planning" | "commander") {
  return render(<SoldierModalProvider><IneligibleSoldiersTable data={response} audience={audience} /></SoldierModalProvider>);
}

describe("IneligibleSoldiersTable", () => {
  it("traverses deliberately unordered hierarchy data and indents localized level labels", () => {
    renderTable();

    const tableRows = within(screen.getByTestId("ineligible-soldiers-table")).getAllByRole("row").slice(1);
    expect(tableRows.map((row) => row.cells[1].textContent)).toEqual([
      "פיקודפיקוד עליון",
      "פלוגהפלוגה א",
      "מחלקהמחלקה 1",
    ]);
    expect(tableRows[1].cells[1].firstElementChild).toHaveStyle({ paddingRight: "16px" });
    expect(tableRows[2].cells[1].firstElementChild).toHaveStyle({ paddingRight: "32px" });
    expect(within(tableRows[0]).getByText("3")).toBeInTheDocument();
    expect(within(tableRows[1]).getByText("3")).toBeInTheDocument();
    expect(within(tableRows[2]).getByText("1")).toBeInTheDocument();
  });

  it("expands a node with each subtree soldier once and shows qualification summaries", () => {
    renderTable();

    fireEvent.click(within(screen.getByTestId("ineligible-node-company")).getByRole("button"));

    expect(screen.getAllByRole("button", { name: "נועם כהן" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "מאיה לוי" })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "אורי פרץ" })).toHaveLength(1);
    expect(screen.getByText("מטווח לייזר בתוקף עד 31.12.2026")).toBeInTheDocument();
  });

  it("renders the same read-only hierarchy table for commander-scoped data", () => {
    renderTable(planningResponse, "commander");

    expect(screen.getByTestId("ineligible-soldiers-table")).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId("ineligible-node-company")).getByRole("button"));

    expect(screen.getByTestId("ineligible-soldiers-node-company")).toBeInTheDocument();
    expect(screen.getByTestId("ineligible-warning-soldier-3")).toHaveTextContent("משובץ לתורנות סיור שדורשת לפחות מטווח מסוג מטווח חי בתאריך 12.08.2026");
    expect(screen.queryByRole("button", { name: /שבץ|הסמך|עדכן/ })).not.toBeInTheDocument();
  });

  it("explains uncovered duties and planned coverage in Hebrew as well as by color", () => {
    renderTable();
    fireEvent.click(within(screen.getByTestId("ineligible-node-company")).getByRole("button"));

    expect(screen.getByTestId("ineligible-warning-soldier-1")).toHaveTextContent("מטווח מתוכנן מסוג מטווח לייזר בתאריך 20.08.2026 מכסה את התורנות; הכשירות צפויה בתוקף עד 20.02.2027");
    expect(screen.getByTestId("ineligible-warning-soldier-2")).toHaveTextContent("טרם שובץ לתורנות שדורשת נשק");
    expect(screen.getByTestId("ineligible-warning-soldier-2")).toHaveClass("bg-amber-100", "dark:bg-amber-900/40");
    expect(screen.getByTestId("ineligible-warning-soldier-3")).toHaveTextContent("משובץ לתורנות סיור שדורשת לפחות מטווח מסוג מטווח חי בתאריך 12.08.2026");
    expect(screen.getByTestId("ineligible-warning-soldier-3")).toHaveClass("bg-red-100", "dark:bg-red-900/40");
  });

  it("sorts the commander hierarchy from fixture order and preserves the expanded unit while sorting soldier columns", () => {
    renderTable(planningResponse, "commander");
    fireEvent.click(within(screen.getByTestId("ineligible-node-company")).getByRole("button"));

    const hierarchyTable = screen.getByTestId("ineligible-soldiers-table");
    expect(screen.getAllByTestId(/^ineligible-node-/).map((row) => row.cells[1].textContent)).toEqual([
      "פיקודפיקוד עליון",
      "פלוגהפלוגה א",
      "מחלקהמחלקה 1",
    ]);
    const hierarchyHeader = within(hierarchyTable).getByRole("columnheader", { name: "יחידה" });
    fireEvent.click(hierarchyHeader);

    expect(screen.getAllByTestId(/^ineligible-node-/).map((row) => row.cells[1].textContent)).toEqual([
      "מחלקהמחלקה 1",
      "פיקודפיקוד עליון",
      "פלוגהפלוגה א",
    ]);
    expect(screen.getByTestId("ineligible-soldiers-node-company")).toBeInTheDocument();

    const soldierTable = screen.getByTestId("ineligible-soldiers-node-company");
    for (const headerName of ["חייל", "כשירות", "הקשר עתידי"]) {
      const before = within(soldierTable).getAllByRole("row").slice(1).map((row) => row.textContent);
      const header = within(soldierTable).getByRole("columnheader", { name: headerName });
      fireEvent.click(header);
      const after = within(soldierTable).getAllByRole("row").slice(1).map((row) => row.textContent);
      expect(header).toHaveTextContent("▲");
      expect(after).not.toEqual(before);
    }
  });

  it("shows loading, error, and empty states", () => {
    const { rerender } = render(<SoldierModalProvider><IneligibleSoldiersTable loading /></SoldierModalProvider>);
    expect(screen.getByRole("status")).toHaveTextContent("טוען חיילים ללא הסמכה");

    rerender(<SoldierModalProvider><IneligibleSoldiersTable error /></SoldierModalProvider>);
    expect(screen.getByRole("alert")).toHaveTextContent("טעינת החיילים ללא הסמכה נכשלה");

    rerender(<SoldierModalProvider><IneligibleSoldiersTable data={{ count: 0, nodes: [], soldiers: [] }} /></SoldierModalProvider>);
    expect(screen.getByRole("status")).toHaveTextContent("אין חיילים ללא הסמכת מטווח");
  });
});
