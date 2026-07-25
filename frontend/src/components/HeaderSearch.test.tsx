import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";
import HeaderSearch from "./HeaderSearch";
import { search, type SearchResponseDTO } from "../api/search";

const mockOpenHelp = vi.fn();

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
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
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
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "search.pages.profile" } });
    expect(screen.getByText("search.pages.profile")).toBeInTheDocument();
  });

  test("role-gated registry entries are excluded for a plain soldier", () => {
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "search.pages.admin_settings" } });
    expect(screen.queryByText("search.pages.admin_settings")).not.toBeInTheDocument();
  });

  test("role-gated registry entries are included for an admin", () => {
    mockUseAuth.mockReturnValue({ user: { role: "admin", is_commander: false, is_duty_manager: false } });
    renderHeaderSearch();
    fireEvent.click(screen.getByRole("button", { name: "search.placeholder" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "search.pages.admin_settings" } });
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
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "search.pages" } });
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
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "search.pages.profile" } });
    vi.useFakeTimers();
    vi.advanceTimersByTime(200);
    vi.useRealTimers();
    expect(await screen.findByText("search.pages.profile")).toBeInTheDocument();
    expect(await screen.findByText("search.error")).toBeInTheDocument();
  });
});
