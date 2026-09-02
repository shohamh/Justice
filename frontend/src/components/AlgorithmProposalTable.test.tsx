import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import AlgorithmProposalTable from "./AlgorithmProposalTable";
import type { AlgorithmJob } from "../api/algorithm";
import { bulkAcceptProposals, bulkRejectProposals } from "../api/algorithm";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: string | (Record<string, unknown> & { defaultValue?: string })) => {
      const fallback = typeof options === "string" ? options : options?.defaultValue;
      let template = fallback ?? key;
      if (options && typeof options === "object") {
        for (const [varName, value] of Object.entries(options)) {
          if (varName === "defaultValue") continue;
          template = template.replaceAll(`{{${varName}}}`, String(value));
        }
      }
      return template;
    },
  }),
}));
vi.mock("../api/algorithm", () => ({
  acceptProposal: vi.fn(), bulkAcceptProposals: vi.fn(), bulkRejectProposals: vi.fn(), rejectProposal: vi.fn(),
}));
vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

const job: AlgorithmJob = {
  id: "job-1", status: "done", mode: "shadow", planning_start: "2026-01-01", planning_end: "2026-01-02",
  started_at: null, finished_at: null, error_message: null, progress_message: null, solver_metrics: {}, relaxed: [], reasons: [], batch_results: [], result_metadata: null,
  proposals: [{ assignment_id: "assignment-1", soldier_id: "soldier-1", duty_type_id: "type-1", duty_location_id: "location-1", start_date: "2026-01-01", end_date: "2026-01-01", status: "algorithm_draft", reserve_soldier_id: null, norm_score_before: null, norm_score_after: null, duty_shift_id: null, candidate_rank: null, candidate_pool_size: null, batch_index: null }],
};

describe("AlgorithmProposalTable", () => {
  it("publishes the reviewed proposals and renders their successful state", async () => {
    vi.mocked(bulkAcceptProposals).mockResolvedValue({ accepted: 1 });
    function Harness() {
      const [currentJob, setCurrentJob] = useState(job);
      return <AlgorithmProposalTable job={currentJob} jobId="job-1" soldiers={[{ id: "soldier-1", full_name: "Dani Cohen" }]} dutyTypes={[{ id: "type-1", name: "Guard" }]} isDraft={currentJob.proposals.some(proposal => proposal.status === "algorithm_draft")} onProposalUpdate={setCurrentJob} />;
    }
    render(<Harness />);

    expect(screen.getByTestId("algorithm-proposal-review")).toBeVisible();
    fireEvent.click(screen.getByTestId("algorithm-publish-proposals"));

    await waitFor(() => expect(bulkAcceptProposals).toHaveBeenCalledWith("job-1", ["assignment-1"]));
    expect(screen.getByTestId("algorithm-proposal-assignment-1")).toHaveClass("bg-green-50");
    expect(screen.queryByTestId("algorithm-publish-proposals")).not.toBeInTheDocument();
  });

  it("does not reject a draft until its translated confirmation is accepted", async () => {
    vi.mocked(bulkRejectProposals).mockResolvedValue(undefined);
    render(<AlgorithmProposalTable job={job} jobId="job-1" soldiers={[{ id: "soldier-1", full_name: "דני כהן" }]} dutyTypes={[{ id: "type-1", name: "שמירה" }]} isDraft onProposalUpdate={vi.fn()} />);

    fireEvent.click(screen.getByText("בטל טיוטות (1)"));
    expect(bulkRejectProposals).not.toHaveBeenCalled();
    expect(screen.getByText("לבטל 1 טיוטות?")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));

    await waitFor(() => expect(bulkRejectProposals).toHaveBeenCalledWith("job-1", ["assignment-1"]));
  });
});
