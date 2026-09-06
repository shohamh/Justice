import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

describe("FairnessComponentsCard", () => {
  it("keeps the pie chart away from the RTL sidebar edge so its tooltip is not clipped", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 2,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt1", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל 1", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
          { soldier_id: "s2", full_name: "חייל 2", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt1"] },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard />);

    await waitFor(() => expect(screen.getByTestId("fairness-component-pie-chart")).toBeInTheDocument());
    expect(screen.getByTestId("fairness-component-pie-chart").parentElement).toHaveClass("md:pr-16");
    expect(screen.getByTestId("fairness-component-pie-chart").parentElement).not.toHaveClass("flex-row-reverse");
  });

  it("hovering a legend row names the specific duty types and highlights the matching badge and people", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 2,
        duty_type_names: ["שמירה", "סיור"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }, { id: "dt-patrol", name: "סיור" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard", "dt-patrol"] },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(
      <FairnessComponentsCard
        activeGroupKeys={new Set(["comp_0"])}
        onGroupToggle={vi.fn()}
      />
    );

    await waitFor(() => expect(screen.getByText("שמירה")).toBeInTheDocument());
    const guardBadge = screen.getByText("שמירה");
    const patrolBadge = screen.getByText("סיור");
    expect(guardBadge).not.toHaveClass("bg-indigo-600");

    // The "2 סוגים" legend row belongs to the soldier eligible for both types.
    // Query the actual hoverable/clickable container (the text span's parent),
    // since mouseenter/mouseleave don't bubble up from a descendant node.
    const twoTypesRow = screen.getByText("1 חיילים — 2 סוגים").closest("div") as HTMLElement;

    fireEvent.mouseEnter(twoTypesRow);
    expect(guardBadge).toHaveClass("bg-indigo-600");
    expect(patrolBadge).toHaveClass("bg-indigo-600");
    expect(screen.getByText("← שמירה, סיור")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים").closest("div")).toHaveClass("bg-indigo-50");

    fireEvent.mouseLeave(twoTypesRow);
    expect(guardBadge).not.toHaveClass("bg-indigo-600");

    // Clicking locks the highlight so it survives the mouse leaving.
    fireEvent.click(twoTypesRow);
    expect(guardBadge).toHaveClass("bg-indigo-600");
    fireEvent.click(twoTypesRow);
    expect(guardBadge).not.toHaveClass("bg-indigo-600");
  });
});
