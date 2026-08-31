import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as rangesApi from "../../api/ranges";
import * as soldiersApi from "../../api/soldiers";
import { useAuth } from "../../auth/AuthContext";
import RangeDetailModal from "./RangeDetailModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));
vi.mock("../../api/ranges");
vi.mock("../../api/soldiers");
vi.mock("../../auth/AuthContext");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useAuth).mockReturnValue({ user: { id: "u1", is_duty_manager: false } } as unknown as ReturnType<typeof useAuth>);
  vi.mocked(soldiersApi.listSoldiers).mockResolvedValue([]);
  vi.mocked(rangesApi.getRangeExcusalRequests).mockResolvedValue([]);
});

function renderModal() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RangeDetailModal rangeId="event-1" onClose={vi.fn()} />
    </QueryClientProvider>
  );
}

describe("RangeDetailModal", () => {
  it("renders the range detail once the event query resolves", async () => {
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1",
      hierarchy_node_id: "node-1",
      range_type: "laser",
      date: "2026-09-01",
      range_location_id: "loc-1",
      location: "מטווח דרום",
      required_count: 2,
      reserve_count: 1,
      status: "planned",
      assignments: [],
    });
    renderModal();

    expect(await screen.findByTestId("range-detail-content")).toBeInTheDocument();
    expect(screen.queryByTestId("range-detail-error")).not.toBeInTheDocument();
  });

  // getRangeEvent throws a descriptive error for a malformed/missing range
  // detail payload (see api/ranges.ts). The modal must surface that failure
  // instead of silently rendering nothing (the previous `if (!data) return
  // null` collapsed a real failure into an unexplained blank modal).
  it("shows a translated alert instead of a blank modal when the range event fails to load", async () => {
    vi.mocked(rangesApi.getRangeEvent).mockRejectedValue(new Error("Invalid range response"));
    renderModal();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("טעינת פרטי המטווח נכשלה");
    expect(screen.queryByTestId("range-detail-content")).not.toBeInTheDocument();
  });
});
