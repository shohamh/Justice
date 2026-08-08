// frontend/src/pages/MyDutiesPage.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MyDutiesPage from "./MyDutiesPage";
import * as assignmentsApi from "../api/assignments";
import * as swapsApi from "../api/swaps";
import type { EffectiveDuty } from "../api/assignments";

const mockUseAuth = vi.fn(() => ({ user: null }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../components/dashboard/DutyTypeBreakdownChart", () => ({
  default: () => <div data-testid="duty-type-breakdown" />,
}));

vi.mock("../api/assignments", () => ({
  listEffectiveDuties: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/scoring", () => ({
  getTransparency: vi.fn(() => Promise.resolve({ rows: [] })),
  getBreakdown: vi.fn(() => Promise.resolve({ per_type: [], adjustments: [] })),
}));

vi.mock("../api/soldiers", () => ({
  getReserveStats: vi.fn(() => Promise.resolve({ used_days: 0, max_days: 0, window_days: 0 })),
}));

vi.mock("../api/dutyConfig", () => ({
  listDutyTypes: vi.fn(() => Promise.resolve([])),
}));

vi.mock("../api/swaps", () => ({
  listMySwaps: vi.fn(() => Promise.resolve([])),
  getEligibleDuties: vi.fn(() => Promise.resolve([])),
  checkCoverEligibility: vi.fn(() => Promise.resolve({ eligible: true, reason: null })),
  createSwap: vi.fn(() => Promise.resolve({})),
  takeDutyFree: vi.fn(() => Promise.resolve({})),
}));

const WEAPON_REASON = "אין הכשרת נשק בתוקף לתאריך התורנות";
const FALLBACK_MESSAGE = "אינך כשיר לתורנות זו";

const SOLDIER = {
  id: "s1",
  personal_number: "111111",
  full_name: "חייל אחד",
  role: "soldier" as const,
  is_commander: false,
  is_duty_manager: false,
};

function makeDuty(overrides: Partial<EffectiveDuty>): EffectiveDuty {
  return {
    assignment_id: "a1",
    soldier_id: "s1",
    duty_type_id: "dt-1",
    duty_type_name: "שמירה",
    duty_location_id: "loc-1",
    start_date: "2099-01-10",
    end_date: "2099-01-11",
    start_time: "08:00",
    end_time: "08:00",
    start_at: "2099-01-10T08:00:00Z",
    end_at: "2099-01-11T08:00:00Z",
    shift_id: "shift-1",
    is_reserve: false,
    weapon_ineligible: false,
    weapon_ineligible_reason: null,
    ...overrides,
  };
}

function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderPage() {
  mockUseAuth.mockReturnValue({ user: SOLDIER });
  return render(
    <QueryClientProvider client={createTestQueryClient()}>
      <MyDutiesPage />
    </QueryClientProvider>
  );
}

describe("MyDutiesPage weapon-ineligibility swap path", () => {
  beforeEach(() => {
    vi.mocked(assignmentsApi.listEffectiveDuties).mockClear();
    vi.mocked(swapsApi.checkCoverEligibility).mockClear();
    vi.mocked(swapsApi.getEligibleDuties).mockClear();
  });

  it("shows the ineligibility reason and a swap-request button on an ineligible upcoming duty", async () => {
    vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([
      makeDuty({
        assignment_id: "a-bad",
        weapon_ineligible: true,
        weapon_ineligible_reason: WEAPON_REASON,
      }),
    ]);
    renderPage();

    expect(await screen.findByText(new RegExp(WEAPON_REASON))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "בקש החלפה" })).toBeInTheDocument();
  });

  it("does not show the swap-request UI for eligible duties", async () => {
    vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([makeDuty({})]);
    renderPage();

    await screen.findByTestId("my-diary-page");
    expect(screen.queryByRole("button", { name: "בקש החלפה" })).toBeNull();
    expect(screen.queryByText(FALLBACK_MESSAGE)).toBeNull();
  });

  it("falls back to the generic message when no reason text is provided", async () => {
    vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([
      makeDuty({ weapon_ineligible: true, weapon_ineligible_reason: null }),
    ]);
    renderPage();

    expect(await screen.findByText(new RegExp(FALLBACK_MESSAGE))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "בקש החלפה" })).toBeInTheDocument();
  });

  it("renders every run of a split-span multi-day assignment (shared assignment_id, distinct start_date)", async () => {
    // listEffectiveDuties can return one entry PER DAY (or per override run) for
    // a multi-day assignment, all sharing the same assignment_id. Both rows must
    // render, each with its own swap-request button — no duplicate React keys.
    vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([
      makeDuty({
        assignment_id: "a-multi",
        start_date: "2099-01-10",
        end_date: "2099-01-11",
        weapon_ineligible: true,
        weapon_ineligible_reason: "אין הכשרת נשק ביום הראשון",
      }),
      makeDuty({
        assignment_id: "a-multi",
        start_date: "2099-01-11",
        end_date: "2099-01-12",
        weapon_ineligible: true,
        weapon_ineligible_reason: "אין הכשרת נשק ביום השני",
      }),
    ]);
    renderPage();

    expect(await screen.findByText("אין הכשרת נשק ביום הראשון", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("אין הכשרת נשק ביום השני", { exact: false })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "בקש החלפה" })).toHaveLength(2);
  });

  it("clicking the swap button opens OfferSwapModal pre-filled with the ineligible assignment", async () => {
    vi.mocked(assignmentsApi.listEffectiveDuties).mockResolvedValue([
      makeDuty({
        assignment_id: "a-bad",
        weapon_ineligible: true,
        weapon_ineligible_reason: WEAPON_REASON,
      }),
    ]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "בקש החלפה" }));

    // The modal loads coverage eligibility for the ineligible assignment and
    // the offering soldier's eligible duties — proving it opened pre-filled
    // with that duty (targetAssignmentId) for that soldier (targetSoldierId).
    await waitFor(() =>
      expect(swapsApi.checkCoverEligibility).toHaveBeenCalledWith("a-bad")
    );
    expect(swapsApi.getEligibleDuties).toHaveBeenCalledWith("s1");
  });
});