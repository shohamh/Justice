import "../i18n";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import AnnouncementsPage from "./AnnouncementsPage";
import * as announcementsApi from "../api/announcements";
import { useAuth } from "../auth/AuthContext";

vi.mock("../api/announcements");
vi.mock("../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("../auth/AuthContext");

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AnnouncementsPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({ items: [], total: 0 });
});

describe("AnnouncementsPage — commander/DM (scoped)", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u1", role: "duty_manager", is_commander: false, is_duty_manager: true },
    } as ReturnType<typeof useAuth>);
    vi.mocked(announcementsApi.getAnnounceScope).mockResolvedValue([
      { id: "node-1", name: "יחידה א", level: "unit" },
    ]);
  });

  it("defaults to sending to the caller's whole scope and submits with that node id", async () => {
    vi.mocked(announcementsApi.postAnnouncement).mockResolvedValue({ id: "ann-1", sent: 5 });
    renderPage();
    await waitFor(() => expect(announcementsApi.getAnnounceScope).toHaveBeenCalled());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("כותרת"), "בדיקה");
    await user.click(screen.getByRole("button", { name: "שלח הכרזה" }));
    await waitFor(() =>
      expect(announcementsApi.postAnnouncement).toHaveBeenCalledWith({
        title: "בדיקה",
        body: undefined,
        hierarchy_node_ids: ["node-1"],
      })
    );
  });
});

describe("AnnouncementsPage — admin (org-wide default)", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u2", role: "admin", is_commander: false, is_duty_manager: false },
    } as ReturnType<typeof useAuth>);
  });

  it("submits with no hierarchy_node_ids by default", async () => {
    vi.mocked(announcementsApi.postAnnouncement).mockResolvedValue({ id: "ann-2", sent: 42 });
    renderPage();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("כותרת"), "הודעה לכולם");
    await user.click(screen.getByRole("button", { name: "שלח הכרזה" }));
    await waitFor(() =>
      expect(announcementsApi.postAnnouncement).toHaveBeenCalledWith({
        title: "הודעה לכולם",
        body: undefined,
        hierarchy_node_ids: undefined,
      })
    );
  });
});

describe("AnnouncementsPage — history list", () => {
  beforeEach(() => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u2", role: "admin", is_commander: false, is_duty_manager: false },
    } as ReturnType<typeof useAuth>);
  });

  it("shows sent announcements with read/recipient counts", async () => {
    vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({
      items: [{
        id: "ann-3", title: "עדכון", body: null, type: "system_announcement",
        hierarchy_node_ids: null, recipient_count: 10, read_count: 3,
        created_at: new Date().toISOString(),
      }],
      total: 1,
    });
    renderPage();
    expect(await screen.findByText("עדכון")).toBeInTheDocument();
    expect(screen.getByText("3 מתוך 10 קראו")).toBeInTheDocument();
  });

  it("fetches and displays recipients when expanded", async () => {
    vi.mocked(announcementsApi.listAnnouncements).mockResolvedValue({
      items: [{
        id: "ann-4", title: "עדכון 2", body: null, type: "announcement",
        hierarchy_node_ids: ["node-1"], recipient_count: 1, read_count: 0,
        created_at: new Date().toISOString(),
      }],
      total: 1,
    });
    vi.mocked(announcementsApi.getAnnouncementRecipients).mockResolvedValue([
      { soldier_id: "s1", full_name: "דני כהן", is_read: false, read_at: null },
    ]);
    renderPage();
    await screen.findByText("עדכון 2");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "הצג נמענים" }));
    expect(await screen.findByText("דני כהן")).toBeInTheDocument();
    expect(screen.getByText("לא נקרא")).toBeInTheDocument();
  });
});
