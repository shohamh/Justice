import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import BugReportDetailModal from "./BugReportDetailModal";
import * as bugReportsApi from "../api/bugReports";
import { api } from "../api/client";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("../api/bugReports", async () => {
  const actual = await vi.importActual<typeof import("../api/bugReports")>("../api/bugReports");
  return {
    ...actual,
    listComments: vi.fn(),
    createComment: vi.fn(),
    uploadCommentAttachment: vi.fn(),
  };
});

vi.mock("../api/client", () => ({
  api: { get: vi.fn() },
}));

const comment = {
  id: "c1",
  bug_report_id: "r1",
  author_id: "a1",
  author_name: "Author",
  body: "hello",
  created_at: "2026-01-01T00:00:00Z",
  attachments: [{ id: "att1", file_name: "photo.png" }],
};

function renderModal() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BugReportDetailModal reportId="r1" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bugReportsApi.listComments).mockResolvedValue([comment]);
});

describe("BugReportDetailModal - attachment thumbnail failure", () => {
  it("shows a fallback icon when the attachment thumbnail fails to load", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network error"));

    renderModal();

    expect(await screen.findByTestId("attachment-thumbnail-fallback")).toBeInTheDocument();
  });
});

describe("BugReportDetailModal - attachment upload retry", () => {
  it("offers a retry button when the attachment upload fails, and retrying succeeds", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });
    vi.mocked(bugReportsApi.createComment).mockResolvedValue({ ...comment, id: "c2" });
    vi.mocked(bugReportsApi.uploadCommentAttachment)
      .mockRejectedValueOnce(new Error("upload failed"))
      .mockResolvedValueOnce(undefined);

    const { container } = renderModal();

    const textarea = await screen.findByPlaceholderText("bug_reports.comment_placeholder");
    fireEvent.change(textarea, { target: { value: "a comment" } });

    const file = new File(["data"], "photo.png", { type: "image/png" });
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    const sendButton = screen.getByRole("button", { name: "bug_reports.send" });
    fireEvent.click(sendButton);

    expect(await screen.findByText(/attachment_upload_failed/i)).toBeInTheDocument();
    const retryButton = screen.getByRole("button", { name: /נסה שוב/ });
    fireEvent.click(retryButton);

    await waitFor(() => expect(screen.queryByText(/attachment_upload_failed/i)).not.toBeInTheDocument());
    expect(bugReportsApi.uploadCommentAttachment).toHaveBeenCalledTimes(2);
    expect(bugReportsApi.createComment).toHaveBeenCalledTimes(1);
  });

  it("does not let a stale retry for an earlier comment clobber a newer comment's failure state", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: new Blob() });

    // Comment A's attachment fails immediately; comment B (sent later, while
    // A's retry is still in flight) also fails, but B's upload never
    // resolves in this test so we can assert on B's state afterward.
    vi.mocked(bugReportsApi.createComment)
      .mockResolvedValueOnce({ ...comment, id: "cA" })
      .mockResolvedValueOnce({ ...comment, id: "cB" });

    let resolveRetryA: (() => void) | undefined;
    const retryAPromise = new Promise<void>((resolve) => {
      resolveRetryA = () => resolve();
    });

    vi.mocked(bugReportsApi.uploadCommentAttachment)
      // Initial upload for comment A fails.
      .mockRejectedValueOnce(new Error("upload A failed"))
      // Retry for comment A: stays pending (and eventually *succeeds*) until
      // resolveRetryA() is called. This is the scenario that actually
      // clobbers newer state on the old buggy code: an unconditional success
      // handler wipes out whatever failure is currently displayed, even if
      // it belongs to a different, newer comment.
      .mockImplementationOnce(() => retryAPromise)
      // Initial upload for comment B fails.
      .mockRejectedValueOnce(new Error("upload B failed"));

    const { container } = renderModal();

    const textarea = await screen.findByPlaceholderText("bug_reports.comment_placeholder");
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const sendButton = screen.getByRole("button", { name: "bug_reports.send" });

    // Send comment A; its attachment upload fails.
    fireEvent.change(textarea, { target: { value: "comment A" } });
    const fileA = new File(["data"], "photoA.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [fileA] } });
    fireEvent.click(sendButton);
    expect(await screen.findByText(/attachment_upload_failed/i)).toBeInTheDocument();

    // Kick off a retry for A — it will hang until resolveRetryA() is called.
    const retryButton = screen.getByRole("button", { name: /נסה שוב/ });
    fireEvent.click(retryButton);

    // While A's retry is in flight, send comment B; its attachment also fails.
    fireEvent.change(textarea, { target: { value: "comment B" } });
    const fileB = new File(["data"], "photoB.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [fileB] } });
    fireEvent.click(sendButton);

    await waitFor(() => expect(bugReportsApi.uploadCommentAttachment).toHaveBeenCalledTimes(3));
    await screen.findByText(/attachment_upload_failed/i);

    // Now let A's stale retry resolve successfully. It must not clobber B's
    // freshly-set failure state: B's error/retry button must survive, even
    // though A's retry "succeeded". A's success path always re-invalidates
    // the comments query, so waiting for that 4th listComments call is a
    // reliable sync point for "A's post-await handling has now run" in both
    // the buggy and fixed implementations.
    resolveRetryA?.();
    await waitFor(() => expect(bugReportsApi.listComments).toHaveBeenCalledTimes(4));
    // Let the state updates that immediately follow the invalidate settle.
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.getByText(/attachment_upload_failed/i)).toBeInTheDocument();
    const retryButtonAfter = screen.getByRole("button", { name: /נסה שוב/ });
    expect(retryButtonAfter).not.toBeDisabled();

    // Retrying now must re-upload B's file, not A's — proving `failedUpload`
    // still points at B.
    fireEvent.click(retryButtonAfter);
    await waitFor(() => expect(bugReportsApi.uploadCommentAttachment).toHaveBeenCalledTimes(4));
    expect(bugReportsApi.uploadCommentAttachment).toHaveBeenNthCalledWith(4, "r1", "cB", fileB);
  });
});
