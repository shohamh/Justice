import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "../../i18n";
import HrIdentityConflictsSection from "./HrIdentityConflictsSection";
import * as hrApi from "../../api/hrReview";
import type { HrIdentityConflictDTO, HrPreferredRecordDTO } from "../../api/hrReview";

vi.mock("../../api/hrReview");

function conflict(overrides: Partial<HrIdentityConflictDTO> = {}): HrIdentityConflictDTO {
  return {
    id: "c1",
    personal_number: "1234567",
    kind: "duplicate_personal_number",
    reason: "latest",
    status: "open",
    applied_index: 1,
    chosen_index: null,
    candidates: [
      {
        index: 0, key_type: "username", key_value: "old.user",
        payload: { fullName: "ישראל ישראלי", mail: "old@corp.example", rank: "סמל" },
        is_applied: false, choosable: true, invalid_reason: null,
      },
      {
        index: 1, key_type: "username", key_value: "new.user",
        payload: { fullName: "ישראל ישראלי", mail: "new@corp.example", rank: "סגן" },
        is_applied: true, choosable: false, invalid_reason: "email_taken",
      },
    ],
    colliding_soldiers: [],
    preferred_record: null,
    hr_person_sync_id: "p1",
    created_at: "2026-10-02T08:00:00Z",
    last_seen_at: "2026-10-02T08:00:00Z",
    acknowledged_at: null,
    resolved_at: null,
    ...overrides,
  };
}

const pref: HrPreferredRecordDTO = {
  personal_number: "7654321", key_type: "mail", key_value: "keep@corp.example",
  chosen_by: "a1", chosen_by_name: "מנהל מערכת", chosen_at: "2026-10-01T09:00:00Z",
};

function renderSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <HrIdentityConflictsSection />
    </QueryClientProvider>,
  );
}

function axiosDetail(detail: string, status = 400) {
  return Object.assign(new Error("req failed"), { response: { status, data: { detail } } });
}

describe("HrIdentityConflictsSection", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(hrApi.listHrIdentityConflicts).mockResolvedValue({ items: [conflict()] });
    vi.mocked(hrApi.listHrPreferredRecords).mockResolvedValue({ items: [] });
  });

  it("shows an empty state when there are no conflicts", async () => {
    vi.mocked(hrApi.listHrIdentityConflicts).mockResolvedValue({ items: [] });
    renderSection();
    expect(await screen.findByTestId("hr-identity-conflicts-empty")).toBeInTheDocument();
  });

  it("shows a load error when the list request fails", async () => {
    vi.mocked(hrApi.listHrIdentityConflicts).mockRejectedValue(new Error("boom"));
    renderSection();
    expect(await screen.findByTestId("hr-identity-conflicts-error")).toBeInTheDocument();
  });

  it("renders duplicate records side by side and marks the applied one", async () => {
    renderSection();
    const card = await screen.findByTestId("hr-identity-conflict-c1");
    expect(within(card).getByText(/1234567/)).toBeInTheDocument();
    const first = within(card).getByTestId("hr-identity-candidate-c1-0");
    const second = within(card).getByTestId("hr-identity-candidate-c1-1");
    expect(within(first).getByText("old@corp.example")).toBeInTheDocument();
    expect(within(second).getByText("new@corp.example")).toBeInTheDocument();
    expect(within(second).getByTestId("hr-identity-applied-c1-1")).toBeInTheDocument();
    expect(within(first).queryByTestId("hr-identity-applied-c1-0")).toBeNull();
  });

  it("acknowledges an open conflict", async () => {
    vi.mocked(hrApi.acknowledgeHrIdentityConflict).mockResolvedValue(conflict({ status: "acknowledged" }));
    renderSection();
    fireEvent.click(await screen.findByTestId("hr-identity-acknowledge-c1"));
    await waitFor(() => expect(hrApi.acknowledgeHrIdentityConflict).toHaveBeenCalledWith("c1"));
  });

  it("offers 'use this one from now on' only for choosable candidates and sends the index", async () => {
    vi.mocked(hrApi.chooseHrIdentityCandidate).mockResolvedValue(conflict({ status: "resolved" }));
    renderSection();
    const card = await screen.findByTestId("hr-identity-conflict-c1");
    expect(within(card).queryByTestId("hr-identity-choose-c1-1")).toBeNull();
    fireEvent.click(within(card).getByTestId("hr-identity-choose-c1-0"));
    await waitFor(() => expect(hrApi.chooseHrIdentityCandidate).toHaveBeenCalledWith("c1", 0));
  });

  it("shows the translated invalid reason for a candidate that cannot be chosen", async () => {
    renderSection();
    const second = await screen.findByTestId("hr-identity-candidate-c1-1");
    const reason = within(second).getByTestId("hr-identity-invalid-c1-1");
    expect(reason).toBeInTheDocument();
    expect(reason.textContent).not.toContain("email_taken");
    expect(reason.textContent).not.toContain("errors.");
  });

  it("shows the remembered-choice marker on a conflict and clears it", async () => {
    vi.mocked(hrApi.listHrIdentityConflicts).mockResolvedValue({
      items: [conflict({ preferred_record: { ...pref, personal_number: "1234567" } })],
    });
    vi.mocked(hrApi.clearHrPreferredRecord).mockResolvedValue(undefined);
    renderSection();
    const marker = await screen.findByTestId("hr-identity-remembered-c1");
    fireEvent.click(within(marker).getByTestId("hr-identity-clear-1234567"));
    await waitFor(() => expect(hrApi.clearHrPreferredRecord).toHaveBeenCalledWith("1234567"));
  });

  it("lists remembered choices separately so they can be cleared once a conflict is resolved", async () => {
    vi.mocked(hrApi.listHrIdentityConflicts).mockResolvedValue({ items: [] });
    vi.mocked(hrApi.listHrPreferredRecords).mockResolvedValue({ items: [pref] });
    vi.mocked(hrApi.clearHrPreferredRecord).mockResolvedValue(undefined);
    renderSection();
    fireEvent.click(await screen.findByTestId("hr-identity-clear-7654321"));
    await waitFor(() => expect(hrApi.clearHrPreferredRecord).toHaveBeenCalledWith("7654321"));
  });

  it("displays a translated error for a backend detail code and never the raw code", async () => {
    vi.mocked(hrApi.chooseHrIdentityCandidate).mockRejectedValue(axiosDetail("candidate_held_for_review"));
    renderSection();
    fireEvent.click(await screen.findByTestId("hr-identity-choose-c1-0"));
    const err = await screen.findByTestId("hr-identity-action-error");
    expect(err.textContent).not.toContain("candidate_held_for_review");
    expect(err.textContent?.trim().length).toBeGreaterThan(0);
  });
});
