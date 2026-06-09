import { render, screen } from "@testing-library/react";
import JusticeLogo from "./JusticeLogo";

describe("JusticeLogo", () => {
  test("renders the word Justice", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo-text")).toHaveTextContent("Justice");
  });

  test("contains an SVG element", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo").querySelector("svg")).not.toBeNull();
  });

  test("defaults to md size (text-2xl)", () => {
    render(<JusticeLogo />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-2xl");
  });

  test("applies text-xl when size=sm", () => {
    render(<JusticeLogo size="sm" />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-xl");
  });

  test("applies text-4xl when size=lg", () => {
    render(<JusticeLogo size="lg" />);
    expect(screen.getByTestId("justice-logo-text")).toHaveClass("text-4xl");
  });

  test("SVG has aria-hidden to hide it from screen readers", () => {
    render(<JusticeLogo />);
    const svg = screen.getByTestId("justice-logo").querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
