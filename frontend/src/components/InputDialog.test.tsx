import { fireEvent, render, screen } from "@testing-library/react";
import InputDialog from "./InputDialog";

describe("InputDialog", () => {
  it("submits a trimmed value", () => {
    const onConfirm = vi.fn();
    render(<InputDialog open title="סיבה" label="הערה" onConfirm={onConfirm} onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("textbox", { name: "הערה" }), { target: { value: "  הערה חשובה  " } });
    fireEvent.click(screen.getByRole("button", { name: "אישור" }));
    expect(onConfirm).toHaveBeenCalledWith("הערה חשובה");
  });

  it("does not submit when cancelled", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<InputDialog open title="סיבה" label="הערה" onConfirm={onConfirm} onClose={onClose} />);

    fireEvent.change(screen.getByRole("textbox", { name: "הערה" }), { target: { value: "הערה" } });
    fireEvent.click(screen.getByRole("button", { name: "ביטול" }));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("disables confirmation for blank required input", () => {
    const onConfirm = vi.fn();
    render(<InputDialog open title="סיבה" label="הערה" required onConfirm={onConfirm} onClose={vi.fn()} />);
    const confirm = screen.getByRole("button", { name: "אישור" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("resets the value when closed and reopened", () => {
    const { rerender } = render(<InputDialog open title="סיבה" label="הערה" onConfirm={vi.fn()} onClose={vi.fn()} />);
    const input = screen.getByRole("textbox", { name: "הערה" });
    fireEvent.change(input, { target: { value: "ערך קודם" } });
    rerender(<InputDialog open={false} title="סיבה" label="הערה" onConfirm={vi.fn()} onClose={vi.fn()} />);
    rerender(<InputDialog open title="סיבה" label="הערה" onConfirm={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "הערה" })).toHaveValue("");
  });
});
