import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import FairnessSpreadBreakdownModal from "./FairnessSpreadBreakdownModal";

vi.mock("./SoldierLink", () => ({
  default: ({ name }: { name: string }) => <span>{name}</span>,
}));

function soldiers(shares: number[]) {
  return shares.map((burdenShare, i) => ({ id: `s${i}`, name: `חייל ${i}`, burdenShare }));
}

describe("FairnessSpreadBreakdownModal", () => {
  it("spells out every term in the formula for a small group (no table rows hidden from the reader)", () => {
    // Regression: an earlier version ellipsized past 4 terms, so a 7-soldier
    // sub-group's σ formula silently dropped 4 of the 7 real contributions —
    // the displayed numbers didn't match any row a reader could see in the
    // table above it. The table comfortably shows ~9 rows before it needs to
    // scroll, so the threshold must cover at least that many.
    render(
      <FairnessSpreadBreakdownModal
        title="7 חיילים"
        soldiers={soldiers([0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.15])}
        onClose={vi.fn()}
      />
    );

    // KaTeX renders \cdots as the Unicode midline ellipsis (⋯) in its
    // accessible MathML output — its absence means every term was spelled out.
    expect(document.body.textContent).not.toContain("⋯");
  });

  it("ellipsizes the formula for a large group, keeping the final computed values correct", () => {
    const shares = Array.from({ length: 50 }, (_, i) => 0.1 + i * 0.001);
    render(
      <FairnessSpreadBreakdownModal title="50 חיילים" soldiers={soldiers(shares)} onClose={vi.fn()} />
    );

    // The formula itself is elided...
    expect(document.body.textContent).toContain("⋯");
    // ...but the final CV in the footer is still the real, fully-computed value.
    const n = shares.length;
    const mean = shares.reduce((a, b) => a + b, 0) / n;
    const variance = shares.reduce((a, b) => a + (b - mean) ** 2, 0) / n;
    const cv = Math.sqrt(variance) / mean;
    expect(screen.getAllByText(`${(cv * 100).toFixed(0)}%`).length).toBeGreaterThan(0);
  });

  it("shows a fallback for fewer than 2 soldiers instead of a broken 0/0 computation", () => {
    render(
      <FairnessSpreadBreakdownModal title="1 חייל" soldiers={soldiers([0.5])} onClose={vi.fn()} />
    );

    expect(screen.getByText("פחות מ-2 חיילים בקבוצה זו — אין מספיק נתונים לחישוב פיזור.")).toBeInTheDocument();
  });

  it("shows a column explanation on click (not hover-only, since title tooltips don't work on touch)", () => {
    render(
      <FairnessSpreadBreakdownModal title="2 חיילים" soldiers={soldiers([0.4, 0.6])} onClose={vi.fn()} />
    );

    const header = screen.getByRole("button", { name: "סטייה בריבוע" });
    expect(screen.queryByText(/הבסיס לחישוב סטיית התקן/)).not.toBeInTheDocument();

    fireEvent.click(header);
    expect(screen.getByText(/הבסיס לחישוב סטיית התקן/)).toBeInTheDocument();

    // Toggles off on a second click.
    fireEvent.click(header);
    expect(screen.queryByText(/הבסיס לחישוב סטיית התקן/)).not.toBeInTheDocument();
  });
});
