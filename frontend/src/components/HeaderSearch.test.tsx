import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import HeaderSearch from "./HeaderSearch";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const mockUseAuth = vi.fn();
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("../hooks/usePublicSettings", () => ({
  usePublicSettings: () => ({ "gimalim.enabled": true }),
}));

vi.mock("../api/search", () => ({
  search: vi.fn().mockResolvedValue({ soldiers: [], duties: [], units: [] }),
}));

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    user: { role: "soldier", is_commander: false, is_duty_manager: false },
  });
});

describe("HeaderSearch", () => {
  test("panel is closed by default", () => {
    render(<HeaderSearch />);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("clicking the trigger opens the panel and focuses the input", () => {
    render(<HeaderSearch />);
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    expect(screen.getByRole("combobox")).toHaveFocus();
  });

  test("Ctrl+K opens the panel from anywhere", () => {
    render(<HeaderSearch />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  test("Escape closes the panel", () => {
    render(<HeaderSearch />);
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("empty query shows no results section", () => {
    render(<HeaderSearch />);
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    expect(screen.queryByText("search.no_results")).not.toBeInTheDocument();
  });
});
