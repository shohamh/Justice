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
      items: [{ id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null }],
    });
    vi.mocked(hrReviewApi.listDivergences).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listVanished).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listRankConflicts).mockResolvedValue({ items: [] });
    vi.mocked(hrReviewApi.listSyncRuns).mockResolvedValue({ person_syncs: [], hierarchy_syncs: [] });
    vi.mocked(hrReviewApi.dismissHeldForReview).mockResolvedValue({
      id: "1", personal_number: "123", review_reason: "bad date", last_synced_at: null,
    });
  });

  it("shows the held-for-review section with the fetched item", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("123")).toBeInTheDocument());
  });

  it("dismisses a held-for-review item on button click", async () => {
    renderWithClient();
    await waitFor(() => expect(screen.getByText("123")).toBeInTheDocument());
    const button = screen.getByTestId("hr-sync-dismiss-1");
    fireEvent.click(button);
    await waitFor(() => expect(hrReviewApi.dismissHeldForReview).toHaveBeenCalledWith("1"));
  });

  it("triggers a manual sync run when the run-now button is clicked", async () => {
    vi.mocked(hrReviewApi.runSyncNow).mockResolvedValue({ hierarchy_sync_id: "h1", person_sync_id: "p1" });
    renderWithClient();
    await waitFor(() => expect(screen.getByText("123")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("hr-sync-run-now"));
    await waitFor(() => expect(hrReviewApi.runSyncNow).toHaveBeenCalled());
  });
});
