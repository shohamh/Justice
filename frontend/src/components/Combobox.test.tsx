import { render, screen, fireEvent } from "@testing-library/react";
import Combobox, { type ComboboxItem } from "./Combobox";

const items: ComboboxItem[] = [
  { id: "1", name: "Alpha" },
  { id: "2", name: "Beta" },
  { id: "3", name: "Gamma" },
];

test("shows the selected item's name in the input", () => {
  render(<Combobox items={items} value="2" onChange={() => {}} />);
  expect(screen.getByRole("textbox")).toHaveValue("Beta");
});

test("opening the input lists all items", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  expect(screen.getByText("Alpha")).toBeInTheDocument();
  expect(screen.getByText("Beta")).toBeInTheDocument();
  expect(screen.getByText("Gamma")).toBeInTheDocument();
});

test("typing filters the list via fuzzy search", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  const input = screen.getByRole("textbox");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "gam" } });
  expect(screen.getByText("Gamma")).toBeInTheDocument();
  expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
});

test("clicking an item calls onChange with its id and closes the list", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("Beta"));
  expect(onChange).toHaveBeenCalledWith("2");
});

test("disabled items are not selectable", () => {
  const onChange = vi.fn();
  const withDisabled: ComboboxItem[] = [...items, { id: "4", name: "Delta", disabled: true }];
  render(<Combobox items={withDisabled} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("Delta"));
  expect(onChange).not.toHaveBeenCalled();
});

test("placeholder renders as a selectable first row that clears the value", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="1" onChange={onChange} placeholder="— none —" />);
  fireEvent.focus(screen.getByRole("textbox"));
  fireEvent.pointerDown(screen.getByText("— none —"));
  expect(onChange).toHaveBeenCalledWith("");
});

test("depth indents an item and shows a tree marker", () => {
  const withDepth: ComboboxItem[] = [
    { id: "1", name: "Root" },
    { id: "2", name: "Child", depth: 1 },
  ];
  render(<Combobox items={withDepth} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  const child = screen.getByText("Child").closest("button");
  expect(child?.textContent).toContain("└");
});

test("group renders a header row before the first item of each group", () => {
  const grouped: ComboboxItem[] = [
    { id: "1", name: "Private", group: "Enlisted" },
    { id: "2", name: "Sergeant", group: "Enlisted" },
    { id: "3", name: "Captain", group: "Officers" },
  ];
  render(<Combobox items={grouped} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("textbox"));
  expect(screen.getByText("Enlisted")).toBeInTheDocument();
  expect(screen.getByText("Officers")).toBeInTheDocument();
  expect(screen.getAllByText("Enlisted")).toHaveLength(1);
});
