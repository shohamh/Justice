import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PopoverDropdown from "./PopoverDropdown";

describe("PopoverDropdown", () => {
  it("is closed by default and opens the panel on trigger click", () => {
    render(
      <PopoverDropdown triggerLabel="סנן" badgeCount={0}>
        {() => <div>תוכן הפאנל</div>}
      </PopoverDropdown>
    );
    expect(screen.queryByText("תוכן הפאנל")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("תוכן הפאנל")).toBeInTheDocument();
  });

  it("shows a count badge when badgeCount > 0, and hides it at 0", () => {
    const { rerender } = render(
      <PopoverDropdown triggerLabel="סנן" badgeCount={2}>{() => <div />}</PopoverDropdown>
    );
    expect(screen.getByText("2")).toBeInTheDocument();
    rerender(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div />}</PopoverDropdown>);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("closes when clicking outside the popover", () => {
    render(
      <div>
        <PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div>תוכן הפאנל</div>}</PopoverDropdown>
        <div data-testid="outside">מחוץ</div>
      </div>
    );
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("תוכן הפאנל")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByText("תוכן הפאנל")).not.toBeInTheDocument();
  });

  it("closes on Escape key when open", () => {
    render(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div>תוכן</div>}</PopoverDropdown>);
    fireEvent.click(screen.getByText("סנן"));
    expect(screen.getByText("תוכן")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("תוכן")).not.toBeInTheDocument();
  });

  it("sets aria-expanded to reflect open state", () => {
    render(<PopoverDropdown triggerLabel="סנן" badgeCount={0}>{() => <div />}</PopoverDropdown>);
    const trigger = screen.getByText("סנן").closest("button")!;
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });
});
