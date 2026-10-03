import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { SoldierDTO, SoldierScoreDTO } from "../api/soldiers";
import { SoldierModalProvider, useSoldierModal } from "./SoldierModalContext";

const mockGetSoldier = vi.fn<(id: string) => Promise<SoldierDTO>>();
const mockGetSoldierScore = vi.fn<(id: string) => Promise<SoldierScoreDTO>>();
const mockGetRanks = vi.fn().mockResolvedValue({ enlisted: [], officers: [], officer_academic: [] });
const mockFetchTree = vi.fn().mockResolvedValue([]);

vi.mock("../api/soldiers", () => ({
  getSoldier: (...args: [string]) => mockGetSoldier(...args),
  getSoldierScore: (...args: [string]) => mockGetSoldierScore(...args),
  getRanks: (...args: unknown[]) => mockGetRanks(...args),
}));

vi.mock("../api/hierarchy", () => ({
  fetchTree: (...args: unknown[]) => mockFetchTree(...args),
  fetchHierarchyBranchPage: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
  searchHierarchyNodes: vi.fn().mockResolvedValue({ matches: [], has_more: false }),
}));

vi.mock("../api/auth", () => ({ getTransparencyAuthorizationScope: () => "all" }));
vi.mock("../api/hierarchyTransfers", () => ({ createTransferRequest: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ user: { role: "admin", personal_number: "admin" } }) }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const soldier = (id: string, overrides: Partial<SoldierDTO> = {}): SoldierDTO => ({
  id,
  personal_number: `pn-${id}`,
  full_name: `Soldier ${id}`,
  role: "soldier",
  hierarchy_node_id: "node-1",
  hierarchy_path: ["Division", "Unit"],
  phone: null,
  must_change_password: false,
  left_at: null,
  enrolled_at: null,
  gender: null,
  is_officer: false,
  is_career: false,
  rank: null,
  rank_track: null,
  next_rank_date: null,
  next_rank_date_overridden: false,
  can_edit_rank_advancement: false,
  bahad1_graduate: false,
  has_military_driving_license: false,
  military_driving_license_expiry: null,
  enlistment_date: null,
  unit_join_date: null,
  mandatory_end_date: null,
  discharge_date: null,
  last_mitvahim_date: null,
  last_alal_date: null,
  telegram_linked: false,
  visibility: "full",
  ...overrides,
});

function OpenButton({ id = "s1", label = "open soldier" }: { id?: string; label?: string }) {
  const { openSoldierModal } = useSoldierModal();
  return <button onClick={() => void openSoldierModal(id)}>{label}</button>;
}

function renderProvider() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <SoldierModalProvider><OpenButton /><OpenButton id="s2" label="open second" /></SoldierModalProvider>
    </QueryClientProvider>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("SoldierModalProvider progressive loading", () => {
  beforeEach(() => {
    mockGetSoldier.mockReset();
    mockGetSoldierScore.mockReset();
    mockGetRanks.mockClear();
    mockFetchTree.mockClear();
  });

  test("shows details before a deferred score resolves and applies that score afterward without fetching the tree", async () => {
    const score = deferred<SoldierScoreDTO>();
    mockGetSoldier.mockResolvedValue(soldier("s1"));
    mockGetSoldierScore.mockReturnValue(score.promise);
    renderProvider();

    fireEvent.click(screen.getByText("open soldier"));

    await waitFor(() => expect(mockGetSoldierScore).toHaveBeenCalledWith("s1"));
    expect(screen.getAllByText("Soldier s1")).toHaveLength(2);
    expect(screen.getByText("Division")).toBeInTheDocument();
    expect(screen.getByText("Unit")).toBeInTheDocument();
    expect(screen.queryByTestId("soldier-modal-opening")).not.toBeInTheDocument();
    expect(mockFetchTree).not.toHaveBeenCalled();

    await act(async () => {
      score.resolve({ active_days: 17, normalised_score: 0.625 } as SoldierScoreDTO);
      await score.promise;
    });

    expect(await screen.findByText("17")).toBeInTheDocument();
    expect(screen.getByText("0.625")).toBeInTheDocument();
  });

  test("public soldier details do not request score or hierarchy data", async () => {
    mockGetSoldier.mockResolvedValue(soldier("s1", {
      visibility: "public",
      full_name: "Public Soldier",
      phone: null,
      hierarchy_path: ["Public Unit"],
    }));
    renderProvider();

    fireEvent.click(screen.getByText("open soldier"));

    expect(await screen.findAllByText("Public Soldier")).toHaveLength(2);
    expect(screen.getByText("Public Unit")).toBeInTheDocument();
    expect(mockGetSoldierScore).not.toHaveBeenCalled();
    expect(mockFetchTree).not.toHaveBeenCalled();
  });

  test("a delayed score for a closed soldier modal is not applied to the next soldier", async () => {
    const score = deferred<SoldierScoreDTO>();
    mockGetSoldier.mockResolvedValueOnce(soldier("s1"));
    mockGetSoldierScore.mockReturnValueOnce(score.promise);
    renderProvider();

    fireEvent.click(screen.getByText("open soldier"));
    await waitFor(() => expect(screen.getAllByText("Soldier s1")).toHaveLength(2));
    fireEvent.click(screen.getByTestId("modal-close"));

    mockGetSoldier.mockResolvedValueOnce(soldier("s2", { full_name: "Soldier s2" }));
    mockGetSoldierScore.mockResolvedValueOnce({ active_days: 4, normalised_score: 0.2 } as SoldierScoreDTO);
    fireEvent.click(screen.getByText("open second"));
    expect(await screen.findAllByText("Soldier s2")).toHaveLength(2);
    await act(async () => {
      score.resolve({ active_days: 99, normalised_score: 9.99 } as SoldierScoreDTO);
      await score.promise;
    });

    await waitFor(() => expect(screen.getByText("4")).toBeInTheDocument());
    expect(screen.queryByText("99")).not.toBeInTheDocument();
  });

  test("a score failure leaves the soldier modal open and removes the opening overlay", async () => {
    mockGetSoldier.mockResolvedValue(soldier("s1"));
    mockGetSoldierScore.mockRejectedValue(new Error("score unavailable"));
    renderProvider();

    fireEvent.click(screen.getByText("open soldier"));

    expect(await screen.findAllByText("Soldier s1")).toHaveLength(2);
    await waitFor(() => expect(mockGetSoldierScore).toHaveBeenCalledWith("s1"));
    expect(screen.queryByTestId("soldier-modal-opening")).not.toBeInTheDocument();
  });
});
