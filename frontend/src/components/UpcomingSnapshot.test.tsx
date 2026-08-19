import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import UpcomingSnapshot from "./UpcomingSnapshot";
import type { UpcomingDay } from "../api/commanderDashboard";
import { listDutyTypes } from "../api/dutyConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      "command_dashboard.view_duty_details": "צפה בפרטי התורנות",
      "duty_detail.required_range": "מטווח נדרש",
      "duty_detail.no_required_range": "לא נדרש",
      "duty_detail.required_range_unavailable": "נתוני מטווח נדרש אינם זמינים",
    })[key] ?? key,
  }),
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

const mockUsePublicSettings = vi.fn();
vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: null }),
}));

vi.mock("../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: vi.fn() }),
}));

vi.mock("../hooks/useModalBackClose", () => ({
  useModalBackClose: () => {},
}));

vi.mock("../api/dutyConfig", () => ({
  listDutyTypes: vi.fn().mockResolvedValue([
    {
      id: "dt-1",
      name: "שמירות",
      required_range_type: "laser",
      start_time: null,
      end_time: null,
      instructions: null,
      contact_name: null,
      contact_phone: null,
    },
  ]),
}));

vi.mock("../api/calendar", () => ({
  getCalendarShift: vi.fn().mockResolvedValue(null),
}));

const data: UpcomingDay[] = [
  {
    date: "2026-07-06",
    assignments: [
      {
        assignment_id: "asg-1",
        soldier_id: "sol-1",
        soldier_name: "דני כהן",
        duty_type_id: "dt-1",
        duty_type_name: "שמירות",
        duty_location_id: "loc-1",
        duty_location_name: "שער צפון",
        start_date: "2026-07-06",
        end_date: "2026-07-07",
        start_time: "08:00",
        end_time: "12:00",
        shift_id: "shift-1",
        node_name: "ספקטרה",
        is_reserve: false,
        status: "published",
      },
    ],
  },
];

function makeDraftDay(status: string): UpcomingDay[] {
  return [
    {
      date: "2026-08-20",
      assignments: [
        {
          assignment_id: "a1",
          soldier_id: "s1",
          soldier_name: "חייל בדיקה",
          duty_type_id: "dt1",
          duty_type_name: "שמירה",
          duty_location_id: "loc1",
          duty_location_name: "שער",
          start_date: "2026-08-20",
          end_date: "2026-08-21",
          start_time: "08:00",
          end_time: "08:00",
          shift_id: null,
          node_name: "יחידה",
          is_reserve: false,
          status,
        },
      ],
    },
  ];
}

beforeEach(() => {
  mockNavigate.mockReset();
  mockUsePublicSettings.mockReset();
  mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": true });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

function renderWithRouter() {
  return render(
    <MemoryRouter>
      <UpcomingSnapshot data={data} />
    </MemoryRouter>
  );
}

describe("UpcomingSnapshot soldier modal", () => {
  it("hides commander release when forced callup is disabled", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": false });
    renderWithRouter();

    fireEvent.click(screen.getByText("דני כהן"));

    expect(screen.queryByRole("button", { name: "שחרור פיקודי" })).not.toBeInTheDocument();
  });

  it("opens the existing duty details from the selected upcoming assignment", async () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));

    fireEvent.click(screen.getByRole("button", { name: "צפה בפרטי התורנות" }));

    expect(screen.getByRole("dialog", { name: "שמירות" })).toBeInTheDocument();
    expect(screen.getByText("06.07.2026")).toBeInTheDocument();
    expect(screen.getByText("שער צפון")).toBeInTheDocument();
    expect(await screen.findByText("מטווח לייזר")).toBeInTheDocument();
  });

  it("shows required-range data as unavailable when the duty type lookup fails", async () => {
    vi.mocked(listDutyTypes).mockRejectedValueOnce(new Error("unavailable"));
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));

    fireEvent.click(screen.getByRole("button", { name: "צפה בפרטי התורנות" }));

    expect(await screen.findByText("נתוני מטווח נדרש אינם זמינים")).toBeInTheDocument();
    expect(screen.queryByText("לא נדרש")).not.toBeInTheDocument();
  });

  it("opens the modal on badge click and closes it via the ✕ button (no bottom ביטול button)", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    expect(screen.getByText("שמירות")).toBeInTheDocument();
    expect(screen.queryByText("command_dashboard.cancel")).not.toBeInTheDocument();
    const closeBtn = screen.getByLabelText("סגור");
    fireEvent.click(closeBtn);
    expect(screen.queryByText("שמירות")).not.toBeInTheDocument();
  });

  it("shows a confirm dialog naming the soldier and mentioning קיצוניים, then navigates to the pre-filled hakpaza URL", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    fireEvent.click(screen.getByText("שחרור פיקודי"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("דני כהן"));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("קיצוניים"));
    expect(mockNavigate).toHaveBeenCalledWith("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
  });

  it("does not navigate when the confirm dialog is dismissed", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    fireEvent.click(screen.getByText("שחרור פיקודי"));
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

describe("UpcomingSnapshot draft badge", () => {
  it("shows a draft badge for an algorithm_draft assignment", () => {
    render(
      <MemoryRouter>
        <UpcomingSnapshot data={makeDraftDay("algorithm_draft")} />
      </MemoryRouter>
    );
    expect(screen.getByTestId("draft-badge-a1")).toBeInTheDocument();
  });

  it("shows no draft badge for a published assignment", () => {
    render(
      <MemoryRouter>
        <UpcomingSnapshot data={makeDraftDay("published")} />
      </MemoryRouter>
    );
    expect(screen.queryByTestId("draft-badge-a1")).not.toBeInTheDocument();
  });
});
