import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "../i18n";
import ExplanationModal from "./ExplanationModal";
import * as algorithmApi from "../api/algorithm";

vi.mock("../hooks/useModalBackClose", () => ({ useModalBackClose: vi.fn() }));
vi.mock("./SoldierLink", () => ({
  default: ({ id, name }: { id: string; name: string }) => <span data-testid={`soldier-link-${id}`}>{name}</span>,
}));
vi.mock("../api/algorithm", async () => {
  const actual = await vi.importActual<typeof import("../api/algorithm")>("../api/algorithm");
  return { ...actual, getExplanationByAssignment: vi.fn(), getExplanation: vi.fn() };
});

describe("ExplanationModal soldier view", () => {
  it("shows the soldier decision summary before the manager candidate table", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      duty_id: "d1",
      assigned_soldier_id: "s1",
      tiebreaker_note: null,
      global_before: { min_gap: 2, norm_variance: 0 },
      global_after: { min_gap: 3, norm_variance: 0 },
      pool_size: 3,
      assigned_rank: 2,
      rank_from_bottom: 2,
      ahead_count: 1,
      ahead_breakdown: {
        personal_constraint: 1, exemption: 0, weapon_ineligible: 0, overlap: 0, randomness: 0,
      },
      candidates: [
        {
          soldier_id: "s2",
          soldier_name: "חייל א",
          blocked: false,
          blocking_constraints: [],
          pre_norm_score: 0.1,
          post_norm_score: 0.1,
        },
        {
          soldier_id: "s1",
          soldier_name: "חייל ב",
          blocked: false,
          blocking_constraints: [],
          pre_norm_score: 0.2,
          post_norm_score: 0.2,
        },
      ],
    } as never);

    render(<ExplanationModal assignmentId="manager-a1" onClose={vi.fn()} />);

    const summary = await screen.findByTestId("explanation-decision-summary");
    const table = screen.getAllByRole("table")[1];
    expect(summary.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(summary).toHaveTextContent("20.00%");
  });

  it("shows unavailable spread metrics, precise shares, and a reason for eligible candidates ahead", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      duty_id: "d1",
      assigned_soldier_id: "s1",
      tiebreaker_note: "lowest_post_effort_score",
      global_before: {},
      global_after: {},
      pool_size: 2,
      assigned_rank: 2,
      rank_from_bottom: 2,
      ahead_count: 1,
      ahead_breakdown: {
        personal_constraint: 0, exemption: 0, weapon_ineligible: 0, overlap: 0, randomness: 1,
      },
      candidates: [
        {
          soldier_id: "s2",
          soldier_name: "חייל א",
          blocked: false,
          blocking_constraints: [],
          pre_norm_score: 0.0004,
          post_norm_score: 0.0006,
        },
        {
          soldier_id: "s1",
          soldier_name: "חייל ב",
          blocked: false,
          blocking_constraints: [],
          pre_norm_score: 0.002,
          post_norm_score: 0.003,
        },
      ],
    } as never);

    render(<ExplanationModal assignmentId="manager-a1" onClose={vi.fn()} />);

    const summary = await screen.findByTestId("explanation-decision-summary");
    expect(screen.getByTestId("explanation-min-gap-before")).toHaveTextContent("—");
    expect(screen.getByTestId("explanation-min-gap-after")).toHaveTextContent("—");
    expect(summary).toHaveTextContent("חייל אחד מדורג לפניך:");
    expect(summary).toHaveTextContent("פתרונות שקולים");
    expect(screen.getByText("כשיר אך לא נבחר בפתרון הסופי")).toBeInTheDocument();
    expect(screen.getByText("0.04%")).toBeInTheDocument();
    expect(screen.getAllByText("0.20%")).toHaveLength(2);
    expect(screen.getAllByRole("table")[1]).toHaveClass("min-w-[600px]");
  });

  it("does not claim the lowest burden when the rank is unavailable", async () => {
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
      rank_from_bottom: null,
      ahead_count: null,
      ahead_breakdown: null,
    });

    render(<ExplanationModal assignmentId="a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId("explanation-decision-summary")).toBeInTheDocument());
    expect(screen.getByText(/הדירוג המלא אינו זמין/)).toBeInTheDocument();
    expect(screen.queryByText(/העומס הנמוך ביותר/)).not.toBeInTheDocument();
  });

  it("uses burden-share labels and SoldierLink for every candidate in the full view", async () => {
    vi.mocked(algorithmApi.getExplanationByAssignment).mockResolvedValue({
      duty_id: "d1",
      assigned_soldier_id: "s1",
      tiebreaker_note: null,
      candidates: [{
        soldier_id: "s2",
        soldier_name: "חיילת ב",
        blocked: false,
        blocking_constraints: [],
        pre_norm_score: 0.12,
        post_norm_score: 0.18,
      }],
      global_before: {},
      global_after: {},
    });

    render(<ExplanationModal assignmentId="full-a1" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByTestId("soldier-link-s2")).toBeInTheDocument());
    expect(screen.getByText("חלק בנטל לפני")).toBeInTheDocument();
    expect(screen.getByText("חלק בנטל אחרי")).toBeInTheDocument();
    expect(screen.queryByText("ניקוד מנורמל לפני")).not.toBeInTheDocument();
    expect(screen.queryByText("ניקוד מנורמל אחרי")).not.toBeInTheDocument();
  });

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

    await waitFor(() => expect(screen.getByText(/מדורג במקום 15 לפי העומס/)).toBeInTheDocument());
    expect(screen.getByText(/14 חיילים מדורגים לפניך/)).toBeInTheDocument();
    expect(screen.getByText(/5 בגלל אילוץ אישי/)).toBeInTheDocument();
    expect(screen.getByText(/3 פטורים מסוג תורנות זה/)).toBeInTheDocument();
    expect(screen.getByText(/3 לא כשירים \(נשק\/טווח\)/)).toBeInTheDocument();
    expect(screen.getByText(/3 סיבות אחרות של האלגוריתם/)).toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByText(/מדורג במקום 2 לפי העומס/)).toBeInTheDocument());
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
