import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import UpcomingSnapshot from "./UpcomingSnapshot";
import type { UpcomingDay } from "../api/commanderDashboard";
import { listDutyTypes } from "../api/dutyConfig";

const dict: Record<string, string> = {
  "command_dashboard.upcoming_scope_command": "תורנויות קרובות בפיקוד",
  "home.upcoming_scope_personal": "התורנויות האישיות הקרובות",
  "command_dashboard.view_duty_details": "צפה בפרטי התורנות",
  "duty_detail.required_range": "מטווח נדרש",
  "duty_detail.no_required_range": "לא נדרש",
  "duty_detail.required_range_unavailable": "נתוני מטווח נדרש אינם זמינים",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: string | (Record<string, unknown> & { defaultValue?: string })) => {
      const fallback = typeof options === "string" ? options : options?.defaultValue;
      let template = dict[key] ?? fallback ?? key;
      if (options && typeof options === "object") {
        for (const [varName, value] of Object.entries(options)) {
          if (varName === "defaultValue") continue;
          template = template.replaceAll(`{{${varName}}}`, String(value));
        }
      }
      return template;
    },
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

const mockOpenSoldierModal = vi.fn();
vi.mock("./SoldierLink", () => ({
  default: ({ id, name }: { id: string; name: string }) => (
    <button onClick={() => mockOpenSoldierModal(id)}>{name}</button>
  ),
}));

const mockUsePublicSettings = vi.fn();
vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => mockUsePublicSettings(),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: null }),
}));

vi.mock("../contexts/SoldierModalContext", () => ({
  useSoldierModal: () => ({ openSoldierModal: mockOpenSoldierModal }),
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
      {
        assignment_id: "asg-2",
        soldier_id: "sol-2",
        soldier_name: "רוני לוי",
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
        is_reserve: true,
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
  mockOpenSoldierModal.mockReset();
  mockUsePublicSettings.mockReset();
  mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": true });
});

function renderWithRouter(days: UpcomingDay[] = data) {
  return render(
    <MemoryRouter>
      <UpcomingSnapshot data={days} />
    </MemoryRouter>
  );
}

describe("UpcomingSnapshot grouping", () => {
  it("labels command-scope upcoming duties explicitly", () => {
    render(
      <MemoryRouter>
        <UpcomingSnapshot scope="command" data={data} />
      </MemoryRouter>,
    );

    expect(screen.getByText("תורנויות קרובות בפיקוד")).toBeInTheDocument();
  });

  it("keeps personal upcoming wording only when the parent explicitly passes personal scope", () => {
    render(
      <MemoryRouter>
        <UpcomingSnapshot scope="personal" data={[]} />
      </MemoryRouter>,
    );

    expect(screen.getByText("התורנויות האישיות הקרובות")).toBeInTheDocument();
  });

  it("groups primary and reserve soldiers under one duty row", () => {
    renderWithRouter();
    expect(screen.getByText(/שמירות/)).toBeInTheDocument();
    expect(screen.getByText("דני כהן")).toBeInTheDocument();
    expect(screen.getByText("רוני לוי")).toBeInTheDocument();
    expect(screen.getByText(/רזרבה/)).toBeInTheDocument();
  });

  it("clicking a soldier name opens the soldier modal directly", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText("דני כהן"));
    expect(mockOpenSoldierModal).toHaveBeenCalledWith("sol-1");
  });

  it("clicking the duty header opens the duty details modal directly", async () => {
    renderWithRouter();
    fireEvent.click(screen.getByText(/שמירות · שער צפון/));
    expect(screen.getByRole("dialog", { name: "שמירות" })).toBeInTheDocument();
    expect(screen.getByText("06.07.2026")).toBeInTheDocument();
    expect(screen.getByText("שער צפון")).toBeInTheDocument();
    expect(await screen.findByText("מטווח לייזר")).toBeInTheDocument();
  });

  it("shows required-range data as unavailable when the duty type lookup fails", async () => {
    vi.mocked(listDutyTypes).mockRejectedValueOnce(new Error("unavailable"));
    renderWithRouter();
    fireEvent.click(screen.getByText(/שמירות · שער צפון/));
    expect(await screen.findByText("נתוני מטווח נדרש אינם זמינים")).toBeInTheDocument();
  });

  it("closes the duty modal via the close button", () => {
    renderWithRouter();
    fireEvent.click(screen.getByText(/שמירות · שער צפון/));
    expect(screen.getByRole("dialog", { name: "שמירות" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("סגור"));
    expect(screen.queryByRole("dialog", { name: "שמירות" })).not.toBeInTheDocument();
  });
});

describe("UpcomingSnapshot forced release", () => {
  it("hides the forced-release icon when forced callup is disabled", () => {
    mockUsePublicSettings.mockReturnValue({ "forced_callup.enabled": false });
    renderWithRouter();
    expect(screen.queryByLabelText("שחרור פיקודי")).not.toBeInTheDocument();
  });

  it("shows a confirmation naming the soldier and only navigates after confirmation", () => {
    renderWithRouter();
    fireEvent.click(screen.getAllByLabelText("שחרור פיקודי")[0]);
    expect(screen.getByText(/דני כהן.*קיצוניים/)).toBeInTheDocument();
    expect(mockNavigate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(mockNavigate).toHaveBeenCalledWith("/commander/hakpaza?soldierId=sol-1&assignmentId=asg-1");
  });

  it("does not navigate when the confirmation is dismissed", () => {
    renderWithRouter();
    fireEvent.click(screen.getAllByLabelText("שחרור פיקודי")[0]);
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

describe("UpcomingSnapshot draft badge", () => {
  it("shows a draft badge for an algorithm_draft assignment", () => {
    renderWithRouter(makeDraftDay("algorithm_draft"));
    expect(screen.getByTestId("draft-badge-a1")).toBeInTheDocument();
  });

  it("shows no draft badge for a published assignment", () => {
    renderWithRouter(makeDraftDay("published"));
    expect(screen.queryByTestId("draft-badge-a1")).not.toBeInTheDocument();
  });
});
