import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FairnessComponentsCard from "./FairnessComponentsCard";
import * as scoringApi from "../api/scoring";

vi.mock("../api/scoring");
vi.mock("recharts", () => ({
  Cell: () => null,
  Pie: () => null,
  PieChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
}));

describe("FairnessComponentsCard", () => {
  it("keeps the pie chart away from the RTL sidebar edge so its tooltip is not clipped", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 2,
        duty_type_names: ["שמירה"],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל 1", burden_share: 0.4, eligible_type_count: 1 },
          { soldier_id: "s2", full_name: "חייל 2", burden_share: 0.6, eligible_type_count: 2 },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard />);

    await waitFor(() => expect(screen.getByTestId("fairness-component-pie-chart")).toBeInTheDocument());
    expect(screen.getByTestId("fairness-component-pie-chart").parentElement).toHaveClass("flex-row-reverse");
  });
});
