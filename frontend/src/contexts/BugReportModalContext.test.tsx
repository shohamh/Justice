import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { BugReportModalProvider, useBugReportModal } from "./BugReportModalContext";

vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn(),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
  getMyBugReports: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listComments: vi.fn().mockResolvedValue([]),
  createComment: vi.fn(),
  uploadCommentAttachment: vi.fn(),
  bugReportCommentAttachmentDownloadUrl: vi.fn(() => ""),
}));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

function Consumer() {
  const { openBugReportModal } = useBugReportModal();
  return <button onClick={() => openBugReportModal()} data-testid="open">open</button>;
}

function renderProvider() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BugReportModalProvider", () => {
  it("renders no modal until openBugReportModal is called", () => {
    renderProvider();
    expect(screen.queryByTestId("bug-report-modal-overlay")).not.toBeInTheDocument();
  });

  it("opens the modal when openBugReportModal is called", async () => {
    renderProvider();
    fireEvent.click(screen.getByTestId("open"));
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
  });

  it("opens automatically from a bugReport query param on mount, then strips it from the URL", async () => {
    window.history.pushState({}, "", "/?bugReport=r1");
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/?bugReport=r1"]}>
          <BugReportModalProvider><Consumer /></BugReportModalProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });
});
