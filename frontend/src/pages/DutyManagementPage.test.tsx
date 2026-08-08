import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DutyManagementContent } from "./DutyManagementPage";
import * as assignmentsApi from "../api/assignments";
import * as soldiersApi from "../api/soldiers";
import type { SoldierDTO } from "../api/soldiers";
const WEAPON_REASON = "אין הכשרת נשק בתוקף לתאריך התורנות";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../api/assignments", () => ({
  listAssignments: vi.fn(() => Promise.resolve([])),
  cancelAssignment: vi.fn(() => Promise.resolve({})),
  setOverride: vi.fn(() => Promise.resolve()),
}));

vi.mock("../api/soldiers", () => ({
  listSoldiers: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/algorithm", () => ({
  getDraftsPreview: vi.fn(() => Promise.resolve({ count: 0, items: [] })),
  resetDrafts: vi.fn(() => Promise.resolve({ rejected: 0 })),
  resetPublished: vi.fn(() => Promise.resolve({ cancelled: 0 })),
}));

vi.mock("../api/scoreAdjustments", () => ({
  createAdjustment: vi.fn(() => Promise.resolve({})),
}));

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DutyManagementContent />
    </QueryClientProvider>,
  );
}

describe("DutyManagementContent weapon-ineligibility markers", () => {
  it("shows the reason as a red warning marker only for ineligible assignments", async () => {
    vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([
      { id: "soldier-1", full_name: "חייל אחד" } as SoldierDTO,
    ]);
    vi.mocked(assignmentsApi.listAssignments).mockResolvedValue([
      {
        id: "assignment-bad",
        soldier_id: "soldier-1",
        duty_type_id: "duty-type-1",
        duty_location_id: "location-1",
        start_date: "2026-08-05",
        end_date: "2026-08-06",
        status: "published",
        notes: null,
        weapon_ineligible: true,
        weapon_ineligible_reason: WEAPON_REASON,
      },
      {
        id: "assignment-ok",
        soldier_id: "soldier-1",
        duty_type_id: "duty-type-1",
        duty_location_id: "location-1",
        start_date: "2026-08-08",
        end_date: "2026-08-09",
        status: "published",
        notes: null,
        weapon_ineligible: false,
        weapon_ineligible_reason: null,
      },
    ]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("assignment-row-assignment-bad")).toBeInTheDocument());

    const ineligibleRow = screen.getByTestId("assignment-row-assignment-bad");
    const eligibleRow = screen.getByTestId("assignment-row-assignment-ok");
    const marker = within(ineligibleRow).getByTitle(WEAPON_REASON);
    expect(marker).toHaveTextContent("⚠️");
    expect(marker).toHaveClass("text-red-500");
    expect(within(eligibleRow).queryByText("⚠️")).not.toBeInTheDocument();
  });
});
