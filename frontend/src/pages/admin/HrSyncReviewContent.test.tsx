import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import HrSyncReviewContent from "./HrSyncReviewContent";
import * as hrReviewApi from "../../api/hrReview";

vi.mock("../../api/hrReview");

function renderWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <HrSyncReviewContent />
    </QueryClientProvider>
  );
}

describe("HrSyncReviewContent", () => {
  beforeEach(() => {
    vi.mocked(hrReviewApi.listHeldForReview).mockResolvedValue({
      items: [{
        id: "1", personal_number: "123",
        review_reason: "unmappable gender: 'X'; unparseable dateOfBirth: 'Y'",
        last_synced_at: null,
        raw_dto: { fullName: "ישראל ישראלי", rank: "bad-value" },
      }],
    });
    vi.mocked(hrReviewApi.listDivergences).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listVanished).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listRankConflicts).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listSyncRuns).mockResolvedValue({ person_syncs: [], hierarchy_syncs: [] });
    vi.mocked(hrReviewApi.dismissHeldForReview).mockResolvedValue({
      id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null, raw_dto: null,
    });
  });

  it("shows the held-for-review section with the fetched item", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
  });

  it("dismisses a held-for-review item on button click", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
    const button = screen.getByTestId("hr-sync-dismiss-1");
    fireEvent.click(button);
    await waitFor(() => expect(hrReviewApi.dismissHeldForReview).toHaveBeenCalledWith("1"));
  });

  it("triggers a manual sync run when the run-now button is clicked", async () => {
    vi.mocked(hrReviewApi.runSyncNow).mockResolvedValue({ hierarchy_sync_id: "h1", person_sync_id: "p1" });
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("hr-sync-run-now"));
    await waitFor(() => expect(hrReviewApi.runSyncNow).toHaveBeenCalled());
  });

  it("shows an error message when the run-now mutation fails", async () => {
    vi.mocked(hrReviewApi.runSyncNow).mockRejectedValue(new Error("hr_sync_already_running"));
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("hr-sync-run-now"));
    await waitFor(() => expect(screen.getByTestId("hr-sync-run-now-error")).toHaveTextContent("hr_sync_already_running"));
  });

  it("shows a load error when a query fails", async () => {
    vi.mocked(hrReviewApi.listVanished).mockRejectedValue(new Error("boom"));
    renderWithClient();
    await waitFor(() => expect(screen.getByTestId("hr-sync-vanished-table-error")).toBeInTheDocument());
  });

  it("opens the raw payload detail modal for a held-for-review row", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("hr-sync-held-detail-1"));
    await waitFor(() => expect(screen.getByTestId("hr-sync-held-detail-modal")).toBeInTheDocument());
    expect(screen.getByTestId("hr-sync-held-detail-raw-dto")).toHaveTextContent("bad-value");
  });

  it("shows the soldier's name and each reason as its own bullet in the detail modal", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("ישראל ישראלי · 123")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("hr-sync-held-detail-1"));
    const modal = await screen.findByTestId("hr-sync-held-detail-modal");
    expect(modal).toHaveTextContent("ישראל ישראלי");
    const reasons = screen.getByTestId("hr-sync-held-detail-reasons");
    expect(reasons.children).toHaveLength(2);
    expect(reasons).toHaveTextContent("unmappable gender: 'X'");
    expect(reasons).toHaveTextContent("unparseable dateOfBirth: 'Y'");
  });

  it("shows soldier identity and can expand run errors", async () => {
    vi.mocked(hrReviewApi.listRankConflicts).mockResolvedValue({
      items: [{
        id: "c1", soldier_id: "s1", soldier_full_name: "ישראל ישראלי", soldier_personal_number: "1234567",
        old_rank: "טוראי", new_rank: "סמל", triggered_by_worker_decision: true, non_sequential_jump: false,
        created_at: "2026-01-01T00:00:00Z",
      }],
    });
    vi.mocked(hrReviewApi.listSyncRuns).mockResolvedValue({
      person_syncs: [{
        id: "r1", status: "completed", started_at: "2026-01-01T00:00:00Z", completed_at: null,
        total_fetched: 10, created_count: 1, updated_count: 1, held_count: 0, vanished_count: 0,
        error_count: 1, error_message: null,
        errors: [{ personal_number: "999", error_message: "bad row" }],
      }],
      hierarchy_syncs: [],
    });
    renderWithClient();
    await waitFor(() => expect(screen.getAllByText(/ישראל ישראלי/).length).toBeGreaterThan(0));
    expect(screen.getByTestId("hr-sync-conflicts-table")).toHaveTextContent("ישראל ישראלי · 1234567");
    fireEvent.click(screen.getByTestId("hr-sync-run-errors-r1"));
    await waitFor(() => expect(screen.getByTestId("hr-sync-run-errors-modal")).toBeInTheDocument());
    expect(screen.getByTestId("hr-sync-run-errors-modal")).toHaveTextContent("bad row");
  });
});
