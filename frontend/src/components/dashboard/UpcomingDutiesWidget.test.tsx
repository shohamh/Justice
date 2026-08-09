import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import UpcomingDutiesWidget from "./UpcomingDutiesWidget";
import type { EffectiveDuty } from "../../api/assignments";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) =>
      Object.entries(options ?? {}).reduce(
        (value, [name, replacement]) => value.replace(`{{${name}}}`, replacement),
        {
          "home.duty_primary": "ראשי",
          "reserve_standby": "רזרבה",
          "reserve_called_up": "הוקפץ",
          "called_up_from_to": "הוקפץ {{from}}–{{to}}",
        }[key] ?? key,
      ),
  }),
}));

function makeDuty(overrides: Partial<EffectiveDuty> = {}): EffectiveDuty {
  return {
    assignment_id: "a1", soldier_id: "s1", duty_type_id: "dt1", duty_type_name: "שמירה",
    duty_location_id: "loc1", start_date: "2099-01-01", end_date: "2099-01-02",
    start_time: "22:00", end_time: "06:00", start_at: "2099-01-01T22:00:00",
    end_at: "2099-01-02T06:00:00", shift_id: null, is_reserve: false,
    called_up_from: null, called_up_to: null,
    weapon_ineligible: false, weapon_ineligible_reason: null,
    ...overrides,
  };
}

describe("UpcomingDutiesWidget", () => {
  it("labels a primary duty as ראשי", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty()]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.getByText("ראשי")).toBeInTheDocument();
  });

  it("labels a reserve duty as רזרבה", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty({ is_reserve: true })]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.getByText("רזרבה")).toBeInTheDocument();
  });

  it("labels a called-up reserve duty as הוקפץ instead of רזרבה", () => {
    render(
      <UpcomingDutiesWidget
        duties={[makeDuty({ is_reserve: true, called_up_from: "2099-01-01", called_up_to: "2099-01-02" })]}
        typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()}
      />,
    );
    expect(screen.queryByText("רזרבה")).not.toBeInTheDocument();
    expect(screen.getByText(/הוקפץ/)).toBeInTheDocument();
  });

  it("does not show any assigned/required headcount", () => {
    render(
      <UpcomingDutiesWidget duties={[makeDuty()]} typeNames={{ dt1: "שמירה" }} locationNames={{ loc1: "שער" }} onOpenDuty={vi.fn()} />,
    );
    expect(screen.queryByText(/\d\/\d/)).not.toBeInTheDocument();
  });
});
