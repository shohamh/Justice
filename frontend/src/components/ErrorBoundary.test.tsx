import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("renders a fallback instead of a blank crash", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByText(/משהו השתבש/)).toBeInTheDocument();
  });
});
