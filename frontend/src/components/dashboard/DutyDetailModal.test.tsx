import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import DutyDetailModal from "./DutyDetailModal";
import type { EffectiveDuty } from "../../api/assignments";
import type { CalendarShift } from "../../api/calendar";
import { getCalendarShift } from "../../api/calendar";
import { listDutyTypes } from "../../api/dutyConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({ user: null }),
}));

vi.mock("../../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: vi.fn() }),
}));

vi.mock("../../hooks/useModalBackClose", () => ({
  useModalBackClose: () => {},
}));

// ShiftDetailPanel is only shown after clicking "פרטי משמרת"; it has its own
// heavy set of dependencies, so it's stubbed out here to keep this test
// focused on DutyDetailModal's own header rendering.
vi.mock("../ShiftDetailPanel", () => ({
  default: () => null,
}));

vi.mock("../../api/dutyConfig", () => ({
  listDutyTypes: vi.fn().mockResolvedValue([]),
}));

vi.mock("../../api/calendar", () => ({
  getCalendarShift: vi.fn(),
}));

const duty: EffectiveDuty = {
  assignment_id: "asg-1",
  soldier_id: "sol-1",
  duty_type_id: "dt-1",
  duty_type_name: "שמירה",
  duty_location_id: "loc-1",
  start_date: "2026-09-12",
  end_date: "2026-09-13",
  start_time: "08:00",
  end_time: "08:00",
  start_at: "2026-09-12T08:00:00Z",
  end_at: "2026-09-13T08:00:00Z",
  shift_id: "shift-1",
  is_reserve: false,
  called_up_from: null,
  called_up_to: null,
  weapon_ineligible: false,
  weapon_ineligible_reason: null,
  status: "published",
};

function makeShift(overrides: Partial<CalendarShift> = {}): CalendarShift {
  return {
    id: "shift-1",
    duty_type_id: "dt-1",
    duty_type_name: "שמירה",
    duty_type_color: "#123456",
    required_range_type: null,
    duty_location_name: "שער ראשי",
    start_date: "2026-09-12",
    end_date: "2026-09-13",
    start_time: "08:00",
    end_time: "08:00",
    start_at: "2026-09-12T08:00:00Z",
    end_at: "2026-09-13T08:00:00Z",
    required_count: 1,
    assigned_count: 1,
    fill_status: "full",
    reserve_count: 0,
    assignees: [],
    crossed_holidays: [],
    ...overrides,
  };
}

const typeNames = { "dt-1": "שמירה" };
const locationNames = { "loc-1": "שער ראשי" };

describe("DutyDetailModal holiday badge", () => {
  beforeEach(() => {
    vi.mocked(listDutyTypes).mockReset().mockResolvedValue([]);
    vi.mocked(getCalendarShift).mockReset();
  });

  it("shows a holiday badge once the shift crosses a holiday", async () => {
    vi.mocked(getCalendarShift).mockResolvedValue(
      makeShift({ crossed_holidays: [{ date: "2026-09-12", name: "Rosh Hashanah" }] })
    );

    render(
      <DutyDetailModal duty={duty} typeNames={typeNames} locationNames={locationNames} onClose={() => {}} />
    );

    expect(await screen.findByTestId("holiday-badge")).toBeInTheDocument();
  });

  it("shows no holiday badge when the shift crosses no holiday", async () => {
    vi.mocked(getCalendarShift).mockResolvedValue(makeShift({ crossed_holidays: [] }));

    render(
      <DutyDetailModal duty={duty} typeNames={typeNames} locationNames={locationNames} onClose={() => {}} />
    );

    // Wait for the fetch to resolve before asserting absence.
    await screen.findByText("שער ראשי");
    expect(screen.queryByTestId("holiday-badge")).not.toBeInTheDocument();
  });

  it("shows no holiday badge before the shift has loaded", () => {
    vi.mocked(getCalendarShift).mockReturnValue(new Promise(() => {}));

    render(
      <DutyDetailModal duty={duty} typeNames={typeNames} locationNames={locationNames} onClose={() => {}} />
    );

    expect(screen.queryByTestId("holiday-badge")).not.toBeInTheDocument();
  });
});
