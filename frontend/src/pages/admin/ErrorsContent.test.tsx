import { expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ErrorsContent } from "./ErrorsContent";
import * as bugReportsApi from "../../api/bugReports";

vi.mock("../../api/bugReports", async () => ({
  ...(await vi.importActual<typeof import("../../api/bugReports")>("../../api/bugReports")),
  listAdminErrors: vi.fn(),
  markAdminErrorsRead: vi.fn().mockResolvedValue(undefined),
  markAllAdminErrorsRead: vi.fn().mockResolvedValue(undefined),
  markAllAdminBugReportsRead: vi.fn().mockResolvedValue(undefined),
}));

function renderContent() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ErrorsContent /></QueryClientProvider>);
}

it("shows correlated errors and expands sanitized details", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "backend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "Unhandled HTTP 500", request_id: "trace-1", details: { msg: "Unhandled HTTP 500", request: { path: "/api/calendar" }, traceback: "RuntimeError: boom" }, record_key: "error-1", unread: false }],
  });
  renderContent();
  await waitFor(() => expect(screen.getByTestId("admin-error-trace-1")).toHaveTextContent("Unhandled HTTP 500"));
  const backendMessage = screen.getByTestId("admin-error-message-trace-1");
  expect(backendMessage.tagName).toBe("P");
  expect(backendMessage).toHaveAttribute("dir", "ltr");
  expect(backendMessage).toHaveClass("text-left");
  expect(screen.queryByText("trace-1")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("admin-error-trace-1").querySelector("button")!);
  expect(screen.getByTestId("admin-error-stack-trace-1")).toHaveTextContent("RuntimeError: boom");
});

it("renders stack trace newlines as real line breaks", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "backend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "boom", request_id: "trace-stack", details: { msg: "Backend summary", request: { path: "/api/boom" }, traceback: "Error: boom\n    at handler (app.py:10)\n    at main (app.py:20)" }, record_key: "error-stack", unread: false }],
  });
  renderContent();
  await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("admin-error-trace-stack").querySelector("button")!);
  const stack = await screen.findByTestId("admin-error-stack-trace-stack");
  expect(stack.textContent).toBe("Error: boom\n    at handler (app.py:10)\n    at main (app.py:20)");
  const path = screen.getByTestId("admin-error-path-trace-stack");
  expect(path).toHaveTextContent("/api/boom");
  expect(path).toHaveAttribute("dir", "ltr");
  expect(path).toHaveClass("text-left");
});

it("shows the frontend message before opening the error", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "frontend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "Frontend error", request_id: "trace-message", details: { msg: "Frontend error", frontend: { message: "The calendar failed\nPlease retry", stack: "Error: failed\n    at render (app.tsx:5)" } }, record_key: "error-message", unread: false }],
  });
  renderContent();
  const message = await screen.findByTestId("admin-error-message-trace-message");
  expect(message.textContent).toBe("The calendar failed\nPlease retry");
  expect(screen.queryByText("Frontend error")).not.toBeInTheDocument();
  fireEvent.click(message);
  expect(await screen.findByTestId("admin-error-stack-trace-message")).toHaveTextContent("Error: failed");
  fireEvent.click(message);
  expect(screen.queryByTestId("admin-error-stack-trace-message")).not.toBeInTheDocument();
});

it("shows the frontend request method and URL in the collapsed description", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "frontend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "Frontend error", request_id: "trace-request", details: { frontend: { message: "Request failed", method: "delete", url: "/admin/errors" } }, record_key: "error-request", unread: false }],
  });
  renderContent();
  const description = await screen.findByTestId("admin-error-message-trace-request");
  expect(description).toHaveTextContent("Request failed");
  expect(description).toHaveAttribute("dir", "ltr");
  expect(description).toHaveClass("text-left");
  const request = screen.getByTestId("admin-error-request-trace-request");
  expect(request).toHaveTextContent("DELETE /admin/errors");
  expect(request).toHaveAttribute("dir", "ltr");
  expect(request).toHaveClass("text-left");
  expect(description.compareDocumentPosition(request) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("copies each expanded code block", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.assign(navigator, { clipboard: { writeText } });
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "backend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "boom", request_id: "trace-copy", details: { msg: "boom", traceback: "line 1\nline 2" }, record_key: "error-copy", unread: false }],
  });
  renderContent();
  await waitFor(() => expect(screen.getByTestId("admin-error-trace-copy")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("admin-error-trace-copy").querySelector("button")!);
  fireEvent.click(screen.getByTestId("admin-error-copy-stack-trace-copy"));
  fireEvent.click(screen.getByTestId("admin-error-copy-json-trace-copy"));
  await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2));
});

it("shows a temporary checkmark after copying", async () => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "backend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "boom", request_id: "trace-feedback", details: { traceback: "line 1" }, record_key: "error-feedback", unread: false }],
  });
  renderContent();
  await waitFor(() => expect(screen.getByTestId("admin-error-trace-feedback")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("admin-error-trace-feedback").querySelector("button")!);
  const copyButton = screen.getByTestId("admin-error-copy-stack-trace-feedback");
  vi.useFakeTimers();
  try {
    await act(async () => {
      fireEvent.click(copyButton);
      await Promise.resolve();
    });
    expect(copyButton).toHaveAttribute("aria-label", "הועתק");
    expect(screen.getByTestId("admin-error-copy-success-stack-trace-feedback")).toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(copyButton).toHaveAttribute("aria-label", "העתק");
  } finally {
    vi.useRealTimers();
  }
});

it("renders multiline messages and marks an unread error read when opened", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({
    total: 1,
    items: [{ source: "frontend", timestamp: "2026-08-28T10:00:00Z", level: "ERROR", message: "Frontend error", request_id: "trace-2", details: { frontend: { message: "first line\nsecond line" } }, record_key: "error-2", unread: true }],
  });
  renderContent();
  await waitFor(() => expect(screen.getByText(/first line/)).toBeInTheDocument());
  expect(screen.getByTestId("admin-error-unread-error-2")).toBeInTheDocument();
  fireEvent.click(screen.getByText(/first line/));
  await waitFor(() => expect(bugReportsApi.markAdminErrorsRead).toHaveBeenCalledWith([{ record_key: "error-2", source: "frontend" }]));
  expect(screen.queryByTestId("admin-error-unread-error-2")).not.toBeInTheDocument();
});

it("marks all errors read using the active filters", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({ total: 1, items: [] });
  renderContent();
  const from = await screen.findByTestId("admin-errors-from");
  fireEvent.change(from, { target: { value: "2026-08-28T10:00" } });
  fireEvent.click(await screen.findByTestId("admin-errors-mark-all-read"));
  await waitFor(() => expect(bugReportsApi.markAllAdminErrorsRead).toHaveBeenCalledWith(expect.objectContaining({ from: expect.any(String) })));
  expect(bugReportsApi.markAllAdminBugReportsRead).not.toHaveBeenCalled();
});

it("clears each datetime picker with its small clear button", async () => {
  vi.mocked(bugReportsApi.listAdminErrors).mockResolvedValue({ total: 0, items: [] });
  renderContent();
  const from = screen.getByLabelText("מתאריך");
  fireEvent.change(from, { target: { value: "2026-08-28T10:00" } });
  const clear = await screen.findByRole("button", { name: "נקה תאריך התחלה" });
  fireEvent.click(clear);
  expect(from).toHaveValue("");
});
