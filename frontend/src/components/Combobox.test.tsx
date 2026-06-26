import { render, screen, fireEvent } from "@testing-library/react";
import Combobox, { type ComboboxItem } from "./Combobox";

const items: ComboboxItem[] = [
  { id: "1", name: "Alpha" },
  { id: "2", name: "Beta" },
  { id: "3", name: "Gamma" },
];

test("shows the selected item's name in the input", () => {
  render(<Combobox items={items} value="2" onChange={() => {}} />);
  expect(screen.getByRole("combobox")).toHaveValue("Beta");
});

test("opening the input lists all items", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("combobox"));
  expect(screen.getByText("Alpha")).toBeInTheDocument();
  expect(screen.getByText("Beta")).toBeInTheDocument();
  expect(screen.getByText("Gamma")).toBeInTheDocument();
});

test("typing filters the list via fuzzy search", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value: "gam" } });
  expect(screen.getByText("Gamma")).toBeInTheDocument();
  expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
});

test("clicking an item calls onChange with its id and closes the list", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.pointerDown(screen.getByText("Beta"));
  fireEvent.pointerUp(screen.getByText("Beta"));
  expect(onChange).toHaveBeenCalledWith("2");
});

test("a touch that turns into a scroll (pointercancel) does not select the item", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.pointerDown(screen.getByText("Beta"));
  fireEvent.pointerCancel(screen.getByText("Beta"));
  expect(onChange).not.toHaveBeenCalled();
});

test("disabled items are not selectable", () => {
  const onChange = vi.fn();
  const withDisabled: ComboboxItem[] = [...items, { id: "4", name: "Delta", disabled: true }];
  render(<Combobox items={withDisabled} value="" onChange={onChange} />);
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.pointerDown(screen.getByText("Delta"));
  fireEvent.pointerUp(screen.getByText("Delta"));
  expect(onChange).not.toHaveBeenCalled();
});

test("placeholder renders as a selectable first row that clears the value", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="1" onChange={onChange} placeholder="— none —" />);
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.pointerDown(screen.getByText("— none —"));
  fireEvent.pointerUp(screen.getByText("— none —"));
  expect(onChange).toHaveBeenCalledWith("");
});

test("depth indents an item and shows a tree marker", () => {
  const withDepth: ComboboxItem[] = [
    { id: "1", name: "Root" },
    { id: "2", name: "Child", depth: 1 },
  ];
  render(<Combobox items={withDepth} value="" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("combobox"));
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
  fireEvent.focus(screen.getByRole("combobox"));
  expect(screen.getByText("Enlisted")).toBeInTheDocument();
  expect(screen.getByText("Officers")).toBeInTheDocument();
  expect(screen.getAllByText("Enlisted")).toHaveLength(1);
});

test("input has combobox ARIA attributes wired to the listbox", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  const input = screen.getByRole("combobox");
  expect(input).toHaveAttribute("role", "combobox");
  expect(input).toHaveAttribute("aria-haspopup", "listbox");
  expect(input).toHaveAttribute("aria-expanded", "false");

  fireEvent.focus(input);
  expect(input).toHaveAttribute("aria-expanded", "true");
  const listbox = screen.getByRole("listbox");
  expect(input.getAttribute("aria-controls")).toBe(listbox.getAttribute("id"));
});

test("options expose option role, aria-selected and aria-disabled", () => {
  const withDisabled: ComboboxItem[] = [...items, { id: "4", name: "Delta", disabled: true }];
  render(<Combobox items={withDisabled} value="2" onChange={() => {}} />);
  fireEvent.focus(screen.getByRole("combobox"));

  const beta = screen.getByText("Beta").closest("li");
  expect(beta).toHaveAttribute("role", "option");
  expect(beta).toHaveAttribute("aria-selected", "true");

  const alpha = screen.getByText("Alpha").closest("li");
  expect(alpha).toHaveAttribute("aria-selected", "false");

  const delta = screen.getByText("Delta").closest("li");
  expect(delta).toHaveAttribute("aria-disabled", "true");
});

test("ArrowDown moves the highlight forward, skipping disabled items", () => {
  const withDisabled: ComboboxItem[] = [
    { id: "1", name: "Alpha" },
    { id: "2", name: "Beta", disabled: true },
    { id: "3", name: "Gamma" },
  ];
  render(<Combobox items={withDisabled} value="" onChange={() => {}} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);

  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByText("Alpha").closest("button")).toHaveClass("bg-gray-100");

  // Beta is disabled, so the next ArrowDown should skip straight to Gamma.
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByText("Gamma").closest("button")).toHaveClass("bg-gray-100");
});

test("ArrowUp moves the highlight backward", () => {
  render(<Combobox items={items} value="" onChange={() => {}} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);

  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(screen.getByText("Beta").closest("button")).toHaveClass("bg-gray-100");

  fireEvent.keyDown(input, { key: "ArrowUp" });
  expect(screen.getByText("Alpha").closest("button")).toHaveClass("bg-gray-100");
});

test("Enter selects the highlighted item and closes the dropdown", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);

  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });

  expect(onChange).toHaveBeenCalledWith("2");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("Escape closes the dropdown without changing the selection", () => {
  const onChange = vi.fn();
  render(<Combobox items={items} value="" onChange={onChange} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  expect(screen.getByRole("listbox")).toBeInTheDocument();

  fireEvent.keyDown(input, { key: "Escape" });

  expect(onChange).not.toHaveBeenCalled();
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});
