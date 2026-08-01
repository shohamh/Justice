import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RangesPage from "./RangesPage";
import * as rangesApi from "../api/ranges";

vi.mock("../api/ranges");
vi.mock("../components/SoldierSearchAutocomplete", () => ({
  default: (props: { onSelect: (soldier: { id: string } | null) => void }) => (
    <div data-testid="soldier-picker">
      <button data-testid="select-soldier-1" onClick={() => props.onSelect({ id: "soldier-1" })}>
        select
      </button>
    </div>
  ),
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

function renderWithQuery(ui: React.ReactElement, initialEntries = ["/ranges"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mockUser = { id: "me", hierarchy_node_id: "node-1", role: "admin", is_duty_manager: true } as any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
});

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

  it("renders Hebrew labels for range_type and status instead of raw English", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getByText("לייזר")).toBeInTheDocument());
    expect(screen.getByText("מתוכנן")).toBeInTheDocument();
    expect(screen.queryByText("laser")).not.toBeInTheDocument();
    expect(screen.queryByText("planned")).not.toBeInTheDocument();
  });
});

describe("RangesPage create event", () => {
  it("creates a new range event via the create form", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([]);
    vi.mocked(rangesApi.createRangeEvent).mockResolvedValue({
      id: "event-2", hierarchy_node_id: "node-1", range_type: "live",
      date: "2026-10-01", location: "מטווח צפון", required_count: 6,
      reserve_count: 2, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />);

    fireEvent.click(await screen.findByTestId("create-event-button"));
    expect(await screen.findByTestId("create-event-form")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("new-range-type"), { target: { value: "live" } });
    fireEvent.change(screen.getByTestId("new-date"), { target: { value: "2026-10-01" } });
    fireEvent.change(screen.getByTestId("new-location"), { target: { value: "מטווח צפון" } });
    fireEvent.change(screen.getByTestId("new-required-count"), { target: { value: "6" } });
    fireEvent.change(screen.getByTestId("new-reserve-count"), { target: { value: "2" } });

    fireEvent.click(screen.getByText("שמור"));

    await waitFor(() =>
      expect(rangesApi.createRangeEvent).toHaveBeenCalledWith({
        hierarchy_node_id: "node-1",
        range_type: "live",
        date: "2026-10-01",
        location: "מטווח צפון",
        required_count: 6,
        reserve_count: 2,
      }),
    );
    await waitFor(() => expect(screen.queryByTestId("create-event-form")).not.toBeInTheDocument());
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

    fireEvent.click(await screen.findByTestId("select-soldier-1"));

    await waitFor(() => expect(rangesApi.addRangeAssignment).toHaveBeenCalledWith("event-1", "soldier-1", false));
    await waitFor(() => expect(screen.queryByTestId("soldier-picker")).not.toBeInTheDocument());
  });

  it("adds a soldier as reserve when the reserve toggle is checked", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
    });
    vi.mocked(rangesApi.addRangeAssignment).mockResolvedValue({
      id: "assignment-1", soldier_id: "soldier-1", is_reserve: true, attendance_status: "pending", note: null,
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));
    fireEvent.click(await screen.findByTestId("add-soldier-button"));

    fireEvent.click(await screen.findByTestId("reserve-toggle"));
    fireEvent.click(await screen.findByTestId("select-soldier-1"));

    await waitFor(() => expect(rangesApi.addRangeAssignment).toHaveBeenCalledWith("event-1", "soldier-1", true));
  });
});

describe("RangesPage read-only mode for commanders", () => {
  it("hides add/remove controls for a commander (not a duty manager)", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mockUser = { id: "u1", hierarchy_node_id: "node-1", role: "commander", is_commander: true, is_duty_manager: false } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(screen.queryByTestId("add-soldier-button")).not.toBeInTheDocument();
    expect(screen.queryByText("הסר")).not.toBeInTheDocument();
  });

  it("hides the attendance panel for a commander even on a past event", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mockUser = { id: "u1", hierarchy_node_id: "node-1", role: "commander", is_commander: true, is_duty_manager: false } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(useAuth).mockReturnValue({ user: mockUser } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    await waitFor(() => expect(screen.getByText("s1")).toBeInTheDocument());
    expect(screen.queryByTestId("present-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-a1")).not.toBeInTheDocument();
  });
});

describe("RangesPage attendance panel", () => {
  it("shows the attendance panel for a past event when the user can manage", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2020-01-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "completed",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(await screen.findByTestId("present-a1")).toBeInTheDocument();
    expect(screen.getByTestId("no-show-a1")).toBeInTheDocument();
  });

  it("does not show the attendance panel for a future event", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    await waitFor(() => expect(screen.getByText("s1")).toBeInTheDocument());
    expect(screen.queryByTestId("present-a1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("no-show-a1")).not.toBeInTheDocument();
  });
});

describe("RangesPage deep link via ?event=", () => {
  it("auto-selects the event id from the query param without a click", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
    });

    renderWithQuery(<RangesPage />, ["/ranges?event=event-1"]);

    await waitFor(() => expect(rangesApi.getRangeEvent).toHaveBeenCalledWith("event-1"));
    expect(await screen.findAllByText("מטווח דרום")).not.toHaveLength(0);
  });
});
