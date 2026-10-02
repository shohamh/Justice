import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../../i18n";
import IdentityConflictsContent from "./IdentityConflictsContent";
import * as api from "../../api/identityConflicts";
import type { IdentityConflictDTO } from "../../api/identityConflicts";

vi.mock("../../api/identityConflicts");

function conflict(overrides: Partial<IdentityConflictDTO> = {}): IdentityConflictDTO {
  return {
    id: "c1", source: "sso", status: "open", ad_username: "dude", personal_number: null,
    created_at: "2026-10-02T08:00:00Z", resolved_at: null, chosen_soldier_id: null, resolution_note: null,
    candidates: [
      { soldier_id: "s1", full_name: "דני כהן", personal_number: "1111111", email_masked: "d***@corp.example", matched_fields: ["email"], active: true },
      { soldier_id: "s2", full_name: "דנה לוי", personal_number: "2222222", email_masked: "d***@other.example", matched_fields: ["ad_username"], active: false },
    ],
    ...overrides,
  };
}

function renderContent() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <IdentityConflictsContent />
    </QueryClientProvider>,
  );
}

function axiosDetail(detail: string, status = 409) {
  return Object.assign(new Error("req failed"), { response: { status, data: { detail } } });
}

describe("IdentityConflictsContent", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.listIdentityConflicts).mockResolvedValue({ items: [conflict()] });
  });

  it("requests only open conflicts", async () => {
    renderContent();
    await screen.findByTestId("identity-conflict-c1");
    expect(api.listIdentityConflicts).toHaveBeenCalledWith("open");
  });

  it("shows an empty state", async () => {
    vi.mocked(api.listIdentityConflicts).mockResolvedValue({ items: [] });
    renderContent();
    expect(await screen.findByTestId("identity-conflicts-empty")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.mocked(api.listIdentityConflicts).mockRejectedValue(new Error("boom"));
    renderContent();
    expect(await screen.findByTestId("identity-conflicts-error")).toBeInTheDocument();
  });

  it("lists candidates with masked emails and an inactive marker", async () => {
    renderContent();
    const card = await screen.findByTestId("identity-conflict-c1");
    expect(within(card).getByText("dude")).toBeInTheDocument();
    const first = within(card).getByTestId("identity-candidate-c1-s1");
    expect(within(first).getByText(/דני כהן/)).toBeInTheDocument();
    expect(within(first).getByText("d***@corp.example")).toBeInTheDocument();
    expect(within(first).queryByTestId("identity-inactive-c1-s1")).toBeNull();
    expect(within(screen.getByTestId("identity-candidate-c1-s2")).getByTestId("identity-inactive-c1-s2")).toBeInTheDocument();
  });

  it("resolves to the chosen soldier", async () => {
    vi.mocked(api.resolveIdentityConflict).mockResolvedValue(conflict({ status: "resolved" }));
    renderContent();
    fireEvent.click(await screen.findByTestId("identity-resolve-c1-s1"));
    await waitFor(() => expect(api.resolveIdentityConflict).toHaveBeenCalledWith("c1", "s1"));
  });

  it("requires a reason before dismissing, then dismisses", async () => {
    vi.mocked(api.dismissIdentityConflict).mockResolvedValue(conflict({ status: "dismissed" }));
    renderContent();
    const submit = await screen.findByTestId("identity-dismiss-submit-c1");
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId("identity-dismiss-reason-c1"), { target: { value: "  כפילות ידועה " } });
    expect(submit).not.toBeDisabled();
    fireEvent.click(submit);
    await waitFor(() => expect(api.dismissIdentityConflict).toHaveBeenCalledWith("c1", "כפילות ידועה"));
  });

  it("shows a translated error for a backend detail code, never the raw code", async () => {
    vi.mocked(api.resolveIdentityConflict).mockRejectedValue(axiosDetail("conflict_not_open"));
    renderContent();
    fireEvent.click(await screen.findByTestId("identity-resolve-c1-s1"));
    const err = await screen.findByTestId("identity-conflicts-action-error");
    expect(err.textContent).not.toContain("conflict_not_open");
    expect(err.textContent?.trim().length).toBeGreaterThan(0);
  });
});
