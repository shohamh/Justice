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
      upcoming_weapon_duties: [{ assignment_id: "duty-1", duty_type_id: "weapon", duty_type_name: "שמירה", start_date: "2026-09-02", end_date: "2026-09-03", required_range_type: "laser" }],
      upcoming_matching_ranges: [{ event_id: "range-1", range_type: "laser", date: "2026-08-20" }],
    },
    {
      soldier_id: "soldier-1", soldier_name: "נועם כהן", personal_number: "12345",
      hierarchy_node_id: "platoon", hierarchy_node_name: "מחלקה 1", hierarchy_path_ids: ["command", "company", "platoon"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-12-31" }],
      has_upcoming_weapon_duty: true, has_upcoming_matching_range: true,
      upcoming_weapon_duties: [{ assignment_id: "duty-1", duty_type_id: "weapon", duty_type_name: "שמירה", start_date: "2026-09-02", end_date: "2026-09-03", required_range_type: "laser" }],
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
      upcoming_weapon_duties: [{ assignment_id: "duty-3", duty_type_id: "weapon", duty_type_name: "סיור", start_date: "2026-08-12", end_date: "2026-08-12", required_range_type: "live" }],
      upcoming_matching_ranges: [],
    },
  ],
};

function renderTable(response = planningResponse) {
  return render(<SoldierModalProvider><IneligibleSoldiersTable data={response} /></SoldierModalProvider>);
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
    expect(screen.getByText("מטווח לייזר בתוקף עד 2026-12-31")).toBeInTheDocument();
  });

  it("labels normal and urgent qualification warnings in Hebrew as well as by color", () => {
    renderTable();
    fireEvent.click(within(screen.getByTestId("ineligible-node-company")).getByRole("button"));

    expect(screen.getByTestId("ineligible-warning-soldier-2")).toHaveTextContent("אין כשירות מטווח בתוקף");
    expect(screen.getByTestId("ineligible-warning-soldier-2")).toHaveClass("bg-amber-100", "dark:bg-amber-900/40");
    expect(screen.getByTestId("ineligible-warning-soldier-3")).toHaveTextContent("תורנות נשק קרובה ללא מטווח תואם");
    expect(screen.getByTestId("ineligible-warning-soldier-3")).toHaveClass("bg-red-100", "dark:bg-red-900/40");
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
