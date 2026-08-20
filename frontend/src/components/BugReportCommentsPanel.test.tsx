import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import BugReportCommentsPanel from "./BugReportCommentsPanel";
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
  attachments: [{ id: "att1", file_name: "photo.png", content_type: "image/png" }],
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BugReportCommentsPanel reportId="r1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(bugReportsApi.listComments).mockResolvedValue([comment]);
  vi.mocked(api.get).mockResolvedValue({ data: new Blob() });
});

describe("BugReportCommentsPanel", () => {
  it("shows a loading state while comments are loading", () => {
    vi.mocked(bugReportsApi.listComments).mockReturnValue(new Promise(() => {}));

    renderPanel();

    expect(screen.getByText("app.loading")).toBeInTheDocument();
  });

  it("shows an empty state when the report has no comments", async () => {
    vi.mocked(bugReportsApi.listComments).mockResolvedValue([]);

    renderPanel();

    expect(await screen.findByText("bug_reports.no_comments")).toBeInTheDocument();
  });

  it("renders an existing comment and attachment fallback", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network error"));

    renderPanel();

    expect(await screen.findByText("hello")).toBeInTheDocument();
    expect(await screen.findByTestId("attachment-thumbnail-fallback")).toBeInTheDocument();
  });

  it("sends a typed comment and refreshes its list", async () => {
    vi.mocked(bugReportsApi.createComment).mockResolvedValue({ ...comment, id: "c2" });

    renderPanel();

    const textarea = await screen.findByPlaceholderText("bug_reports.comment_placeholder");
    fireEvent.change(textarea, { target: { value: "a comment" } });
    fireEvent.click(screen.getByRole("button", { name: "bug_reports.send" }));

    await waitFor(() => expect(bugReportsApi.createComment).toHaveBeenCalledWith("r1", "a comment"));
    expect(textarea).toHaveValue("");
    expect(bugReportsApi.listComments).toHaveBeenCalledTimes(2);
  });

  it("sends the comment on Ctrl+Enter without inserting a newline", async () => {
    vi.mocked(bugReportsApi.createComment).mockResolvedValue({ ...comment, id: "c2" });

    renderPanel();

    const textarea = await screen.findByPlaceholderText("bug_reports.comment_placeholder");
    fireEvent.change(textarea, { target: { value: "a comment" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });

    await waitFor(() => expect(bugReportsApi.createComment).toHaveBeenCalledWith("r1", "a comment"));
    expect(textarea).toHaveValue("");
  });

  it("opens an image attachment in a fullscreen preview modal when clicked", async () => {
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn();
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();
    const createObjectURLSpy = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake-url");
    const revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    renderPanel();

    const thumbnail = await screen.findByAltText("bug_reports.attachment_preview_alt");
    fireEvent.click(thumbnail);

    expect(await screen.findByText("הורדה")).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();

    createObjectURLSpy.mockRestore();
    revokeObjectURLSpy.mockRestore();
  });

  it("offers a retry after an attachment upload fails and clears it after success", async () => {
    vi.mocked(bugReportsApi.createComment).mockResolvedValue({ ...comment, id: "c2" });
    vi.mocked(bugReportsApi.uploadCommentAttachment)
      .mockRejectedValueOnce(new Error("upload failed"))
      .mockResolvedValueOnce(undefined);

    const { container } = renderPanel();

    const textarea = await screen.findByPlaceholderText("bug_reports.comment_placeholder");
    fireEvent.change(textarea, { target: { value: "a comment" } });
    const file = new File(["data"], "photo.png", { type: "image/png" });
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "bug_reports.send" }));

    expect(await screen.findByText(/attachment_upload_failed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /נסה שוב/ }));

    await waitFor(() => expect(screen.queryByText(/attachment_upload_failed/i)).not.toBeInTheDocument());
    expect(bugReportsApi.uploadCommentAttachment).toHaveBeenCalledTimes(2);
  });
});
