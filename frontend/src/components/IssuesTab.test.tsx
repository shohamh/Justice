import { render, screen } from "@testing-library/react";
import IssuesTab from "./IssuesTab";
import { AlgorithmJob, BatchResult } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";

function makeJob(batchResults: BatchResult[]): AlgorithmJob {
  return {
    id: "job-1",
    status: "done",
    mode: "shadow",
    planning_start: "2026-07-01",
    planning_end: "2026-08-01",
    started_at: null,
    finished_at: null,
    error_message: null,
    progress_message: null,
    proposals: [],
    solver_metrics: {},
    relaxed: [],
    reasons: [],
    batch_results: batchResults,
    result_metadata: null,
  };
}

const dutyTypes: DutyType[] = [
  { id: "dt-a", name: "שמירה כללית", score_per_day: "1", description: null, active: true },
  { id: "dt-b", name: "תורנות מטבח", score_per_day: "1", description: null, active: true },
];

const SATURATED_BATCH: BatchResult = {
  batch_index: 0,
  component_index: 0,
  date_from: "2026-07-06",
  date_to: "2026-07-14",
  duty_count: 1,
  soldier_count: 57,
  assigned_count: 0,
  unassigned_count: 1,
  outcome: "FEASIBLE",
  relaxations: ["R→20", "T→10"],
  wall_time_seconds: 140,
  shifts: [{ shift_id: "shift-1", required_count: 1, assigned_count: 0 }],
  saturation_clusters: [
    {
      date_from: "2026-07-06",
      date_to: "2026-07-14",
      shift_ids: ["shift-1"],
      eligible_pool_size: 57,
      free_count: 0,
      competing_duty_types: [
        { duty_type_id: "dt-a", count: 42 },
        { duty_type_id: "dt-b", count: 15 },
      ],
    },
  ],
};

test("renders saturation cluster explanation naming competing duty types", () => {
  render(
    <IssuesTab
      job={makeJob([SATURATED_BATCH])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
    />
  );
  expect(screen.getByText(/57/)).toBeInTheDocument();
  expect(screen.getByText(/שמירה כללית/)).toBeInTheDocument();
  expect(screen.getByText(/תורנות מטבח/)).toBeInTheDocument();
  expect(screen.getByText(/42/)).toBeInTheDocument();
  expect(screen.getByText(/15/)).toBeInTheDocument();
});

test("does not recommend raising relax ceiling when shortfall is saturation-dominated", () => {
  render(
    <IssuesTab
      job={makeJob([SATURATED_BATCH])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
      onRerun={() => {}}
    />
  );
  expect(screen.queryByText(/relax_r_ceiling/)).not.toBeInTheDocument();
  expect(screen.queryByText(/הרץ שוב עם הגדרות מומלצות/)).not.toBeInTheDocument();
});

test("still recommends raising relax ceiling for non-saturated relaxation shortfalls", () => {
  const nonSaturatedBatch: BatchResult = {
    ...SATURATED_BATCH,
    saturation_clusters: [],
  };
  render(
    <IssuesTab
      job={makeJob([nonSaturatedBatch])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
      onRerun={() => {}}
    />
  );
  expect(screen.getByText(/relax_r_ceiling/)).toBeInTheDocument();
});
