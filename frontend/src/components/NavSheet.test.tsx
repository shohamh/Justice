import { render, screen } from "@testing-library/react";
import NavSheet from "./NavSheet";

vi.mock("react-router-dom", () => ({
  Link: ({ to, children, className, ...props }: { to: string; children: React.ReactNode; className?: string; [key: string]: unknown }) => (
    <a href={to} className={className} {...props}>{children}</a>
  ),
}));

describe("NavSheet — badge rendering", () => {
  test("badge with no badgeColor falls back to red", () => {
    render(
      <NavSheet
        open
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item", badge: 5 }]}
      />
    );
    const badge = screen.getByText("5");
    expect(badge.className).toContain("bg-red-500");
  });

  test("badge with badgeColor 'blue' renders blue", () => {
    render(
      <NavSheet
        open
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item", badge: 3, badgeColor: "blue" }]}
      />
    );
    const badge = screen.getByText("3");
    expect(badge.className).toContain("bg-blue-500");
  });

  test("badge with badgeColor 'yellow' renders yellow with dark text", () => {
    render(
      <NavSheet
        open
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item", badge: 2, badgeColor: "yellow" }]}
      />
    );
    const badge = screen.getByText("2");
    expect(badge.className).toContain("bg-yellow-500");
    expect(badge.className).toContain("text-gray-900");
  });

  test("badge of 0 renders no badge element", () => {
    render(
      <NavSheet
        open
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item", badge: 0 }]}
      />
    );
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  test("item with no badge renders no badge element", () => {
    render(
      <NavSheet
        open
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item" }]}
      />
    );
    expect(screen.getByText("Item")).toBeInTheDocument();
    expect(screen.queryByTestId("badge")).not.toBeInTheDocument();
  });

  test("when open is false, nothing renders", () => {
    const { container } = render(
      <NavSheet
        open={false}
        onClose={vi.fn()}
        items={[{ label: "Item", to: "/item", badge: 5 }]}
        testId="my-sheet"
      />
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("my-sheet")).not.toBeInTheDocument();
  });
});
