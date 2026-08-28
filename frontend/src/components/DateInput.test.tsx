import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import DateInput from "./DateInput";
import { listHolidays } from "../api/calendarHolidays";

vi.mock("../api/calendarHolidays", () => ({
  listHolidays: vi.fn().mockResolvedValue([{ date: "2026-08-15", name: "חג" }]),
}));

describe("DateInput", () => {
  it("interprets two-digit years with a pivot year of 50", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);

    fireEvent.change(screen.getByTestId("date-input"), { target: { value: "140820" } });

    expect(onChange).toHaveBeenLastCalledWith("2020-08-14");
  });

  it("maps years at and above the pivot to the twentieth century", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);

    fireEvent.change(screen.getByTestId("date-input"), { target: { value: "141250" } });

    expect(onChange).toHaveBeenLastCalledWith("1950-12-14");
  });

  it("keeps typing digits after the implied four-digit year", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);
    const input = screen.getByTestId("date-input");

    fireEvent.change(input, { target: { value: "010320" } });
    expect(input).toHaveValue("01/03/2020");

    fireEvent.change(input, { target: { value: "010320202" } });
    expect(input).toHaveValue("01/03/202");

    fireEvent.change(input, { target: { value: "01032028" } });
    expect(input).toHaveValue("01/03/2028");
    expect(onChange).toHaveBeenLastCalledWith("2028-03-01");
  });

  it("lets backspace remove the implied year digits", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);
    const input = screen.getByTestId("date-input");

    fireEvent.change(input, { target: { value: "14122020" } });
    expect(input).toHaveValue("14/12/2020");

    fireEvent.input(input, { target: { value: "1412202" }, inputType: "deleteContentBackward" });
    expect(input).toHaveValue("14/12/202");
    fireEvent.input(input, { target: { value: "141220" }, inputType: "deleteContentBackward" });
    expect(input).toHaveValue("14/12/20");

    fireEvent.input(input, { target: { value: "1412201" }, inputType: "insertText" });
    fireEvent.input(input, { target: { value: "14122017" }, inputType: "insertText" });
    expect(input).toHaveValue("14/12/2017");
    expect(onChange).toHaveBeenLastCalledWith("2017-12-14");
  });

  it("commits a typed 8-digit date when used in controlled mode (as in registration forms)", () => {
    function ControlledWrapper() {
      const [value, setValue] = useState("");
      return (
        <div>
          <DateInput value={value} onChange={setValue} data-testid="date-input" />
          <span data-testid="committed">{value}</span>
        </div>
      );
    }
    render(<ControlledWrapper />);
    const input = screen.getByTestId("date-input");
    for (const v of ["0", "01", "01/0", "01/03", "01/03/2", "01/03/20", "01/03/202", "01/03/2028"]) {
      fireEvent.change(input, { target: { value: v } });
    }
    expect(screen.getByTestId("committed").textContent).toBe("2028-03-01");
  });

  it("commits a typed short-year date in controlled mode with a cross-field max prop set", () => {
    function ControlledWrapper() {
      const [value, setValue] = useState("");
      return (
        <div>
          <DateInput value={value} onChange={setValue} max="2030-01-01" data-testid="date-input" />
          <span data-testid="committed">{value}</span>
        </div>
      );
    }
    render(<ControlledWrapper />);
    const input = screen.getByTestId("date-input");
    for (const v of ["1", "14", "14/0", "14/08", "14/08/2", "14/08/20"]) {
      fireEvent.change(input, { target: { value: v } });
    }
    expect(screen.getByTestId("committed").textContent).toBe("2020-08-14");
  });

  it("commits an already-ISO value driven directly via a change event", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);

    fireEvent.change(screen.getByTestId("date-input"), { target: { value: "2026-02-01" } });

    expect(onChange).toHaveBeenLastCalledWith("2026-02-01");
    expect(screen.getByTestId("date-input")).toHaveValue("01/02/2026");
  });

  it("rejects a malformed ISO-shaped value instead of committing garbage", () => {
    const onChange = vi.fn();
    render(<DateInput onChange={onChange} data-testid="date-input" />);

    fireEvent.change(screen.getByTestId("date-input"), { target: { value: "2026-13-40" } });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("uses a block-level (not inline-flex) wrapper, so it stacks onto its own line next to a preceding label span", () => {
    // Regression test: an inline-flex wrapper only stacked below preceding
    // inline content (e.g. a label's <span>) via a "100%-width inline
    // element can't fit, so it wraps" trick, which rendered fields
    // overlapping instead of stacking on mobile RTL layouts. A block-level
    // wrapper stacks unconditionally.
    render(<DateInput data-testid="date-input" />);
    const wrapper = screen.getByTestId("date-input").parentElement;
    expect(wrapper?.className).toMatch(/(^|\s)flex(\s|$)/);
    expect(wrapper?.className).not.toMatch(/inline-flex/);
  });

  it("puts the visible text input in its own always-growing relative wrapper, regardless of the caller's className", () => {
    // Regression test: the text input sits in a dedicated
    // `relative flex-1 min-w-0` wrapper (so the clear button, absolutely
    // positioned inside that wrapper, is anchored to the input's own box
    // rather than the whole flex row). That inner wrapper must always be
    // able to grow/shrink correctly next to the calendar button, no
    // matter what className the caller passed the input itself.
    render(<DateInput className="border p-1 w-full" data-testid="date-input" />);
    const input = screen.getByTestId("date-input");
    expect(input.className).toMatch(/(^|\s)w-full(\s|$)/);
    expect(input.className).toMatch(/(^|\s)min-w-0(\s|$)/);
    const innerWrapper = input.parentElement;
    expect(innerWrapper?.className).toMatch(/(^|\s)relative(\s|$)/);
    expect(innerWrapper?.className).toMatch(/(^|\s)flex-1(\s|$)/);
    expect(innerWrapper?.className).toMatch(/(^|\s)min-w-0(\s|$)/);
  });

  it("also grows the outer wrapper when the caller passes flex-1 (nested in its own flex row next to a button)", () => {
    // Regression test: a caller nesting DateInput in its own
    // `<div className="flex ...">` (next to a "clear" button) passes
    // flex-1 in className expecting DateInput to grow and fill that row.
    // The OUTER <span> (two levels up from the input — the input's own
    // relative wrapper is always flex-1 regardless, see the test above)
    // is the element that's actually the flex item of the caller's row —
    // without flex-grow on it too, it stayed at its own content width,
    // leaving a visible gap before the input even though the input
    // inside it was internally full-width.
    render(<DateInput className="border p-1 flex-1" data-testid="date-input" />);
    const outerWrapper = screen.getByTestId("date-input").parentElement?.parentElement;
    expect(outerWrapper?.className).toMatch(/(^|\s)flex-1(\s|$)/);
  });

  it("shows a built-in clear button only when there's a value, and clearing it commits an empty string", () => {
    const onChange = vi.fn();
    render(<DateInput value="2026-08-21" onChange={onChange} data-testid="date-input" />);

    const clearButton = screen.getByLabelText("נקה");
    expect(clearButton).toBeInTheDocument();

    fireEvent.click(clearButton);
    expect(onChange).toHaveBeenLastCalledWith("");
    expect(screen.getByTestId("date-input")).toHaveValue("");
    expect(screen.queryByLabelText("נקה")).not.toBeInTheDocument();
  });

  it("hides the built-in clear button when the field is empty", () => {
    render(<DateInput data-testid="date-input" />);
    expect(screen.queryByLabelText("נקה")).not.toBeInTheDocument();
  });

  it("opens an in-app calendar grid when the calendar button is clicked", () => {
    render(<DateInput data-testid="date-input" />);
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    expect(screen.getByRole("grid")).toBeInTheDocument();
  });

  it("commits the picked date and closes the grid when a day is clicked", () => {
    const onChange = vi.fn();
    render(<DateInput value="2026-08-14" onChange={onChange} data-testid="date-input" />);
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    fireEvent.click(screen.getByRole("button", { name: "15" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-08-15");
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
  });

  it("closes the grid when clicking outside it", () => {
    render(
      <div>
        <DateInput data-testid="date-input" />
        <button>outside</button>
      </div>
    );
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    expect(screen.getByRole("grid")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("grid")).not.toBeInTheDocument();
  });

  it("shades holiday days in the grid when showHolidays is set", async () => {
    render(<DateInput value="2026-08-01" showHolidays data-testid="date-input" />);
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    await waitFor(() => expect(listHolidays).toHaveBeenCalledWith(2026));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "15" }).className).toMatch(/holiday-date-tile/);
    });
  });

  it("shades holiday days by default", async () => {
    render(<DateInput value="2026-08-01" data-testid="date-input" />);
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    await waitFor(() => expect(screen.getByRole("button", { name: "15" }).className).toMatch(/holiday-date-tile/));
  });

  it("does not fetch holidays when showHolidays is explicitly false", () => {
    vi.mocked(listHolidays).mockClear();
    render(<DateInput value="2026-08-01" showHolidays={false} data-testid="date-input" />);
    fireEvent.click(screen.getByLabelText("פתח לוח שנה"));
    expect(listHolidays).not.toHaveBeenCalled();
  });
  it("opens above the field when the calendar would extend below the mobile viewport", () => {
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 600 });
    const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
      if (this.tagName === "BUTTON") {
        return { top: 520, bottom: 552, left: 20, right: 52, width: 32, height: 32, x: 20, y: 520, toJSON: () => ({}) } as DOMRect;
      }
      return { top: 0, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    });

    render(<DateInput data-testid="date-input" />);
    fireEvent.click(screen.getAllByRole("button")[0]);

    expect(Number.parseFloat(screen.getByTestId("date-picker-popover").style.top)).toBeLessThan(520);

    bounds.mockRestore();
    Object.defineProperty(window, "innerHeight", { configurable: true, value: originalHeight });
  });

  it("marks the calendar for the shared dark-mode calendar theme", () => {
    render(<DateInput data-testid="date-input" />);
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(document.querySelector(".date-picker-calendar")).toBeInTheDocument();
  });

  it("closes only the picker on browser back, leaving its parent modal mounted", async () => {
    window.history.replaceState(null, "", "/date-picker-test");
    render(
      <div data-testid="parent-modal">
        <DateInput data-testid="date-input" />
      </div>,
    );
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(screen.getByRole("grid")).toBeInTheDocument();

    window.history.back();

    await waitFor(() => expect(screen.queryByRole("grid")).not.toBeInTheDocument());
    expect(screen.getByTestId("parent-modal")).toBeInTheDocument();
  });
});
