import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
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
    // Without shrink-0, the fixed 96x96 chart gets squeezed toward zero size
    // by its flex sibling once that sibling's content grows long (e.g. the
    // "← <long duty-type list>" line that appears on hover) — reproduced live
    // as the donut collapsing to near-invisible slivers on hover.
    expect(screen.getByTestId("fairness-component-pie-chart")).toHaveClass("shrink-0");
  });

  it("hovering a legend row shows that sub-group's burden-share spread and highlights the matching badge and people", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 3,
        duty_type_names: ["שמירה", "סיור"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }, { id: "dt-patrol", name: "סיור" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard", "dt-patrol"] },
          { soldier_id: "s3", full_name: "חייל שלוש", burden_share: 0.8, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard", "dt-patrol"] },
        ],
        burden_share: { mean: 0.6, cv: 0.24, stddev: 0.14 },
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

    // The "2 סוגים" legend row belongs to the two soldiers eligible for both types
    // (burden share 60% and 80% — mean 70%, stddev 10%, CV ≈14%).
    // Query the actual hoverable/clickable container (the text span's parent),
    // since mouseenter/mouseleave don't bubble up from a descendant node.
    const twoTypesRow = screen.getByText("2 חיילים — 2 סוגים").closest("div") as HTMLElement;

    fireEvent.mouseEnter(twoTypesRow);
    expect(guardBadge).toHaveClass("bg-indigo-600");
    expect(patrolBadge).toHaveClass("bg-indigo-600");
    expect(screen.getByText("טווח: 60.0%–80.0% · סטיית תקן: ±10.0% · פיזור CV 14%")).toBeInTheDocument();
    // The candidate list filters down to just this sub-group's soldiers
    // (a full group can run to hundreds — tinting rows within an unfiltered
    // list of that size made them practically unfindable, confirmed live).
    expect(screen.getByText("חיילים בקבוצות שנבחרו (2), ממוינים לפי חלק בנטל:")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();
    expect(screen.getByText("חייל שלוש")).toBeInTheDocument();
    expect(screen.queryByText("חייל אחד")).not.toBeInTheDocument();

    fireEvent.mouseLeave(twoTypesRow);
    expect(guardBadge).not.toHaveClass("bg-indigo-600");

    // Clicking locks the highlight so it survives the mouse leaving.
    fireEvent.click(twoTypesRow);
    expect(guardBadge).toHaveClass("bg-indigo-600");
    fireEvent.click(twoTypesRow);
    expect(guardBadge).not.toHaveClass("bg-indigo-600");
  });

  it("shows a fallback instead of a spread for a sub-group with fewer than 2 soldiers", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 2,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard"] },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard />);

    const soloRow = await screen.findByText("1 חיילים — 2 סוגים");
    fireEvent.mouseEnter(soloRow.closest("div") as HTMLElement);
    expect(screen.getByText("פחות מ-2 חיילים בקבוצה זו")).toBeInTheDocument();
  });

  it("deselects on a second tap even though touch never fires mouseleave", async () => {
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

    render(<FairnessComponentsCard activeGroupKeys={new Set(["comp_0"])} onGroupToggle={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("שמירה")).toBeInTheDocument());
    const guardBadge = screen.getByText("שמירה");
    const twoTypesRow = screen.getByText("1 חיילים — 2 סוגים").closest("div") as HTMLElement;

    // A touch tap fires a synthetic mouseenter followed by click — with no
    // mouseleave in between, since there's no real pointer to leave with.
    fireEvent.mouseEnter(twoTypesRow);
    fireEvent.click(twoTypesRow);
    expect(guardBadge).toHaveClass("bg-indigo-600");

    // A second tap (mouseenter fires again, still no mouseleave) must unlock —
    // without clearing hoveredCount, the stale hover value kept the row
    // looking selected via the `lockedCount ?? hoveredCount` fallback.
    fireEvent.mouseEnter(twoTypesRow);
    fireEvent.click(twoTypesRow);
    expect(guardBadge).not.toHaveClass("bg-indigo-600");
  });

  it("ctrl+click combines several sub-groups as a filter, without replacing the existing selection", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 3,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.2, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.4, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s3", full_name: "חייל שלוש", burden_share: 0.6, eligible_type_count: 3, eligible_duty_type_ids: ["dt-guard"] },
        ],
        burden_share: { mean: 0.4, cv: 0.3, stddev: 0.16 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard />);

    const row1 = (await screen.findByText("1 חיילים — 1 סוגים")).closest("div") as HTMLElement;
    const row2 = screen.getByText("1 חיילים — 2 סוגים").closest("div") as HTMLElement;

    // Plain click: single-select, just this one sub-group.
    fireEvent.click(row1);
    expect(screen.getByText("חייל אחד")).toBeInTheDocument();
    expect(screen.queryByText("חייל שתיים")).not.toBeInTheDocument();
    expect(screen.queryByText("חייל שלוש")).not.toBeInTheDocument();

    // Ctrl+click a second row: adds to the selection instead of replacing it.
    fireEvent.click(row2, { ctrlKey: true });
    expect(screen.getByText("חייל אחד")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();
    expect(screen.queryByText("חייל שלוש")).not.toBeInTheDocument();

    // Ctrl+click the first row again: removes just that one from the selection.
    fireEvent.click(row1, { ctrlKey: true });
    expect(screen.queryByText("חייל אחד")).not.toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();
  });

  it("reveals the ranked candidate list on a sub-group hover, without needing the whole group selected first", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 2,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard"] },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    // No activeGroupKeys/onGroupToggle — the whole group is never toggled active.
    render(<FairnessComponentsCard />);

    expect(screen.queryByText("סדר עדיפויות לתורנות הבאה (חלק בנטל עולה — מקום 1 מועמד ראשי):")).not.toBeInTheDocument();

    const soloRow = await screen.findByText("1 חיילים — 2 סוגים");
    fireEvent.mouseEnter(soloRow.closest("div") as HTMLElement);

    // Filtered to just this sub-group's one soldier — "חייל אחד" (count 1,
    // not part of this sub-group) is excluded.
    expect(screen.getByText("חיילים בקבוצות שנבחרו (1), ממוינים לפי חלק בנטל:")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();
    expect(screen.queryByText("חייל אחד")).not.toBeInTheDocument();
  });

  it("opens a calculation breakdown for a sub-group with the underlying soldiers and computed CV", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 3,
        duty_type_names: ["שמירה", "סיור"],
        duty_types: [{ id: "dt-guard", name: "שמירה" }, { id: "dt-patrol", name: "סיור" }],
        soldiers: [
          { soldier_id: "s1", full_name: "חייל אחד", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt-guard"] },
          { soldier_id: "s2", full_name: "חייל שתיים", burden_share: 0.6, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard", "dt-patrol"] },
          { soldier_id: "s3", full_name: "חייל שלוש", burden_share: 0.8, eligible_type_count: 2, eligible_duty_type_ids: ["dt-guard", "dt-patrol"] },
        ],
        burden_share: { mean: 0.6, cv: 0.24, stddev: 0.14 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard />);

    const twoTypesRow = await screen.findByText("2 חיילים — 2 סוגים");
    const rowContainer = twoTypesRow.closest("div") as HTMLElement;
    fireEvent.mouseEnter(rowContainer);

    // There's also a group-level "הצג פירוט חישוב" button in the card header —
    // scope to this row's own wrapper (row + revealed stats line share a parent).
    fireEvent.click(within(rowContainer.parentElement as HTMLElement).getByRole("button", { name: "הצג פירוט חישוב" }));

    const heading = screen.getByText("📊 פירוט חישוב פיזור — 2 חיילים — 2 סוגים");
    // Modal root: header's grandparent (header row -> dialog card).
    const modal = heading.closest("div")?.parentElement as HTMLElement;
    expect(within(modal).getByText("חייל שתיים")).toBeInTheDocument();
    expect(within(modal).getByText("חייל שלוש")).toBeInTheDocument();
    // Only the two soldiers in this sub-group appear — not the third (count 1) soldier,
    // who's also named "חייל אחד" in the (still-visible, unrelated) candidate list behind it.
    expect(within(modal).queryByText("חייל אחד")).not.toBeInTheDocument();
    // Burden share 60%/80% -> CV 14%, shown in both the derivation and the footer.
    expect(within(modal).getAllByText("14%").length).toBeGreaterThan(0);
  });
});
