import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import "../i18n";
import NotificationsPage from "./NotificationsPage";
import { listNotifications } from "../api/notifications";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock("../api/notifications", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/notifications")>()),
  listNotifications: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <NotificationsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("NotificationsPage", () => {
  beforeEach(() => {
    navigate.mockReset();
    vi.mocked(listNotifications).mockResolvedValue({
      items: [{
        id: "notification-1",
        soldier_id: "soldier-1",
        title: "תגובה חדשה לדיווח באג",
        body: null,
        type: "bug_report_comment",
        reference_type: "bug_report",
        reference_id: "report-123",
        is_read: false,
        created_at: "2026-08-03T12:00:00Z",
      }],
      total: 1,
    });
  });

  it("opens the referenced bug report from its notification", async () => {
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "תגובה חדשה לדיווח באג" }));

    expect(navigate).toHaveBeenCalledWith("/my-bug-reports?report=report-123");
  });
});
