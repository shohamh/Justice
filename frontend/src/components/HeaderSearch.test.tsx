import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import HeaderSearch from "./HeaderSearch";
import { search, type SearchResponseDTO } from "../api/search";

const mockOpenHelp = vi.fn();
const mockNavigate = vi.fn();

function renderHeaderSearch() {
  return render(
    <MemoryRouter>
      <HeaderSearch openHelp={mockOpenHelp} />
    </MemoryRouter>,
  );
}

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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
  mockOpenHelp.mockClear();
  mockNavigate.mockClear();
});

describe("HeaderSearch", () => {
  test("panel is closed by default", () => {
    renderHeaderSearch();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("clicking the trigger opens the panel and focuses the input", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    expect(screen.getByRole("combobox")).toHaveFocus();
  });

  test("Ctrl+K opens the panel from anywhere", () => {
    renderHeaderSearch();
    fireEvent.keyDown(window, { key: "k", code: "KeyK", ctrlKey: true });
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  test("Escape closes the panel", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  test("empty query shows no results section", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    expect(screen.queryByText("search.no_results")).not.toBeInTheDocument();
  });

  test("typing filters the pages registry via fuzzy match", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "פרופיל" } });
    expect(screen.getByText("search.pages.profile")).toBeInTheDocument();
  });

  test("role-gated registry entries are excluded for a plain soldier", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "הגדרות מערכת" } });
    expect(screen.queryByText("search.pages.admin_settings")).not.toBeInTheDocument();
  });

  test("role-gated registry entries are included for an admin", () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin", is_commander: false, is_duty_manager: false } });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "הגדרות מערכת" } });
    expect(screen.getByText("search.pages.admin_settings")).toBeInTheDocument();
  });

  test("typing a real Hebrew label matches via keywords, not just the i18n key", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "פרופיל" } });
    expect(screen.getByText("search.pages.profile")).toBeInTheDocument();
  });

  test("no-results message shown when nothing matches", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzz-no-such-thing-zzz" } });
    expect(screen.getByText("search.no_results")).toBeInTheDocument();
  });

  test("debounces the backend call by ~200ms", async () => {
    vi.useFakeTimers();
    const mockedSearch = vi.mocked(search);
    mockedSearch.mockClear();
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "yo" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "yos" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "yossi" } });
    expect(mockedSearch).not.toHaveBeenCalled();
    vi.advanceTimersByTime(200);
    expect(mockedSearch).toHaveBeenCalledTimes(1);
    expect(mockedSearch).toHaveBeenCalledWith("yossi");
    vi.useRealTimers();
  });

  test("ArrowDown moves the roving selection across groups", async () => {
    vi.mocked(search).mockResolvedValue({ soldiers: [], duties: [], units: [] });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "החלפות" } });
    const options = await screen.findAllByRole("option");
    expect(options.length).toBeGreaterThan(1);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    expect(options[0]).toHaveClass("bg-gray-100");
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    expect(options[1]).toHaveClass("bg-gray-100");
  });

  test("ignores a stale response that resolves after a newer one", async () => {
    vi.useFakeTimers();
    const mockedSearch = vi.mocked(search);
    mockedSearch.mockClear();

    function deferred<T>() {
      let resolve!: (value: T) => void;
      const promise = new Promise<T>((res) => {
        resolve = res;
      });
      return { promise, resolve };
    }

    const abDeferred = deferred<Awaited<ReturnType<typeof search>>>();
    const abcDeferred = deferred<Awaited<ReturnType<typeof search>>>();

    mockedSearch.mockImplementation((q: string) => {
      if (q === "ab") return abDeferred.promise;
      if (q === "abc") return abcDeferred.promise;
      return Promise.resolve({ soldiers: [], duties: [], units: [] });
    });

    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ab" } });
    vi.advanceTimersByTime(200);
    expect(mockedSearch).toHaveBeenCalledWith("ab");

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "abc" } });
    vi.advanceTimersByTime(200);
    expect(mockedSearch).toHaveBeenCalledWith("abc");

    vi.useRealTimers();

    // The newer request ("abc") resolves first...
    abcDeferred.resolve({
      soldiers: [{ id: "1", full_name: "Abc Soldier" } as SearchResponseDTO["soldiers"][number]],
      duties: [],
      units: [],
    });
    await screen.findByText("Abc Soldier");

    // ...then the stale request ("ab") resolves late and must be ignored.
    abDeferred.resolve({
      soldiers: [{ id: "2", full_name: "Ab Soldier" } as SearchResponseDTO["soldiers"][number]],
      duties: [],
      units: [],
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.getByText("Abc Soldier")).toBeInTheDocument();
    expect(screen.queryByText("Ab Soldier")).not.toBeInTheDocument();
  });

  test("graceful degradation: backend failure keeps local groups working", async () => {
    vi.mocked(search).mockRejectedValue(new Error("network error"));
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "פרופיל" } });
    vi.useFakeTimers();
    vi.advanceTimersByTime(200);
    vi.useRealTimers();
    expect(await screen.findByText("search.pages.profile")).toBeInTheDocument();
    expect(await screen.findByText("search.error")).toBeInTheDocument();
  });

  test("clicking a help-topic result calls openHelp with that topic's id", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "algorithm" } });
    fireEvent.click(screen.getByText("search.help.algorithm"));
    expect(mockOpenHelp).toHaveBeenCalledWith("algorithm");
  });

  test("pressing Enter on the selected result navigates the same as a click", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "פרופיל" } });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/profile");
  });

  test("selecting a soldier result navigates to /team", async () => {
    vi.mocked(search).mockResolvedValue({
      soldiers: [{ id: "1", full_name: "Yossi Cohen" } as SearchResponseDTO["soldiers"][number]],
      duties: [],
      units: [],
    });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "yossi" } });
    vi.useFakeTimers();
    vi.advanceTimersByTime(200);
    vi.useRealTimers();
    const soldierResult = await screen.findByText("Yossi Cohen");
    fireEvent.click(soldierResult);
    expect(mockNavigate).toHaveBeenCalledWith("/team");
  });

  test("selecting a duty result navigates to /unit-calendar", async () => {
    vi.mocked(search).mockResolvedValue({
      soldiers: [],
      duties: [{ id: "1", duty_type_name: "Guard Duty" } as SearchResponseDTO["duties"][number]],
      units: [],
    });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "guard" } });
    vi.useFakeTimers();
    vi.advanceTimersByTime(200);
    vi.useRealTimers();
    const dutyResult = await screen.findByText("Guard Duty");
    fireEvent.click(dutyResult);
    expect(mockNavigate).toHaveBeenCalledWith("/unit-calendar");
  });

  test("selecting a result closes the panel", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "פרופיל" } });
    fireEvent.click(screen.getByText("search.pages.profile"));
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
