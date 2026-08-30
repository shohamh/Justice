import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../i18n";
import { AdminInviteCodesContent } from "./AdminInviteCodesPage";
import * as inviteCodesApi from "../api/inviteCodes";

vi.mock("../api/inviteCodes", async () => {
  const actual = await vi.importActual<typeof import("../api/inviteCodes")>("../api/inviteCodes");
  return {
    ...actual,
    listInviteCodes: vi.fn(),
  };
});

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminInviteCodesContent />
    </QueryClientProvider>,
  );
}

describe("AdminInviteCodesContent", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText: vi.fn() },
    });
    vi.mocked(inviteCodesApi.listInviteCodes).mockResolvedValue([
      { id: "active-id", code: "ACTIVE-123", uses_left: 3, created_by: null },
      { id: "revoked-id", code: "REVOKED-456", uses_left: 0, created_by: null },
    ]);
  });

  it("copies the exact active invite code and shows a Hebrew success state", async () => {
    vi.mocked(navigator.clipboard.writeText).mockResolvedValue(undefined);
    renderPage();

    const copyButton = await screen.findByRole("button", { name: "העתקת קוד ACTIVE-123" });
    fireEvent.click(copyButton);

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("ACTIVE-123"));
    expect(await screen.findByText("הועתק")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE-123")).toBeInTheDocument();
  });

  it("shows an actionable error when copying fails and keeps the revoked row usable", async () => {
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new Error("clipboard blocked"));
    renderPage();

    const copyButton = await screen.findByRole("button", { name: "העתקת קוד REVOKED-456" });
    fireEvent.click(copyButton);

    expect(await screen.findByText("לא ניתן להעתיק — נסה שוב")).toBeInTheDocument();
    expect(screen.getByText("REVOKED-456")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "בטל" })).toHaveLength(2);
  });

  it("does not crash when the invite-code endpoint returns a non-array payload", async () => {
    vi.mocked(inviteCodesApi.listInviteCodes).mockResolvedValue({ unexpected: true } as never);

    renderPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("ACTIVE-123")).not.toBeInTheDocument();
  });
});
