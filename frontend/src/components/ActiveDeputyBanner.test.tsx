import { render, screen } from "@testing-library/react";
import ActiveDeputyBanner from "./ActiveDeputyBanner";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => {
    if (key === "deputies.acting_as_banner") {
      return `פועל/ת כממלא/ת מקום עבור ${opts?.principal} (${opts?.role}) עד ${opts?.endDate}`;
    }
    return key;
  } }),
}));

test("renders nothing when there are no active grants", () => {
  const { container } = render(<ActiveDeputyBanner grants={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("renders one line per active grant", () => {
  render(
    <ActiveDeputyBanner
      grants={[
        { principal_id: "p1", principal_name: "דנה לוי", role: "commander", end_date: "2026-09-01" },
        { principal_id: "p2", principal_name: "רון כהן", role: "duty_manager", end_date: "2026-09-15" },
      ]}
    />
  );
  expect(screen.getByText(/דנה לוי/)).toBeInTheDocument();
  expect(screen.getByText(/רון כהן/)).toBeInTheDocument();
});
