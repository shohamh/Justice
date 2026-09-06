import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import Tooltip from "./Tooltip";

describe("Tooltip", () => {
  it("carries the native title attribute for hover, and opens/closes a popover on click", () => {
    render(
      <Tooltip ariaLabel="פרטים" title="הסבר מלא" content="הסבר מלא">
        ⚠
      </Tooltip>
    );
    const trigger = screen.getByLabelText("פרטים");
    expect(trigger).toHaveAttribute("title", "הסבר מלא");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("הסבר מלא");

    fireEvent.click(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("closes on outside click", () => {
    render(
      <div>
        <Tooltip ariaLabel="פרטים" content="תוכן">x</Tooltip>
        <button type="button">אחר</button>
      </div>
    );
    fireEvent.click(screen.getByLabelText("פרטים"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("אחר"));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    render(<Tooltip ariaLabel="פרטים" content="תוכן">x</Tooltip>);
    fireEvent.click(screen.getByLabelText("פרטים"));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows an optional bold label heading above the content", () => {
    render(
      <Tooltip ariaLabel="פרטים" label="כותרת" content="תוכן">x</Tooltip>
    );
    fireEvent.click(screen.getByLabelText("פרטים"));
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("כותרת");
    expect(tooltip).toHaveTextContent("תוכן");
  });

  it("renders as a non-button element (role=button) when as='span', for use inside other clickable elements", () => {
    render(
      <Tooltip as="span" ariaLabel="פרטים" content="תוכן">x</Tooltip>
    );
    const trigger = screen.getByLabelText("פרטים");
    expect(trigger.tagName).toBe("SPAN");
    expect(trigger).toHaveAttribute("role", "button");
    fireEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });

  it("does not let its own click bubble to an ancestor's onClick", () => {
    let bubbled = false;
    render(
      <div onClick={() => { bubbled = true; }}>
        <Tooltip ariaLabel="פרטים" content="תוכן">x</Tooltip>
      </div>
    );
    fireEvent.click(screen.getByLabelText("פרטים"));
    expect(bubbled).toBe(false);
  });
});
