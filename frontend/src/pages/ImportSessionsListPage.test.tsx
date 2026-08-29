import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ImportSessionsListPage from "./ImportSessionsListPage";
import * as importSessionsApi from "../api/importSessions";
import type { SessionSummary } from "../api/importSessions";

vi.mock("../api/importSessions");

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockSessions: SessionSummary[] = [
  {
    id: "draft-1",
    status: "draft",
    filename: "draft-file.xlsx",
    created_at: "2026-06-30T10:00:00Z",
    row_summary: { soldiers: 2, duty_shifts: 1 },
  },
  {
    id: "confirmed-1",
    status: "confirmed",
    filename: "confirmed-file.xlsx",
    created_at: "2026-06-29T10:00:00Z",
    row_summary: { soldiers: 3, duty_shifts: 0 },
  },
  {
    id: "done-1",
    status: "done",
    filename: "done-file.xlsx",
    created_at: "2026-06-28T10:00:00Z",
    row_summary: { soldiers: 1, duty_shifts: 1 },
  },
  {
    id: "cancelled-1",
    status: "cancelled",
    filename: "cancelled-file.xlsx",
    created_at: "2026-06-27T10:00:00Z",
    row_summary: { soldiers: 0, duty_shifts: 0 },
  },
];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ImportSessionsListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ImportSessionsListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(importSessionsApi.listSessions).mockResolvedValue(mockSessions);
    vi.mocked(importSessionsApi.cancelSession).mockResolvedValue(undefined);
    vi.mocked(importSessionsApi.markSessionDone).mockResolvedValue(undefined);
  });

  it("renders session rows with correct filename and status label", async () => {
    renderPage();

    expect(await screen.findByText("draft-file.xlsx")).toBeInTheDocument();
    expect(screen.getByText("confirmed-file.xlsx")).toBeInTheDocument();
    expect(screen.getByText("done-file.xlsx")).toBeInTheDocument();
    expect(screen.getByText("cancelled-file.xlsx")).toBeInTheDocument();

    expect(screen.getByText("טיוטה")).toBeInTheDocument();
    expect(screen.getByText("אושר")).toBeInTheDocument();
    expect(screen.getByText("בוצע")).toBeInTheDocument();
    expect(screen.getByText("בוטל")).toBeInTheDocument();
  });

  it("shows correct action buttons per row status", async () => {
    renderPage();
    await screen.findByText("draft-file.xlsx");

    const draftRow = screen.getByText("draft-file.xlsx").closest("tr")!;
    expect(within(draftRow).getByText("המשך")).toBeInTheDocument();
    expect(within(draftRow).getByText("בטל")).toBeInTheDocument();

    const confirmedRow = screen.getByText("confirmed-file.xlsx").closest("tr")!;
    expect(within(confirmedRow).getByText("צפה")).toBeInTheDocument();
    expect(within(confirmedRow).getByText("סמן כבוצע")).toBeInTheDocument();

    const doneRow = screen.getByText("done-file.xlsx").closest("tr")!;
    expect(within(doneRow).getByText("צפה")).toBeInTheDocument();
    expect(within(doneRow).queryByText("סמן כבוצע")).not.toBeInTheDocument();
    expect(within(doneRow).queryByText("המשך")).not.toBeInTheDocument();

    const cancelledRow = screen.getByText("cancelled-file.xlsx").closest("tr")!;
    expect(within(cancelledRow).getByText("צפה")).toBeInTheDocument();
    expect(within(cancelledRow).queryByText("בטל")).not.toBeInTheDocument();
  });

  it("calls listSessions with no filter by default and with broader filter when toggled", async () => {
    renderPage();
    await screen.findByText("draft-file.xlsx");

    expect(importSessionsApi.listSessions).toHaveBeenCalledWith(undefined);

    const toggle = screen.getByLabelText("הצג הכל (כולל בוצע/בוטל)");
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(importSessionsApi.listSessions).toHaveBeenCalledWith(
        "draft,confirmed,cancelled,done",
      );
    });
  });

  it("opens a translated confirmation and cancels only after confirmation", async () => {
    renderPage();
    await screen.findByText("draft-file.xlsx");

    const draftRow = screen.getByText("draft-file.xlsx").closest("tr")!;
    fireEvent.click(within(draftRow).getByText("בטל"));

    expect(importSessionsApi.cancelSession).not.toHaveBeenCalled();
    expect(screen.getByText("ביטול טיוטת ייבוא")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));

    await waitFor(() => {
      expect(importSessionsApi.cancelSession).toHaveBeenCalledWith("draft-1");
    });
  });

  it("calls markSessionDone and reloads when 'סמן כבוצע' is clicked", async () => {
    renderPage();
    await screen.findByText("confirmed-file.xlsx");

    const confirmedRow = screen.getByText("confirmed-file.xlsx").closest("tr")!;
    fireEvent.click(within(confirmedRow).getByText("סמן כבוצע"));

    await waitFor(() => {
      expect(importSessionsApi.markSessionDone).toHaveBeenCalledWith(
        "confirmed-1",
      );
    });
  });

  it("shows an error banner and stops loading when listSessions rejects", async () => {
    vi.mocked(importSessionsApi.listSessions).mockRejectedValue(new Error("boom"));
    renderPage();

    expect(
      await screen.findByText("שגיאה בטעינת רשימת הייבואים"),
    ).toBeInTheDocument();
    expect(screen.getByText("אין ייבואים להצגה")).toBeInTheDocument();
  });

  it("does not call cancelSession when the confirmation is dismissed", async () => {
    renderPage();
    await screen.findByText("draft-file.xlsx");

    const draftRow = screen.getByText("draft-file.xlsx").closest("tr")!;
    fireEvent.click(within(draftRow).getByText("בטל"));

    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(importSessionsApi.cancelSession).not.toHaveBeenCalled();
  });

  it("shows a message dialog when cancelSession rejects", async () => {
    vi.mocked(importSessionsApi.cancelSession).mockRejectedValue({
      response: { data: { detail: "only_draft_sessions_can_be_cancelled" } },
    });
    renderPage();
    await screen.findByText("draft-file.xlsx");

    const draftRow = screen.getByText("draft-file.xlsx").closest("tr")!;
    fireEvent.click(within(draftRow).getByText("בטל"));
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));

    expect(await screen.findByText("שגיאה בביטול הייבוא")).toBeInTheDocument();
  });

  it("shows a message dialog when markSessionDone rejects without a detail message", async () => {
    vi.mocked(importSessionsApi.markSessionDone).mockRejectedValue(new Error("boom"));
    renderPage();
    await screen.findByText("confirmed-file.xlsx");

    const confirmedRow = screen.getByText("confirmed-file.xlsx").closest("tr")!;
    fireEvent.click(within(confirmedRow).getByText("סמן כבוצע"));

    expect(await screen.findByText("שגיאה בעדכון הייבוא")).toBeInTheDocument();
  });
});
