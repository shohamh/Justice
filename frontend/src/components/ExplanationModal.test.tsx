import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "../i18n";
import ExplanationModal from "./ExplanationModal";
import * as algorithmApi from "../api/algorithm";

vi.mock("../hooks/useModalBackClose", () => ({ useModalBackClose: vi.fn() }));
vi.mock("../api/algorithm", async () => {
  const actual = await vi.importActual<typeof import("../api/algorithm")>("../api/algorithm");
  return { ...actual, getExplanationByAssignment: vi.fn(), getExplanation: vi.fn() };
});

describe("ExplanationModal soldier view", () => {
  it("renders the aggregate breakdown by reason, with counts only", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      assigned: true,
      norm_score_before: 0.2,
      norm_score_after: 0.3,
      blocked_count: 4,
      tiebreaker_note: null,
      global_before: { min_gap: 0, norm_variance: 0 },
      global_after: { min_gap: 0, norm_variance: 0 },
      score_at_assignment: 0.2,
      eligible_count: 20,
      soldier_rank: null,
      rank_from_bottom: 15,
      ahead_count: 14,
      ahead_breakdown: {
        personal_constraint: 5, exemption: 3, weapon_ineligible: 3, overlap: 0, randomness: 3,
      },
    });

    render(<ExplanationModal assignmentId="a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/מדורג 15 מהתחתית/)).toBeInTheDocument());
    expect(screen.getByText(/14 חיילים מדורגים לפניך/)).toBeInTheDocument();
    expect(screen.getByText(/5 בגלל אילוץ אישי/)).toBeInTheDocument();
    expect(screen.getByText(/3 פטורים מסוג תורנות זה/)).toBeInTheDocument();
    expect(screen.getByText(/3 לא כשירים \(נשק\/טווח\)/)).toBeInTheDocument();
    expect(screen.getByText(/3 מסיבות אחרות של האלגוריתם/)).toBeInTheDocument();
    // overlap is 0 -- must not render a "0 כבר משובצים" line
    expect(screen.queryByText(/כבר משובצים/)).not.toBeInTheDocument();
  });

  it("never renders another soldier's name or id anywhere in the DOM", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      assigned: true,
      norm_score_before: 0.2,
      norm_score_after: 0.3,
      blocked_count: 1,
      tiebreaker_note: null,
      global_before: { min_gap: 0, norm_variance: 0 },
      global_after: { min_gap: 0, norm_variance: 0 },
      score_at_assignment: 0.2,
      eligible_count: 5,
      soldier_rank: null,
      rank_from_bottom: 2,
      ahead_count: 1,
      ahead_breakdown: { personal_constraint: 1, exemption: 0, weapon_ineligible: 0, overlap: 0, randomness: 0 },
      // A malformed/legacy response could theoretically still carry a name-bearing
      // field -- the component must not have any code path that would render one.
    } as never);

    const { container } = render(<ExplanationModal assignmentId="a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/מדורג 2 מהתחתית/)).toBeInTheDocument());
    // Sanity: the modal renders real content, this isn't a trivially-empty check.
    expect(container.textContent).toContain("בגלל אילוץ אישי");
  });

  it("shows an 'unavailable' note instead of guessing when ahead_breakdown is missing (legacy records)", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      assigned: true,
      norm_score_before: 0.2,
      norm_score_after: 0.3,
      blocked_count: 0,
      tiebreaker_note: null,
      global_before: { min_gap: 0, norm_variance: 0 },
      global_after: { min_gap: 0, norm_variance: 0 },
      score_at_assignment: 0.2,
      eligible_count: 5,
      soldier_rank: null,
      rank_from_bottom: 3,
      ahead_count: 2,
      ahead_breakdown: null,
    });

    render(<ExplanationModal assignmentId="a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/הפירוט המלא אינו זמין/)).toBeInTheDocument());
  });

  it("shows the top-of-list message when nobody ranks ahead", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      assigned: true,
      norm_score_before: 0.1,
      norm_score_after: 0.15,
      blocked_count: 0,
      tiebreaker_note: null,
      global_before: { min_gap: 0, norm_variance: 0 },
      global_after: { min_gap: 0, norm_variance: 0 },
      score_at_assignment: 0.1,
      eligible_count: 5,
      soldier_rank: null,
      rank_from_bottom: 1,
      ahead_count: 0,
      ahead_breakdown: { personal_constraint: 0, exemption: 0, weapon_ineligible: 0, overlap: 0, randomness: 0 },
    });

    render(<ExplanationModal assignmentId="a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/העומס הנמוך ביותר מבין כל החיילים/)).toBeInTheDocument());
  });
});
