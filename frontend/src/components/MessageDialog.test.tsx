import { fireEvent, render, screen } from "@testing-library/react";
import MessageDialog from "./MessageDialog";

describe("MessageDialog", () => {
  it("closes with the Hebrew fallback label and has no confirm action", () => {
    const onClose = vi.fn();
    render(<MessageDialog open title="שגיאה" message="משהו השתבש" onClose={onClose} />);

    expect(screen.getByText("משהו השתבש")).toBeInTheDocument();
    const close = screen.getByTestId("message-dialog-close");
    expect(screen.getByRole("dialog")).not.toHaveTextContent("אישור");
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledOnce();
  });
});
