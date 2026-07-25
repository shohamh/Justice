import { render, screen, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import { ThemeProvider, useTheme } from "./ThemeContext";

const mockUpdateThemePreference = vi.fn();
vi.mock("../api/theme", () => ({
  updateThemePreference: (...args: unknown[]) => mockUpdateThemePreference(...args),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

function Probe() {
  const { theme, resolvedTheme, cycleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved">{resolvedTheme}</span>
      <button onClick={cycleTheme}>cycle</button>
    </div>
  );
}

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    mockUpdateThemePreference.mockReset().mockResolvedValue("dark");
    mockUseAuth.mockReturnValue({ user: null });
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })));
  });

  it("cycles light -> dark -> system -> light and applies the dark class", async () => {
    localStorage.setItem("theme", "light");
    render(<ThemeProvider><Probe /></ThemeProvider>);

    expect(screen.getByTestId("theme").textContent).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(mockUpdateThemePreference).toHaveBeenCalledWith("dark");

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("system"));

    act(() => screen.getByText("cycle").click());
    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("light"));
  });

  it("adopts the profile's theme_preference once the user loads, overriding localStorage", async () => {
    localStorage.setItem("theme", "light");
    mockUseAuth.mockReturnValue({ user: { theme_preference: "dark" } });
    render(<ThemeProvider><Probe /></ThemeProvider>);

    await waitFor(() => expect(screen.getByTestId("theme").textContent).toBe("dark"));
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});
