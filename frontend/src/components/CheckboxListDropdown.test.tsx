import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CheckboxListDropdown from "./CheckboxListDropdown";

describe("CheckboxListDropdown", () => {
  const items = [
    { id: "1", label: "אלפא" },
    { id: "2", label: "ברבו" },
  ];

  it("opens the panel on trigger click and shows all items", () => {
    render(<CheckboxListDropdown items={items} selected={[]} onChange={() => {}} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("אלפא")).toBeInTheDocument();
    expect(screen.getByText("ברבו")).toBeInTheDocument();
  });

  it("calls onChange with the toggled item added when checked", () => {
    let selected: string[] = [];
    const onChange = (ids: string[]) => { selected = ids; };
    render(<CheckboxListDropdown items={items} selected={[]} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    fireEvent.click(screen.getByLabelText("אלפא"));
    expect(selected).toEqual(["1"]);
  });

  it("select-all toggles every item on and off", () => {
    let selected: string[] = [];
    const onChange = (ids: string[]) => { selected = ids; };
    const { rerender } = render(<CheckboxListDropdown items={items} selected={selected} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByText("סנן"));
    fireEvent.click(screen.getByLabelText("הכל"));
    expect(selected).toEqual(["1", "2"]);
    rerender(<CheckboxListDropdown items={items} selected={selected} onChange={onChange} triggerLabel="סנן" />);
    fireEvent.click(screen.getByLabelText("הכל"));
    expect(selected).toEqual([]);
  });
});
