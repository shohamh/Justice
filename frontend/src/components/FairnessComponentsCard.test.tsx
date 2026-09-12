import { render, screen, waitFor, fireEvent, within, act } from "@testing-library/react";
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
  it("shows a loading indicator while the data is still in flight", async () => {
    let resolveFetch: (value: scoringApi.FairnessComponents) => void = () => {};
    vi.mocked(scoringApi.getFairnessComponents).mockReturnValue(
      new Promise((resolve) => { resolveFetch = resolve; })
    );

    render(<FairnessComponentsCard />);

    expect(screen.getByTestId("fairness-components-loading")).toBeInTheDocument();

    resolveFetch({ components: [], exempt_from_all: { count: 0, soldiers: [] } });
    await waitFor(() => expect(screen.queryByTestId("fairness-components-loading")).not.toBeInTheDocument());
  });

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

  it("positions each candidate's bar relative to the group mean, not a min/max stretch of the list", async () => {
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 3,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt1", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s-low", full_name: "חייל נמוך", burden_share: 0.4, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
          { soldier_id: "s-mid", full_name: "חייל אמצע", burden_share: 0.5, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
          { soldier_id: "s-high", full_name: "חייל גבוה", burden_share: 0.6, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
        ],
        burden_share: { mean: 0.5, cv: 0.2, stddev: 0.1 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard activeGroupKeys={new Set(["comp_0"])} onGroupToggle={vi.fn()} />);

    // Below the mean: bar grows leftward from the center line (anchored at
    // its right edge), gradient ending on the green side.
    const lowBar = await screen.findByTestId("deviation-bar-s-low");
    expect(lowBar).toHaveStyle({ right: "50%" });
    const lowEndColor = lowBar.style.background.match(/rgb\([^)]+\)/g)![1];
    const [rLowEnd, gLowEnd] = lowEndColor.match(/\d+/g)!.map(Number);
    expect(gLowEnd).toBeGreaterThan(rLowEnd);

    // At the mean: no meaningful bar (z ~ 0), unlike the old min/max
    // stretch where a mid-pack value could still render a large bar.
    const midBar = screen.getByTestId("deviation-bar-s-mid");
    expect(parseFloat(midBar.style.width)).toBeCloseTo(0, 5);

    // Above the mean: bar grows rightward from the center line (anchored at
    // its left edge), gradient ending on the red side.
    const highBar = screen.getByTestId("deviation-bar-s-high");
    expect(highBar).toHaveStyle({ left: "50%" });
    const highEndColor = highBar.style.background.match(/rgb\([^)]+\)/g)![1];
    const [rHighEnd, gHighEnd] = highEndColor.match(/\d+/g)!.map(Number);
    expect(rHighEnd).toBeGreaterThan(gHighEnd);

    // s-high and s-low are both exactly 1 stddev from the mean, and neither
    // any other soldier in this group goes further — so the cap here is the
    // group's own max |z| (1), not a fixed constant, and both should reach
    // the full half-width of the track (fully saturated color included).
    expect(parseFloat(highBar.style.width)).toBeCloseTo(50, 5);
    expect(parseFloat(lowBar.style.width)).toBeCloseTo(50, 5);
  });

  it("caps the deviation scale at this group's own largest actual deviation, not a fixed number of standard deviations", async () => {
    // Burden share is often heavily right-skewed — a fixed ±2.5σ cap (about
    // right for a normal distribution) badly underestimates real spread
    // here: mean 1%, stddev 1%, but one soldier at 8% is 7σ out. A fixed
    // cap would peg both the 4%-soldier (3σ) and the 8%-soldier (7σ) to the
    // same maxed-out bar; capping at the group's actual max (7σ) instead
    // keeps them visually distinct.
    vi.mocked(scoringApi.getFairnessComponents).mockResolvedValue({
      components: [{
        soldier_count: 3,
        duty_type_names: ["שמירה"],
        duty_types: [{ id: "dt1", name: "שמירה" }],
        soldiers: [
          { soldier_id: "s-typical", full_name: "חייל טיפוסי", burden_share: 0.01, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
          { soldier_id: "s-elevated", full_name: "חייל מוגבר", burden_share: 0.04, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
          { soldier_id: "s-extreme", full_name: "חייל קיצוני", burden_share: 0.08, eligible_type_count: 1, eligible_duty_type_ids: ["dt1"] },
        ],
        burden_share: { mean: 0.01, cv: 1, stddev: 0.01 },
      }],
      exempt_from_all: { count: 0, soldiers: [] },
    });

    render(<FairnessComponentsCard activeGroupKeys={new Set(["comp_0"])} onGroupToggle={vi.fn()} />);

    const elevatedBar = await screen.findByTestId("deviation-bar-s-elevated");
    const extremeBar = screen.getByTestId("deviation-bar-s-extreme");
    const elevatedWidth = parseFloat(elevatedBar.style.width);
    const extremeWidth = parseFloat(extremeBar.style.width);

    // Only the true extreme (7σ, the group's own max) reaches the full
    // half-width — the 3σ soldier is visibly shorter, not maxed out too.
    expect(extremeWidth).toBeCloseTo(50, 5);
    expect(elevatedWidth).toBeLessThan(extremeWidth);
    expect(elevatedWidth).toBeGreaterThan(0);
  });

  it("still previews a different sub-group on hover after one is already locked", async () => {
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

    render(<FairnessComponentsCard />);

    const row1 = (await screen.findByText("1 חיילים — 1 סוגים")).closest("div") as HTMLElement;
    const row2 = screen.getByText("1 חיילים — 2 סוגים").closest("div") as HTMLElement;

    fireEvent.click(row1);
    expect(screen.getByText("חייל אחד")).toBeInTheDocument();
    expect(screen.queryByText("חייל שתיים")).not.toBeInTheDocument();

    // Hovering the OTHER (unlocked) sub-group must still do something —
    // previously any hover was ignored entirely once something was locked.
    fireEvent.mouseEnter(row2);
    expect(screen.getByText("חייל אחד")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();

    // Moving away drops back to just the locked sub-group.
    fireEvent.mouseLeave(row2);
    await act(() => new Promise((resolve) => setTimeout(resolve, 260)));
    expect(screen.getByText("חייל אחד")).toBeInTheDocument();
    expect(screen.queryByText("חייל שתיים")).not.toBeInTheDocument();
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
    // The CV portion renders as its own colored badge (like the group-level
    // one), separate from the plain range/stddev text.
    expect(screen.getByText("טווח: 60.0%–80.0% · סטיית תקן: ±10.0%")).toBeInTheDocument();
    expect(screen.getByText("פיזור CV 14%")).toBeInTheDocument();
    // The candidate list filters down to just this sub-group's soldiers
    // (a full group can run to hundreds — tinting rows within an unfiltered
    // list of that size made them practically unfindable, confirmed live).
    expect(screen.getByText("חיילים בקבוצות שנבחרו (2), ממוינים לפי חלק בנטל:")).toBeInTheDocument();
    expect(screen.getByText("חייל שתיים")).toBeInTheDocument();
    expect(screen.getByText("חייל שלוש")).toBeInTheDocument();
    expect(screen.queryByText("חייל אחד")).not.toBeInTheDocument();

    // The close is delayed (not instant) so the mouse has time to cross into
    // the floating stats panel beside the row without it disappearing first,
    // and once it does close, it fades out rather than vanishing outright.
    // Real (short) waits here, not fake timers — vi.useFakeTimers() mocks the
    // same setTimeout React's own scheduler relies on in jsdom, which stalled
    // every test after this one when tried.
    fireEvent.mouseLeave(twoTypesRow);
    await act(() => new Promise((resolve) => setTimeout(resolve, 260)));
    expect(guardBadge).not.toHaveClass("bg-indigo-600");
    const fadingPanel = screen.getByText("טווח: 60.0%–80.0% · סטיית תקן: ±10.0%").closest("div")?.parentElement;
    expect(fadingPanel).toHaveClass("opacity-0");
    await act(() => new Promise((resolve) => setTimeout(resolve, 200)));
    expect(screen.queryByText("טווח: 60.0%–80.0% · סטיית תקן: ±10.0%")).not.toBeInTheDocument();

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

    // There's also a group-level CV badge with the same "?" in the card header —
    // scope to this row's own wrapper (row + revealed stats line share a parent).
    fireEvent.click(within(rowContainer.parentElement as HTMLElement).getByRole("button", { name: "מה זה CV? הצג פירוט חישוב" }));

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
