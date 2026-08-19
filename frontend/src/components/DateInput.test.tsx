import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import DateInput from "./DateInput";

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
});
