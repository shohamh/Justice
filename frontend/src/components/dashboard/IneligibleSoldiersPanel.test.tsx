import { render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { SoldierModalProvider } from "../../contexts/SoldierModalContext";
import type { IneligibleSoldiersResponse } from "../../api/ineligibleSoldiers";
import { IneligibleSoldiersPanel } from "./IneligibleSoldiersPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { date?: string }) => ({
      "range_qualification.dashboard.title": "חיילים ללא כשירות מטווח",
      "range_qualification.dashboard.description": "חיילים ללא כשירות מטווח בתוקף או ללא מטווח תואם לתורנות נשק קרובה.",
      "range_qualification.dashboard.empty": "אין חיילים הדורשים טיפול",
      "range_qualification.loading": "טוען נתוני כשירות...",
      "range_qualification.error": "טעינת נתוני הכשירות נכשלה",
      "range_qualification.warning.normal": "אין כשירות מטווח בתוקף",
      "range_qualification.warning.urgent": "תורנות נשק קרובה ללא מטווח תואם",
      "range_qualification.qualificationExpiry": `בתוקף עד ${options?.date}`,
      "range_qualification.columns.hierarchy": "מסגרת",
    }[key] ?? key),
  }),
}));

vi.mock("../../api/ineligibleSoldiers", () => ({
  getIneligibleSoldiers: vi.fn(),
}));

import { getIneligibleSoldiers } from "../../api/ineligibleSoldiers";

const commanderResponse: IneligibleSoldiersResponse = {
  count: 4,
  nodes: [],
  soldiers: [
    {
      soldier_id: "soldier-warning",
      soldier_name: "נועה כהן",
      personal_number: "12345",
      hierarchy_node_id: "node-1",
      hierarchy_node_name: "מחלקה א",
      hierarchy_path_ids: ["root", "node-1"],
      valid_qualifications: [],
      has_upcoming_weapon_duty: false,
      has_upcoming_matching_range: false,
      upcoming_weapon_duties: [],
      upcoming_matching_ranges: [],
    },
    {
      soldier_id: "soldier-urgent",
      soldier_name: "אורי לוי",
      personal_number: "67890",
      hierarchy_node_id: "node-2",
      hierarchy_node_name: "מחלקה ב",
      hierarchy_path_ids: ["root", "node-2"],
      valid_qualifications: [{ range_type: "live", valid_until: "2026-08-12" }],
      has_upcoming_weapon_duty: true,
      has_upcoming_matching_range: false,
      upcoming_weapon_duties: [{
        assignment_id: "duty-1",
        duty_type_id: "weapon",
        duty_type_name: "שמירה",
        start_date: "2026-08-11",
        end_date: "2026-08-11",
        required_range_type: "live",
      }],
      upcoming_matching_ranges: [],
    },
    {
      soldier_id: "soldier-planned-range",
      soldier_name: "דן מזרחי",
      personal_number: "24680",
      hierarchy_node_id: "node-3",
      hierarchy_node_name: "מחלקה ג",
      hierarchy_path_ids: ["root", "node-3"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-08-20" }],
      has_upcoming_weapon_duty: true,
      has_upcoming_matching_range: true,
      upcoming_weapon_duties: [{
        assignment_id: "duty-2",
        duty_type_id: "weapon",
        duty_type_name: "סיור",
        start_date: "2026-08-15",
        end_date: "2026-08-15",
        required_range_type: "laser",
      }],
      upcoming_matching_ranges: [{ event_id: "range-1", range_type: "laser", date: "2026-08-14" }],
    },
    {
      soldier_id: "soldier-qualified",
      soldier_name: "רון דרור",
      personal_number: "13579",
      hierarchy_node_id: "node-4",
      hierarchy_node_name: "מחלקה ד",
      hierarchy_path_ids: ["root", "node-4"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-12-31" }],
      has_upcoming_weapon_duty: false,
      has_upcoming_matching_range: true,
      upcoming_weapon_duties: [],
      upcoming_matching_ranges: [{ event_id: "range-2", range_type: "laser", date: "2026-09-01" }],
    },
  ],
};

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={queryClient}>
      <SoldierModalProvider>
        <IneligibleSoldiersPanel />
      </SoldierModalProvider>
    </QueryClientProvider>,
  );
  return { queryClient, ...result };
}

describe("IneligibleSoldiersPanel", () => {
  it("renders only actionable soldiers with hierarchy, qualification, and warning context", async () => {
    vi.mocked(getIneligibleSoldiers).mockResolvedValue(commanderResponse);
    renderPanel();

    await waitFor(() => expect(getIneligibleSoldiers).toHaveBeenCalledWith("commander"));
    await screen.findByRole("button", { name: "נועה כהן" });
    const panel = document.querySelector("#panel-ineligible-soldiers");
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("id", "panel-ineligible-soldiers");
    expect(within(panel).getByRole("button", { name: "נועה כהן" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "אורי לוי" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "דן מזרחי" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "רון דרור" })).not.toBeInTheDocument();

    expect(within(panel).getByText("מחלקה א")).toBeInTheDocument();
    expect(within(panel).getByText("מחלקה ב")).toBeInTheDocument();
    expect(within(panel).getByText("מחלקה ג")).toBeInTheDocument();
    expect(within(panel).getByText("מטווח חי בתוקף עד 2026-08-12")).toBeInTheDocument();
    expect(within(panel).getByText("מטווח לייזר בתוקף עד 2026-08-20")).toBeInTheDocument();
    expect(within(panel).getByText("שמירה 2026-08-11")).toBeInTheDocument();
    expect(within(panel).getByText(/סיור 2026-08-15/)).toBeInTheDocument();
    expect(within(panel).getByText(/מטווח לייזר 2026-08-14/)).toBeInTheDocument();
  });

  it("distinguishes normal and urgent warnings without showing actions", async () => {
    vi.mocked(getIneligibleSoldiers).mockResolvedValue(commanderResponse);
    renderPanel();

    expect(await screen.findByTestId("ineligible-warning-soldier-warning")).toHaveTextContent("אין כשירות מטווח בתוקף");
    expect(screen.getByTestId("ineligible-warning-soldier-warning")).toHaveClass("bg-amber-100");
    expect(screen.getByTestId("ineligible-warning-soldier-urgent")).toHaveTextContent("תורנות נשק קרובה ללא מטווח תואם");
    expect(screen.getByTestId("ineligible-warning-soldier-urgent")).toHaveClass("bg-red-100", "font-semibold");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /שבץ|ערוך|אשר/i })).not.toBeInTheDocument();
  });

  it("shows loading, empty, and error states", async () => {
    let resolveQuery!: (value: IneligibleSoldiersResponse) => void;
    vi.mocked(getIneligibleSoldiers).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveQuery = resolve;
      }),
    );
    const { queryClient, rerender } = renderPanel();
    expect(screen.getByRole("status")).toHaveTextContent("טוען נתוני כשירות...");

    resolveQuery({ count: 0, nodes: [], soldiers: [] });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("אין חיילים הדורשים טיפול"));

    vi.mocked(getIneligibleSoldiers).mockRejectedValueOnce(new Error("boom"));
    queryClient.clear();
    rerender(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <SoldierModalProvider>
          <IneligibleSoldiersPanel />
        </SoldierModalProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("טעינת נתוני הכשירות נכשלה");
  });
});
