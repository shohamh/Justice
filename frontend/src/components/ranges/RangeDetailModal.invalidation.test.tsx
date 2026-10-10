import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as rangesApi from "../../api/ranges";
import * as soldiersApi from "../../api/soldiers";
import { useAuth } from "../../auth/AuthContext";
import { queryKeys } from "../../queryKeys";
import RangeDetailModal from "./RangeDetailModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));
vi.mock("../../api/ranges");
vi.mock("../../api/soldiers");
vi.mock("../../auth/AuthContext");
vi.mock("./RangeDetailContent", () => ({
  default: (props: {
    onExcuse: (id: string, reason: string) => Promise<void>;
    onDecide: (id: string, approve: boolean) => Promise<void>;
    onAttendance: () => void;
  }) => (
    <div>
      <button onClick={() => void props.onExcuse("a1", "why")}>excuse</button>
      <button onClick={() => void props.onDecide("r1", true)}>decide</button>
      <button onClick={() => props.onAttendance()}>attendance</button>
    </div>
  ),
}));

const IDS = [
  queryKeys.ineligibleSoldierCount(),
  [...queryKeys.ineligibleSoldierCount(), "planning", "scope"],
  queryKeys.adminIneligibleSoldierCount("admin-1", "scope"),
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({ user: { id: "u1", is_duty_manager: false } } as unknown as ReturnType<typeof useAuth>);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([]);
  vi.mocked(rangesApi.getRangeExcusalRequests).mockResolvedValue([]);
  vi.mocked(rangesApi.excuseRangeAssignment).mockResolvedValue({} as never);
  vi.mocked(rangesApi.decideRangeExcusal).mockResolvedValue({} as never);
  vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
    id: "event-1", hierarchy_node_id: "n", range_type: "laser", date: "2026-09-01", range_location_id: "l",
    location: "x", required_count: 1, reserve_count: 0, status: "planned", assignments: [],
  });
});

async function renderModal() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <RangeDetailModal rangeId="event-1" onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  await screen.findByText("excuse");
  for (const key of IDS) queryClient.setQueryData(key, { count: 3 });
  return queryClient;
}

describe("RangeDetailModal refreshes the ineligible-soldier count", () => {
  it.each([["excuse"], ["decide"], ["attendance"]])("after %s, every ineligible-count variant is invalidated", async (action) => {
    const queryClient = await renderModal();
    for (const key of IDS) expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);

    fireEvent.click(screen.getByText(action));

    await waitFor(() => {
      for (const key of IDS) expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
    });
  });
});
