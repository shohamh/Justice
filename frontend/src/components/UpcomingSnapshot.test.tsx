import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import UpcomingSnapshot from "./UpcomingSnapshot";
import type { UpcomingDay } from "../api/commanderDashboard";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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
        node_name: "ספקטרה",
        is_reserve: false,
      },
    ],
  },
];

beforeEach(() => {
  mockNavigate.mockReset();
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
