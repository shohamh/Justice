import { describe, expect, test } from "vitest";
import { useEffect } from "react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { act, render, screen } from "@testing-library/react";
import { NavigationHistoryProvider, useNavigationHistory } from "./useNavigationHistory";

function Probe() {
  const history = useNavigationHistory();
  return <div data-testid="history">{JSON.stringify(history.map((h) => h.path))}</div>;
}

function NavCapture({ navigateRef }: { navigateRef: { current: ((path: string) => void) | null } }) {
  const navigate = useNavigate();
  useEffect(() => { navigateRef.current = navigate; }, [navigate]);
  return <Probe />;
}

describe("useNavigationHistory", () => {
  test("records the initial route", () => {
    render(
      <MemoryRouter initialEntries={["/duty"]}>
        <NavigationHistoryProvider>
          <Probe />
        </NavigationHistoryProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("history").textContent).toBe(JSON.stringify(["/duty"]));
  });

  test("caps the ring buffer at 15 entries, keeping the most recent", () => {
    const navigateRef: { current: ((path: string) => void) | null } = { current: null };
    render(
      <MemoryRouter initialEntries={["/start"]}>
        <NavigationHistoryProvider>
          <NavCapture navigateRef={navigateRef} />
        </NavigationHistoryProvider>
      </MemoryRouter>,
    );

    for (let i = 0; i < 20; i++) {
      act(() => {
        navigateRef.current!(`/page-${i}`);
      });
    }

    const recorded = JSON.parse(screen.getByTestId("history").textContent!);
    expect(recorded).toHaveLength(15);
    expect(recorded[0]).toBe("/page-5");
    expect(recorded[14]).toBe("/page-19");
  });

  test("throws when used outside the provider", () => {
    function Bare() {
      useNavigationHistory();
      return null;
    }
    expect(() => render(<Bare />)).toThrow("useNavigationHistory must be used inside NavigationHistoryProvider");
  });
});
