import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RangesPage from "./RangesPage";
import * as rangesApi from "../api/ranges";

vi.mock("../api/ranges");
vi.mock("../components/SoldierSearchAutocomplete", () => ({
  default: () => <div data-testid="soldier-picker" />,
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: { id: "me", hierarchy_node_id: "node-1" } }),
}));

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("RangesPage", () => {
  it("renders the list of range events", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getByText("מטווח דרום")).toBeInTheDocument());
  });
});

describe("RangesPage roster add", () => {
  it("adds a soldier to the roster via the picker", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
    });
    vi.mocked(rangesApi.addRangeAssignment).mockResolvedValue({
      id: "assignment-1", soldier_id: "soldier-1", is_reserve: false, attendance_status: "pending", note: null,
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));
    fireEvent.click(await screen.findByTestId("add-soldier-button"));

    expect(await screen.findByTestId("soldier-picker")).toBeInTheDocument();
  });
});
