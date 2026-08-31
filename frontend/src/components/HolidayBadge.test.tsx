import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HolidayBadge from "./HolidayBadge";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

describe("HolidayBadge", () => {
  it("renders nothing when there are no crossed holidays", () => {
    const { container } = render(<HolidayBadge holidays={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a badge and opens a popover listing holiday names on click", () => {
    render(<HolidayBadge holidays={[{ date: "2026-09-12", name: "Rosh Hashanah" }]} />);
    const badge = screen.getByTestId("holiday-badge");
    expect(badge).toBeInTheDocument();
    expect(screen.queryByText(/Rosh Hashanah/)).not.toBeInTheDocument();

    fireEvent.click(badge);
    expect(screen.getByText(/Rosh Hashanah/)).toBeInTheDocument();
  });

  it("renders the holiday tooltip right-to-left", () => {
    render(<HolidayBadge holidays={[{ date: "2026-09-12", name: "Rosh Hashanah" }]} />);
    fireEvent.click(screen.getByTestId("holiday-badge"));

    expect(screen.getByRole("tooltip")).toHaveAttribute("dir", "rtl");
    expect(screen.getByRole("tooltip")).toHaveClass("text-right");
  });

  it("lists every crossed holiday when there are multiple", () => {
    render(
      <HolidayBadge
        holidays={[
          { date: "2026-09-12", name: "Rosh Hashanah" },
          { date: "2026-09-13", name: "Rosh Hashanah II" },
        ]}
      />
    );
    fireEvent.click(screen.getByTestId("holiday-badge"));
    expect(screen.getByText(/Rosh Hashanah(?!\s+II)/)).toBeInTheDocument();
    expect(screen.getByText(/Rosh Hashanah II/)).toBeInTheDocument();
  });
});
