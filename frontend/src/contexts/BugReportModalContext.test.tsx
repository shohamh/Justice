import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { BugReportModalProvider, useBugReportModal } from "./BugReportModalContext";

vi.mock("../api/bugReports", () => ({
  submitBugReport: vi.fn(),
  getMyBugReportsUnseenCount: vi.fn().mockResolvedValue({ count: 0 }),
}));
vi.mock("../hooks/useNavigationHistory", () => ({ useNavigationHistory: () => [] }));

function Consumer() {
  const { openBugReportModal } = useBugReportModal();
  return <button onClick={() => openBugReportModal()} data-testid="open">open</button>;
}

describe("BugReportModalProvider", () => {
  it("renders no modal until openBugReportModal is called", () => {
    render(
      <MemoryRouter>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("bug-report-modal-overlay")).not.toBeInTheDocument();
  });

  it("opens the modal when openBugReportModal is called", async () => {
    render(
      <MemoryRouter>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("open"));
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
  });

  it("opens automatically from a bugReport query param on mount, then strips it from the URL", async () => {
    window.history.pushState({}, "", "/?bugReport=r1");
    render(
      <MemoryRouter initialEntries={["/?bugReport=r1"]}>
        <BugReportModalProvider><Consumer /></BugReportModalProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("bug-report-modal-overlay")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });
});
