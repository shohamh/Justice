import { fireEvent, render, screen } from "@testing-library/react";
import { EventDetailModal } from "./EventDetailModal";

describe("EventDetailModal", () => {
  it("renders the header, metadata, actions, and content slot", () => {
    render(
      <EventDetailModal
        open
        title="Morning shift"
        subtitle="Gate 1"
        metadata={[{ id: "date", label: "Date", value: "2026-08-02" }]}
        actions={<button type="button">Edit</button>}
        onClose={vi.fn()}
      >
        <p>Details</p>
      </EventDetailModal>,
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Morning shift");
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-labelledby", screen.getByRole("heading", { name: "Morning shift" }).id);
    expect(screen.getByText("Date")).toBeInTheDocument();
    expect(screen.getByText("2026-08-02")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
  });

  it("focuses close on open and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <>
        <button type="button">Open</button>
        <EventDetailModal open title="Shift" onClose={onClose}>Content</EventDetailModal>
      </>,
    );
    expect(screen.getByRole("button", { name: "סגור" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("restores focus to the opener when closed", () => {
    const { rerender } = render(<><button type="button">Open</button><EventDetailModal open={false} title="Shift" onClose={vi.fn()}>Content</EventDetailModal></>);
    const trigger = screen.getByRole("button", { name: "Open" });
    trigger.focus();
    rerender(<><button type="button">Open</button><EventDetailModal open title="Shift" onClose={vi.fn()}>Content</EventDetailModal></>);
    rerender(<><button type="button">Open</button><EventDetailModal open={false} title="Shift" onClose={vi.fn()}>Content</EventDetailModal></>);
    expect(trigger).toHaveFocus();
  });
});