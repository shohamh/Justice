import { fireEvent, render, screen } from "@testing-library/react";
import { EventDetailModal } from "./EventDetailModal";

describe("EventDetailModal", () => {
  it("renders the header, metadata, actions, and content slot", () => {
    render(
      <EventDetailModal
        open
        title="Morning shift"
        subtitle="Gate 1"
        metadata={[{ label: "Date", value: "2026-08-02" }]}
        actions={<button type="button">Edit</button>}
        onClose={vi.fn()}
      >
        <p>Details</p>
      </EventDetailModal>,
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Morning shift");
    expect(screen.getByText("Date")).toBeInTheDocument();
    expect(screen.getByText("2026-08-02")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
  });

  it("calls close from the accessible close action", () => {
    const onClose = vi.fn();
    render(<EventDetailModal open title="Shift" onClose={onClose}>Content</EventDetailModal>);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
