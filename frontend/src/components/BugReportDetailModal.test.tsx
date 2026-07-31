import { render, screen } from "@testing-library/react";
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
